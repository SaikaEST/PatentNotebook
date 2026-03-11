from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from ep_ingest.errors import BlockedError, NetworkError, NotFoundError, ParsingError

OPS_BASE_URL = "https://ops.epo.org/3.2"
OPS_REST_BASE_URL = f"{OPS_BASE_URL}/rest-services"
OPS_AUTH_URL = f"{OPS_BASE_URL}/auth/accesstoken"


@dataclass
class OpsResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class OpsClient:
    def __init__(
        self,
        *,
        key: str,
        secret: str,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.key = key
        self.secret = secret
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "ep-ingest/0.1 (+OPS-v3.2)"},
        )
        self._token: str | None = None
        self._token_expiry_monotonic = 0.0

    def close(self) -> None:
        self.client.close()

    def _ensure_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._token_expiry_monotonic:
            return self._token

        try:
            response = self.client.post(
                OPS_AUTH_URL,
                auth=(self.key, self.secret),
                content="grant_type=client_credentials",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        except httpx.RequestError as exc:
            raise NetworkError("Failed to request OPS access token") from exc

        if response.status_code in (401, 403):
            detail = self._error_detail(response)
            raise BlockedError(
                "OPS authentication failed "
                f"(status={response.status_code}, detail={detail})"
            )
        if response.status_code >= 400:
            detail = self._error_detail(response)
            raise NetworkError(
                f"OPS token endpoint returned status {response.status_code} (detail={detail})"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ParsingError("OPS token response is not valid JSON") from exc

        token = payload.get("access_token")
        if not token:
            raise ParsingError("OPS token response missing access_token")
        expires_in = int(payload.get("expires_in", 1199))

        # Keep a safety buffer to avoid using nearly expired tokens.
        self._token = str(token)
        self._token_expiry_monotonic = time.monotonic() + max(30, expires_in - 30)
        return self._token

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                desc = payload.get("error_description") or payload.get("message")
                if error and desc:
                    return f"{error}: {desc}"
                if error:
                    return str(error)
        except ValueError:
            pass
        text = response.text.strip()
        if not text:
            return "empty response body"
        compact = " ".join(text.split())
        return compact[:200]

    def _request(
        self,
        method: str,
        path: str,
        *,
        accept: str,
        params: dict[str, Any] | None = None,
        content: str | bytes | None = None,
        content_type: str | None = None,
        _retry_on_unauthorized: bool = True,
    ) -> OpsResponse:
        token = self._ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": accept,
        }
        if content_type:
            headers["Content-Type"] = content_type

        url = f"{OPS_REST_BASE_URL}/{path.lstrip('/')}"
        try:
            response = self.client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                content=content,
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"OPS request failed for {url}") from exc

        if response.status_code == 401 and _retry_on_unauthorized:
            self._token = None
            return self._request(
                method,
                path,
                accept=accept,
                params=params,
                content=content,
                content_type=content_type,
                _retry_on_unauthorized=False,
            )
        if response.status_code == 404:
            raise NotFoundError(f"OPS resource not found: {path}")
        if response.status_code in (401, 403, 429):
            raise BlockedError(f"OPS access blocked (status={response.status_code})")
        if response.status_code >= 400:
            raise NetworkError(f"OPS returned status {response.status_code} for {path}")

        return OpsResponse(
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            content=response.content,
        )

    def register_endpoint(
        self,
        *,
        reference_type: str,
        epodoc_input: str,
        endpoint: str,
        accept: str = "application/register+xml",
    ) -> str:
        response = self._request(
            "GET",
            f"register/{reference_type}/epodoc/{epodoc_input}/{endpoint}",
            accept=accept,
        )
        return response.text

    def published_images_inquiry(
        self,
        *,
        reference_type: str,
        epodoc_input: str,
        accept: str = "application/xml",
    ) -> str:
        path = f"published-data/images/{reference_type}/epodoc/{epodoc_input}"
        try:
            response = self._request(
                "GET",
                path,
                accept=accept,
            )
            return response.text
        except NetworkError as exc:
            # OPS may reject some Accept values for specific resources.
            if "status 406" not in str(exc) or accept == "text/xml":
                raise
            retry_response = self._request(
                "GET",
                path,
                accept="text/xml",
            )
            return retry_response.text

    def published_image_retrieval(
        self,
        *,
        image_path: str,
        page: int = 1,
        accept: str = "application/pdf",
    ) -> bytes:
        response = self._request(
            "POST",
            "published-data/images",
            accept=accept,
            params={"Range": str(page)},
            content=image_path,
            content_type="text/plain",
        )
        return response.content
