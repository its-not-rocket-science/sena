from __future__ import annotations

import base64
import json
from urllib import request


class JiraRestClient:
    def __init__(
        self,
        *,
        base_url: str | None,
        username: str | None,
        api_token: str | None,
        oauth_token: str | None,
        approved_transition_id: str | None,
        blocked_transition_id: str | None,
    ) -> None:
        if not base_url:
            raise ValueError("SENA_JIRA_BASE_URL is required for write-back")
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._api_token = api_token
        self._oauth_token = oauth_token
        self._approved_transition_id = approved_transition_id
        self._blocked_transition_id = blocked_transition_id

    def _auth_headers(self) -> dict[str, str]:
        if self._oauth_token:
            return {"Authorization": f"Bearer {self._oauth_token}"}
        if self._username and self._api_token:
            token = base64.b64encode(
                f"{self._username}:{self._api_token}".encode("utf-8")
            ).decode("utf-8")
            return {"Authorization": f"Basic {token}"}
        raise ValueError(
            "Jira write-back requires OAuth token or username/api token credentials"
        )

    def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self._base_url}{path}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                **self._auth_headers(),
            },
        )
        with request.urlopen(req, timeout=10) as resp:  # nosec B310
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {"status": resp.status}

    def publish_comment(self, issue_key: str, message: str) -> dict:
        return self._post(
            f"/rest/api/3/issue/{issue_key}/comment",
            {"body": message},
        )

    def publish_status(self, issue_key: str, payload: dict) -> dict:
        summary = str(payload.get("summary") or "")
        transition_id = None
        if summary == "APPROVED":
            transition_id = self._approved_transition_id
        elif summary in {"BLOCKED", "ESCALATE_FOR_HUMAN_REVIEW"}:
            transition_id = self._blocked_transition_id
        if not transition_id:
            return {"status": "skipped", "reason": "no transition mapping"}
        return self._post(
            f"/rest/api/3/issue/{issue_key}/transitions",
            {"transition": {"id": transition_id}},
        )
