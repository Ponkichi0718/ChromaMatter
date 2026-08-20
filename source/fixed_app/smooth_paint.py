"""Adaptive, screen-space painting compatible with OrcaSlicer ``paint_color``.

The application's original brush stores one colour per source triangle.  This
module keeps the source mesh unchanged and stores a sparse subdivision tree for
only the triangles that need a finer paint boundary.  New subdivisions always
use Orca's four-child midpoint layout, while the decoder also understands the
two- and three-child layouts that Orca may write itself.

Public colour states are zero based (0..15).  Orca stores those as Extruder1 ..
Extruder32.  States above ten use Orca's existing base-15 extension nibbles;
the mesh and subdivision-tree format itself is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from enum import IntEnum
import math
from typing import Literal

import numpy as np


STATE_COUNT = 32
MAX_DEPTH = 6
_HEX_DIGITS = "0123456789ABCDEF"
_EPSILON = 1.0e-9


class SmoothPaintError(ValueError):
    """Base class for invalid adaptive-paint data or geometry."""


class PaintColorCodecError(SmoothPaintError):
    """Raised when an Orca ``paint_color`` string cannot be decoded."""


def _validate_state(state: int) -> int:
    value = int(state)
    if value < 0 or value >= STATE_COUNT:
        raise SmoothPaintError(f"paint state must be in 0..{STATE_COUNT - 1}: {state!r}")
    return value


@dataclass(slots=True)
class PaintNode:
    """One node in an Orca-compatible triangle subdivision tree.

    ``children`` are always stored in Orca's geometric child order.  A leaf has
    a state and no children.  An internal node has two, three, or four children
    and ``split_sides == len(children) - 1``.  Brush-created nodes always use
    four children (``split_sides == 3``); the other forms exist so that an Orca
    project can be decoded and re-encoded without changing its tree.
    """

    state: int | None = 0
    children: tuple["PaintNode", ...] | None = None
    split_sides: int = 0
    special_side: int = 0

    def __post_init__(self) -> None:
        if self.children is None:
            if self.state is None:
                raise SmoothPaintError("a leaf PaintNode requires a state")
            self.state = _validate_state(self.state)
            self.split_sides = 0
            self.special_side = 0
            return

        self.children = tuple(self.children)
        inferred = len(self.children) - 1
        if self.split_sides == 0:
            self.split_sides = inferred
        if self.split_sides not in (1, 2, 3):
            raise SmoothPaintError("split_sides must be 1, 2, or 3 for an internal node")
        if inferred != self.split_sides:
            raise SmoothPaintError(
                f"split_sides={self.split_sides} requires {self.split_sides + 1} children"
            )
        if self.special_side not in (0, 1, 2):
            raise SmoothPaintError("special_side must be 0, 1, or 2")
        if self.split_sides == 3 and self.special_side != 0:
            raise SmoothPaintError("a three-side split must use special_side=0")
        if not all(isinstance(child, PaintNode) for child in self.children):
            raise SmoothPaintError("all children must be PaintNode instances")
        self.state = None

    @property
    def is_leaf(self) -> bool:
        return self.children is None

    @classmethod
    def branch(
        cls,
        children: tuple["PaintNode", ...] | list["PaintNode"],
        *,
        split_sides: int | None = None,
        special_side: int = 0,
    ) -> "PaintNode":
        values = tuple(children)
        sides = len(values) - 1 if split_sides is None else int(split_sides)
        return cls(None, values, sides, special_side)

    def clone(self) -> "PaintNode":
        """Return a deep copy suitable for an undo snapshot."""

        if self.children is None:
            return PaintNode(int(self.state))
        return PaintNode.branch(
            tuple(child.clone() for child in self.children),
            split_sides=self.split_sides,
            special_side=self.special_side,
        )

    def make_leaf(self, state: int) -> bool:
        """Replace this subtree with one leaf; return whether it changed."""

        requested = _validate_state(state)
        if self.children is None and self.state == requested:
            return False
        self.state = requested
        self.children = None
        self.split_sides = 0
        self.special_side = 0
        return True

    def split_four(self) -> bool:
        """Split a leaf into Orca's four midpoint children.

        Existing internal nodes are retained and return ``False``.  All new
        children inherit the former leaf state.
        """

        if self.children is not None:
            return False
        inherited = int(self.state)
        self.state = None
        self.children = tuple(PaintNode(inherited) for _ in range(4))
        self.split_sides = 3
        self.special_side = 0
        return True

    def collapse(self) -> "PaintNode":
        """Recursively remove subdivisions whose leaves all have one state."""

        if self.children is None:
            return self
        for child in self.children:
            child.collapse()
        first = self.children[0]
        if first.children is None and all(
            child.children is None and child.state == first.state
            for child in self.children[1:]
        ):
            self.make_leaf(int(first.state))
        return self

    def max_depth(self) -> int:
        if self.children is None:
            return 0
        return 1 + max(child.max_depth() for child in self.children)

    def leaf_count(self) -> int:
        if self.children is None:
            return 1
        return sum(child.leaf_count() for child in self.children)

    def state_areas(self) -> tuple[float, ...]:
        """Return the fraction of the source triangle occupied by each state."""

        result = [0.0] * STATE_COUNT

        def visit(node: PaintNode, weight: float) -> None:
            if node.children is None:
                result[int(node.state)] += weight
                return
            if node.split_sides == 1:
                child_weights = (0.5, 0.5)
            elif node.split_sides == 2:
                # Orca's first two children are quarter triangles; the final
                # child spans the remaining half of the source triangle.
                child_weights = (0.25, 0.25, 0.5)
            else:
                child_weights = (0.25, 0.25, 0.25, 0.25)
            for child, fraction in zip(node.children, child_weights, strict=True):
                visit(child, weight * fraction)

        visit(self, 1.0)
        return tuple(result)

    def dominant_state(self) -> int:
        """Return the largest-area state, choosing the lower state on a tie."""

        areas = self.state_areas()
        return max(range(STATE_COUNT), key=lambda state: (areas[state], -state))

    def validate(self, *, max_depth: int = MAX_DEPTH) -> "PaintNode":
        """Validate this tree recursively and return ``self``."""

        limit = int(max_depth)
        if limit < 0 or limit > MAX_DEPTH:
            raise SmoothPaintError(f"max_depth must be in 0..{MAX_DEPTH}")

        def visit(node: PaintNode, depth: int) -> None:
            if depth > limit:
                raise SmoothPaintError(
                    f"paint tree depth {depth} exceeds configured limit {limit}"
                )
            if node.children is None:
                _validate_state(int(node.state))
                return
            if node.split_sides not in (1, 2, 3):
                raise SmoothPaintError("invalid split_sides in PaintNode")
            if len(node.children) != node.split_sides + 1:
                raise SmoothPaintError("child count does not match split_sides")
            if node.special_side not in (0, 1, 2):
                raise SmoothPaintError("invalid special_side in PaintNode")
            if node.split_sides == 3 and node.special_side != 0:
                raise SmoothPaintError("a three-side split must use special_side=0")
            for child in node.children:
                visit(child, depth + 1)

        visit(self, 0)
        return self


def clone_node(node: PaintNode) -> PaintNode:
    return node.clone()


def collapse_node(node: PaintNode) -> PaintNode:
    return node.collapse()


def dominant_state(node: PaintNode) -> int:
    return node.dominant_state()


def _as_triangle(vertices: np.ndarray) -> np.ndarray:
    triangle = np.asarray(vertices, dtype=np.float64)
    if triangle.ndim != 2 or triangle.shape[0] != 3 or triangle.shape[1] < 2:
        raise SmoothPaintError("triangle must be a finite 3xD array with D >= 2")
    if not bool(np.all(np.isfinite(triangle))):
        raise SmoothPaintError("triangle contains a non-finite coordinate")
    return triangle


def subdivide_triangle(
    vertices: np.ndarray,
    *,
    split_sides: int = 3,
    special_side: int = 0,
) -> tuple[np.ndarray, ...]:
    """Return child triangles in the exact geometric order used by Orca."""

    triangle = _as_triangle(vertices)
    sides = int(split_sides)
    special = int(special_side)
    if sides not in (1, 2, 3):
        raise SmoothPaintError("split_sides must be 1, 2, or 3")
    if special not in (0, 1, 2):
        raise SmoothPaintError("special_side must be 0, 1, or 2")
    if sides == 3 and special != 0:
        raise SmoothPaintError("a three-side split must use special_side=0")

    if sides == 3:
        a, b, c = triangle
        ab = 0.5 * (a + b)
        bc = 0.5 * (b + c)
        ca = 0.5 * (c + a)
        return (
            np.stack((a, ab, ca)),
            np.stack((ab, b, bc)),
            np.stack((bc, c, ca)),
            np.stack((ab, bc, ca)),
        )

    # Orca rotates the source vertices so that special_side is first.
    rotated = tuple(triangle[(special + offset) % 3] for offset in range(3))
    a, b, c = rotated
    if sides == 1:
        bc = 0.5 * (b + c)
        return (
            np.stack((a, b, bc)),
            np.stack((bc, c, a)),
        )

    ab = 0.5 * (a + b)
    ca = 0.5 * (c + a)
    return (
        np.stack((a, ab, ca)),
        np.stack((ab, b, ca)),
        np.stack((b, c, ca)),
    )


@dataclass(frozen=True, slots=True)
class LeafTriangle:
    state: int
    vertices: np.ndarray
    depth: int
    path: tuple[int, ...]
    area_fraction: float


def iter_leaf_triangles(
    node: PaintNode,
    vertices: np.ndarray,
    *,
    max_depth: int = MAX_DEPTH,
) -> Iterator[LeafTriangle]:
    """Yield all leaf triangles with state, path, depth, and area fraction."""

    root_triangle = _as_triangle(vertices)
    node.validate(max_depth=max_depth)

    def visit(
        current: PaintNode,
        triangle: np.ndarray,
        depth: int,
        path: tuple[int, ...],
        fraction: float,
    ) -> Iterator[LeafTriangle]:
        if current.children is None:
            yield LeafTriangle(int(current.state), triangle.copy(), depth, path, fraction)
            return
        children = subdivide_triangle(
            triangle,
            split_sides=current.split_sides,
            special_side=current.special_side,
        )
        if current.split_sides == 1:
            weights = (0.5, 0.5)
        elif current.split_sides == 2:
            weights = (0.25, 0.25, 0.5)
        else:
            weights = (0.25, 0.25, 0.25, 0.25)
        for index, (child_node, child_triangle, weight) in enumerate(
            zip(current.children, children, weights, strict=True)
        ):
            yield from visit(
                child_node,
                child_triangle,
                depth + 1,
                path + (index,),
                fraction * weight,
            )

    yield from visit(node, root_triangle, 0, (), 1.0)


class CapsuleRelation(IntEnum):
    OUTSIDE = 0
    PARTIAL = 1
    INSIDE = 2


# Marker and round strokes use the same three-way triangle classification.
# Keep the original public name for backwards compatibility while offering a
# shape-neutral spelling to new callers.
StrokeRelation = CapsuleRelation


def _as_point2(value: np.ndarray, label: str) -> np.ndarray:
    point = np.asarray(value, dtype=np.float64)
    if point.shape != (2,) or not bool(np.all(np.isfinite(point))):
        raise SmoothPaintError(f"{label} must be a finite 2D point")
    return point


def _as_screen_segments(value: np.ndarray) -> np.ndarray:
    segments = np.asarray(value, dtype=np.float64)
    if segments.ndim != 3 or segments.shape[1:] != (2, 2):
        raise SmoothPaintError("segments must be a finite Nx2x2 array")
    if not bool(np.all(np.isfinite(segments))):
        raise SmoothPaintError("segments contain a non-finite coordinate")
    return segments


def _point_segment_distance_sq(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    delta = end - start
    length_sq = float(np.dot(delta, delta))
    if length_sq <= _EPSILON:
        difference = point - start
        return float(np.dot(difference, difference))
    amount = float(np.dot(point - start, delta) / length_sq)
    amount = min(1.0, max(0.0, amount))
    closest = start + amount * delta
    difference = point - closest
    return float(np.dot(difference, difference))


def _cross2(first: np.ndarray, second: np.ndarray) -> float:
    return float(first[0] * second[1] - first[1] * second[0])


def _point_in_triangle(point: np.ndarray, triangle: np.ndarray) -> bool:
    a, b, c = triangle
    area = _cross2(b - a, c - a)
    tolerance = _EPSILON * max(1.0, abs(area))
    if abs(area) <= tolerance:
        return False
    first = _cross2(b - a, point - a)
    second = _cross2(c - b, point - b)
    third = _cross2(a - c, point - c)
    return bool(
        (first >= -tolerance and second >= -tolerance and third >= -tolerance)
        or (first <= tolerance and second <= tolerance and third <= tolerance)
    )


def _point_in_convex_polygon(point: np.ndarray, polygon: np.ndarray) -> bool:
    """Return whether ``point`` is inside or on a finite convex polygon."""

    edges = np.roll(polygon, -1, axis=0) - polygon
    offsets = point - polygon
    crosses = edges[:, 0] * offsets[:, 1] - edges[:, 1] * offsets[:, 0]
    scale = max(1.0, float(np.max(np.sum(edges * edges, axis=1))))
    tolerance = _EPSILON * scale
    return bool(np.all(crosses >= -tolerance) or np.all(crosses <= tolerance))


def _orientation(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return _cross2(b - a, c - a)


def _on_segment(a: np.ndarray, b: np.ndarray, point: np.ndarray) -> bool:
    tolerance = _EPSILON
    return bool(
        min(a[0], b[0]) - tolerance <= point[0] <= max(a[0], b[0]) + tolerance
        and min(a[1], b[1]) - tolerance <= point[1] <= max(a[1], b[1]) + tolerance
    )


def _segments_intersect(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    d: np.ndarray,
) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    tolerance = _EPSILON
    if (
        ((first > tolerance and second < -tolerance) or (first < -tolerance and second > tolerance))
        and ((third > tolerance and fourth < -tolerance) or (third < -tolerance and fourth > tolerance))
    ):
        return True
    if abs(first) <= tolerance and _on_segment(a, b, c):
        return True
    if abs(second) <= tolerance and _on_segment(a, b, d):
        return True
    if abs(third) <= tolerance and _on_segment(c, d, a):
        return True
    if abs(fourth) <= tolerance and _on_segment(c, d, b):
        return True
    return False


def _segment_segment_distance_sq(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    d: np.ndarray,
) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance_sq(a, c, d),
        _point_segment_distance_sq(b, c, d),
        _point_segment_distance_sq(c, a, b),
        _point_segment_distance_sq(d, a, b),
    )


def _convex_hull(points: np.ndarray) -> np.ndarray:
    """Return a counter-clockwise convex hull for a small finite point set."""

    values = sorted({(float(point[0]), float(point[1])) for point in points})
    if len(values) < 3:
        raise SmoothPaintError("marker stroke polygon must contain at least three points")

    def turn(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower: list[tuple[float, float]] = []
    for point in values:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], point) <= _EPSILON:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(values):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], point) <= _EPSILON:
            upper.pop()
        upper.append(point)
    hull = np.asarray(lower[:-1] + upper[:-1], dtype=np.float64)
    if hull.shape[0] < 3:
        raise SmoothPaintError("marker stroke polygon is degenerate")
    return hull


def marker_stroke_polygon(
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    width: float,
    *,
    thickness: float | None = None,
    angle_degrees: float | None = None,
) -> np.ndarray:
    """Build the exact convex sweep of a rectangular marker nib.

    ``width`` is the nib's long dimension and ``thickness`` is its short
    dimension.  When ``angle_degrees`` is omitted, the long dimension remains
    perpendicular to the stroke direction, producing a flat-ended band.  A
    supplied angle fixes the nib orientation in screen coordinates; positive
    angles turn from +X toward +Y (clockwise on the usual Y-down canvas).

    The returned convex polygon includes the rectangular footprint at both
    endpoints, so adjacent input samples form a continuous stroke rather than
    a chain of disconnected rectangles.
    """

    start = _as_point2(start_xy, "start_xy")
    end = _as_point2(end_xy, "end_xy")
    marker_width = float(width)
    if not math.isfinite(marker_width) or marker_width <= 0.0:
        raise SmoothPaintError("marker width must be finite and positive")
    marker_thickness = marker_width * 0.25 if thickness is None else float(thickness)
    if not math.isfinite(marker_thickness) or marker_thickness <= 0.0:
        raise SmoothPaintError("marker thickness must be finite and positive")

    if angle_degrees is None:
        travel = end - start
        travel_length = float(np.linalg.norm(travel))
        if travel_length <= _EPSILON:
            major = np.asarray((1.0, 0.0), dtype=np.float64)
        else:
            direction = travel / travel_length
            major = np.asarray((-direction[1], direction[0]), dtype=np.float64)
    else:
        angle = float(angle_degrees)
        if not math.isfinite(angle):
            raise SmoothPaintError("marker angle must be finite")
        radians = math.radians(angle)
        major = np.asarray((math.cos(radians), math.sin(radians)), dtype=np.float64)
    minor = np.asarray((-major[1], major[0]), dtype=np.float64)
    major *= marker_width * 0.5
    minor *= marker_thickness * 0.5

    corners = np.asarray(
        [
            center + major_sign * major + minor_sign * minor
            for center in (start, end)
            for major_sign in (-1.0, 1.0)
            for minor_sign in (-1.0, 1.0)
        ],
        dtype=np.float64,
    )
    return _convex_hull(corners)


def _triangle_convex_polygon_relation(
    triangle: np.ndarray,
    polygon: np.ndarray,
) -> CapsuleRelation:
    """Fast unchecked relation used by the recursive marker painter."""

    triangle_min = np.min(triangle, axis=0)
    triangle_max = np.max(triangle, axis=0)
    polygon_min = np.min(polygon, axis=0)
    polygon_max = np.max(polygon, axis=0)
    if bool(np.any(triangle_max < polygon_min - _EPSILON)) or bool(
        np.any(polygon_max < triangle_min - _EPSILON)
    ):
        return CapsuleRelation.OUTSIDE

    return _triangle_convex_polygon_relation_after_bounds(triangle, polygon)


def _triangle_convex_polygon_relation_after_bounds(
    triangle: np.ndarray,
    polygon: np.ndarray,
) -> CapsuleRelation:
    """Classify geometry whose axis-aligned bounds are known to overlap."""

    triangle_inside = tuple(
        _point_in_convex_polygon(vertex, polygon) for vertex in triangle
    )
    if all(triangle_inside):
        return CapsuleRelation.INSIDE
    if any(triangle_inside):
        return CapsuleRelation.PARTIAL
    if any(_point_in_triangle(vertex, triangle) for vertex in polygon):
        return CapsuleRelation.PARTIAL
    for triangle_index in range(3):
        triangle_start = triangle[triangle_index]
        triangle_end = triangle[(triangle_index + 1) % 3]
        for polygon_index in range(polygon.shape[0]):
            if _segments_intersect(
                triangle_start,
                triangle_end,
                polygon[polygon_index],
                polygon[(polygon_index + 1) % polygon.shape[0]],
            ):
                return CapsuleRelation.PARTIAL
    return CapsuleRelation.OUTSIDE


def triangle_marker_relation(
    projected_triangle: np.ndarray,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    width: float,
    *,
    thickness: float | None = None,
    angle_degrees: float | None = None,
) -> CapsuleRelation:
    """Classify a projected triangle against a rectangular marker sweep."""

    triangle = _as_triangle(projected_triangle)[:, :2]
    polygon = marker_stroke_polygon(
        start_xy,
        end_xy,
        width,
        thickness=thickness,
        angle_degrees=angle_degrees,
    )
    return _triangle_convex_polygon_relation(triangle, polygon)


def triangle_capsule_relation(
    projected_triangle: np.ndarray,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    radius: float,
) -> CapsuleRelation:
    """Classify a projected triangle against a closed screen-space capsule."""

    triangle = _as_triangle(projected_triangle)[:, :2]
    start = _as_point2(start_xy, "start_xy")
    end = _as_point2(end_xy, "end_xy")
    brush_radius = float(radius)
    if not math.isfinite(brush_radius) or brush_radius < 0.0:
        raise SmoothPaintError("radius must be finite and non-negative")
    radius_sq = brush_radius * brush_radius
    tolerance = _EPSILON * max(1.0, radius_sq)
    distances = tuple(
        _point_segment_distance_sq(vertex, start, end) for vertex in triangle
    )
    if all(distance <= radius_sq + tolerance for distance in distances):
        return CapsuleRelation.INSIDE

    if _point_in_triangle(start, triangle) or _point_in_triangle(end, triangle):
        return CapsuleRelation.PARTIAL
    minimum = min(
        _segment_segment_distance_sq(start, end, triangle[index], triangle[(index + 1) % 3])
        for index in range(3)
    )
    if minimum > radius_sq + tolerance:
        return CapsuleRelation.OUTSIDE
    return CapsuleRelation.PARTIAL


@dataclass(frozen=True, slots=True)
class CapsulePaintResult:
    changed: bool
    visited_nodes: int
    split_nodes: int
    painted_nodes: int
    deepest_visit: int


StrokePaintResult = CapsulePaintResult


Projector = Callable[[np.ndarray], np.ndarray]
BoundaryRule = Literal["center", "inside", "intersect"]


RegionRelation = Callable[[np.ndarray, int], CapsuleRelation]
RegionCenterTest = Callable[[np.ndarray, int], bool]


def _apply_segment_regions(
    node: PaintNode,
    triangle: np.ndarray,
    region_count: int,
    requested: int,
    *,
    relation: RegionRelation,
    contains_center: RegionCenterTest,
    region_bounds: np.ndarray | None,
    projector: Projector | None,
    depth_limit: int,
    edge_limit: float,
    boundary_rule: BoundaryRule,
) -> CapsulePaintResult:
    """Apply the union of prevalidated screen regions in one tree traversal."""

    node.validate(max_depth=MAX_DEPTH)
    if region_count == 0:
        return CapsulePaintResult(False, 0, 0, 0, 0)

    def project(current: np.ndarray) -> np.ndarray:
        if projector is None:
            output = current[:, :2]
        else:
            output = np.asarray(projector(current), dtype=np.float64)
        if output.shape != (3, 2) or not bool(np.all(np.isfinite(output))):
            raise SmoothPaintError("projector must return a finite 3x2 array")
        return output

    visited = 0
    split_count = 0
    painted = 0
    deepest = 0

    def visit(
        current: PaintNode,
        geometry: np.ndarray,
        depth: int,
        active_regions: tuple[int, ...] | list[int],
    ) -> bool:
        nonlocal visited, split_count, painted, deepest
        visited += 1
        deepest = max(deepest, depth)
        screen = project(geometry)
        partial: list[int] = []
        if region_bounds is not None:
            triangle_min_x = min(screen[0, 0], screen[1, 0], screen[2, 0])
            triangle_min_y = min(screen[0, 1], screen[1, 1], screen[2, 1])
            triangle_max_x = max(screen[0, 0], screen[1, 0], screen[2, 0])
            triangle_max_y = max(screen[0, 1], screen[1, 1], screen[2, 1])
        for region_index in active_regions:
            if region_bounds is not None:
                bounds = region_bounds[region_index]
                if (
                    triangle_max_x < bounds[0]
                    or bounds[2] < triangle_min_x
                    or triangle_max_y < bounds[1]
                    or bounds[3] < triangle_min_y
                ):
                    continue
            region_relation = relation(screen, region_index)
            if region_relation == CapsuleRelation.INSIDE:
                changed = current.make_leaf(requested)
                if changed:
                    painted += 1
                return changed
            if region_relation == CapsuleRelation.PARTIAL:
                partial.append(region_index)
        if not partial:
            return False

        edges = np.roll(screen, -1, axis=0) - screen
        maximum_edge = float(np.sqrt(np.max(np.sum(edges * edges, axis=1))))
        stop = depth >= depth_limit or maximum_edge <= edge_limit
        if stop:
            should_paint = boundary_rule == "intersect"
            if boundary_rule == "center":
                center = screen.mean(axis=0)
                should_paint = any(
                    contains_center(center, region_index)
                    for region_index in partial
                )
            if not should_paint:
                return False
            changed = current.make_leaf(requested)
            if changed:
                painted += 1
            return changed

        created_split = current.children is None
        if created_split:
            current.split_four()
            split_count += 1
        child_triangles = subdivide_triangle(
            geometry,
            split_sides=current.split_sides,
            special_side=current.special_side,
        )
        changed = False
        for child, child_triangle in zip(current.children, child_triangles, strict=True):
            changed = visit(child, child_triangle, depth + 1, partial) or changed
        if changed:
            current.collapse()
        elif created_split:
            # A relation can touch this triangle while no terminal child center
            # is paintable.  Do not retain an invisible no-op subdivision.
            current.collapse()
        return changed

    did_change = visit(node, triangle, 0, tuple(range(region_count)))
    node.validate(max_depth=MAX_DEPTH)
    return CapsulePaintResult(did_change, visited, split_count, painted, deepest)


def _triangle_capsule_relation_prevalidated(
    triangle: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    radius_sq: float,
    tolerance: float,
) -> CapsuleRelation:
    distances = tuple(
        _point_segment_distance_sq(vertex, start, end) for vertex in triangle
    )
    if all(distance <= radius_sq + tolerance for distance in distances):
        return CapsuleRelation.INSIDE
    if _point_in_triangle(start, triangle) or _point_in_triangle(end, triangle):
        return CapsuleRelation.PARTIAL
    minimum = min(
        _segment_segment_distance_sq(
            start,
            end,
            triangle[index],
            triangle[(index + 1) % 3],
        )
        for index in range(3)
    )
    if minimum > radius_sq + tolerance:
        return CapsuleRelation.OUTSIDE
    return CapsuleRelation.PARTIAL


def apply_capsule(
    node: PaintNode,
    vertices: np.ndarray,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    radius: float,
    state: int,
    *,
    projector: Projector | None = None,
    max_depth: int = MAX_DEPTH,
    min_edge_pixels: float = 1.0,
    boundary_rule: BoundaryRule = "center",
) -> CapsulePaintResult:
    """Paint a continuous screen-space capsule into ``node`` in place.

    ``vertices`` may be 2D projected coordinates or higher-dimensional model
    coordinates.  For model coordinates, ``projector`` must map an NxD array to
    finite Nx2 screen coordinates.  Partial triangles are split only until
    ``max_depth`` or ``min_edge_pixels`` is reached.
    """

    triangle = _as_triangle(vertices)
    start = _as_point2(start_xy, "start_xy")
    end = _as_point2(end_xy, "end_xy")
    brush_radius = float(radius)
    if not math.isfinite(brush_radius) or brush_radius < 0.0:
        raise SmoothPaintError("radius must be finite and non-negative")
    requested = _validate_state(state)
    depth_limit = int(max_depth)
    if depth_limit < 0 or depth_limit > MAX_DEPTH:
        raise SmoothPaintError(f"max_depth must be in 0..{MAX_DEPTH}")
    edge_limit = float(min_edge_pixels)
    if not math.isfinite(edge_limit) or edge_limit < 0.0:
        raise SmoothPaintError("min_edge_pixels must be finite and non-negative")
    if boundary_rule not in ("center", "inside", "intersect"):
        raise SmoothPaintError(f"unknown boundary_rule: {boundary_rule!r}")
    node.validate(max_depth=MAX_DEPTH)

    def project(current: np.ndarray) -> np.ndarray:
        if projector is None:
            output = current[:, :2]
        else:
            output = np.asarray(projector(current), dtype=np.float64)
        if output.shape != (3, 2) or not bool(np.all(np.isfinite(output))):
            raise SmoothPaintError("projector must return a finite 3x2 array")
        return output

    visited = 0
    split_count = 0
    painted = 0
    deepest = 0

    def visit(current: PaintNode, geometry: np.ndarray, depth: int) -> bool:
        nonlocal visited, split_count, painted, deepest
        visited += 1
        deepest = max(deepest, depth)
        screen = project(geometry)
        relation = triangle_capsule_relation(screen, start, end, brush_radius)
        if relation == CapsuleRelation.OUTSIDE:
            return False
        if relation == CapsuleRelation.INSIDE:
            changed = current.make_leaf(requested)
            if changed:
                painted += 1
            return changed

        edges = np.roll(screen, -1, axis=0) - screen
        maximum_edge = float(np.sqrt(np.max(np.sum(edges * edges, axis=1))))
        stop = depth >= depth_limit or maximum_edge <= edge_limit
        if stop:
            should_paint = boundary_rule == "intersect"
            if boundary_rule == "center":
                center = screen.mean(axis=0)
                should_paint = (
                    _point_segment_distance_sq(center, start, end)
                    <= brush_radius * brush_radius + _EPSILON
                )
            if not should_paint:
                return False
            changed = current.make_leaf(requested)
            if changed:
                painted += 1
            return changed

        created_split = current.children is None
        if created_split:
            current.split_four()
            split_count += 1
        child_triangles = subdivide_triangle(
            geometry,
            split_sides=current.split_sides,
            special_side=current.special_side,
        )
        changed = False
        for child, child_triangle in zip(current.children, child_triangles, strict=True):
            changed = visit(child, child_triangle, depth + 1) or changed
        if changed:
            current.collapse()
        elif created_split:
            current.collapse()
        return changed

    did_change = visit(node, triangle, 0)
    node.validate(max_depth=MAX_DEPTH)
    return CapsulePaintResult(did_change, visited, split_count, painted, deepest)


def apply_capsule_segments(
    node: PaintNode,
    vertices: np.ndarray,
    segments_xy: np.ndarray,
    radius: float,
    state: int,
    *,
    projector: Projector | None = None,
    max_depth: int = MAX_DEPTH,
    min_edge_pixels: float = 1.0,
    boundary_rule: BoundaryRule = "center",
) -> CapsulePaintResult:
    """Paint same-state round-brush segments in one subdivision-tree pass.

    The result is identical to applying :func:`apply_capsule` to every segment
    in order when the options and requested state are the same.  Grouping a
    sampled stroke avoids repeatedly validating and traversing the same tree.
    ``segments_xy`` must be a finite ``Nx2x2`` array of start/end screen points.
    """

    triangle = _as_triangle(vertices)
    segments = _as_screen_segments(segments_xy)
    brush_radius = float(radius)
    if not math.isfinite(brush_radius) or brush_radius < 0.0:
        raise SmoothPaintError("radius must be finite and non-negative")
    requested = _validate_state(state)
    depth_limit = int(max_depth)
    if depth_limit < 0 or depth_limit > MAX_DEPTH:
        raise SmoothPaintError(f"max_depth must be in 0..{MAX_DEPTH}")
    edge_limit = float(min_edge_pixels)
    if not math.isfinite(edge_limit) or edge_limit < 0.0:
        raise SmoothPaintError("min_edge_pixels must be finite and non-negative")
    if boundary_rule not in ("center", "inside", "intersect"):
        raise SmoothPaintError(f"unknown boundary_rule: {boundary_rule!r}")

    starts = segments[:, 0]
    ends = segments[:, 1]
    radius_sq = brush_radius * brush_radius
    relation_tolerance = _EPSILON * max(1.0, radius_sq)
    # Keep the broad phase conservative at floating-point boundaries; the
    # exact relation below remains the authority for candidate regions.
    bounds_radius = math.sqrt(radius_sq + relation_tolerance) + _EPSILON
    region_bounds = np.concatenate(
        (
            np.minimum(starts, ends) - bounds_radius,
            np.maximum(starts, ends) + bounds_radius,
        ),
        axis=1,
    )

    def relation(screen: np.ndarray, region_index: int) -> CapsuleRelation:
        return _triangle_capsule_relation_prevalidated(
            screen,
            starts[region_index],
            ends[region_index],
            radius_sq,
            relation_tolerance,
        )

    def contains_center(center: np.ndarray, region_index: int) -> bool:
        return bool(
            _point_segment_distance_sq(
                center,
                starts[region_index],
                ends[region_index],
            )
            <= radius_sq + _EPSILON
        )

    return _apply_segment_regions(
        node,
        triangle,
        len(segments),
        requested,
        relation=relation,
        contains_center=contains_center,
        region_bounds=region_bounds,
        projector=projector,
        depth_limit=depth_limit,
        edge_limit=edge_limit,
        boundary_rule=boundary_rule,
    )


def apply_variable_capsule_segments(
    node: PaintNode,
    vertices: np.ndarray,
    segments_xy: np.ndarray,
    radii: np.ndarray,
    state: int,
    *,
    projector: Projector | None = None,
    max_depth: int = MAX_DEPTH,
    min_edge_pixels: float = 1.0,
    boundary_rule: BoundaryRule = "center",
) -> CapsulePaintResult:
    """Paint round-brush segments with one radius per segment.

    The regions are still applied in one subdivision-tree traversal, matching
    :func:`apply_capsule_segments` performance and union semantics.  This is
    used by the pressure/taper nib after the UI thread has frozen its width
    profile; no tablet or Tk state is consulted here.
    """

    triangle = _as_triangle(vertices)
    segments = _as_screen_segments(segments_xy)
    brush_radii = np.asarray(radii, dtype=np.float64)
    if brush_radii.shape != (len(segments),):
        raise SmoothPaintError("radii must contain one value per segment")
    if not bool(np.all(np.isfinite(brush_radii))) or bool(
        np.any(brush_radii < 0.0)
    ):
        raise SmoothPaintError("radii must be finite and non-negative")
    requested = _validate_state(state)
    depth_limit = int(max_depth)
    if depth_limit < 0 or depth_limit > MAX_DEPTH:
        raise SmoothPaintError(f"max_depth must be in 0..{MAX_DEPTH}")
    edge_limit = float(min_edge_pixels)
    if not math.isfinite(edge_limit) or edge_limit < 0.0:
        raise SmoothPaintError("min_edge_pixels must be finite and non-negative")
    if boundary_rule not in ("center", "inside", "intersect"):
        raise SmoothPaintError(f"unknown boundary_rule: {boundary_rule!r}")

    starts = segments[:, 0]
    ends = segments[:, 1]
    radii_sq = brush_radii * brush_radii
    relation_tolerances = _EPSILON * np.maximum(1.0, radii_sq)
    bounds_radii = np.sqrt(radii_sq + relation_tolerances) + _EPSILON
    region_bounds = np.concatenate(
        (
            np.minimum(starts, ends) - bounds_radii[:, None],
            np.maximum(starts, ends) + bounds_radii[:, None],
        ),
        axis=1,
    )

    def relation(screen: np.ndarray, region_index: int) -> CapsuleRelation:
        return _triangle_capsule_relation_prevalidated(
            screen,
            starts[region_index],
            ends[region_index],
            float(radii_sq[region_index]),
            float(relation_tolerances[region_index]),
        )

    def contains_center(center: np.ndarray, region_index: int) -> bool:
        return bool(
            _point_segment_distance_sq(
                center,
                starts[region_index],
                ends[region_index],
            )
            <= float(radii_sq[region_index]) + _EPSILON
        )

    return _apply_segment_regions(
        node,
        triangle,
        len(segments),
        requested,
        relation=relation,
        contains_center=contains_center,
        region_bounds=region_bounds,
        projector=projector,
        depth_limit=depth_limit,
        edge_limit=edge_limit,
        boundary_rule=boundary_rule,
    )


def apply_layered_variable_capsule_segments(
    node: PaintNode,
    vertices: np.ndarray,
    segments_xy: np.ndarray,
    radii: np.ndarray,
    layers: Sequence[tuple[float, int]],
    *,
    projector: Projector | None = None,
    max_depth: int = MAX_DEPTH,
    min_edge_pixels: float = 1.0,
    boundary_rule: BoundaryRule = "center",
) -> CapsulePaintResult:
    """Paint concentric variable-radius bands in one subdivision-tree pass.

    ``layers`` contains ``(radius_fraction, state)`` pairs in the same
    outer-to-inner order used by :func:`paint_tools.airbrush_state_layers`.
    The final encoded :class:`PaintNode` is identical to calling
    :func:`apply_variable_capsule_segments` once for each pair in order.

    Midpoint-only trees use one traversal and share each triangle/segment
    distance calculation across every band.  Imported Orca trees may contain
    two- or three-child splits; an intermediate collapse can change their
    later split geometry, so those uncommon trees take the exact sequential
    fallback.  Non-concentric layer orderings use the same safe fallback.
    Projectors are expected to be deterministic, as for the other paint APIs.
    """

    triangle = _as_triangle(vertices)
    segments = _as_screen_segments(segments_xy)
    brush_radii = np.asarray(radii, dtype=np.float64)
    if brush_radii.shape != (len(segments),):
        raise SmoothPaintError("radii must contain one value per segment")
    if not bool(np.all(np.isfinite(brush_radii))) or bool(
        np.any(brush_radii < 0.0)
    ):
        raise SmoothPaintError("radii must be finite and non-negative")

    layer_values: list[tuple[float, int]] = []
    for radius_fraction, state in layers:
        fraction = float(radius_fraction)
        if not math.isfinite(fraction) or fraction < 0.0:
            raise SmoothPaintError(
                "layer radius fractions must be finite and non-negative"
            )
        layer_values.append((fraction, _validate_state(state)))

    depth_limit = int(max_depth)
    if depth_limit < 0 or depth_limit > MAX_DEPTH:
        raise SmoothPaintError(f"max_depth must be in 0..{MAX_DEPTH}")
    edge_limit = float(min_edge_pixels)
    if not math.isfinite(edge_limit) or edge_limit < 0.0:
        raise SmoothPaintError("min_edge_pixels must be finite and non-negative")
    if boundary_rule not in ("center", "inside", "intersect"):
        raise SmoothPaintError(f"unknown boundary_rule: {boundary_rule!r}")
    node.validate(max_depth=MAX_DEPTH)
    if not layer_values or len(segments) == 0:
        return CapsulePaintResult(False, 0, 0, 0, 0)

    scales = np.asarray(
        [radius_fraction for radius_fraction, _state in layer_values],
        dtype=np.float64,
    )
    states = np.asarray(
        [state for _radius_fraction, state in layer_values],
        dtype=np.int8,
    )

    def midpoint_only(current: PaintNode) -> bool:
        if current.children is None:
            return True
        return current.split_sides == 3 and all(
            midpoint_only(child) for child in current.children
        )

    nested = bool(np.all(scales[:-1] >= scales[1:]))
    if not nested or not midpoint_only(node):
        changed = False
        visited = 0
        split_count = 0
        painted = 0
        deepest = 0
        for radius_fraction, state in layer_values:
            result = apply_variable_capsule_segments(
                node,
                triangle,
                segments,
                brush_radii * radius_fraction,
                state,
                projector=projector,
                max_depth=depth_limit,
                min_edge_pixels=edge_limit,
                boundary_rule=boundary_rule,
            )
            changed = changed or result.changed
            visited += result.visited_nodes
            split_count += result.split_nodes
            painted += result.painted_nodes
            deepest = max(deepest, result.deepest_visit)
        return CapsulePaintResult(
            changed,
            visited,
            split_count,
            painted,
            deepest,
        )

    starts = segments[:, 0]
    ends = segments[:, 1]
    scaled_radii = scales[:, None] * brush_radii[None, :]
    radii_sq = scaled_radii * scaled_radii
    relation_tolerances = _EPSILON * np.maximum(1.0, radii_sq)
    bounds_radii = np.sqrt(radii_sq + relation_tolerances) + _EPSILON
    minimum = np.minimum(starts, ends)[None, :, :] - bounds_radii[:, :, None]
    maximum = np.maximum(starts, ends)[None, :, :] + bounds_radii[:, :, None]
    region_bounds = np.concatenate((minimum, maximum), axis=2)

    def project(current: np.ndarray) -> np.ndarray:
        if projector is None:
            output = current[:, :2]
        else:
            output = np.asarray(projector(current), dtype=np.float64)
        if output.shape != (3, 2) or not bool(np.all(np.isfinite(output))):
            raise SmoothPaintError("projector must return a finite 3x2 array")
        return output

    visited = 0
    split_count = 0
    painted = 0
    deepest = 0
    initial_active = tuple(
        (layer_index, tuple(range(len(segments))))
        for layer_index in range(len(layer_values))
    )

    def visit(
        current: PaintNode,
        geometry: np.ndarray,
        depth: int,
        active_layers: tuple[tuple[int, tuple[int, ...]], ...],
    ) -> bool:
        nonlocal visited, split_count, painted, deepest
        visited += 1
        deepest = max(deepest, depth)
        screen = project(geometry)
        triangle_min_x = min(screen[0, 0], screen[1, 0], screen[2, 0])
        triangle_min_y = min(screen[0, 1], screen[1, 1], screen[2, 1])
        triangle_max_x = max(screen[0, 0], screen[1, 0], screen[2, 0])
        triangle_max_y = max(screen[0, 1], screen[1, 1], screen[2, 1])

        partial_by_layer: dict[int, list[int]] = {
            layer_index: [] for layer_index, _regions in active_layers
        }
        inside_layers: set[int] = set()
        latest_inside = -1
        layers_by_region: dict[int, list[int]] = {}
        for layer_index, candidate_regions in active_layers:
            for region_index in candidate_regions:
                layers_by_region.setdefault(region_index, []).append(layer_index)

        # The two capsule relation distances depend on the triangle and line
        # segment, but not on radius.  Calculate them once and classify all
        # concentric bands through scalar threshold comparisons.
        for region_index, candidate_layers in layers_by_region.items():
            widest_layer = candidate_layers[0]
            bounds = region_bounds[widest_layer, region_index]
            if (
                triangle_max_x < bounds[0]
                or bounds[2] < triangle_min_x
                or triangle_max_y < bounds[1]
                or bounds[3] < triangle_min_y
            ):
                continue

            start = starts[region_index]
            end = ends[region_index]
            maximum_vertex_distance = max(
                _point_segment_distance_sq(vertex, start, end)
                for vertex in screen
            )
            endpoint_inside = _point_in_triangle(
                start, screen
            ) or _point_in_triangle(end, screen)
            minimum_edge_distance: float | None = None
            for layer_index in candidate_layers:
                threshold = float(
                    radii_sq[layer_index, region_index]
                    + relation_tolerances[layer_index, region_index]
                )
                if maximum_vertex_distance <= threshold:
                    inside_layers.add(layer_index)
                    latest_inside = max(latest_inside, layer_index)
                    continue
                if endpoint_inside:
                    partial_by_layer[layer_index].append(region_index)
                    continue
                if minimum_edge_distance is None:
                    minimum_edge_distance = min(
                        _segment_segment_distance_sq(
                            start,
                            end,
                            screen[index],
                            screen[(index + 1) % 3],
                        )
                        for index in range(3)
                    )
                if minimum_edge_distance <= threshold:
                    partial_by_layer[layer_index].append(region_index)

        classified = tuple(
            (
                layer_index,
                tuple(partial_by_layer[layer_index]),
                layer_index in inside_layers,
            )
            for layer_index, _regions in active_layers
        )
        changed = False
        if latest_inside >= 0:
            changed = current.make_leaf(int(states[latest_inside]))
            if changed:
                painted += 1

        remaining = tuple(
            (layer_index, partial)
            for layer_index, partial, inside in classified
            if layer_index > latest_inside and not inside and partial
        )
        if not remaining:
            return changed

        edges = np.roll(screen, -1, axis=0) - screen
        maximum_edge = float(np.sqrt(np.max(np.sum(edges * edges, axis=1))))
        stop = depth >= depth_limit or maximum_edge <= edge_limit
        if stop:
            chosen_state: int | None = None
            if boundary_rule == "intersect":
                chosen_state = int(states[remaining[-1][0]])
            elif boundary_rule == "center":
                center = screen.mean(axis=0)
                for layer_index, partial in remaining:
                    if any(
                        _point_segment_distance_sq(
                            center,
                            starts[region_index],
                            ends[region_index],
                        )
                        <= float(radii_sq[layer_index, region_index]) + _EPSILON
                        for region_index in partial
                    ):
                        chosen_state = int(states[layer_index])
            if chosen_state is not None:
                terminal_changed = current.make_leaf(chosen_state)
                if terminal_changed:
                    painted += 1
                changed = terminal_changed or changed
            return changed

        created_split = current.children is None
        if created_split:
            current.split_four()
            split_count += 1
        child_triangles = subdivide_triangle(
            geometry,
            split_sides=current.split_sides,
            special_side=current.special_side,
        )
        child_changed = False
        for child, child_triangle in zip(
            current.children,
            child_triangles,
            strict=True,
        ):
            child_changed = (
                visit(child, child_triangle, depth + 1, remaining) or child_changed
            )
        if child_changed or created_split:
            current.collapse()
        return changed or child_changed

    did_change = visit(node, triangle, 0, initial_active)
    node.validate(max_depth=MAX_DEPTH)
    return CapsulePaintResult(
        did_change,
        visited,
        split_count,
        painted,
        deepest,
    )


def painted_capsule(
    node: PaintNode,
    vertices: np.ndarray,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    radius: float,
    state: int,
    **kwargs: object,
) -> tuple[PaintNode, CapsulePaintResult]:
    """Clone ``node``, apply a capsule, and return the copy plus statistics."""

    output = node.clone()
    result = apply_capsule(
        output,
        vertices,
        start_xy,
        end_xy,
        radius,
        state,
        **kwargs,
    )
    return output, result


def apply_marker(
    node: PaintNode,
    vertices: np.ndarray,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    width: float,
    state: int,
    *,
    thickness: float | None = None,
    angle_degrees: float | None = None,
    projector: Projector | None = None,
    max_depth: int = MAX_DEPTH,
    min_edge_pixels: float = 1.0,
    boundary_rule: BoundaryRule = "center",
) -> CapsulePaintResult:
    """Paint a continuous rectangular-marker sweep into ``node`` in place.

    This follows the same sparse Orca-compatible subdivision rules as
    :func:`apply_capsule`.  ``width`` and ``thickness`` describe the marker nib
    in screen pixels.  ``angle_degrees=None`` follows the stroke direction;
    pass an angle to keep the rectangular nib fixed while the pointer moves.
    """

    triangle = _as_triangle(vertices)
    polygon = marker_stroke_polygon(
        start_xy,
        end_xy,
        width,
        thickness=thickness,
        angle_degrees=angle_degrees,
    )
    requested = _validate_state(state)
    depth_limit = int(max_depth)
    if depth_limit < 0 or depth_limit > MAX_DEPTH:
        raise SmoothPaintError(f"max_depth must be in 0..{MAX_DEPTH}")
    edge_limit = float(min_edge_pixels)
    if not math.isfinite(edge_limit) or edge_limit < 0.0:
        raise SmoothPaintError("min_edge_pixels must be finite and non-negative")
    if boundary_rule not in ("center", "inside", "intersect"):
        raise SmoothPaintError(f"unknown boundary_rule: {boundary_rule!r}")
    node.validate(max_depth=MAX_DEPTH)

    def project(current: np.ndarray) -> np.ndarray:
        if projector is None:
            output = current[:, :2]
        else:
            output = np.asarray(projector(current), dtype=np.float64)
        if output.shape != (3, 2) or not bool(np.all(np.isfinite(output))):
            raise SmoothPaintError("projector must return a finite 3x2 array")
        return output

    visited = 0
    split_count = 0
    painted = 0
    deepest = 0

    def visit(current: PaintNode, geometry: np.ndarray, depth: int) -> bool:
        nonlocal visited, split_count, painted, deepest
        visited += 1
        deepest = max(deepest, depth)
        screen = project(geometry)
        relation = _triangle_convex_polygon_relation(screen, polygon)
        if relation == CapsuleRelation.OUTSIDE:
            return False
        if relation == CapsuleRelation.INSIDE:
            changed = current.make_leaf(requested)
            if changed:
                painted += 1
            return changed

        edges = np.roll(screen, -1, axis=0) - screen
        maximum_edge = float(np.sqrt(np.max(np.sum(edges * edges, axis=1))))
        stop = depth >= depth_limit or maximum_edge <= edge_limit
        if stop:
            should_paint = boundary_rule == "intersect"
            if boundary_rule == "center":
                should_paint = _point_in_convex_polygon(screen.mean(axis=0), polygon)
            if not should_paint:
                return False
            changed = current.make_leaf(requested)
            if changed:
                painted += 1
            return changed

        created_split = current.children is None
        if created_split:
            current.split_four()
            split_count += 1
        child_triangles = subdivide_triangle(
            geometry,
            split_sides=current.split_sides,
            special_side=current.special_side,
        )
        changed = False
        for child, child_triangle in zip(current.children, child_triangles, strict=True):
            changed = visit(child, child_triangle, depth + 1) or changed
        if changed:
            current.collapse()
        elif created_split:
            current.collapse()
        return changed

    did_change = visit(node, triangle, 0)
    node.validate(max_depth=MAX_DEPTH)
    return CapsulePaintResult(did_change, visited, split_count, painted, deepest)


def apply_marker_segments(
    node: PaintNode,
    vertices: np.ndarray,
    segments_xy: np.ndarray,
    width: float,
    state: int,
    *,
    thickness: float | None = None,
    angle_degrees: float | None = None,
    projector: Projector | None = None,
    max_depth: int = MAX_DEPTH,
    min_edge_pixels: float = 1.0,
    boundary_rule: BoundaryRule = "center",
) -> CapsulePaintResult:
    """Paint same-state rectangular-marker segments in one tree traversal.

    Each segment keeps the exact :func:`apply_marker` footprint.  In
    particular, ``angle_degrees=None`` follows each segment independently, so
    batching does not alter a direction-following marker's geometry.
    """

    triangle = _as_triangle(vertices)
    segments = _as_screen_segments(segments_xy)
    if len(segments) == 0:
        # Keep argument validation consistent with one ordinary marker call,
        # even though there is no footprint to retain for an empty batch.
        marker_stroke_polygon(
            np.zeros(2, dtype=np.float64),
            np.zeros(2, dtype=np.float64),
            width,
            thickness=thickness,
            angle_degrees=angle_degrees,
        )
    polygons = tuple(
        marker_stroke_polygon(
            segment[0],
            segment[1],
            width,
            thickness=thickness,
            angle_degrees=angle_degrees,
        )
        for segment in segments
    )
    polygon_bounds = np.empty((len(polygons), 4), dtype=np.float64)
    for polygon_index, polygon in enumerate(polygons):
        polygon_bounds[polygon_index, :2] = np.min(polygon, axis=0) - 2.0 * _EPSILON
        polygon_bounds[polygon_index, 2:] = np.max(polygon, axis=0) + 2.0 * _EPSILON
    requested = _validate_state(state)
    depth_limit = int(max_depth)
    if depth_limit < 0 or depth_limit > MAX_DEPTH:
        raise SmoothPaintError(f"max_depth must be in 0..{MAX_DEPTH}")
    edge_limit = float(min_edge_pixels)
    if not math.isfinite(edge_limit) or edge_limit < 0.0:
        raise SmoothPaintError("min_edge_pixels must be finite and non-negative")
    if boundary_rule not in ("center", "inside", "intersect"):
        raise SmoothPaintError(f"unknown boundary_rule: {boundary_rule!r}")

    def relation(screen: np.ndarray, region_index: int) -> CapsuleRelation:
        return _triangle_convex_polygon_relation_after_bounds(
            screen,
            polygons[region_index],
        )

    def contains_center(center: np.ndarray, region_index: int) -> bool:
        return _point_in_convex_polygon(center, polygons[region_index])

    return _apply_segment_regions(
        node,
        triangle,
        len(polygons),
        requested,
        relation=relation,
        contains_center=contains_center,
        region_bounds=polygon_bounds,
        projector=projector,
        depth_limit=depth_limit,
        edge_limit=edge_limit,
        boundary_rule=boundary_rule,
    )


def painted_marker(
    node: PaintNode,
    vertices: np.ndarray,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    width: float,
    state: int,
    **kwargs: object,
) -> tuple[PaintNode, CapsulePaintResult]:
    """Clone ``node``, apply a rectangular marker, and return both results."""

    output = node.clone()
    result = apply_marker(
        output,
        vertices,
        start_xy,
        end_xy,
        width,
        state,
        **kwargs,
    )
    return output, result


def _leaf_nibbles(state: int) -> list[int]:
    extruder = _validate_state(state) + 1
    if extruder < 3:
        return [extruder << 2]
    output = [0xC]
    extension = extruder - 3
    while extension >= 15:
        output.append(0xF)
        extension -= 15
    output.append(extension)
    return output


def encode_paint_color(node: PaintNode, *, max_depth: int = MAX_DEPTH) -> str:
    """Encode a tree into Orca v2.3.4's canonical hexadecimal attribute."""

    node.validate(max_depth=max_depth)
    nibbles: list[int] = []

    def serialize(current: PaintNode) -> None:
        if current.children is None:
            nibbles.extend(_leaf_nibbles(int(current.state)))
            return
        code = current.split_sides | (current.special_side << 2)
        nibbles.append(code)
        # Orca serializes children in reverse geometric order for compatibility
        # with PrusaSlicer 2.3.1.
        for child in reversed(current.children):
            serialize(child)

    serialize(node)
    # FacetsAnnotation::get_triangle_as_string inserts every nibble at the
    # beginning of the output string, reversing the serialized stream once more.
    return "".join(_HEX_DIGITS[nibble] for nibble in reversed(nibbles))


def decode_paint_color(value: str, *, max_depth: int = MAX_DEPTH) -> PaintNode:
    """Decode a Full Spectrum Orca ``paint_color`` string into a PaintNode."""

    if not isinstance(value, str):
        raise PaintColorCodecError("paint_color must be a string")
    encoded = value.strip().upper()
    if not encoded:
        raise PaintColorCodecError("paint_color must not be empty")
    try:
        nibbles = [_HEX_DIGITS.index(character) for character in reversed(encoded)]
    except ValueError as exc:
        raise PaintColorCodecError(f"paint_color is not hexadecimal: {value!r}") from exc

    depth_limit = int(max_depth)
    if depth_limit < 0 or depth_limit > MAX_DEPTH:
        raise PaintColorCodecError(f"max_depth must be in 0..{MAX_DEPTH}")
    offset = 0

    def take() -> int:
        nonlocal offset
        if offset >= len(nibbles):
            raise PaintColorCodecError("paint_color ended in the middle of a node")
        result = nibbles[offset]
        offset += 1
        return result

    def parse(depth: int) -> PaintNode:
        if depth > depth_limit:
            raise PaintColorCodecError(
                f"paint_color tree exceeds maximum depth {depth_limit}"
            )
        code = take()
        split_sides = code & 0x3
        upper = code >> 2
        if split_sides == 0:
            if upper == 3:
                extruder = 3
                while True:
                    extension = take()
                    extruder += extension
                    if extension != 0xF:
                        break
            else:
                extruder = upper
            if extruder < 1 or extruder > STATE_COUNT:
                raise PaintColorCodecError(
                    f"paint_color leaf uses unsupported extruder state {extruder}"
                )
            return PaintNode(extruder - 1)

        special_side = upper
        if special_side not in (0, 1, 2):
            raise PaintColorCodecError(
                f"paint_color uses invalid special side {special_side}"
            )
        if split_sides == 3 and special_side != 0:
            raise PaintColorCodecError("a three-side split must use special side 0")
        serialized_children = tuple(parse(depth + 1) for _ in range(split_sides + 1))
        return PaintNode.branch(
            tuple(reversed(serialized_children)),
            split_sides=split_sides,
            special_side=special_side,
        )

    root = parse(0)
    if offset != len(nibbles):
        raise PaintColorCodecError(
            f"paint_color has {len(nibbles) - offset} trailing nibble(s)"
        )
    root.validate(max_depth=depth_limit)
    return root


def reencode_paint_color(value: str, *, max_depth: int = MAX_DEPTH) -> str:
    """Decode and emit the canonical uppercase Orca representation."""

    return encode_paint_color(decode_paint_color(value, max_depth=max_depth), max_depth=max_depth)


__all__ = [
    "BoundaryRule",
    "CapsulePaintResult",
    "CapsuleRelation",
    "LeafTriangle",
    "MAX_DEPTH",
    "PaintColorCodecError",
    "PaintNode",
    "STATE_COUNT",
    "SmoothPaintError",
    "StrokePaintResult",
    "StrokeRelation",
    "apply_capsule",
    "apply_capsule_segments",
    "apply_variable_capsule_segments",
    "apply_marker",
    "apply_marker_segments",
    "clone_node",
    "collapse_node",
    "decode_paint_color",
    "dominant_state",
    "encode_paint_color",
    "iter_leaf_triangles",
    "marker_stroke_polygon",
    "painted_capsule",
    "painted_marker",
    "reencode_paint_color",
    "subdivide_triangle",
    "triangle_capsule_relation",
    "triangle_marker_relation",
]
