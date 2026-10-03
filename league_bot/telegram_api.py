"""Minimal Telegram Bot API client built on urllib (no dependencies)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

API_ROOT = "https://api.telegram.org"


class TelegramError(RuntimeError):
    def __init__(self, message: str, code: Optional[int] = None, retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class TelegramAPI:
    def __init__(self, token: str, opener: Callable = urllib.request.urlopen, timeout: float = 30.0) -> None:
        self._token = token
        self._opener = opener
        self._timeout = timeout

    def _redact(self, text: str) -> str:
        """Request URLs contain the token; keep it out of anything that might get logged or pasted."""
        return text.replace(self._token, "<token>") if self._token else text

    def _request(self, method: str, data: bytes, content_type: str, timeout: float) -> Any:
        url = f"{API_ROOT}/bot{self._token}/{method}"
        request = urllib.request.Request(url, data=data, headers={"Content-Type": content_type}, method="POST")
        status: Optional[int] = None
        try:
            with self._opener(request, timeout=timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = exc.read()  # Telegram explains the failure in a JSON body
        except (urllib.error.URLError, OSError) as exc:
            raise TelegramError(self._redact(f"network error calling {method}: {exc}")) from None
        try:
            body = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise TelegramError(f"{method}: unreadable response (HTTP {status})", code=status) from None
        if not body.get("ok"):
            params = body.get("parameters") or {}
            raise TelegramError(
                self._redact(f"{method}: {body.get('description', 'unknown error')}"),
                code=body.get("error_code", status),
                retry_after=params.get("retry_after"),
            )
        return body.get("result")

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Any:
        data = json.dumps(params or {}).encode("utf-8")
        return self._request(method, data, "application/json", timeout or self._timeout)

    # -- bot methods -----------------------------------------------------------

    def get_me(self) -> Dict[str, Any]:
        return self.call("getMe")

    def get_updates(self, offset: Optional[int] = None, poll_timeout: int = 25) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"timeout": poll_timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return self.call("getUpdates", params, timeout=poll_timeout + 10)

    def send_message(self, chat_id: int, text: str) -> None:
        # Plain text on purpose: error messages are full of underscores and backticks.
        self.call("sendMessage", {"chat_id": chat_id, "text": text[:4000]})

    def set_commands(self, commands: Sequence[Tuple[str, str]]) -> None:
        self.call("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in commands]})

    def send_photo(self, chat_id: int, png: bytes, caption: str = "") -> None:
        self._send_file("sendPhoto", "photo", chat_id, png, "shot.png", "image/png", caption)

    def send_document(self, chat_id: int, content: bytes, filename: str, caption: str = "") -> None:
        self._send_file("sendDocument", "document", chat_id, content, filename, "application/octet-stream", caption)

    def _send_file(self, method: str, field: str, chat_id: int, content: bytes,
                   filename: str, content_type: str, caption: str) -> None:
        boundary = uuid.uuid4().hex
        parts: List[bytes] = []

        def text_part(name: str, value: str) -> None:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))

        text_part("chat_id", str(chat_id))
        if caption:
            text_part("caption", caption[:1000])
        header = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        )
        parts.append(header.encode("utf-8") + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("ascii"))
        self._request(method, b"".join(parts), f"multipart/form-data; boundary={boundary}", 60)
