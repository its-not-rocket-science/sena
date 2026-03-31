from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvaluateRequest:
    action_type: str
    request_id: str | None = None
    actor_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
