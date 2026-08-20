"""Executable reference for Orca v2.3.4 ``paint_color`` encoding.

The reference codec below is intentionally independent of ``smooth_paint``.
It is a direct translation of these Snapmaker Orca v2.3.4 code paths:

* ``TriangleSelector::serialize`` / ``deserialize``
* ``FacetsAnnotation::get_triangle_as_string``
* ``FacetsAnnotation::set_triangle_from_string``

Raw reference leaf states use Orca's ``EnforcerBlockerType`` numbering:
``NONE=0``, ``Extruder1=1``, ..., ``Extruder255=255``.  The application-facing
``smooth_paint.PaintNode`` deliberately uses Full Spectrum palette indices
0..9 instead, so its compatibility adapter adds or removes one.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unittest
from typing import Any


try:
    import smooth_paint as sut
except ModuleNotFoundError as exc:  # Allow the reference suite to run first.
    if exc.name != "smooth_paint":
        raise
    sut = None


VECTOR_PATH = Path(__file__).with_name("orca_paint_vectors.json")
HEX_DIGITS = "0123456789ABCDEF"
UPPER_HEX = re.compile(r"[0-9A-F]+\Z")
RawTree = dict[str, Any]


def load_vectors() -> dict[str, Any]:
    with VECTOR_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    return value


def reference_encode_paint_color(tree: RawTree) -> str:
    """Encode a raw Orca subdivision tree exactly like v2.3.4.

    The generated nibble list is the logical root-first bitstream.  Orca then
    prepends each nibble while producing the XML attribute, hence the final
    reversal in the return statement.
    """

    logical_nibbles: list[int] = []

    def serialize(node: object) -> None:
        if not isinstance(node, dict):
            raise ValueError("each paint tree node must be an object")
        if "state" in node:
            if set(node) != {"state"}:
                raise ValueError("a leaf node may contain only state")
            state = _strict_int(node["state"], "state")
            if not 0 <= state <= 255:
                raise ValueError("state must be in Orca's range 0..255")
            if state < 3:
                logical_nibbles.append(state << 2)
                return
            logical_nibbles.append(0xC)
            extension = state - 3
            while extension >= 15:
                logical_nibbles.append(0xF)
                extension -= 15
            logical_nibbles.append(extension)
            return

        required = {"split_sides", "special_side", "children"}
        if set(node) != required:
            raise ValueError(
                "an internal node requires split_sides, special_side, and children"
            )
        split_sides = _strict_int(node["split_sides"], "split_sides")
        special_side = _strict_int(node["special_side"], "special_side")
        children = node["children"]
        if split_sides not in (1, 2, 3):
            raise ValueError("split_sides must be 1, 2, or 3")
        if special_side not in (0, 1, 2):
            raise ValueError("special_side must be 0, 1, or 2")
        if split_sides == 3 and special_side != 0:
            raise ValueError("a three-side split requires special_side 0")
        if not isinstance(children, list) or len(children) != split_sides + 1:
            raise ValueError("child count must equal split_sides + 1")

        logical_nibbles.append(split_sides | (special_side << 2))
        # TriangleSelector::serialize visits child N down to child 0.
        for child in reversed(children):
            serialize(child)

    serialize(tree)
    return "".join(HEX_DIGITS[nibble] for nibble in reversed(logical_nibbles))


def reference_decode_paint_color(value: str) -> RawTree:
    """Decode one uppercase Orca ``paint_color`` value into a raw tree."""

    if not isinstance(value, str) or not value or UPPER_HEX.fullmatch(value) is None:
        raise ValueError("paint_color must be a non-empty uppercase hexadecimal string")

    # set_triangle_from_string iterates the XML string in reverse.
    logical_nibbles = [int(character, 16) for character in reversed(value)]
    offset = 0

    def take(context: str) -> int:
        nonlocal offset
        if offset >= len(logical_nibbles):
            raise ValueError(f"paint_color is truncated {context}")
        nibble = logical_nibbles[offset]
        offset += 1
        return nibble

    def parse() -> RawTree:
        code = take("in a node")
        split_sides = code & 0x3
        upper = code >> 2
        if split_sides:
            special_side = upper
            if special_side not in (0, 1, 2):
                raise ValueError(f"invalid special_side {special_side}")
            if split_sides == 3 and special_side != 0:
                raise ValueError(
                    f"invalid special_side {special_side} for a three-side split"
                )

            children: list[RawTree | None] = [None] * (split_sides + 1)
            # Serialized order is child N..0, but the public tree is child 0..N.
            for child_index in range(split_sides, -1, -1):
                children[child_index] = parse()
            return {
                "split_sides": split_sides,
                "special_side": special_side,
                "children": children,
            }

        state = upper
        if state == 3:
            extension_count = 0
            extension = take("inside an extended leaf state")
            while extension == 0xF:
                extension_count += 1
                extension = take("inside an extended leaf state")
            state = 3 + 15 * extension_count + extension
        if state > 255:
            raise ValueError(f"decoded state {state} exceeds Orca maximum 255")
        return {"state": state}

    tree = parse()
    if offset != len(logical_nibbles):
        raise ValueError(
            f"paint_color contains {len(logical_nibbles) - offset} trailing nibble(s)"
        )
    return tree


def summarize_raw_tree(tree: RawTree) -> dict[str, Any]:
    """Return stable structural facts used by the embedded archive vectors."""

    state_counts: Counter[int] = Counter()
    split_sides_counts: Counter[int] = Counter()
    special_side_counts: Counter[int] = Counter()
    node_count = 0
    leaf_count = 0
    split_count = 0
    max_depth = 0

    def visit(node: RawTree, depth: int) -> None:
        nonlocal node_count, leaf_count, split_count, max_depth
        node_count += 1
        max_depth = max(max_depth, depth)
        if "state" in node:
            leaf_count += 1
            state_counts[int(node["state"])] += 1
            return
        split_count += 1
        split_sides_counts[int(node["split_sides"])] += 1
        special_side_counts[int(node["special_side"])] += 1
        for child in node["children"]:
            visit(child, depth + 1)

    visit(tree, 0)
    canonical = json.dumps(tree, sort_keys=True, separators=(",", ":"))
    return {
        "node_count": node_count,
        "leaf_count": leaf_count,
        "split_count": split_count,
        "max_depth": max_depth,
        "state_counts": {
            str(key): value for key, value in sorted(state_counts.items())
        },
        "split_sides_counts": {
            str(key): value for key, value in sorted(split_sides_counts.items())
        },
        "special_side_counts": {
            str(key): value for key, value in sorted(special_side_counts.items())
        },
        "tree_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _raw_tree_to_sut(tree: RawTree):
    """Convert raw Extruder1..10 leaves to zero-based Full Spectrum nodes."""

    if sut is None:
        raise RuntimeError("smooth_paint is not installed")
    if "state" in tree:
        orca_state = int(tree["state"])
        if not 1 <= orca_state <= 10:
            raise ValueError("tree is outside the Full Spectrum state range")
        return sut.PaintNode(orca_state - 1)
    return sut.PaintNode.branch(
        tuple(_raw_tree_to_sut(child) for child in tree["children"]),
        split_sides=int(tree["split_sides"]),
        special_side=int(tree["special_side"]),
    )


def _sut_tree_to_raw(node: object) -> RawTree:
    children = getattr(node, "children")
    if children is None:
        # Public PaintNode state 0 is Orca Extruder1, not Orca NONE.
        return {"state": int(getattr(node, "state")) + 1}
    return {
        "split_sides": int(getattr(node, "split_sides")),
        "special_side": int(getattr(node, "special_side")),
        "children": [_sut_tree_to_raw(child) for child in children],
    }


class OrcaReferenceCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vectors = load_vectors()

    def test_vectors_are_pinned_to_snapmaker_orca_234(self):
        source = self.vectors["source"]
        self.assertEqual(source["tag"], "v2.3.4")
        self.assertEqual(
            source["commit"], "9fd12ffb2b1b80c9fb4c14564754d2ec1573a626"
        )

    def test_all_declared_tree_vectors_encode_and_decode_exactly(self):
        for vector in self.vectors["tree_vectors"]:
            with self.subTest(vector=vector["name"]):
                expected = vector["expected"]
                tree = vector["tree"]
                self.assertEqual(reference_encode_paint_color(tree), expected)
                self.assertEqual(reference_decode_paint_color(expected), tree)
                self.assertEqual(
                    reference_encode_paint_color(
                        reference_decode_paint_color(expected)
                    ),
                    expected,
                )

    def test_every_raw_orca_state_round_trips(self):
        for state in range(256):
            with self.subTest(state=state):
                tree = {"state": state}
                encoded = reference_encode_paint_color(tree)
                self.assertEqual(reference_decode_paint_color(encoded), tree)

    def test_embedded_real_archive_values_round_trip_and_match_summaries(self):
        for vector in self.vectors["archive_vectors"]:
            with self.subTest(vector=vector["name"]):
                encoded = vector["paint_color"]
                self.assertEqual(len(encoded), vector["expected_length"])
                self.assertEqual(
                    hashlib.sha256(encoded.encode("ascii")).hexdigest(),
                    vector["paint_color_sha256"],
                )
                tree = reference_decode_paint_color(encoded)
                self.assertEqual(summarize_raw_tree(tree), vector["expected_summary"])
                self.assertEqual(reference_encode_paint_color(tree), encoded)

    def test_invalid_streams_are_rejected(self):
        for vector in self.vectors["invalid_vectors"]:
            with self.subTest(value=vector["value"]):
                with self.assertRaisesRegex(
                    ValueError, re.escape(vector["error_contains"])
                ):
                    reference_decode_paint_color(vector["value"])


@unittest.skipIf(sut is None, "smooth_paint.py has not been added yet")
class SmoothPaintCodecCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vectors = load_vectors()

    def test_expected_public_codec_api_exists(self):
        for name in (
            "PaintNode",
            "decode_paint_color",
            "encode_paint_color",
            "reencode_paint_color",
        ):
            self.assertTrue(hasattr(sut, name), name)

    def test_full_spectrum_tree_vectors_match_reference(self):
        for vector in self.vectors["tree_vectors"]:
            if not vector.get("sut_compatible", False):
                continue
            with self.subTest(vector=vector["name"]):
                expected = vector["expected"]
                raw_tree = vector["tree"]
                node = _raw_tree_to_sut(raw_tree)
                self.assertEqual(sut.encode_paint_color(node), expected)
                decoded = sut.decode_paint_color(expected)
                self.assertEqual(_sut_tree_to_raw(decoded), raw_tree)
                self.assertEqual(sut.encode_paint_color(decoded), expected)
                self.assertEqual(sut.reencode_paint_color(expected), expected)

    def test_real_full_spectrum_subdivision_stream_matches_reference(self):
        compatible = [
            vector
            for vector in self.vectors["archive_vectors"]
            if vector.get("sut_compatible", False)
        ]
        self.assertTrue(compatible)
        for vector in compatible:
            with self.subTest(vector=vector["name"]):
                encoded = vector["paint_color"]
                decoded = sut.decode_paint_color(encoded)
                raw_tree = _sut_tree_to_raw(decoded)
                self.assertEqual(summarize_raw_tree(raw_tree), vector["expected_summary"])
                self.assertEqual(sut.encode_paint_color(decoded), encoded)
                self.assertEqual(sut.reencode_paint_color(encoded), encoded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
