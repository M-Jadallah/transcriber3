from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import requests

from app.formatting.config import FormattingConfig


class OpenCodeUnavailable(RuntimeError):
    pass


_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")


def validate_provider_id(provider_id: str) -> str:
    value = provider_id.strip()
    if not _PROVIDER_ID.fullmatch(value):
        raise ValueError("معرّف مزود OpenCode غير صالح")
    return value


def _safe_http_error(service: str, status_code: int) -> OpenCodeUnavailable:
    # Upstream bodies can contain echoed OAuth codes, tokens, or internal details.
    return OpenCodeUnavailable(f"رفضت خدمة {service} الطلب (HTTP {status_code})")


class OpenCodeClient:
    def __init__(self, config: FormattingConfig) -> None:
        self.base_url = config.opencode_url
        self.control_url = config.opencode_control_url
        self.auth = (
            (config.opencode_username, config.opencode_password)
            if config.opencode_password
            else None
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                auth=self.auth,
                timeout=kwargs.pop("timeout", 5),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise OpenCodeUnavailable("تعذر الاتصال بخدمة OpenCode الداخلية") from exc
        if not response.ok:
            raise _safe_http_error("OpenCode", response.status_code)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise OpenCodeUnavailable("أعاد OpenCode استجابة غير صالحة") from exc

    def health(self) -> dict[str, Any] | None:
        try:
            data = self._request("GET", "/global/health", timeout=5)
        except OpenCodeUnavailable:
            return None
        return data if isinstance(data, dict) else {"healthy": True}

    def providers(self) -> dict[str, Any]:
        data = self._request("GET", "/provider", timeout=5)
        return data if isinstance(data, dict) else {"all": [], "connected": []}

    def auth_methods(self) -> dict[str, list[dict[str, Any]]]:
        data = self._request("GET", "/provider/auth", timeout=5)
        if not isinstance(data, dict):
            return {}
        return {
            str(provider_id): methods
            for provider_id, methods in data.items()
            if isinstance(methods, list)
        }

    def start_oauth(
        self,
        provider_id: str,
        method_index: int,
        inputs: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        provider_id = validate_provider_id(provider_id)
        payload: dict[str, Any] = {"method": method_index}
        if inputs:
            payload["inputs"] = inputs
        data = self._request(
            "POST",
            f"/provider/{quote(provider_id, safe='')}/oauth/authorize",
            json=payload,
            timeout=30,
        )
        if not isinstance(data, dict) or not isinstance(data.get("url"), str):
            raise OpenCodeUnavailable("لم يُرجع OpenCode رابط مصادقة صالحًا")
        parsed = urlsplit(data["url"].strip())
        scheme = parsed.scheme.lower()
        try:
            parsed.port
        except ValueError as exc:
            raise OpenCodeUnavailable("لم يُرجع OpenCode رابط مصادقة HTTP صالحًا") from exc
        if (
            scheme not in {"http", "https"}
            or not parsed.netloc
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(ord(character) <= 32 for character in data["url"])
        ):
            raise OpenCodeUnavailable("لم يُرجع OpenCode رابط مصادقة HTTP صالحًا")
        result: dict[str, Any] = {
            "url": urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)),
            "method": data.get("method") if data.get("method") in {"auto", "code"} else "auto",
        }
        if isinstance(data.get("instructions"), str):
            result["instructions"] = data["instructions"]
        return result

    def finish_oauth(
        self,
        provider_id: str,
        method_index: int,
        code: str | None = None,
    ) -> bool:
        provider_id = validate_provider_id(provider_id)
        payload: dict[str, Any] = {"method": method_index}
        if code:
            payload["code"] = code
        data = self._request(
            "POST",
            f"/provider/{quote(provider_id, safe='')}/oauth/callback",
            json=payload,
            timeout=90,
        )
        if isinstance(data, bool):
            return data
        if isinstance(data, dict) and isinstance(data.get("success"), bool):
            return data["success"]
        raise OpenCodeUnavailable("أعاد OpenCode نتيجة مصادقة غير صالحة")

    def logout(self) -> dict[str, Any]:
        try:
            response = requests.post(
                f"{self.control_url}/logout",
                auth=self.auth,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise OpenCodeUnavailable("تعذر الاتصال بخدمة التحكم في OpenCode") from exc
        if not response.ok:
            raise _safe_http_error("التحكم في OpenCode", response.status_code)
        try:
            data = response.json()
        except ValueError as exc:
            raise OpenCodeUnavailable("أعادت خدمة التحكم استجابة غير صالحة") from exc
        if not isinstance(data, dict) or not isinstance(data.get("success"), bool):
            raise OpenCodeUnavailable("أعادت خدمة التحكم نتيجة فصل غير صالحة")
        return {
            "success": data["success"],
            "removed": data.get("removed") is True,
            "restarting": data.get("restarting") is True,
        }
