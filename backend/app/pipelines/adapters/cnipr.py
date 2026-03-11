from __future__ import annotations

import time
from typing import Any, Dict, List

import httpx

from app.core.config import settings
from app.pipelines.adapters.base import IngestAdapter


class CNIPRAdapter(IngestAdapter):
    name = "cnipr"
    is_official = True

    def __init__(self):
        self._token: str | None = None
        self._openid: str | None = None
        self._token_expires_at: float = 0.0

    def list_documents(self, case_no: str) -> List[Dict]:
        if not case_no or not self._is_configured():
            return []

        if not self._ensure_token():
            return []

        field = "申请号" if "/" in case_no else "公开（公告）号"
        search_payload = {
            "openid": self._openid,
            "access_token": self._token,
            "exp": f"{field}='{case_no}'",
            "dbs": [db.strip() for db in settings.cnipr_dbs.split(",") if db.strip()],
            "from": 0,
            "size": 3,
            "pidSign": 1,
            "displayCols": [
                "pid",
                "公开（公告）号",
                "申请号",
                "发明名称",
            ],
        }
        url = f"{settings.cnipr_base_url.rstrip('/')}/cnipr-api/v1/api/search/sf1/{settings.cnipr_client_id}"
        data = self._post_json(url, search_payload)
        if not data or data.get("status") != 0:
            return []

        raw_results = data.get("results") or []
        if not isinstance(raw_results, list):
            return []

        docs: List[Dict] = []
        for row in raw_results:
            if not isinstance(row, dict):
                continue
            pid = row.get("pid")
            if not pid:
                continue
            docs.append(
                {
                    "pid": str(pid),
                    "doc_type": "patent_pdf",
                    "language": "zh",
                    "title": row.get("发明名称"),
                    "publication_no": row.get("公开（公告）号"),
                    "application_no": row.get("申请号"),
                    "source_uri": f"cnipr://pid/{pid}",
                }
            )
        return docs

    def fetch_document(self, doc_meta: dict) -> Dict:
        pid = doc_meta.get("pid")
        if not pid:
            return {}
        if not self._ensure_token():
            return {}

        # CNIPR official doc: pi1 returns full-text PDF by pid.
        url = f"{settings.cnipr_base_url.rstrip('/')}/cnipr-api/v1/api/picture/pi1/{settings.cnipr_client_id}"
        params = {
            "openid": self._openid,
            "access_token": self._token,
            "pid": pid,
        }
        try:
            with httpx.Client(timeout=settings.cnipr_timeout_sec, follow_redirects=True) as client:
                resp = client.get(url, params=params)
        except Exception:
            return {}

        if resp.status_code != 200:
            return {}
        content = resp.content or b""
        if not content:
            return {}

        content_type = resp.headers.get("content-type", "application/octet-stream")
        file_name = f"{pid}.pdf"
        if "pdf" not in content_type.lower() and not content.startswith(b"%PDF"):
            # Some CNIPR errors still return JSON payload with 200.
            return {}

        return {
            "file_name": file_name,
            "content_type": "application/pdf",
            "bytes": content,
            "source_uri": str(resp.url),
        }

    def _is_configured(self) -> bool:
        if settings.cnipr_access_token and settings.cnipr_openid:
            return True
        return bool(
            settings.cnipr_client_id
            and settings.cnipr_client_secret
            and settings.cnipr_user_account
            and settings.cnipr_user_password
        )

    def _ensure_token(self) -> bool:
        if settings.cnipr_access_token and settings.cnipr_openid:
            self._token = settings.cnipr_access_token
            self._openid = settings.cnipr_openid
            self._token_expires_at = time.time() + max(settings.cnipr_token_expires_in - 60, 60)
            return True

        if self._token and self._openid and time.time() < self._token_expires_at:
            return True

        url = f"{settings.cnipr_base_url.rstrip('/')}/oauth/json/user/login"
        payload = {
            "client_id": settings.cnipr_client_id,
            "client_secret": settings.cnipr_client_secret,
            "grant_type": "password",
            "username": settings.cnipr_user_account,
            "password": settings.cnipr_user_password,
            "scope": "",
            "return_refresh_token": 1,
        }
        data = self._post_json(url, payload)
        if not data:
            return False
        if str(data.get("status")) != "0":
            return False

        access_token = data.get("access_token")
        openid = data.get("open_id") or data.get("openid")
        expires_in = data.get("expires_in", 3600)
        if not access_token or not openid:
            return False

        self._token = str(access_token)
        self._openid = str(openid)
        try:
            ttl = int(expires_in)
        except (TypeError, ValueError):
            ttl = 3600
        self._token_expires_at = time.time() + max(ttl - 60, 60)
        return True

    @staticmethod
    def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            with httpx.Client(timeout=settings.cnipr_timeout_sec) as client:
                # CNIPR examples use standard form parameters.
                resp = client.post(url, data=payload)
                if resp.status_code != 200:
                    return None
                body = resp.json()
        except Exception:
            return None
        if not isinstance(body, dict):
            return None
        return body
