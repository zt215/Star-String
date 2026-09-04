"""Minimal glTF/GLB reader used by the VRM renderer.

Loads a ``.vrm`` (GLB container) via pygltflib and exposes accessor
buffer data as numpy arrays.  Only dense accessors backed by the GLB
binary chunk are fully supported; sparse accessors are read best-effort.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pygltflib

# glTF componentType -> numpy dtype
_COMPONENT_DTYPE: dict[int, np.dtype] = {
    5120: np.dtype(np.int8),
    5121: np.dtype(np.uint8),
    5122: np.dtype(np.int16),
    5123: np.dtype(np.uint16),
    5125: np.dtype(np.uint32),
    5126: np.dtype(np.float32),
}

# glTF accessor type -> number of components
_NUM_COMPONENTS: dict[str, int] = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


class GLB:
    """A loaded GLB together with its binary chunk."""

    def __init__(self, gltf: pygltflib.GLTF2, binary_blob: bytes) -> None:
        self.gltf = gltf
        self.binary_blob = binary_blob


def load(path: str | Path) -> GLB:
    """Load a .vrm/.glb file. Returns a :class:`GLB`."""
    gltf = pygltflib.GLTF2().load_binary(str(path))
    return GLB(gltf, gltf.binary_blob())


def _read_sparse(
    gltf: pygltflib.GLTF2,
    blob: bytes,
    accessor,
    dtype: np.dtype,
    ncomp: int,
    count: int,
) -> np.ndarray:
    """Read a sparse accessor (used for morph-target deltas).

    ``out = base`` (zeros when ``bufferView`` is None), then the ``count``
    sparse indices receive the ``count`` sparse values.
    """
    sparse = accessor.sparse
    out = np.zeros((count, ncomp), dtype=dtype)

    # base values (often fully zero for morph targets)
    if accessor.bufferView is not None:
        bv = gltf.bufferViews[accessor.bufferView]
        item = np.dtype(dtype).itemsize * ncomp
        off = (bv.byteOffset or 0) + (accessor.byteOffset or 0)
        base = np.frombuffer(blob, dtype=dtype, count=count * ncomp, offset=off)
        out[:] = base.reshape(count, ncomp)

    # sparse indices
    ind = sparse.indices
    iv = gltf.bufferViews[ind.bufferView]
    idtype = _COMPONENT_DTYPE[ind.componentType]
    ioff = (iv.byteOffset or 0) + (ind.byteOffset or 0)
    idx = np.frombuffer(blob, dtype=idtype, count=sparse.count, offset=ioff).astype(np.int64)

    # sparse values (componentType is inherited from the parent accessor)
    val = sparse.values
    vv = gltf.bufferViews[val.bufferView]
    vdtype = _COMPONENT_DTYPE[accessor.componentType]
    voff = (vv.byteOffset or 0) + (val.byteOffset or 0)
    vals = np.frombuffer(blob, dtype=vdtype, count=sparse.count * ncomp, offset=voff).reshape(sparse.count, ncomp)

    out[idx] = vals
    return out


def read_accessor(glb: GLB, index: int) -> np.ndarray:
    """Read accessor ``index`` as a ``(count, ncomp)`` numpy array."""
    gltf = glb.gltf
    blob = glb.binary_blob
    acc = gltf.accessors[index]
    comp = _COMPONENT_DTYPE[acc.componentType]
    ncomp = _NUM_COMPONENTS[acc.type]
    count = acc.count

    if acc.sparse is not None:
        return _read_sparse(gltf, blob, acc, comp, ncomp, count)
    if acc.bufferView is None:
        # A NULL bufferView means all-zero (or the accessor has no data).
        return np.zeros((count, ncomp), dtype=comp)

    bv = gltf.bufferViews[acc.bufferView]
    dtype = np.dtype(comp)
    item_size = dtype.itemsize * ncomp
    offset = (bv.byteOffset or 0) + (acc.byteOffset or 0)
    stride = bv.byteStride or item_size

    if stride == item_size:
        data = np.frombuffer(blob, dtype=comp, count=count * ncomp, offset=offset)
        return data.reshape(count, ncomp)

    # Interleaved: read element by element.
    out = np.empty((count, ncomp), dtype=comp)
    for i in range(count):
        start = offset + i * stride
        out[i] = np.frombuffer(blob, dtype=comp, count=ncomp, offset=start)
    return out


def _mat4_from_dtype(values: np.ndarray) -> np.ndarray:
    """glTF MAT4 accessors are column-major; convert to row-major (4,4)."""
    if values.ndim == 2 and values.shape[1] == 16:
        return values.reshape(-1, 4, 4).transpose(0, 2, 1).copy()
    return values
