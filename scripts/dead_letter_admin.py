from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _request_json(url: str, method: str, api_key: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
    )
    with urllib.request.urlopen(request) as response:  # nosec B310
        return response.status, json.loads(response.read().decode("utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operator helper for outbound dead-letter list/replay/manual-redrive"
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--connector", choices=["jira", "servicenow"], required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--dry-run", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--limit", type=int, default=20)

    replay_cmd = sub.add_parser("replay")
    replay_cmd.add_argument("--ids", type=int, nargs="+", required=True)

    redrive_cmd = sub.add_parser("manual-redrive")
    redrive_cmd.add_argument("--ids", type=int, nargs="+", required=True)
    redrive_cmd.add_argument("--note", default="manually redriven")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    base = args.base_url.rstrip("/")
    prefix = f"{base}/v1/integrations/{args.connector}/admin/outbound/dead-letter"

    if args.command == "list":
        method = "GET"
        url = f"{prefix}?limit={args.limit}"
        body = None
    elif args.command == "replay":
        method = "POST"
        url = f"{prefix}/replay"
        body = args.ids
    else:
        method = "POST"
        url = f"{prefix}/manual-redrive"
        body = {"ids": args.ids, "note": args.note}

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "method": method,
                    "url": url,
                    "body": body,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    try:
        if args.command == "manual-redrive":
            # FastAPI expects query params for primitive args.
            query = "&".join([f"ids={value}" for value in args.ids])
            query = f"{query}&note={urllib.parse.quote(args.note)}"
            status, payload = _request_json(
                f"{url}?{query}",
                method,
                api_key=args.api_key,
                body=None,
            )
        elif args.command == "replay":
            status, payload = _request_json(url, method, api_key=args.api_key, body=args.ids)
        else:
            status, payload = _request_json(url, method, api_key=args.api_key, body=None)
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        print(
            json.dumps(
                {
                    "status": "http_error",
                    "code": exc.code,
                    "reason": exc.reason,
                    "response": message,
                },
                indent=2,
            )
        )
        raise SystemExit(1) from exc

    print(json.dumps({"status": "ok", "http_status": status, "response": payload}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
