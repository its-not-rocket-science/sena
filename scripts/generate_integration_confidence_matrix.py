from __future__ import annotations

import argparse
from pathlib import Path

from sena.integrations.confidence_matrix import render_integration_confidence_matrix_json


DEFAULT_JIRA_MAPPING = Path("src/sena/examples/integrations/jira_mappings.yaml")
DEFAULT_SERVICENOW_MAPPING = Path("src/sena/examples/integrations/servicenow_mappings.yaml")
DEFAULT_ASSERTIONS = Path("tests/fixtures/integrations/confidence_assertions.json")
DEFAULT_OUTPUT = Path("docs/artifacts/integrations/jira_servicenow_confidence_matrix.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or validate the Jira + ServiceNow integration confidence matrix."
    )
    parser.add_argument("--jira-mapping", type=Path, default=DEFAULT_JIRA_MAPPING)
    parser.add_argument("--servicenow-mapping", type=Path, default=DEFAULT_SERVICENOW_MAPPING)
    parser.add_argument("--assertions", type=Path, default=DEFAULT_ASSERTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the output file does not match the generated matrix.",
    )
    args = parser.parse_args()

    rendered = render_integration_confidence_matrix_json(
        jira_mapping_path=args.jira_mapping,
        servicenow_mapping_path=args.servicenow_mapping,
        assertions_path=args.assertions,
    )

    if args.check:
        existing = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if rendered != existing:
            raise SystemExit(
                f"integration confidence matrix drift detected: run `python {Path(__file__).as_posix()}`"
            )
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
