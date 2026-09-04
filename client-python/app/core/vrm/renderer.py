"""OpenGL renderer for a :class:`VRMModel`.

Strategy: the rig and morph targets are applied on the CPU each frame and
the resulting positions/normals are uploaded to a dynamic VBO, so the GPU
shader only does a simple MVP + diffuse lighting.  This keeps the GL
requirements minimal (one program, VAO/VBO) and robust across context
profiles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from OpenGL import GL

from app.core.vrm.model import VRMModel
from app.core.vrm.rig import VRMRig

# --------------------------------------------------------------------------
# shaders
# --------------------------------------------------------------------------

_VERT_SRC = """#version 150
in vec3 a_pos;
in vec3 a_normal;
in vec2 a_uv;
uniform mat4 u_mvp;
uniform mat3 u_normal_mat;
out vec2 v_uv;
out vec3 v_normal;
void main() {
    gl_Position = u_mvp * vec4(a_pos, 1.0);
    v_uv = a_uv;
    v_normal = normalize(u_normal_mat * a_normal);
}
"""

_FRAG_SRC = """#version 150
in vec2 v_uv;
in vec3 v_normal;
uniform sampler2D u_tex;
uniform vec4 u_color;
uniform float u_unlit;
uniform float u_alpha;
uniform vec3 u_light_dir;
out vec4 fragColor;
void main() {
    vec4 texel = texture(u_tex, v_uv);
    vec3 base = texel.rgb * u_color.rgb;
    vec3 n = normalize(v_normal);
    float diff = max(dot(n, normalize(u_light_dir)), 0.0);
    vec3 lit = base * (0.45 + 0.55 * diff);
    vec3 outColor = mix(lit, base, u_unlit);
    fragColor = vec4(outColor, texel.a * u_color.a * u_alpha);
}
"""


def _as_int(value):
    """PyOpenGL gen* calls sometimes return a scalar, sometimes a 1-elem array."""
    if isinstance(value, (list, tuple, np.ndarray)):
        return int(value[0])
    return int(value)


# --------------------------------------------------------------------------
# GPU primitive
# --------------------------------------------------------------------------

@dataclass
class _PrimGPU:
    vao: int
    vbo_pos: int
    vbo_nrm: int
    vbo_uv: int
    ebo: int
    count: int
    material_index: int
    skin_index: int
    base_pos: np.ndarray
    base_nrm: np.ndarray
    morph_pos: list = field(default_factory=list)
    morph_norm: list = field(default_factory=list)
    joints: np.ndarray | None = None
    weights: np.ndarray | None = None
    _skipped: bool = False


class VRMRenderer:
    """Owns the GL resources and draws a :class:`VRMModel`."""

    def __init__(self) -> None:
        self._program = 0
        self._prims: list[_PrimGPU] = []
        self._gpu_by_item: dict[int, list[_PrimGPU]] = {}
        self._textures: dict[int, int] = {}
        self._model: VRMModel | None = None
        self._rig: VRMRig | None = None
        self._morph_layers: dict[int, list] = {}
        self._width = 1
        self._height = 1
        self._fit = np.eye(4, dtype=np.float32)
        self._camera_dist = 2.6
        self._ready = False
        self._white_tex = 0
        # location cache
        self._loc = {}

    # The PyOpenGL wrapper for glGenTextures is broken in some builds, so use
    # the raw function to create/delete texture names.
    @staticmethod
    def _gen_texture() -> int:
        import ctypes
        from OpenGL.raw.GL.VERSION.GL_1_1 import glGenTextures as _raw_gen
        a = (ctypes.c_uint * 1)()
        _raw_gen(1, a)
        return int(a[0])

    @staticmethod
    def _delete_texture(tex: int) -> None:
        import ctypes
        from OpenGL.raw.GL.VERSION.GL_1_1 import glDeleteTextures as _raw_del
        a = (ctypes.c_uint * 1)(tex)
        _raw_del(1, a)

    # ---- lifecycle -----------------------------------------------------
    def initialize(self, model: VRMModel, rig: VRMRig) -> None:
        self._model = model
        self._rig = rig
        self._compile_program()
        self._create_resources()
        self._rig.update()
        self._compute_fit()
        self._ready = True

    def release(self) -> None:
        if self._program:
            try:
                GL.glDeleteProgram(self._program)
            except Exception:
                pass
        for tex in self._textures.values():
            try:
                self._delete_texture(tex)
            except Exception:
                pass
        self._textures.clear()
        if self._white_tex:
            try:
                self._delete_texture(self._white_tex)
            except Exception:
                pass
            self._white_tex = 0
        # VBO/VAO cleanup
        for prim in self._prims:
            try:
                GL.glDeleteBuffers([prim.vbo_pos, prim.vbo_nrm, prim.vbo_uv, prim.ebo])
                GL.glDeleteVertexArrays(1, [prim.vao])
            except Exception:
                pass
        self._prims.clear()
        self._program = 0
        self._ready = False

    # ---- shaders -------------------------------------------------------
    def _compile(self, src: str, kind: int) -> int:
        sh = GL.glCreateShader(kind)
        GL.glShaderSource(sh, [src])
        GL.glCompileShader(sh)
        if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
            log = GL.glGetShaderInfoLog(sh)
            raise RuntimeError(f"shader compile error: {log}")
        return sh

    def _compile_program(self) -> None:
        vs = self._compile(_VERT_SRC, GL.GL_VERTEX_SHADER)
        fs = self._compile(_FRAG_SRC, GL.GL_FRAGMENT_SHADER)
        prog = GL.glCreateProgram()
        GL.glAttachShader(prog, vs)
        GL.glAttachShader(prog, fs)
        # bind attribute locations
        GL.glBindAttribLocation(prog, 0, "a_pos")
        GL.glBindAttribLocation(prog, 1, "a_normal")
        GL.glBindAttribLocation(prog, 2, "a_uv")
        GL.glLinkProgram(prog)
        GL.glDeleteShader(vs)
        GL.glDeleteShader(fs)
        if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
            log = GL.glGetProgramInfoLog(prog)
            raise RuntimeError(f"program link error: {log}")
        self._program = prog
        for name in ("u_mvp", "u_normal_mat", "u_tex", "u_color", "u_unlit", "u_alpha", "u_light_dir"):
            self._loc[name] = GL.glGetUniformLocation(prog, name)

    # ---- GPU resources -------------------------------------------------
    def _make_vbo(self, data: np.ndarray, dynamic: bool = False) -> int:
        buf = _as_int(GL.glGenBuffers(1))
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buf)
        usage = GL.GL_DYNAMIC_DRAW if dynamic else GL.GL_STATIC_DRAW
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.astype(np.float32).tobytes(), usage)
        return buf

    def _create_resources(self) -> None:
        model = self._model
        assert model is not None
        self._morph_layers.clear()
        self._gpu_by_item.clear()
        for it_index, it in enumerate(model.mesh_items):
            item_gpus: list[_PrimGPU] = []
            for prim in it.primitives:
                count = prim.positions.shape[0]
                vao = _as_int(GL.glGenVertexArrays(1))
                GL.glBindVertexArray(vao)
                vbo_pos = self._make_vbo(prim.positions, dynamic=True)
                vbo_nrm = self._make_vbo(prim.normals, dynamic=True)
                vbo_uv = self._make_vbo(prim.uvs)
                ebo = _as_int(GL.glGenBuffers(1))
                GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ebo)
                GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, prim.indices.astype(np.uint32).tobytes(), GL.GL_STATIC_DRAW)
                self._set_attrib_pointer(0, 3, vbo_pos)
                self._set_attrib_pointer(1, 3, vbo_nrm)
                self._set_attrib_pointer(2, 2, vbo_uv)
                GL.glBindVertexArray(0)

                prim_gpu = _PrimGPU(
                    vao=vao, vbo_pos=vbo_pos, vbo_nrm=vbo_nrm, vbo_uv=vbo_uv, ebo=ebo,
                    count=count, material_index=prim.material_index, skin_index=it.skin_index,
                    base_pos=prim.positions, base_nrm=prim.normals,
                    morph_pos=prim.morph_pos, morph_norm=prim.morph_norm,
                    joints=prim.joints, weights=prim.weights,
                )
                self._prims.append(prim_gpu)
                item_gpus.append(prim_gpu)
            self._gpu_by_item[it_index] = item_gpus

        # load images -> textures
        for tex_i, img_i in enumerate(model.texture_to_image):
            if img_i < 0 or img_i >= len(model.images):
                continue
            data, mime = model.images[img_i]
            if not data:
                continue
            try:
                from PIL import Image
                import io
                pil = Image.open(io.BytesIO(data)).convert("RGBA")
                arr = np.asarray(pil).astype(np.uint8)
                tex = self._gen_texture()
                GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, arr.shape[1], arr.shape[0], 0,
                                GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, arr.tobytes())
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
                GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
                self._textures[tex_i] = tex
            except Exception as tex_err:
                import sys
                print(f"[vrm] texture {tex_i} load failed: {tex_err!r}", file=sys.stderr)

        # 1x1 white fallback texture (bound when a material has no texture)
        try:
            white = np.ones((1, 1, 4), dtype=np.uint8) * 255
            wt = self._gen_texture()
            GL.glBindTexture(GL.GL_TEXTURE_2D, wt)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, 1, 1, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE,
                            white.tobytes())
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            self._white_tex = wt
        except Exception:
            self._white_tex = 0

    @staticmethod
    def _set_attrib_pointer(index: int, size: int, vbo: int) -> None:
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glEnableVertexAttribArray(index)
        GL.glVertexAttribPointer(index, size, GL.GL_FLOAT, GL.GL_FALSE, 0, None)

    # ---- fit / camera --------------------------------------------------
    def _compute_fit(self) -> None:
        rig = self._rig
        model = self._model
        assert rig is not None and model is not None
        pts = []
        for it in model.mesh_items:
            for prim in it.primitives:
                if prim.joints is None or it.skin_index < 0:
                    pts.append(prim.positions)
                else:
                    sk = rig.skin_matrices(it.skin_index)
                    pts.append(self._skin_positions(prim, sk))
        all_pts = np.concatenate([p.reshape(-1, 3) for p in pts], axis=0)
        mn = all_pts.min(0)
        mx = all_pts.max(0)
        center = (mn + mx) * 0.5
        size = np.maximum(mx - mn, 1e-4)
        scale = 2.0 / max(size)
        fit = np.eye(4, dtype=np.float32)
        fit[0, 0] = fit[1, 1] = fit[2, 2] = scale
        fit[:3, 3] = -center * scale
        # Auto-face the +Z camera: rotate the model so its forward points +Z.
        self._fit = self._face_rotation(rig, model) @ fit
        self._camera_dist = 2.6

    @staticmethod
    def _face_rotation(rig: VRMRig, model: VRMModel) -> np.ndarray:
        """A rotation (about Y) that turns the model's forward onto +Z.

        Forward is taken from the head->eyes vector when eye bones exist,
        otherwise from the head bone's local +Z axis projected to the
        horizontal plane.
        """
        import math
        hb = model.humanoid
        fwd = None
        if hb.get("leftEye") is not None and hb.get("rightEye") is not None:
            head = hb.get("head")
            if head is not None:
                hp = rig.global_of(head)[:3, 3]
                mid = (rig.global_of(hb["leftEye"])[:3, 3] + rig.global_of(hb["rightEye"])[:3, 3]) * 0.5
                v = mid - hp
                fwd = np.array([v[0], 0.0, v[2]], dtype=np.float32)
        if fwd is None:
            head = hb.get("head")
            if head is not None:
                g = rig.global_of(head)
                fwd = g[:3, 2].copy()  # head +Z axis in world
        if fwd is None:
            return np.eye(4, dtype=np.float32)
        norm = float(math.hypot(fwd[0], fwd[2]))
        if norm < 1e-6:
            return np.eye(4, dtype=np.float32)
        fwd = fwd / norm
        angle = -math.atan2(fwd[0], fwd[2])  # rotate forward onto +Z
        c, s = math.cos(angle), math.sin(angle)
        rot = np.eye(4, dtype=np.float32)
        rot[0, 0] = c
        rot[0, 2] = s
        rot[2, 0] = -s
        rot[2, 2] = c
        return rot

    # ---- skinning helpers ---------------------------------------------
    @staticmethod
    def _skin_positions(prim, sk: np.ndarray) -> np.ndarray:
        pos = prim.positions
        joints = prim.joints
        weights = prim.weights
        if joints is None or weights is None or sk.shape[0] == 0:
            return pos
        gathered = sk[joints]  # (N,4,4,4)
        p4 = np.concatenate([pos, np.ones((pos.shape[0], 1), np.float32)], axis=1)
        tmp = np.einsum("nirc,nc->nir", gathered, p4)
        skinned = np.einsum("ni,nir->nr", weights, tmp)[:, :3]
        return skinned

    # ---- per-frame -----------------------------------------------------
    def set_morph(self, weights: dict[str, float]) -> None:
        """weights: expression name -> 0..1. Applied on top of base pose."""
        model = self._model
        if model is None:
            return
        # clear layers
        layers: dict[int, list[tuple[int, float]]] = {}
        for name, w in weights.items():
            for bind in model.expressions.get(name, []):
                layers.setdefault(bind.mesh_item, []).append((bind.morph_index, bind.weight * w))
        self._morph_layers = layers

    def render(self) -> None:
        if not self._ready or self._model is None or self._rig is None:
            return
        GL.glUseProgram(self._program)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthFunc(GL.GL_LESS)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glClearColor(0.06, 0.08, 0.14, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        proj_view = self._view_proj()
        # model-view (view @ fit) used for normals; projection only for clip space
        modelview = self._view_matrix() @ self._fit
        mvp_base = proj_view @ self._fit
        normal_mat = np.linalg.inv(modelview[:3, :3]).T

        GL.glUniformMatrix4fv(self._loc["u_mvp"], 1, GL.GL_TRUE, mvp_base.astype(np.float32))
        GL.glUniformMatrix3fv(self._loc["u_normal_mat"], 1, GL.GL_TRUE, normal_mat.astype(np.float32))
        GL.glUniform3f(self._loc["u_light_dir"], 0.3, 0.8, 0.6)

        for it_index, prim in enumerate(self._model.mesh_items):
            for pi, pr in enumerate(prim.primitives):
                gpu = self._gpu_for(it_index, pi)
                if gpu is None:
                    continue
                self._update_prim(gpu, pr, it_index)
                self._draw_prim(gpu, pr)
        GL.glUseProgram(0)

    def _gpu_for(self, it_index: int, pi: int) -> _PrimGPU | None:
        gpus = self._gpu_by_item.get(it_index)
        if gpus is None or pi >= len(gpus):
            return None
        return gpus[pi]

    def _update_prim(self, gpu: _PrimGPU, prim, it_index: int) -> None:
        model = self._model
        rig = self._rig
        assert model is not None and rig is not None
        pos = gpu.base_pos
        nrm = gpu.base_nrm
        # morph
        for morph_index, w in self._morph_layers.get(it_index, []):
            if 0 <= morph_index < len(gpu.morph_pos):
                pos = pos + w * gpu.morph_pos[morph_index]
                if morph_index < len(gpu.morph_norm):
                    nrm = nrm + w * gpu.morph_norm[morph_index]
        # skinning
        if gpu.joints is not None and gpu.weights is not None and gpu.skin_index >= 0:
            sk = rig.skin_matrices(gpu.skin_index)
            if sk.shape[0] > 0:
                pos = self._skin_positions_cpu(pos, gpu.joints, gpu.weights, sk)
                nrm = self._skin_normals_cpu(nrm, gpu.joints, gpu.weights, sk)
        # upload
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, gpu.vbo_pos)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, pos.astype(np.float32).tobytes(), GL.GL_DYNAMIC_DRAW)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, gpu.vbo_nrm)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, nrm.astype(np.float32).tobytes(), GL.GL_DYNAMIC_DRAW)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)

    @staticmethod
    def _skin_positions_cpu(pos, joints, weights, sk):
        gathered = sk[joints]
        p4 = np.concatenate([pos, np.ones((pos.shape[0], 1), np.float32)], axis=1)
        tmp = np.einsum("nirc,nc->nir", gathered, p4)
        return np.einsum("ni,nir->nr", weights, tmp)[:, :3]

    @staticmethod
    def _skin_normals_cpu(nrm, joints, weights, sk):
        rot = sk[:, :3, :3]  # (J,3,3)
        gathered = rot[joints]  # (N,4,3,3)
        tmp = np.einsum("nirc,nc->nir", gathered, nrm)
        out = np.einsum("ni,nir->nr", weights, tmp)
        norm = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norm, 1e-6)

    def _draw_prim(self, gpu: _PrimGPU, prim) -> None:
        GL.glBindVertexArray(gpu.vao)
        mat_idx = gpu.material_index
        mat = self._model.materials[mat_idx] if 0 <= mat_idx < len(self._model.materials) else None
        color = (1.0, 1.0, 1.0, 1.0)
        tex = self._white_tex
        unlit = 0.0
        if mat is not None:
            color = mat.base_color_factor
            unlit = 1.0 if mat.unlit else 0.0
            if mat.base_color_texture is not None:
                tex = self._textures.get(mat.base_color_texture, self._white_tex)
        GL.glUniform4f(self._loc["u_color"], *color)
        GL.glUniform1f(self._loc["u_unlit"], unlit)
        GL.glUniform1f(self._loc["u_alpha"], 1.0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glUniform1i(self._loc["u_tex"], 0)
        GL.glDrawElements(GL.GL_TRIANGLES, len(prim.indices), GL.GL_UNSIGNED_INT, None)
        GL.glBindVertexArray(0)

    # ---- projection ----------------------------------------------------
    def _view_matrix(self) -> np.ndarray:
        eye = np.array([0.0, 0.05, self._camera_dist], dtype=np.float32)
        center = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        z = eye - center
        z = z / np.linalg.norm(z)
        x = np.cross(up, z)
        x = x / np.linalg.norm(x)
        y = np.cross(z, x)
        view = np.eye(4, dtype=np.float32)
        view[0, :3] = x
        view[1, :3] = y
        view[2, :3] = z
        view[0, 3] = -np.dot(x, eye)
        view[1, 3] = -np.dot(y, eye)
        view[2, 3] = -np.dot(z, eye)
        return view

    def _view_proj(self) -> np.ndarray:
        return self._projection() @ self._view_matrix()

    def _projection(self) -> np.ndarray:
        aspect = max(1, self._width) / max(1, self._height)
        fov = np.radians(45.0)
        near, far = 0.05, 100.0
        f = 1.0 / np.tan(fov * 0.5)
        proj = np.zeros((4, 4), dtype=np.float32)
        proj[0, 0] = f / aspect
        proj[1, 1] = f
        proj[2, 2] = (far + near) / (near - far)
        proj[2, 3] = (2 * far * near) / (near - far)
        proj[3, 2] = -1.0
        return proj

    def resize(self, w: int, h: int) -> None:
        self._width = max(1, w)
        self._height = max(1, h)
        GL.glViewport(0, 0, w, h)
