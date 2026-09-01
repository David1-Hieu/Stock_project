"""Client giao tiếp với Ollama local cho AI Agent phân tích chứng khoán VN."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests
from requests import Response
from requests.exceptions import ConnectionError, HTTPError, ReadTimeout, RequestException, Timeout


logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


class OllamaConnectionError(RuntimeError):
    """Lỗi khi không thể kết nối tới Ollama local."""


class OllamaClient:
    """Client đơn giản để gọi Ollama local qua HTTP API.

    Mặc định Ollama chạy ở http://localhost:11434. Khi khởi tạo, client sẽ gọi
    /api/tags để kiểm tra Ollama có đang chạy hay không.
    """

    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434") -> None:
        """Khởi tạo client Ollama và kiểm tra kết nối.

        Args:
            model: Tên model Ollama mặc định, ví dụ llama3.2, gemma3:12b, mistral.
            base_url: URL Ollama server local.

        Raises:
            OllamaConnectionError: Nếu Ollama chưa chạy hoặc không truy cập được.
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._check_connection()

    def _url(self, path: str) -> str:
        """Ghép base_url với path API."""
        return f"{self.base_url}/{path.lstrip('/')}"

    def _check_connection(self) -> None:
        """Kiểm tra Ollama server có đang online không."""
        try:
            response = self.session.get(self._url("/api/tags"), timeout=10)
            response.raise_for_status()
        except (ConnectionError, Timeout, HTTPError, RequestException) as exc:
            raise OllamaConnectionError(
                "Ollama chưa được khởi động. Hãy chạy lệnh: ollama serve"
            ) from exc

    def list_models(self) -> List[str]:
        """Trả về danh sách tên model Ollama hiện có trên máy local.

        Returns:
            Danh sách tên model, ví dụ ["llama3.2:latest", "mistral:latest"].
        """
        try:
            response = self.session.get(self._url("/api/tags"), timeout=10)
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            result: List[str] = []
            for item in models:
                name = item.get("name") if isinstance(item, dict) else None
                if name:
                    result.append(str(name))
            return result
        except Exception as exc:  # noqa: BLE001 - cần log rõ cho app local
            logger.exception("Không thể lấy danh sách model Ollama: %s", exc)
            return []

    def _post_chat(self, payload: Dict[str, Any], timeout: int = 240) -> Response:
        """Gửi request chat tới Ollama."""
        response = self.session.post(self._url("/api/chat"), json=payload, timeout=timeout)
        response.raise_for_status()
        return response

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 900,
        timeout: Optional[int] = None,
        max_attempts: Optional[int] = None,
    ) -> str:
        """Gửi hội thoại tới Ollama và nhận nội dung phản hồi.

        Args:
            messages: List message dạng {"role": "system/user/assistant", "content": "..."}.
            temperature: Độ sáng tạo của model. Phân tích tài chính nên để thấp.
            max_tokens: Số token sinh tối đa. Với máy local nên để 600-1000.
            timeout: Số giây chờ Ollama trả lời cho mỗi request.
            max_attempts: Số lần thử. Nên để 1 để tránh chờ quá lâu khi model chậm.

        Returns:
            Nội dung text từ assistant.

        Raises:
            OllamaConnectionError: Nếu Ollama không chạy hoặc request thất bại.
            ValueError: Nếu messages không hợp lệ hoặc response thiếu content.
        """
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages phải là list không rỗng")

        normalized_messages: List[Dict[str, str]] = []
        allowed_roles = {"system", "user", "assistant"}
        for message in messages:
            role = str(message.get("role", "")).strip()
            content = str(message.get("content", "")).strip()
            if role not in allowed_roles:
                raise ValueError(f"Role không hợp lệ: {role}")
            if not content:
                raise ValueError("Nội dung message không được rỗng")
            normalized_messages.append({"role": role, "content": content})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": normalized_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": 4096,
            },
        }

        last_error: Optional[Exception] = None
        if timeout is None:
            timeout = int(os.getenv("OLLAMA_TIMEOUT", "240"))
        if max_attempts is None:
            max_attempts = int(os.getenv("OLLAMA_MAX_ATTEMPTS", "1"))
        max_attempts = max(1, int(max_attempts))

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info("Gửi request Ollama chat, attempt=%s, model=%s", attempt, self.model)
                response = self._post_chat(payload, timeout=timeout)
                data = response.json()
                message = data.get("message", {})
                content = message.get("content") if isinstance(message, dict) else None
                if not content:
                    raise ValueError(f"Ollama response thiếu message.content: {data}")
                return str(content).strip()
            except ReadTimeout as exc:
                last_error = exc
                logger.warning("Ollama timeout ở lần %s/%s", attempt, max_attempts)
                if attempt < max_attempts:
                    time.sleep(2 * attempt)
                    continue
            except (ConnectionError, Timeout) as exc:
                last_error = exc
                logger.exception("Không thể kết nối Ollama")
                break
            except (HTTPError, RequestException, ValueError) as exc:
                last_error = exc
                logger.exception("Lỗi khi gọi Ollama chat")
                break

        raise OllamaConnectionError(
            "Không thể nhận phản hồi từ Ollama. Kiểm tra Ollama server và model đang dùng."
        ) from last_error

    def analyze(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        max_tokens: int = 900,
        timeout: Optional[int] = None,
    ) -> str:
        """Wrapper tiện lợi cho một lượt phân tích.

        Args:
            system_prompt: Prompt hệ thống định nghĩa vai trò/chính sách trả lời.
            user_content: Nội dung dữ liệu/câu hỏi đưa cho model.
            temperature: Độ sáng tạo, mặc định thấp để phân tích ổn định.
            max_tokens: Số token sinh tối đa.
            timeout: Số giây chờ Ollama trả lời.

        Returns:
            Chuỗi phân tích của model.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        return self.chat(messages=messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)


_client_instance: Optional[OllamaClient] = None


def get_client(model: str = "llama3.2", base_url: str = "http://localhost:11434") -> OllamaClient:
    """Trả về singleton OllamaClient.

    Args:
        model: Tên model mặc định nếu chưa có instance.
        base_url: URL Ollama server local nếu chưa có instance.

    Returns:
        OllamaClient duy nhất trong tiến trình hiện tại.
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = OllamaClient(model=model, base_url=base_url)
    return _client_instance


if __name__ == "__main__":
    try:
        client = get_client()
        print("Ollama online")
        print("Models:", client.list_models())
    except OllamaConnectionError as exc:
        print(str(exc))
