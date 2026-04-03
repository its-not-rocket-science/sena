from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

PROMPT = "Suggest a change to this deployment to handle high traffic"


@dataclass(frozen=True)
class AISuggestedChange:
    deployment_name: str
    namespace: str
    current_replicas: int
    proposed_replicas: int
    reasoning: str

    def as_dict(self) -> dict[str, object]:
        return {
            "deployment_name": self.deployment_name,
            "namespace": self.namespace,
            "current_replicas": self.current_replicas,
            "proposed_replicas": self.proposed_replicas,
            "reasoning": self.reasoning,
        }


def _extract_replicas(raw_text: str, default: int = 10) -> int:
    match = re.search(r"(?:replicas?|scale\s+to)\D*(\d{1,3})", raw_text, re.I)
    if match is None:
        return default
    return int(match.group(1))


def _call_openai_for_suggestion(
    *, deployment_name: str, namespace: str, current_replicas: int
) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    user_prompt = (
        f"{PROMPT}. Deployment={deployment_name} namespace={namespace} "
        f"current_replicas={current_replicas}. Keep answer short."
    )
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            }
        ],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))

    output = body.get("output", [])
    text_parts: list[str] = []
    for item in output:
        for content in item.get("content", []):
            maybe_text = content.get("text")
            if isinstance(maybe_text, str):
                text_parts.append(maybe_text)
    return " ".join(text_parts).strip() or "Increase replicas to 10"


def suggest_change(
    *,
    deployment_name: str = "payments-api",
    namespace: str = "production",
    current_replicas: int = 3,
) -> AISuggestedChange:
    backend = os.getenv("AI_SIMULATOR_BACKEND", "simulated")
    raw_suggestion: str
    if backend == "openai":
        try:
            raw_suggestion = _call_openai_for_suggestion(
                deployment_name=deployment_name,
                namespace=namespace,
                current_replicas=current_replicas,
            )
        except (RuntimeError, urllib.error.URLError, TimeoutError):
            raw_suggestion = "Scale to 10 replicas to absorb expected demand spikes."
    else:
        raw_suggestion = "Scale to 10 replicas to absorb expected demand spikes."

    proposed_replicas = _extract_replicas(raw_suggestion)
    return AISuggestedChange(
        deployment_name=deployment_name,
        namespace=namespace,
        current_replicas=current_replicas,
        proposed_replicas=proposed_replicas,
        reasoning=raw_suggestion,
    )


def main() -> None:
    suggestion = suggest_change()
    print(json.dumps({"prompt": PROMPT, "suggested_change": suggestion.as_dict()}, indent=2))


if __name__ == "__main__":
    main()
