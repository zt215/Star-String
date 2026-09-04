"""Parse a VRM/GLB into a render-friendly :class:`VRMModel`.

This module holds no OpenGL calls: it only turns the binary glTF + VRM
extension into plain numpy arrays and semantic structures.  The rig and
renderer build on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.core.vrm.gltf import load as _load_glb, read_accessor


# --------------------------------------------------------------------------
# data classes
# --------------------------------------------------------------------------

@dataclass
class Primitive:
    positions: np.ndarray                 # (N,3) float32
    normals: np.ndarray                   # (N,3) float32
    uvs: np.ndarray                       # (N,2) float32
    joints: np.ndarray | None             # (N,4) int32 -> index into skin.joints
    weights: np.ndarray | None            # (N,4) float32
    indices: np.ndarray                   # (M,) int32
    morph_pos: list[np.ndarray] = field(default_factory=list)   # deltas (N,3)
    morph_norm: list[np.ndarray] = field(default_factory=list)  # deltas (N,3)
    material_index: int = -1
    mode: int = 4


@dataclass
class MeshItem:
    mesh_index: int                       # original glTF mesh index
    node_index: int                       # node that references this mesh
    skin_index: int                       # glTF skin index or -1
    primitives: list[Primitive] = field(default_factory=list)


@dataclass
class Skin:
    joints: list[int]                     # node indices
    inv_bind: np.ndarray                  # (J,4,4) row-major
    skeleton: int | None = None


@dataclass
class Material:
    index: int
    name: str = ""
    base_color_factor: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    base_color_texture: int | None = None
    metallic_factor: float = 0.0
    roughness_factor: float = 1.0
    emissive_factor: tuple[float, float, float] = (0.0, 0.0, 0.0)
    double_sided: bool = True
    alpha_mode: str = "OPAQUE"
    unlit: bool = False


@dataclass
class Node:
    index: int
    name: str
    children: list[int]
    parent: int | None
    matrix: np.ndarray                    # (4,4) local transform
    mesh: int | None
    skin: int | None


@dataclass
class ExpressionBind:
    mesh_item: int
    morph_index: int
    weight: float


@dataclass
class VRMModel:
    nodes: list[Node]
    node_by_index: dict[int, Node]
    root_nodes: list[int]
    mesh_items: list[MeshItem]
    skins: list[Skin]
    materials: list[Material]
    images: list[tuple[bytes, str]]       # (data, mime)
    texture_to_image: list[int]           # glTF texture index -> image index
    humanoid: dict[str, int]              # semantic bone name -> node index
    expressions: dict[str, list[ExpressionBind]]
    spec_version: str
    scene_scale: float = 1.0
    # convenience
    name: str = ""


# --------------------------------------------------------------------------
# JSON access helpers
# --------------------------------------------------------------------------

def _vrm_extension(gltf) -> dict | None:
    exts = getattr(gltf, "extensions", None) or {}
    for key in ("VRMC_vrm", "VRM", "VRM0"):
        if key in exts:
            return exts[key]
    return None


def _human_bones(vrm: dict) -> dict[str, int]:
    bones = {}
    humanoid = vrm.get("humanoid") or {}
    hb = humanoid.get("humanBones") or []
    if isinstance(hb, dict):
        hb = [{"name": k, **v} for k, v in hb.items()]
    for bone in hb:
        # VRM 1.0 uses "name", VRM 0.x uses "bone".
        name = bone.get("name") or bone.get("bone")
        node = bone.get("node")
        if name is not None and node is not None:
            bones[name] = node
    return bones


def _local_matrix(node) -> np.ndarray:
    """Return the node's local transform as a row-major (4,4)."""
    m = getattr(node, "matrix", None)
    if m is not None and len(m) == 16:
        return np.asarray(m, dtype=np.float32).reshape(4, 4).T.copy()
    t = np.asarray(getattr(node, "translation", None) or [0, 0, 0], dtype=np.float32)
    r = np.asarray(getattr(node, "rotation", None) or [0, 0, 0, 1], dtype=np.float32)  # xyzw
    s = np.asarray(getattr(node, "scale", None) or [1, 1, 1], dtype=np.float32)
    x, y, z, w = r
    rot = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
            [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
            [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float32,
    )
    out = np.eye(4, dtype=np.float32)
    out[:3, :3] = rot * s.reshape(3, 1)
    out[:3, 3] = t
    return out


def _vec(value: list | None, default, dtype=np.float32) -> np.ndarray:
    if not value:
        return np.asarray(default, dtype=dtype)
    return np.asarray(value, dtype=dtype)


def _norm_weight(value) -> float:
    """Normalise an expression bind weight to 0..1.

    VRM 1.0 uses 0..1; VRM 0.x `blendShapeMaster` uses 0..100.
    """
    weight = float(value if value is not None else 1.0)
    return weight / 100.0 if weight > 1.0 else weight


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def build(path: str | Path) -> VRMModel:
    glb = _load_glb(path)
    gltf = glb.gltf

    # ---- nodes ----
    nodes: list[Node] = []
    node_by_index: dict[int, Node] = {}
    parent_of: dict[int, int] = {}
    for i, gnode in enumerate(gltf.nodes):
        parent = None
        children = list(getattr(gnode, "children", None) or [])
        matrix = _local_matrix(gnode)
        node = Node(
            index=i,
            name=getattr(gnode, "name", "") or f"node{i}",
            children=children,
            parent=parent,
            matrix=matrix,
            mesh=getattr(gnode, "mesh", None),
            skin=getattr(gnode, "skin", None),
        )
        nodes.append(node)
        node_by_index[i] = node
    for i, gnode in enumerate(gltf.nodes):
        for c in (getattr(gnode, "children", None) or []):
            parent_of[c] = i
            nodes[c].parent = i

    roots = [i for i in range(len(nodes)) if i not in parent_of]

    # ---- skins ----
    skins: list[Skin] = []
    for gsk in gltf.skins or []:
        inv = read_accessor(glb, gsk.inverseBindMatrices).reshape(-1, 4, 4).transpose(0, 2, 1).copy()
        skins.append(Skin(joints=list(gsk.joints), inv_bind=inv, skeleton=gsk.skeleton))

    # ---- meshes (one MeshItem per node that references a mesh) ----
    mesh_items: list[MeshItem] = []
    for i, gnode in enumerate(gltf.nodes):
        mesh_attr = getattr(gnode, "mesh", None)
        if mesh_attr is None:
            continue
        gmesh = gltf.meshes[mesh_attr]
        item = MeshItem(mesh_index=mesh_attr, node_index=i,
                        skin_index=getattr(gnode, "skin", None) if getattr(gnode, "skin", None) is not None else -1)
        for prim in gmesh.primitives:
            attrs = prim.attributes
            pos = read_accessor(glb, attrs.POSITION).astype(np.float32)
            nrm = read_accessor(glb, attrs.NORMAL).astype(np.float32) if getattr(attrs, "NORMAL", None) is not None else np.zeros_like(pos)
            uv = read_accessor(glb, attrs.TEXCOORD_0).astype(np.float32) if getattr(attrs, "TEXCOORD_0", None) is not None else np.zeros((pos.shape[0], 2), np.float32)
            joints = weights = None
            if getattr(attrs, "JOINTS_0", None) is not None and getattr(attrs, "WEIGHTS_0", None) is not None:
                joints = read_accessor(glb, attrs.JOINTS_0).astype(np.int32)
                weights = read_accessor(glb, attrs.WEIGHTS_0).astype(np.float32)
            indices = read_accessor(glb, prim.indices).reshape(-1).astype(np.int32) if prim.indices is not None else np.arange(pos.shape[0], dtype=np.int32)
            p = Primitive(
                positions=pos,
                normals=nrm,
                uvs=uv,
                joints=joints,
                weights=weights,
                indices=indices,
                material_index=prim.material if prim.material is not None else -1,
                mode=prim.mode or 4,
            )
            for tgt in prim.targets or []:
                p.morph_pos.append(read_accessor(glb, tgt["POSITION"]).astype(np.float32) if "POSITION" in tgt else np.zeros_like(pos))
                p.morph_norm.append(read_accessor(glb, tgt["NORMAL"]).astype(np.float32) if "NORMAL" in tgt else np.zeros_like(nrm))
            item.primitives.append(p)
        mesh_items.append(item)

    # ---- materials ----
    materials: list[Material] = []
    for mi, gmat in enumerate(gltf.materials or []):
        pbr = getattr(gmat, "pbrMetallicRoughness", None)
        tex = None
        if pbr is not None and getattr(pbr, "baseColorTexture", None) is not None:
            tex = pbr.baseColorTexture.index
        factor = None
        if pbr is not None and getattr(pbr, "baseColorFactor", None) is not None:
            factor = tuple(float(v) for v in pbr.baseColorFactor)
        mat = Material(
            index=mi,
            name=getattr(gmat, "name", "") or f"mat{mi}",
            base_color_factor=factor or (1.0, 1.0, 1.0, 1.0),
            base_color_texture=tex,
            metallic_factor=(getattr(pbr, "metallicFactor", None) if pbr is not None else None) or 0.0,
            roughness_factor=(getattr(pbr, "roughnessFactor", None) if pbr is not None else None) or 1.0,
            emissive_factor=tuple(float(v) for v in (getattr(gmat, "emissiveFactor", None) or [0, 0, 0])),
            double_sided=bool(getattr(gmat, "doubleSided", True)),
            alpha_mode=getattr(gmat, "alphaMode", "OPAQUE") or "OPAQUE",
            unlit=bool((getattr(gmat, "extensions", None) or {}).get("KHR_materials_unlit")),
        )
        materials.append(mat)

    # ---- images & textures ----
    images: list[tuple[bytes, str]] = []
    for gimg in gltf.images or []:
        data = b""
        mime = getattr(gimg, "mimeType", None) or "image/png"
        if getattr(gimg, "bufferView", None) is not None:
            bv = gltf.bufferViews[gimg.bufferView]
            start = bv.byteOffset or 0
            data = glb.binary_blob[start:start + (bv.byteLength or 0)]
        elif getattr(gimg, "uri", None):
            uri = gimg.uri
            if uri.startswith("data:"):
                # data:<mime>;base64,<payload>
                try:
                    import base64
                    mime, payload = uri.split(",", 1)
                    mime = mime.split(";", 1)[0].split(":", 1)[1]
                    data = base64.b64decode(payload)
                except Exception:
                    data = b""
            else:
                # external file: resolve relative to model dir
                base = Path(path).parent
                fp = base / uri
                if fp.exists():
                    data = fp.read_bytes()
        images.append((data, mime))

    texture_to_image: list[int] = []
    for gtex in gltf.textures or []:
        texture_to_image.append(gtex.source if getattr(gtex, "source", None) is not None else -1)

    # ---- VRM extension ----
    vrm = _vrm_extension(gltf)
    humanoid: dict[str, int] = {}
    expressions: dict[str, list[ExpressionBind]] = {}
    spec_version = ""
    name = ""
    scene_scale = 1.0

    if vrm is not None:
        spec_version = vrm.get("specVersion", "")
        humanoid = _human_bones(vrm)
        meta = vrm.get("meta") or {}
        name = meta.get("name", "") if isinstance(meta, dict) else ""
        _build_expressions(vrm, gltf, mesh_items, node_by_index, expressions)

    return VRMModel(
        nodes=nodes,
        node_by_index=node_by_index,
        root_nodes=roots,
        mesh_items=mesh_items,
        skins=skins,
        materials=materials,
        images=images,
        texture_to_image=texture_to_image,
        humanoid=humanoid,
        expressions=expressions,
        spec_version=spec_version,
        name=name,
    )


def _build_expressions(vrm, gltf, mesh_items, node_by_index, out) -> None:
    """Populate ``out`` with preset/custom expression morph binds.

    Handles both VRM 1.0 (``expressions.preset``) and VRM 0.x
    (``blendShapeMaster.blendShapeGroups``).
    """
    mesh_items_by_node: dict[int, list[int]] = {}
    mesh_items_by_mesh: dict[int, list[int]] = {}
    for mi, item in enumerate(mesh_items):
        mesh_items_by_node.setdefault(item.node_index, []).append(mi)
        mesh_items_by_mesh.setdefault(item.mesh_index, []).append(mi)

    def resolve(node, index):
        """Return (mesh_item_index, morph_index) for a (node, target index)."""
        for mi in mesh_items_by_node.get(node, []):
            item = mesh_items[mi]
            for pi, prim in enumerate(item.primitives):
                if index < len(prim.morph_pos):
                    return mi, index
        return None

    # VRM 1.0
    exp = vrm.get("expressions")
    if exp is not None:
        def collect(group):
            if not isinstance(group, dict):
                return
            for key, obj in group.items():
                if not isinstance(obj, dict):
                    continue
                binds = []
                for b in obj.get("morphTargetBinds") or []:
                    res = resolve(b.get("node"), b.get("index"))
                    if res is not None:
                        binds.append(ExpressionBind(res[0], res[1], _norm_weight(b.get("weight"))))
                if binds:
                    out.setdefault(key, []).extend(binds)
        collect(exp.get("preset"))
        # custom expressions (list of {name, morphTargetBinds,...})
        for obj in exp.get("custom") or []:
            if isinstance(obj, dict):
                binds = []
                for b in obj.get("morphTargetBinds") or []:
                    res = resolve(b.get("node"), b.get("index"))
                    if res is not None:
                        binds.append(ExpressionBind(res[0], res[1], _norm_weight(b.get("weight"))))
                if binds:
                    out.setdefault(obj.get("name", ""), []).extend(binds)
        return

    # VRM 0.x
    bsm = vrm.get("blendShapeMaster")
    if bsm is not None:
        for grp in bsm.get("blendShapeGroups") or []:
            binds = []
            for b in grp.get("binds") or []:
                mesh_idx = b.get("mesh")
                index = b.get("index")
                for mi in mesh_items_by_mesh.get(mesh_idx, []):
                    item = mesh_items[mi]
                    for prim in item.primitives:
                        if index < len(prim.morph_pos):
                            binds.append(ExpressionBind(mi, index, _norm_weight(b.get("weight"))))
                            break
                    break
            key = grp.get("presetName") or grp.get("name") or ""
            if binds:
                out.setdefault(key, []).extend(binds)
