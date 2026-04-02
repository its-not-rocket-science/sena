from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from sena.integrations.base import Connector, DecisionPayload, IntegrationError


class SlackIntegrationError(IntegrationError):
    """Raised when Slack integration calls fail deterministically."""


@dataclass(frozen=True)
class SlackEscalationMessage:
    channel: str
    text: str
    blocks: list[dict[str, Any]]


class SlackClient(Connector):
    name = "slack"
    """Minimal Slack Web API wrapper for posting escalation decisions."""

    def __init__(self, bot_token: str, default_channel: str):
        if not bot_token.strip():
            raise SlackIntegrationError("Slack bot token must be non-empty")
        if not default_channel.strip():
            raise SlackIntegrationError("Slack default channel must be non-empty")
        self._bot_token = bot_token.strip()
        self._default_channel = default_channel.strip()

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return parse_interaction_decision(event)

    def send_decision(self, payload: DecisionPayload) -> dict[str, Any]:
        return self.post_escalation(
            decision_id=payload.decision_id,
            request_id=payload.request_id,
            action_type=payload.action_type,
            matched_rule_ids=payload.matched_rule_ids,
            summary=payload.summary,
        )

    def build_escalation_message(
        self,
        *,
        decision_id: str,
        request_id: str | None,
        action_type: str,
        matched_rule_ids: list[str],
        summary: str,
        channel: str | None = None,
    ) -> SlackEscalationMessage:
        destination = (channel or self._default_channel).strip()
        if not destination:
            raise SlackIntegrationError("Slack channel must be non-empty")

        timestamp = datetime.now(timezone.utc).isoformat()
        rules_text = ", ".join(matched_rule_ids) if matched_rule_ids else "none"
        request_label = request_id or "unknown"
        fallback_text = f"SENA escalation: decision={decision_id} action={action_type} request={request_label}"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*SENA escalation requires human review*\n"
                        f"*Decision ID:* `{decision_id}`\n"
                        f"*Request ID:* `{request_label}`\n"
                        f"*Action:* `{action_type}`\n"
                        f"*Matched rules:* `{rules_text}`\n"
                        f"*Summary:* {summary}\n"
                        f"*Timestamp (UTC):* `{timestamp}`"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "sena_escalation_approve",
                        "value": decision_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": "sena_escalation_reject",
                        "value": decision_id,
                    },
                ],
            },
        ]
        return SlackEscalationMessage(
            channel=destination, text=fallback_text, blocks=blocks
        )

    def post_escalation(
        self,
        *,
        decision_id: str,
        request_id: str | None,
        action_type: str,
        matched_rule_ids: list[str],
        summary: str,
        channel: str | None = None,
    ) -> dict[str, Any]:
        message = self.build_escalation_message(
            decision_id=decision_id,
            request_id=request_id,
            action_type=action_type,
            matched_rule_ids=matched_rule_ids,
            summary=summary,
            channel=channel,
        )
        body = json.dumps(
            {
                "channel": message.channel,
                "text": message.text,
                "blocks": message.blocks,
            }
        ).encode("utf-8")
        req = request.Request(
            "https://slack.com/api/chat.postMessage",
            data=body,
            headers={
                "Authorization": f"Bearer {self._bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as resp:  # nosec: B310
                payload = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise SlackIntegrationError(f"Slack API HTTP error: {exc.code}") from exc
        except URLError as exc:
            raise SlackIntegrationError(
                f"Slack API connectivity error: {exc.reason}"
            ) from exc

        if not payload.get("ok"):
            raise SlackIntegrationError(
                f"Slack API rejected message: {payload.get('error', 'unknown')}"
            )
        return payload


def parse_interaction_decision(payload: dict[str, Any]) -> dict[str, str]:
    """Extract deterministic decision from a Slack interaction callback payload."""

    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        raise SlackIntegrationError("Slack interaction missing actions")
    action = actions[0]
    action_id = action.get("action_id")
    if action_id == "sena_escalation_approve":
        decision = "APPROVE"
    elif action_id == "sena_escalation_reject":
        decision = "REJECT"
    else:
        raise SlackIntegrationError(f"Unsupported Slack action_id '{action_id}'")

    decision_id = str(action.get("value") or "").strip()
    if not decision_id:
        raise SlackIntegrationError(
            "Slack interaction action value is missing decision id"
        )

    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    reviewer = str(user.get("id") or "unknown")

    return {
        "decision": decision,
        "decision_id": decision_id,
        "reviewer": reviewer,
    }
