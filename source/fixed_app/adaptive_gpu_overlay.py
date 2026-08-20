"""Persistent GPU rendering for adaptive Full Spectrum paint trees.

The 1.5 hotfix composited every subdivided triangle with PIL after each paint
operation and deliberately hid that composite while the camera was moving.
That made the display progressively slower and caused painted details to
appear to revert during an orbit.  This module expands only the sparse adaptive
trees into a small, cached GPU mesh.  The original 450k-face mesh, face-ID map,
and Orca ``paint_color`` tree remain unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import weakref
from typing import Any

import numpy as np
from PIL import Image

import smooth_paint


GPU_OVERLAY_INFO_KEY = "tripo_spectrum_adaptive_gpu_revision"
_VERTEX_FLOATS = 9
_VERTEX_STRIDE = _VERTEX_FLOATS * np.dtype(np.float32).itemsize
# One completely split depth-6 root has 4**6 leaves / 12,288 vertices.  A page
# of this size keeps the normal path to one or a few draw calls while allowing
# every changed root to be updated independently.
_PAGE_VERTEX_FLOOR = 12_288
# Repacking a few roots would throw away useful stable allocations.  At this
# scale, however, thousands of individual ``buffer.write`` calls cost far more
# than rebuilding the sparse pages once.  Keep the threshold deliberately
# above ordinary interactive edits.
_BULK_REBUILD_ROOT_THRESHOLD = 256
_BULK_CHUNK_BATCH_ROOTS = 2_048
_FAST_MIDPOINT_MAX_DEPTH = 3


def _build_midpoint_triangle_templates() -> np.ndarray:
    """Return root-barycentric triangles for every four-way path to depth 3."""

    levels = [np.eye(3, dtype=np.float64)[None, :, :]]
    current = levels[0]
    for _depth in range(_FAST_MIDPOINT_MAX_DEPTH):
        a = current[:, 0]
        b = current[:, 1]
        c = current[:, 2]
        ab = 0.5 * (a + b)
        bc = 0.5 * (b + c)
        ca = 0.5 * (c + a)
        following = np.stack(
            (
                np.stack((a, ab, ca), axis=1),
                np.stack((ab, b, bc), axis=1),
                np.stack((bc, c, ca), axis=1),
                np.stack((ab, bc, ca), axis=1),
            ),
            axis=1,
        ).reshape(-1, 3, 3)
        levels.append(following)
        current = following
    templates = np.concatenate(levels, axis=0)
    templates.setflags(write=False)
    return templates


_MIDPOINT_TRIANGLE_TEMPLATES = _build_midpoint_triangle_templates()
_MIDPOINT_DEPTH_OFFSETS = (0, 1, 5, 21)


def _release(resource: Any) -> None:
    if resource is None:
        return
    release = getattr(resource, "release", None)
    if callable(release):
        try:
            release()
        except Exception:
            pass


def _palette_token(palette: Any) -> tuple[object, ...]:
    secondary = getattr(palette, "secondary_mix_ratios_b", [67] * 6)
    return (
        tuple(str(value).upper() for value in palette.physical_hex),
        tuple(
            None if value is None else str(value).upper()
            for value in palette.mix_hex_overrides
        ),
        tuple(int(value) for value in palette.mix_ratios_b),
        tuple(int(value) for value in secondary),
    )


def _palette_rgb(palette: Any, mixer_module: Any) -> np.ndarray:
    arguments = [
        list(palette.physical_hex),
        list(palette.mix_hex_overrides),
        list(palette.mix_ratios_b),
    ]
    if hasattr(palette, "secondary_mix_ratios_b"):
        arguments.append(list(palette.secondary_mix_ratios_b))
    _hex_values, rgb = mixer_module.build_palette_rgb(*arguments)
    values = np.asarray(rgb, dtype=np.float32)
    if float(values.max(initial=0.0)) > 1.5:
        values = values / np.float32(255.0)
    return np.clip(values, 0.0, 1.0).astype(np.float32, copy=False)


def _root_palette_key(
    face: int,
    palette_key: tuple[object, ...],
    face_part_ids: np.ndarray | None,
    part_palette_keys: tuple[tuple[object, ...], ...] | None,
) -> tuple[object, ...]:
    """Return the cache key for one root without touching the common path."""

    if face_part_ids is None or part_palette_keys is None:
        return palette_key
    face_index = int(face)
    if face_index < 0 or face_index >= len(face_part_ids):
        raise ValueError("adaptive root face is outside face_part_ids")
    part_index = int(face_part_ids[face_index])
    if part_index < 0 or part_index >= len(part_palette_keys):
        raise ValueError("face_part_ids references a missing part palette")
    return part_palette_keys[part_index]


def _root_palette_rgb(
    face: int,
    palette_rgb: np.ndarray,
    face_part_ids: np.ndarray | None,
    part_palette_rgb_tables: np.ndarray | None,
) -> np.ndarray:
    if face_part_ids is None or part_palette_rgb_tables is None:
        return palette_rgb
    face_index = int(face)
    if face_index < 0 or face_index >= len(face_part_ids):
        raise ValueError("adaptive root face is outside face_part_ids")
    part_index = int(face_part_ids[face_index])
    if part_index < 0 or part_index >= len(part_palette_rgb_tables):
        raise ValueError("face_part_ids references a missing part palette")
    return part_palette_rgb_tables[part_index]


def build_root_overlay_chunk(
    vertices: np.ndarray,
    faces: np.ndarray,
    face: int,
    node: smooth_paint.PaintNode,
    palette_rgb: np.ndarray,
) -> np.ndarray:
    """Return interleaved position/normal/colour vertices for one root face."""

    vertex_values = np.asarray(vertices, dtype=np.float32)
    face_values = np.asarray(faces, dtype=np.int64)
    face_index = int(face)
    if face_index < 0 or face_index >= len(face_values) or node.is_leaf:
        return np.empty((0, 9), dtype=np.float32)
    colors = np.asarray(palette_rgb, dtype=np.float32)
    if colors.ndim != 2 or colors.shape[1] != 3 or len(colors) < 1:
        raise ValueError(
            "palette_rgb must have shape (N, 3) with at least one state"
        )

    root = vertex_values[face_values[face_index]]
    normal = np.cross(root[1] - root[0], root[2] - root[0])
    length = float(np.linalg.norm(normal))
    if not np.isfinite(length) or length <= 1.0e-12:
        return np.empty((0, 9), dtype=np.float32)
    normal = (normal / length).astype(np.float32, copy=False)

    leaves = tuple(smooth_paint.iter_leaf_triangles(node, root))
    if leaves and max(int(leaf.state) for leaf in leaves) >= len(colors):
        raise ValueError("adaptive tree references a state missing from palette_rgb")
    packed = np.empty((len(leaves) * 3, 9), dtype=np.float32)
    for index, leaf in enumerate(leaves):
        start = index * 3
        packed[start : start + 3, 0:3] = np.asarray(
            leaf.vertices, dtype=np.float32
        )
        packed[start : start + 3, 3:6] = normal
        packed[start : start + 3, 6:9] = colors[int(leaf.state)]
    return packed


def _midpoint_leaf_spec(
    node: smooth_paint.PaintNode,
) -> tuple[list[int], list[int]] | None:
    """Return template indices/states for a depth-3 four-way tree.

    Automatic shading creates exactly this family of trees.  Anything outside
    it deliberately returns ``None`` so the general Orca subdivision routine
    remains the source of truth for two/three-child or deeper imported trees.
    """

    template_indices: list[int] = []
    states: list[int] = []
    stack: list[tuple[smooth_paint.PaintNode, int, int]] = [(node, 0, 0)]
    while stack:
        current, depth, path_code = stack.pop()
        children = current.children
        if children is None:
            try:
                state = int(current.state)
            except (TypeError, ValueError):
                return None
            if state < 0 or state >= smooth_paint.STATE_COUNT:
                return None
            template_indices.append(_MIDPOINT_DEPTH_OFFSETS[depth] + path_code)
            states.append(state)
            continue

        if (
            depth >= _FAST_MIDPOINT_MAX_DEPTH
            or current.split_sides != 3
            or current.special_side != 0
            or len(children) != 4
            or not all(isinstance(child, smooth_paint.PaintNode) for child in children)
        ):
            return None
        next_depth = depth + 1
        for child_index in range(3, -1, -1):
            stack.append(
                (
                    children[child_index],
                    next_depth,
                    path_code * 4 + child_index,
                )
            )
    return template_indices, states


def _build_root_overlay_chunks_batched(
    vertices: np.ndarray,
    faces: np.ndarray,
    roots: list[tuple[int, smooth_paint.PaintNode]],
    palette_rgb: np.ndarray,
    *,
    batch_roots: int = _BULK_CHUNK_BATCH_ROOTS,
    face_part_ids: np.ndarray | None = None,
    part_palette_rgb_tables: np.ndarray | None = None,
) -> list[np.ndarray]:
    """Build common automatic-shading chunks with batched NumPy geometry."""

    vertex_values = np.asarray(vertices, dtype=np.float32)
    face_values = np.asarray(faces, dtype=np.int64)
    colors = np.asarray(palette_rgb, dtype=np.float32)
    if colors.ndim != 2 or colors.shape[1] != 3 or len(colors) < 1:
        raise ValueError(
            "palette_rgb must have shape (N, 3) with at least one state"
        )
    count_per_batch = int(batch_roots)
    if count_per_batch <= 0:
        raise ValueError("batch_roots must be positive")

    part_ids: np.ndarray | None = None
    part_tables: np.ndarray | None = None
    if face_part_ids is not None or part_palette_rgb_tables is not None:
        if face_part_ids is None or part_palette_rgb_tables is None:
            raise ValueError(
                "face_part_ids and part_palette_rgb_tables must be provided together"
            )
        part_ids = np.asarray(face_part_ids)
        part_tables = np.asarray(part_palette_rgb_tables, dtype=np.float32)
        if (
            part_ids.ndim != 1
            or len(part_ids) != len(face_values)
            or not np.issubdtype(part_ids.dtype, np.integer)
        ):
            raise ValueError("face_part_ids must contain one integer per face")
        if (
            part_tables.ndim != 3
            or part_tables.shape[1:] != colors.shape
            or len(part_tables) < 1
        ):
            raise ValueError(
                "part_palette_rgb_tables must have shape (P, N, 3)"
            )

    root_items = list(roots)
    output = [np.empty((0, 9), dtype=np.float32) for _ in root_items]
    # Unexpected source layouts retain the exact general implementation.
    if (
        vertex_values.ndim != 2
        or vertex_values.shape[1] != 3
        or face_values.ndim != 2
        or face_values.shape[1] != 3
    ):
        return [
            build_root_overlay_chunk(
                vertex_values,
                face_values,
                face,
                node,
                _root_palette_rgb(
                    face,
                    colors,
                    part_ids,
                    part_tables,
                ),
            )
            for face, node in root_items
        ]

    for batch_start in range(0, len(root_items), count_per_batch):
        batch_stop = min(len(root_items), batch_start + count_per_batch)
        records: list[tuple[int, int, list[int], list[int], int]] = []
        for output_index in range(batch_start, batch_stop):
            face, node = root_items[output_index]
            spec = _midpoint_leaf_spec(node)
            if spec is None:
                output[output_index] = build_root_overlay_chunk(
                    vertex_values,
                    face_values,
                    face,
                    node,
                    _root_palette_rgb(
                        face,
                        colors,
                        part_ids,
                        part_tables,
                    ),
                )
                continue
            if face < 0 or face >= len(face_values) or node.is_leaf:
                continue
            template_indices, states = spec
            part_index = -1
            if part_ids is not None:
                part_index = int(part_ids[int(face)])
                if part_index < 0 or part_index >= len(part_tables):
                    raise ValueError(
                        "face_part_ids references a missing part palette"
                    )
            records.append(
                (output_index, int(face), template_indices, states, part_index)
            )
        if not records:
            continue

        face_indices = np.fromiter(
            (record[1] for record in records),
            dtype=np.int64,
            count=len(records),
        )
        root_float32 = vertex_values[face_values[face_indices]]
        normal_values = np.cross(
            root_float32[:, 1] - root_float32[:, 0],
            root_float32[:, 2] - root_float32[:, 0],
        )
        normal_lengths = np.linalg.norm(normal_values, axis=1)
        drawable = np.isfinite(normal_lengths) & (normal_lengths > 1.0e-12)
        if not bool(np.any(drawable)):
            continue
        if not bool(np.all(drawable)):
            selected = np.flatnonzero(drawable)
            records = [records[int(index)] for index in selected]
            root_float32 = root_float32[selected]
            normal_values = normal_values[selected]
            normal_lengths = normal_lengths[selected]

        normals = (
            normal_values / normal_lengths[:, None]
        ).astype(np.float32, copy=False)
        root_float64 = root_float32.astype(np.float64)
        leaf_counts = np.fromiter(
            (len(record[2]) for record in records),
            dtype=np.int64,
            count=len(records),
        )
        total_leaves = int(leaf_counts.sum())
        owners = np.repeat(
            np.arange(len(records), dtype=np.int64),
            leaf_counts,
        )
        template_indices = np.fromiter(
            (
                template_index
                for record in records
                for template_index in record[2]
            ),
            dtype=np.int16,
            count=total_leaves,
        )
        states = np.fromiter(
            (state for record in records for state in record[3]),
            dtype=np.int16,
            count=total_leaves,
        )
        positions = np.einsum(
            "lij,ljk->lik",
            _MIDPOINT_TRIANGLE_TEMPLATES[template_indices],
            root_float64[owners],
            optimize=True,
        ).astype(np.float32, copy=False)
        packed = np.empty((total_leaves, 3, _VERTEX_FLOATS), dtype=np.float32)
        packed[:, :, 0:3] = positions
        packed[:, :, 3:6] = normals[owners, None, :]
        if len(states) and int(states.max()) >= len(colors):
            raise ValueError(
                "adaptive tree references a state missing from palette_rgb"
            )
        if part_tables is None:
            packed[:, :, 6:9] = colors[states, None, :]
        else:
            leaf_part_ids = np.repeat(
                np.fromiter(
                    (record[4] for record in records),
                    dtype=np.int64,
                    count=len(records),
                ),
                leaf_counts,
            )
            packed[:, :, 6:9] = part_tables[
                leaf_part_ids, states, None, :
            ]

        leaf_offset = 0
        for record, leaf_count in zip(records, leaf_counts, strict=True):
            following = leaf_offset + int(leaf_count)
            output[record[0]] = packed[leaf_offset:following].reshape(-1, _VERTEX_FLOATS)
            leaf_offset = following
    return output


def image_has_gpu_overlay(image: Image.Image | None) -> bool:
    return bool(
        image is not None and GPU_OVERLAY_INFO_KEY in getattr(image, "info", {})
    )


def _palette_usage_focus_table(
    table: np.ndarray,
    state: int,
    *,
    highlight: bool,
) -> np.ndarray:
    """Apply the manual editor's display-only focus to one small RGB LUT."""

    values = np.asarray(table, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("palette usage focus requires an Nx3 RGB table")
    selected_state = int(state)
    if selected_state < 0 or selected_state >= len(values):
        raise ValueError("palette usage focus references a missing state")
    muted = np.asarray((0.075, 0.085, 0.10), dtype=np.float32)
    accent = np.asarray((0.22, 0.88, 1.0), dtype=np.float32)
    focused = np.clip(muted[None, :] + values * 0.10, 0.0, 1.0)
    if highlight:
        focused[selected_state] = np.clip(
            values[selected_state] * 0.72 + accent * 0.28,
            0.0,
            1.0,
        )
    return np.ascontiguousarray(focused, dtype=np.float32)


def _reserved_vertices(vertex_count: int) -> int:
    """Round a root allocation to a power-of-two triangle bucket."""

    triangles = max(1, (int(vertex_count) + 2) // 3)
    bucket = 1 << (triangles - 1).bit_length()
    return bucket * 3


@dataclass(eq=False)
class _OverlayAllocation:
    page: "_OverlayPage"
    offset_vertices: int
    capacity_vertices: int
    count_vertices: int = 0


@dataclass(eq=False)
class _OverlayPage:
    buffer: Any
    vao: Any
    capacity_vertices: int
    free_ranges: list[tuple[int, int]]
    allocations: set[_OverlayAllocation] = field(default_factory=set)


class _OverlayArena:
    """Sparse, zero-filled GPU pages for adaptive root chunks.

    Holes are kept as degenerate zero-area triangles.  Consequently each page
    is one draw call, while an ordinary root replacement needs only one local
    ``buffer.write`` and never concatenates or uploads all existing leaves.
    """

    def __init__(
        self,
        context: Any,
        program: Any,
        vertices: np.ndarray,
        faces: np.ndarray,
        *,
        page_vertex_floor: int = _PAGE_VERTEX_FLOOR,
    ) -> None:
        self.context = context
        self.program = program
        self.vertices = vertices
        self.faces = faces
        self.page_vertex_floor = _reserved_vertices(page_vertex_floor)
        self.pages: list[_OverlayPage] = []
        # Tuple prefix remains compatible with the 1.5 cache probes:
        # (strong PaintNode identity, palette token, CPU chunk, allocation).
        self.chunks: dict[
            int,
            tuple[
                smooth_paint.PaintNode,
                tuple[object, ...],
                np.ndarray,
                _OverlayAllocation,
            ],
        ] = {}
        self.vertex_count = 0
        self.rebuilt_roots = 0
        self.uploaded_bytes = 0
        self.full_upload_bytes = 0
        self.partial_upload_bytes = 0
        self.partial_write_calls = 0
        self.created_pages = 0
        self.released_pages = 0

    def _reset_stats(self) -> None:
        self.rebuilt_roots = 0
        self.uploaded_bytes = 0
        self.full_upload_bytes = 0
        self.partial_upload_bytes = 0
        self.partial_write_calls = 0
        self.created_pages = 0
        self.released_pages = 0

    def _create_page(
        self,
        required_vertices: int,
        *,
        zero_initialize: bool = True,
    ) -> _OverlayPage:
        capacity = max(
            self.page_vertex_floor,
            _reserved_vertices(required_vertices),
        )
        byte_count = capacity * _VERTEX_STRIDE
        buffer = None
        vao = None
        try:
            # Normal incremental pages start zeroed so every unallocated range
            # is a collection of degenerate triangles.  Bulk rebuilds reserve
            # storage here and upload one complete zero-padded CPU page after
            # all root allocations have been packed.
            if zero_initialize:
                buffer = self.context.buffer(bytes(byte_count), dynamic=True)
            else:
                buffer = self.context.buffer(reserve=byte_count, dynamic=True)
            vao = self.context.vertex_array(
                self.program,
                [
                    (
                        buffer,
                        "3f 3f 3f",
                        "in_position",
                        "in_normal",
                        "in_color",
                    )
                ],
            )
        except Exception:
            _release(vao)
            _release(buffer)
            raise
        page = _OverlayPage(buffer, vao, capacity, [(0, capacity)])
        self.pages.append(page)
        self.created_pages += 1
        if zero_initialize:
            self.full_upload_bytes += byte_count
            self.uploaded_bytes += byte_count
        return page

    @staticmethod
    def _take_range(page: _OverlayPage, needed: int) -> int | None:
        best_index = -1
        best_length: int | None = None
        for index, (_offset, length) in enumerate(page.free_ranges):
            if length < needed:
                continue
            if best_length is None or length < best_length:
                best_index = index
                best_length = length
        if best_index < 0:
            return None
        offset, length = page.free_ranges.pop(best_index)
        if length > needed:
            page.free_ranges.append((offset + needed, length - needed))
            page.free_ranges.sort()
        return offset

    def _allocate(
        self,
        vertex_count: int,
        *,
        zero_initialize_new_pages: bool = True,
    ) -> _OverlayAllocation:
        needed = _reserved_vertices(vertex_count)
        candidates = sorted(
            self.pages,
            key=lambda page: min(
                (length for _offset, length in page.free_ranges if length >= needed),
                default=2**63 - 1,
            ),
        )
        for page in candidates:
            offset = self._take_range(page, needed)
            if offset is not None:
                allocation = _OverlayAllocation(page, offset, needed)
                page.allocations.add(allocation)
                return allocation
        page = self._create_page(
            needed,
            zero_initialize=zero_initialize_new_pages,
        )
        offset = self._take_range(page, needed)
        if offset is None:  # Defensive: the new page is sized for this root.
            raise RuntimeError("GPU overlay page allocation failed")
        allocation = _OverlayAllocation(page, offset, needed)
        page.allocations.add(allocation)
        return allocation

    def _write_bytes(self, allocation: _OverlayAllocation, data: bytes, offset: int) -> None:
        allocation.page.buffer.write(
            data,
            offset=(allocation.offset_vertices + offset) * _VERTEX_STRIDE,
        )
        self.partial_write_calls += 1
        self.partial_upload_bytes += len(data)
        self.uploaded_bytes += len(data)

    def _write_chunk(
        self, allocation: _OverlayAllocation, chunk: np.ndarray
    ) -> None:
        count = int(len(chunk))
        if count > allocation.capacity_vertices:
            raise RuntimeError("GPU overlay allocation is smaller than its chunk")
        contiguous = np.ascontiguousarray(chunk, dtype=np.float32)
        self._write_bytes(allocation, contiguous.tobytes(), 0)
        if allocation.count_vertices > count:
            stale = allocation.count_vertices - count
            self._write_bytes(allocation, bytes(stale * _VERTEX_STRIDE), count)
        allocation.count_vertices = count

    def _write_full_page(self, page: _OverlayPage, packed: np.ndarray) -> None:
        values = np.ascontiguousarray(packed, dtype=np.float32)
        if values.shape != (page.capacity_vertices, _VERTEX_FLOATS):
            raise RuntimeError("GPU overlay full-page upload has an invalid shape")
        data = values.tobytes()
        page.buffer.write(data, offset=0)
        self.full_upload_bytes += len(data)
        self.uploaded_bytes += len(data)

    def _bulk_rebuild(
        self,
        desired: dict[int, smooth_paint.PaintNode],
        palette_key: tuple[object, ...],
        palette_rgb: np.ndarray,
        face_part_ids: np.ndarray | None = None,
        part_palette_rgb_tables: np.ndarray | None = None,
        part_palette_keys: tuple[tuple[object, ...], ...] | None = None,
    ) -> None:
        """Pack every desired root and upload each new page exactly once."""

        invalid_items = [
            (face, node)
            for face, node in desired.items()
            if (
                (cached := self.chunks.get(face)) is None
                or cached[0] is not node
                or cached[1]
                != _root_palette_key(
                    face,
                    palette_key,
                    face_part_ids,
                    part_palette_keys,
                )
            )
        ]
        generated = _build_root_overlay_chunks_batched(
            self.vertices,
            self.faces,
            invalid_items,
            palette_rgb,
            face_part_ids=face_part_ids,
            part_palette_rgb_tables=part_palette_rgb_tables,
        )
        generated_chunks = {
            face: chunk
            for (face, _node), chunk in zip(invalid_items, generated, strict=True)
        }
        self.rebuilt_roots += len(invalid_items)
        prepared: list[
            tuple[
                int,
                smooth_paint.PaintNode,
                tuple[object, ...],
                np.ndarray,
            ]
        ] = []
        for face, node in desired.items():
            root_palette_key = _root_palette_key(
                face,
                palette_key,
                face_part_ids,
                part_palette_keys,
            )
            cached = self.chunks.get(face)
            if (
                cached is not None
                and cached[0] is node
                and cached[1] == root_palette_key
            ):
                chunk = cached[2]
            else:
                chunk = generated_chunks[face]
            if len(chunk):
                prepared.append((face, node, root_palette_key, chunk))

        old_pages = self.pages
        old_chunks = self.chunks
        self.pages = []
        self.chunks = {}
        try:
            for face, node, root_palette_key, chunk in prepared:
                allocation = self._allocate(
                    len(chunk),
                    zero_initialize_new_pages=False,
                )
                allocation.count_vertices = int(len(chunk))
                self.chunks[face] = (
                    node,
                    root_palette_key,
                    chunk,
                    allocation,
                )

            page_payloads = [
                np.zeros(
                    (page.capacity_vertices, _VERTEX_FLOATS),
                    dtype=np.float32,
                )
                for page in self.pages
            ]
            page_indices = {id(page): index for index, page in enumerate(self.pages)}
            for _face, (_node, _token, chunk, allocation) in self.chunks.items():
                start = allocation.offset_vertices
                stop = start + int(len(chunk))
                page_payloads[page_indices[id(allocation.page)]][start:stop] = chunk
            for page, payload in zip(self.pages, page_payloads):
                self._write_full_page(page, payload)
        except Exception:
            for page in self.pages:
                _release(page.vao)
                _release(page.buffer)
            self.pages = old_pages
            self.chunks = old_chunks
            raise

        for page in old_pages:
            _release(page.vao)
            _release(page.buffer)
            self.released_pages += 1

    @staticmethod
    def _return_range(page: _OverlayPage, offset: int, length: int) -> None:
        ranges = sorted(page.free_ranges + [(int(offset), int(length))])
        merged: list[tuple[int, int]] = []
        for current_offset, current_length in ranges:
            if merged and merged[-1][0] + merged[-1][1] == current_offset:
                previous_offset, previous_length = merged[-1]
                merged[-1] = (previous_offset, previous_length + current_length)
            else:
                merged.append((current_offset, current_length))
        page.free_ranges = merged

    def _free_allocation(self, allocation: _OverlayAllocation) -> None:
        if allocation.count_vertices:
            self._write_bytes(
                allocation,
                bytes(allocation.count_vertices * _VERTEX_STRIDE),
                0,
            )
        allocation.page.allocations.discard(allocation)
        self._return_range(
            allocation.page,
            allocation.offset_vertices,
            allocation.capacity_vertices,
        )
        allocation.count_vertices = 0

    def _release_empty_pages(self) -> None:
        active: list[_OverlayPage] = []
        for page in self.pages:
            if page.allocations:
                active.append(page)
                continue
            _release(page.vao)
            _release(page.buffer)
            self.released_pages += 1
        self.pages = active

    def sync(
        self,
        store: dict[int, smooth_paint.PaintNode],
        palette_key: tuple[object, ...],
        palette_rgb: np.ndarray,
        *,
        face_part_ids: np.ndarray | None = None,
        part_palette_rgb_tables: np.ndarray | None = None,
        part_palette_keys: tuple[tuple[object, ...], ...] | None = None,
    ) -> bool:
        """Synchronize changed roots and return whether anything is drawable."""

        self._reset_stats()
        if (
            face_part_ids is None
            or part_palette_rgb_tables is None
            or part_palette_keys is None
        ):
            if any(
                value is not None
                for value in (
                    face_part_ids,
                    part_palette_rgb_tables,
                    part_palette_keys,
                )
            ):
                raise ValueError(
                    "multipart palette routing arguments must be provided together"
                )
            face_part_ids = None
            part_palette_rgb_tables = None
            part_palette_keys = None
        desired = {
            int(face): node
            for face, node in tuple(store.items())
            if not node.is_leaf
        }

        invalid_roots = sum(
            1
            for face, node in desired.items()
            if (
                (cached := self.chunks.get(face)) is None
                or cached[0] is not node
                or cached[1]
                != _root_palette_key(
                    face,
                    palette_key,
                    face_part_ids,
                    part_palette_keys,
                )
            )
        )
        if (
            invalid_roots > _BULK_REBUILD_ROOT_THRESHOLD
            and invalid_roots * 2 > len(desired)
        ):
            self._bulk_rebuild(
                desired,
                palette_key,
                palette_rgb,
                face_part_ids,
                part_palette_rgb_tables,
                part_palette_keys,
            )
            self.vertex_count = int(
                sum(len(value[2]) for value in self.chunks.values())
            )
            return bool(self.chunks)

        # Remove first so additions can reuse their zeroed ranges.
        for face in tuple(self.chunks):
            if face in desired:
                continue
            old = self.chunks.pop(face)
            self._free_allocation(old[3])

        for face, node in desired.items():
            root_palette_key = _root_palette_key(
                face,
                palette_key,
                face_part_ids,
                part_palette_keys,
            )
            cached = self.chunks.get(face)
            if (
                cached is not None
                and cached[0] is node
                and cached[1] == root_palette_key
            ):
                continue

            chunk = build_root_overlay_chunk(
                self.vertices,
                self.faces,
                face,
                node,
                _root_palette_rgb(
                    face,
                    palette_rgb,
                    face_part_ids,
                    part_palette_rgb_tables,
                ),
            )
            self.rebuilt_roots += 1
            if len(chunk) == 0:
                if cached is not None:
                    self._free_allocation(cached[3])
                    self.chunks.pop(face, None)
                continue

            if cached is not None and len(chunk) <= cached[3].capacity_vertices:
                allocation = cached[3]
                self._write_chunk(allocation, chunk)
            else:
                # Allocate and upload the replacement before clearing the old
                # range.  If allocation fails, the caller discards the whole
                # arena, never exposing half-moved geometry.
                allocation = self._allocate(len(chunk))
                self._write_chunk(allocation, chunk)
                if cached is not None:
                    self._free_allocation(cached[3])
            self.chunks[face] = (node, root_palette_key, chunk, allocation)

        self._release_empty_pages()
        self.vertex_count = int(sum(len(value[2]) for value in self.chunks.values()))
        return bool(self.chunks)

    def release(self) -> None:
        for page in self.pages:
            _release(page.vao)
            _release(page.buffer)
        self.pages.clear()
        self.chunks.clear()
        self.vertex_count = 0


def install_gpu_overlay(
    renderer_module: Any,
    mixer_module: Any,
    context_provider: Callable[[Any], tuple[dict[int, smooth_paint.PaintNode], int] | None],
) -> Any:
    """Patch ``InteractiveMeshRenderer`` with a persistent adaptive mesh pass."""

    renderer_class = renderer_module.InteractiveMeshRenderer
    if bool(getattr(renderer_class, "_adaptive_gpu_overlay_applied", False)):
        return renderer_class

    original_init = renderer_class.__init__
    original_render_color = renderer_class._render_color_image
    original_release_resources = renderer_class._release_resources

    def init_with_overlay(self, level, *args, **kwargs):
        original_init(self, level, *args, **kwargs)
        try:
            self._hotfix_overlay_level_ref = weakref.ref(level)
        except TypeError:
            self._hotfix_overlay_level_ref = lambda: level
        self._hotfix_overlay_arena = _OverlayArena(
            self._context,
            self._program,
            self._vertices,
            self._faces,
        )
        self._hotfix_overlay_pages = []
        self._hotfix_overlay_buffer = None
        self._hotfix_overlay_vao = None
        self._hotfix_overlay_token = None
        self._hotfix_overlay_error_token = None
        self._hotfix_overlay_chunks = {}
        self._hotfix_overlay_vertex_count = 0
        self._hotfix_overlay_rebuilt_roots = 0
        self._hotfix_overlay_uploaded_bytes = 0
        self._hotfix_overlay_full_upload_bytes = 0
        self._hotfix_overlay_partial_upload_bytes = 0
        self._hotfix_overlay_partial_write_calls = 0
        self._hotfix_overlay_created_pages = 0
        self._hotfix_overlay_released_pages = 0
        self._hotfix_overlay_face_part_source = None

    def publish_arena(self) -> None:
        arena = getattr(self, "_hotfix_overlay_arena", None)
        pages = list(arena.pages) if arena is not None else []
        self._hotfix_overlay_pages = pages
        self._hotfix_overlay_buffer = pages[0].buffer if pages else None
        self._hotfix_overlay_vao = pages[0].vao if pages else None
        self._hotfix_overlay_chunks = arena.chunks if arena is not None else {}
        self._hotfix_overlay_vertex_count = (
            int(arena.vertex_count) if arena is not None else 0
        )
        self._hotfix_overlay_rebuilt_roots = (
            int(arena.rebuilt_roots) if arena is not None else 0
        )
        self._hotfix_overlay_uploaded_bytes = (
            int(arena.uploaded_bytes) if arena is not None else 0
        )
        self._hotfix_overlay_full_upload_bytes = (
            int(arena.full_upload_bytes) if arena is not None else 0
        )
        self._hotfix_overlay_partial_upload_bytes = (
            int(arena.partial_upload_bytes) if arena is not None else 0
        )
        self._hotfix_overlay_partial_write_calls = (
            int(arena.partial_write_calls) if arena is not None else 0
        )
        self._hotfix_overlay_created_pages = (
            int(arena.created_pages) if arena is not None else 0
        )
        self._hotfix_overlay_released_pages = (
            int(arena.released_pages) if arena is not None else 0
        )

    def release_overlay(self) -> None:
        arena = getattr(self, "_hotfix_overlay_arena", None)
        if arena is not None:
            arena.release()
        publish_arena(self)
        self._hotfix_overlay_token = None
        self._hotfix_overlay_error_token = None

    def release_resources_with_overlay(self):
        release_overlay(self)
        return original_release_resources(self)

    def ensure_overlay(self) -> tuple[bool, int]:
        level_ref = getattr(self, "_hotfix_overlay_level_ref", None)
        level = level_ref() if callable(level_ref) else None
        if level is None:
            return False, -1
        context_value = context_provider(level)
        palette = getattr(level, "_hotfix_palette", None)
        raw_part_tables = getattr(
            level, "_hotfix_part_palette_rgb_tables", None
        )
        raw_face_part_ids = getattr(level, "_hotfix_face_part_ids", None)
        focus_state = getattr(self, "_palette_usage_focus_state", None)
        focus_part_id = getattr(self, "_palette_usage_focus_part_id", None)
        if focus_state is not None:
            renderer_part_ids = np.asarray(
                getattr(self, "_face_part_ids", np.zeros(len(self._faces))),
                dtype=np.int64,
            )
            if renderer_part_ids.shape != (len(self._faces),):
                raise ValueError(
                    "palette usage focus requires one part ID per face"
                )
            part_count = max(
                1,
                (
                    int(renderer_part_ids.max()) + 1
                    if len(renderer_part_ids)
                    else 1
                ),
            )
            if raw_part_tables is None:
                if palette is None:
                    return False, -1
                base_table = np.asarray(
                    _palette_rgb(palette, mixer_module),
                    dtype=np.float32,
                )
                source_tables = np.repeat(
                    base_table[None, :, :],
                    part_count,
                    axis=0,
                )
            else:
                source_tables = np.asarray(raw_part_tables, dtype=np.float32)
                if len(source_tables) < part_count:
                    raise ValueError(
                        "palette usage focus is missing a part palette table"
                    )
            requested_part = (
                None if focus_part_id is None else int(focus_part_id)
            )
            raw_part_tables = np.stack(
                tuple(
                    _palette_usage_focus_table(
                        table,
                        int(focus_state),
                        highlight=(
                            requested_part is None
                            or part_index == requested_part
                        ),
                    )
                    for part_index, table in enumerate(source_tables)
                ),
                axis=0,
            )
            raw_face_part_ids = renderer_part_ids
        multipart_requested = (
            raw_part_tables is not None or raw_face_part_ids is not None
        )
        if context_value is None or (palette is None and not multipart_requested):
            if getattr(self, "_hotfix_overlay_pages", None):
                release_overlay(self)
            return False, -1
        store, revision = context_value

        face_part_ids = None
        part_palette_rgb_tables = None
        part_palette_keys = None
        if multipart_requested:
            if raw_part_tables is None or raw_face_part_ids is None:
                raise ValueError(
                    "multipart GPU palette tables and face part IDs are both required"
                )
            face_part_ids = np.asarray(raw_face_part_ids)
            part_palette_rgb_tables = np.asarray(
                raw_part_tables, dtype=np.float32
            )
            if (
                face_part_ids.ndim != 1
                or len(face_part_ids) != len(self._faces)
                or not np.issubdtype(face_part_ids.dtype, np.integer)
            ):
                raise ValueError(
                    "_hotfix_face_part_ids must contain one integer per face"
                )
            if (
                part_palette_rgb_tables.ndim != 3
                or part_palette_rgb_tables.shape[2] != 3
                or len(part_palette_rgb_tables) < 1
            ):
                raise ValueError(
                    "_hotfix_part_palette_rgb_tables must have shape (P, N, 3)"
                )
            if (
                not np.all(np.isfinite(part_palette_rgb_tables))
                or np.any(part_palette_rgb_tables < 0.0)
                or np.any(part_palette_rgb_tables > 1.0)
            ):
                raise ValueError(
                    "multipart GPU palette RGB values must stay in the 0..1 range"
                )
            face_part_source = (
                id(raw_face_part_ids),
                face_part_ids.shape,
                face_part_ids.dtype.str,
                len(part_palette_rgb_tables),
            )
            if face_part_source != getattr(
                self, "_hotfix_overlay_face_part_source", None
            ):
                if len(face_part_ids) and (
                    int(face_part_ids.min()) < 0
                    or int(face_part_ids.max()) >= len(part_palette_rgb_tables)
                ):
                    raise ValueError(
                        "_hotfix_face_part_ids references a missing palette table"
                    )
                self._hotfix_overlay_face_part_source = face_part_source
            # A table is only 16 x 3 float32 values.  Its exact byte token is
            # cheap to compute and guarantees that changing one part invalidates
            # only roots belonging to that part.
            part_palette_keys = tuple(
                (
                    "part-palette-rgb32",
                    part_index,
                    np.ascontiguousarray(table).tobytes(),
                )
                for part_index, table in enumerate(part_palette_rgb_tables)
            )
            palette_key = ("multipart-palettes",)
            palette_rgb = part_palette_rgb_tables[0]
            routing_key: tuple[object, ...] = (
                "multipart-palettes",
                id(raw_face_part_ids),
                part_palette_keys,
            )
        else:
            palette_key = _palette_token(palette)
            palette_rgb = _palette_rgb(palette, mixer_module)
            routing_key = palette_key

        token = (id(store), int(revision), routing_key)
        if token == getattr(self, "_hotfix_overlay_token", None):
            return bool(getattr(self, "_hotfix_overlay_pages", None)), int(revision)
        if token == getattr(self, "_hotfix_overlay_error_token", None):
            return False, int(revision)

        context = getattr(self, "_context", None)
        program = getattr(self, "_program", None)
        if context is None or program is None:
            return False, int(revision)

        arena = getattr(self, "_hotfix_overlay_arena", None)
        if arena is None:
            arena = _OverlayArena(
                context,
                program,
                self._vertices,
                self._faces,
            )
            self._hotfix_overlay_arena = arena
        try:
            available = arena.sync(
                store,
                palette_key,
                palette_rgb,
                face_part_ids=face_part_ids,
                part_palette_rgb_tables=part_palette_rgb_tables,
                part_palette_keys=part_palette_keys,
            )
        except Exception:
            # An error after one partial write must not leave a half-current
            # arena eligible for a later revision.  Release it atomically and
            # suppress repeated construction attempts for this exact token.
            arena.release()
            publish_arena(self)
            self._hotfix_overlay_error_token = token
            raise
        publish_arena(self)
        self._hotfix_overlay_token = token
        self._hotfix_overlay_error_token = None
        return bool(available), int(revision)

    def render_color_with_overlay(self, vao):
        is_target = vao is getattr(self, "_target_vao", None)
        if not is_target:
            return original_render_color(self, vao)
        # The base renderer performs a dedicated opaque + transparent pass
        # whenever manual part visibility is active.  Overlay pages do not
        # carry per-root alpha/discard attributes, so drawing them here would
        # make hidden parts reappear or make transparent parts opaque.  Fall
        # back to the visibility-aware base renderer; the CPU compositor will
        # still draw adaptive detail for ordinary visible roots only.
        if bool(getattr(self, "_visibility_active", False)):
            return original_render_color(self, vao)
        try:
            available, revision = ensure_overlay(self)
        except Exception as exc:
            self._hotfix_overlay_last_error = f"{type(exc).__name__}: {exc}"
            return original_render_color(self, vao)
        if not available:
            return original_render_color(self, vao)

        context = getattr(self, "_context", None)
        framebuffer = getattr(self, "_color_framebuffer", None)
        pages = tuple(getattr(self, "_hotfix_overlay_pages", ()))
        if context is None or framebuffer is None or not pages:
            return original_render_color(self, vao)
        try:
            framebuffer.use()
            context.viewport = (0, 0, self._size[0], self._size[1])
            clear = tuple(channel / 255.0 for channel in self._background)
            framebuffer.clear(clear[0], clear[1], clear[2], 1.0, depth=1.0)
            vao.render(mode=renderer_module.moderngl.TRIANGLES)
            try:
                # Subdivision vertices are coplanar with their source face.
                # LEQUAL alone is angle/driver dependent and lets base-colour
                # pixels win in a flickering triangular pattern.  A small
                # negative polygon offset consistently places the detail pass
                # in front while keeping the exported geometry untouched.
                context.polygon_offset = (-1.0, -1.0)
                context.depth_func = "<"
                for page in pages:
                    page.vao.render(
                        mode=renderer_module.moderngl.TRIANGLES,
                        vertices=page.capacity_vertices,
                    )
            finally:
                context.polygon_offset = (0.0, 0.0)
                context.depth_func = "<"
            pixels = framebuffer.read(components=4, alignment=1)
            image = Image.frombytes("RGBA", self._size, pixels).transpose(
                Image.Transpose.FLIP_TOP_BOTTOM
            ).convert("RGB")
            image.info[GPU_OVERLAY_INFO_KEY] = int(revision)
            return image
        except Exception as exc:
            self._hotfix_overlay_last_error = f"{type(exc).__name__}: {exc}"
            return original_render_color(self, vao)

    renderer_class.__init__ = init_with_overlay
    renderer_class._release_resources = release_resources_with_overlay
    renderer_class._render_color_image = render_color_with_overlay
    renderer_class._adaptive_gpu_overlay_applied = True
    return renderer_class


__all__ = [
    "GPU_OVERLAY_INFO_KEY",
    "build_root_overlay_chunk",
    "image_has_gpu_overlay",
    "install_gpu_overlay",
]
