"""Rebuild or verify the bundled polynomial filament-mixer data.

Input is the MIT-licensed ``cpp/filament_mixer.h`` from the exact upstream
revision recorded in ``assets/mixer_model_PROVENANCE.md``.  No network access
is performed; callers supply the downloaded header explicitly.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import numpy as np


SOURCE_NOTE = "Snapmaker Orca filament_mixer_model.h, MIT, 2026 Justin Hayes"


def _array_block(text: str, declaration: str, next_declaration: str) -> str:
    try:
        return text.split(declaration, 1)[1].split(next_declaration, 1)[0]
    except IndexError as exc:
        raise ValueError(f"missing C++ array declaration: {declaration}") from exc


def parse_header(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    text = path.read_text(encoding="utf-8")
    powers_block = _array_block(
        text,
        "static const int POWERS",
        "static const double COEF",
    )
    coefficients_block = _array_block(
        text,
        "static const double COEF",
        "static const double INTERCEPT",
    )
    power_rows = re.findall(r"\{([^{}]+)\}", powers_block)
    coefficient_rows = re.findall(r"\{([^{}]+)\}", coefficients_block)
    intercept_match = re.search(
        r"static const double INTERCEPT\[3\]\s*=\s*\{([^}]+)\}",
        text,
    )
    if intercept_match is None:
        raise ValueError("missing INTERCEPT array")

    powers = np.asarray(
        [[int(value) for value in row.split(",")] for row in power_rows],
        dtype=np.int8,
    )
    coefficients = np.asarray(
        [[float(value) for value in row.split(",")] for row in coefficient_rows],
        dtype=np.float64,
    )
    intercept = np.asarray(
        [float(value) for value in intercept_match.group(1).split(",")],
        dtype=np.float64,
    )
    if powers.shape != (330, 7):
        raise ValueError(f"unexpected POWERS shape: {powers.shape}")
    if coefficients.shape != (330, 3):
        raise ValueError(f"unexpected COEF shape: {coefficients.shape}")
    if intercept.shape != (3,):
        raise ValueError(f"unexpected INTERCEPT shape: {intercept.shape}")
    return powers, coefficients, intercept


def write_model(
    output: Path,
    powers: np.ndarray,
    coefficients: np.ndarray,
    intercept: np.ndarray,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        powers=powers,
        coefficients=coefficients,
        intercept=intercept,
        source=np.asarray(SOURCE_NOTE),
    )


def verify_model(
    model: Path,
    powers: np.ndarray,
    coefficients: np.ndarray,
    intercept: np.ndarray,
) -> None:
    with np.load(model, allow_pickle=False) as data:
        expected_keys = ["powers", "coefficients", "intercept", "source"]
        if list(data.files) != expected_keys:
            raise ValueError(f"unexpected NPZ entries: {data.files}")
        if not np.array_equal(data["powers"], powers):
            raise ValueError("POWERS differ from the supplied header")
        if not np.array_equal(data["coefficients"], coefficients):
            raise ValueError("COEF differs from the supplied header")
        if not np.array_equal(data["intercept"], intercept):
            raise ValueError("INTERCEPT differs from the supplied header")
        if str(data["source"].item()) != SOURCE_NOTE:
            raise ValueError("source note differs from the recorded provenance")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("header", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify", type=Path)
    args = parser.parse_args()

    powers, coefficients, intercept = parse_header(args.header)
    if args.output is not None:
        write_model(args.output, powers, coefficients, intercept)
        print(f"wrote {args.output}")
    else:
        verify_model(args.verify, powers, coefficients, intercept)
        print(f"verified {args.verify}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

