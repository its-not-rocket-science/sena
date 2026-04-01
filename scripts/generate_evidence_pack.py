from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

DEFAULT_REFERENCE_ROOT = ROOT / "examples" / "design_partner_reference"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic evidence pack artifacts for policy releases")
    parser.add_argument("--reference-root", type=Path, default=DEFAULT_REFERENCE_ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path)
    parser.add_argument("--clean", action="store_true", help="Delete existing output directory before generating")
    return parser.parse_args()


def main() -> None:
    from sena.evidence_pack import build_evidence_pack, stable_zip_dir

    args = parse_args()
    result = build_evidence_pack(reference_root=args.reference_root, output_dir=args.output_dir, clean=args.clean)
    if args.output_zip:
        stable_zip_dir(args.output_dir, args.output_zip)
        result["output_zip"] = str(args.output_zip)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
