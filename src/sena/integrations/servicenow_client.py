from __future__ import annotations

import base64
import json
from urllib import request


class ServiceNowRestClient:
    def __init__(
        self,
        *,
        base_url: str | None,
        username: str | None,
        password: str | None,
        oauth_token: str | None,
    ) -> None:
        if not base_url:
            raise ValueError("SENA_SERVICENOW_BASE_URL is required for write-back")
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._oauth_token = oauth_token

    def _auth_headers(self) -> dict[str, str]:
        if self._oauth_token:
            return {"Authorization": f"Bearer {self._oauth_token}"}
        if self._username and self._password:
            token = base64.b64encode(
                f"{self._username}:{self._password}".encode("utf-8")
            ).decode("utf-8")
            return {"Authorization": f"Basic {token}"}
        raise ValueError(
            "ServiceNow write-back requires OAuth token or username/password credentials"
        )

    def publish_callback(self, payload: dict) -> dict:
        req = request.Request(
            url=f"{self._base_url}/api/now/table/change_request",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", **self._auth_headers()},
        )
        with request.urlopen(req, timeout=10) as resp:  # nosec B310
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {"status": resp.status}
