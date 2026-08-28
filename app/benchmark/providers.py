import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

@dataclass
class BenchmarkResult:
    provider: str
    model: str
    success: bool
    text: Optional[str] = None
    parsed_json: Optional[Dict[str, Any]] = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    headers: Optional[Dict[str, str]] = None

    def to_dict(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "success": self.success,
            "text": self.text,
            "parsed_json": self.parsed_json,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }

class LLMProvider:
    def __init__(self, name: str, models: List[str], default_timeout: float = 15.0):
        self.name = name
        self.models = models
        self.default_timeout = default_timeout

    def get_api_key(self) -> str:
        raise NotImplementedError

    def check_availability(self) -> Dict[str, str]:
        raise NotImplementedError

    def generate(self, model: str, system_prompt: str, user_prompt: str) -> BenchmarkResult:
        raise NotImplementedError

    def _extract_json(self, value: str) -> str:
        import re
        stripped = value.strip()
        fence_match = re.search(r"`(?:json)?\s*([\s\S]+?)\s*`", stripped)
        if fence_match:
            stripped = fence_match.group(1).strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end >= start:
            return stripped[start : end + 1]
        return stripped

    def _parse_and_validate(self, text: str) -> tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
        try:
            extracted = self._extract_json(text)
            parsed = json.loads(extracted)
            return parsed, None, None
        except Exception as e:
            return None, "INVALID_JSON", str(e)

    def _post(self, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: Optional[float] = None) -> tuple[int, str, Optional[Exception], Dict[str, str]]:
        if "User-Agent" not in headers:
            headers["User-Agent"] = "mios-benchmark/1.0"
        
        req_timeout = timeout if timeout is not None else self.default_timeout
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=req_timeout) as response:
                return response.status, response.read().decode("utf-8"), None, dict(response.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e, dict(e.headers)
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                return 0, "", TimeoutError(), {}
            return 0, "", e, {}
        except TimeoutError as e:
            return 0, "", e, {}
        except Exception as e:
            return 0, "", e, {}

    def _get(self, url: str, headers: Dict[str, str], timeout: float = 10.0) -> tuple[int, str, Optional[Exception]]:
        if "User-Agent" not in headers:
            headers["User-Agent"] = "mios-benchmark/1.0"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8"), None
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e
        except Exception as e:
            return 0, "", e

    def _classify_error(self, status: int, body: str, exception: Optional[Exception]) -> tuple[str, str]:
        if status == 401:
            return "AUTH_FAILED", body or str(exception)
        if status == 403:
            return "FORBIDDEN", body or str(exception)
        if status == 404:
            return "MODEL_NOT_FOUND", body or str(exception)
        if status == 413:
            return "REQUEST_TOO_LARGE", body or str(exception)
        if status == 429:
            return "RATE_LIMITED", body or str(exception)
        if status >= 500:
            return "SERVER_ERROR", body or str(exception)
        if isinstance(exception, TimeoutError) or status == 0 and "timeout" in str(exception).lower():
            return "TIMEOUT", str(exception)
        if exception:
            return "UNKNOWN", str(exception)
        return "PROVIDER_ERROR", body

class OpenCodeZenProvider(LLMProvider):
    def __init__(self, models: List[str]):
        super().__init__("opencode", models, default_timeout=60.0)
        self.base_url = "https://opencode.ai/zen/v1"

    def get_api_key(self) -> str:
        return os.environ.get("OPENCODE_API_KEY", "")

    def check_availability(self) -> Dict[str, str]:
        api_key = self.get_api_key()
        if not api_key:
            return {m: "AUTH_MISSING" for m in self.models}
        
        headers = {"Authorization": f"Bearer {api_key}"}
        status, body, exc = self._get(f"{self.base_url}/models", headers)
        
        excluded = {
            "deepseek-v4-flash-free": "EXCLUDED_OPERATIONAL_LIMIT (100% Rate Limit Failures in Pilot)",
            "mimo-v2.5-free": "EXCLUDED_OPERATIONAL_LIMIT (100% Rate Limit Failures in Pilot)"
        }
        
        if status == 401:
            res = {m: "AUTH_FAILED" for m in self.models}
            for e_model, reason in excluded.items():
                if e_model in res: res[e_model] = reason
            return res
        if status == 403:
            res = {m: "FORBIDDEN" for m in self.models}
            for e_model, reason in excluded.items():
                if e_model in res: res[e_model] = reason
            return res
        if status != 200:
            res = {m: "MODEL_AVAILABLE" for m in self.models}
            for e_model, reason in excluded.items():
                if e_model in res: res[e_model] = reason
            return res
            
        try:
            data = json.loads(body)
            available_ids = {item["id"] for item in data.get("data", [])}
            res = {
                m: "MODEL_AVAILABLE" if m in available_ids else "MODEL_UNAVAILABLE"
                for m in self.models
            }
            for e_model, reason in excluded.items():
                if e_model in res: res[e_model] = reason
            return res
        except Exception:
            res = {m: "MODEL_AVAILABLE" for m in self.models}
            for e_model, reason in excluded.items():
                if e_model in res: res[e_model] = reason
            return res

    def generate(self, model: str, system_prompt: str, user_prompt: str) -> BenchmarkResult:
        api_key = self.get_api_key()
        if not api_key:
            return BenchmarkResult(self.name, model, False, error_code="AUTH_MISSING", error_message="Missing OPENCODE_API_KEY")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        start_time = time.perf_counter()
        status, body, exc, resp_headers = self._post(f"{self.base_url}/chat/completions", headers, payload)
        latency = int((time.perf_counter() - start_time) * 1000)

        if status == 200:
            try:
                data = json.loads(body)
                text = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                parsed_json, err_code, err_msg = self._parse_and_validate(text)
                return BenchmarkResult(
                    provider=self.name, model=model, success=(err_code is None),
                    text=text, parsed_json=parsed_json,
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    latency_ms=latency, error_code=err_code, error_message=err_msg, headers=resp_headers
                )
            except Exception as e:
                return BenchmarkResult(self.name, model, False, latency_ms=latency, error_code="PROVIDER_ERROR", error_message=f"Parse error: {e}, body: {body}", headers=resp_headers)

        err_code, err_msg = self._classify_error(status, body, exc)
        return BenchmarkResult(self.name, model, False, latency_ms=latency, error_code=err_code, error_message=err_msg, headers=resp_headers)

class GroqProvider(LLMProvider):
    def __init__(self, models: List[str]):
        super().__init__("groq", models, default_timeout=30.0)
        self.base_url = "https://api.groq.com/openai/v1"

    def get_api_key(self) -> str:
        return os.environ.get("GROQ_API_KEY", "")

    def check_availability(self) -> Dict[str, str]:
        api_key = self.get_api_key()
        if not api_key:
            return {m: "AUTH_MISSING" for m in self.models}
        headers = {"Authorization": f"Bearer {api_key}"}
        status, body, exc = self._get(f"{self.base_url}/models", headers)
        if status == 401:
            return {m: "AUTH_FAILED" for m in self.models}
        if status == 403:
            return {m: "FORBIDDEN" for m in self.models}
        if status != 200:
            return {m: "MODEL_AVAILABLE" for m in self.models}
            
        try:
            data = json.loads(body)
            available_ids = {item["id"] for item in data.get("data", [])}
            return {
                m: "MODEL_AVAILABLE" if m in available_ids else "MODEL_UNAVAILABLE"
                for m in self.models
            }
        except Exception:
            return {m: "MODEL_AVAILABLE" for m in self.models}

    def generate(self, model: str, system_prompt: str, user_prompt: str) -> BenchmarkResult:
        api_key = self.get_api_key()
        if not api_key:
            return BenchmarkResult(self.name, model, False, error_code="AUTH_MISSING", error_message="Missing GROQ_API_KEY")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        start_time = time.perf_counter()
        status, body, exc, resp_headers = self._post(f"{self.base_url}/chat/completions", headers, payload)
        latency = int((time.perf_counter() - start_time) * 1000)

        if status == 200:
            try:
                data = json.loads(body)
                text = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                parsed_json, err_code, err_msg = self._parse_and_validate(text)
                return BenchmarkResult(
                    provider=self.name, model=model, success=(err_code is None),
                    text=text, parsed_json=parsed_json,
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    latency_ms=latency, error_code=err_code, error_message=err_msg, headers=resp_headers
                )
            except Exception as e:
                return BenchmarkResult(self.name, model, False, latency_ms=latency, error_code="PROVIDER_ERROR", error_message=f"Parse error: {e}, body: {body}", headers=resp_headers)

        err_code, err_msg = self._classify_error(status, body, exc)
        return BenchmarkResult(self.name, model, False, latency_ms=latency, error_code=err_code, error_message=err_msg, headers=resp_headers)

class OllamaCloudProvider(LLMProvider):
    def __init__(self, models: List[str]):
        super().__init__("ollama-cloud", models, default_timeout=45.0)
        self.base_url = "https://ollama.com/v1"

    def get_api_key(self) -> str:
        return os.environ.get("OLLAMA_API_KEY", "")

    def check_availability(self) -> Dict[str, str]:
        api_key = self.get_api_key()
        if not api_key:
            return {m: "AUTH_MISSING" for m in self.models}
        headers = {"Authorization": f"Bearer {api_key}"}
        status, body, exc = self._get(f"{self.base_url}/models", headers)
        if status == 401:
            return {m: "AUTH_FAILED" for m in self.models}
        if status == 403:
            return {m: "FORBIDDEN" for m in self.models}
        if status != 200:
            return {m: "MODEL_AVAILABLE" for m in self.models}
            
        try:
            data = json.loads(body)
            available_ids = {item["id"] for item in data.get("data", [])}
            return {
                m: "MODEL_AVAILABLE" if m in available_ids else "MODEL_UNAVAILABLE"
                for m in self.models
            }
        except Exception:
            return {m: "MODEL_AVAILABLE" for m in self.models}

    def generate(self, model: str, system_prompt: str, user_prompt: str) -> BenchmarkResult:
        api_key = self.get_api_key()
        if not api_key:
            return BenchmarkResult(self.name, model, False, error_code="AUTH_MISSING", error_message="Missing OLLAMA_API_KEY")

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        start_time = time.perf_counter()
        status, body, exc, resp_headers = self._post(f"{self.base_url}/chat/completions", headers, payload)
        latency = int((time.perf_counter() - start_time) * 1000)

        if status == 200:
            try:
                data = json.loads(body)
                text = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                parsed_json, err_code, err_msg = self._parse_and_validate(text)
                return BenchmarkResult(
                    provider=self.name, model=model, success=(err_code is None),
                    text=text, parsed_json=parsed_json,
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    latency_ms=latency, error_code=err_code, error_message=err_msg, headers=resp_headers
                )
            except Exception as e:
                return BenchmarkResult(self.name, model, False, latency_ms=latency, error_code="PROVIDER_ERROR", error_message=f"Parse error: {e}, body: {body}", headers=resp_headers)

        err_code, err_msg = self._classify_error(status, body, exc)
        return BenchmarkResult(self.name, model, False, latency_ms=latency, error_code=err_code, error_message=err_msg, headers=resp_headers)

class GeminiProvider(LLMProvider):
    def __init__(self, models: List[str]):
        super().__init__("gemini", models, default_timeout=45.0)

    def get_api_key(self) -> str:
        return os.environ.get("GEMINI_API_KEY", "")

    def check_availability(self) -> Dict[str, str]:
        if not self.get_api_key():
            return {m: "AUTH_MISSING" for m in self.models}
        return {m: "MODEL_AVAILABLE" for m in self.models}

    def generate(self, model: str, system_prompt: str, user_prompt: str) -> BenchmarkResult:
        api_key = self.get_api_key()
        if not api_key:
            return BenchmarkResult(self.name, model, False, error_code="AUTH_MISSING", error_message="Missing GEMINI_API_KEY")

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "responseMimeType": "application/json"
            }
        }
        
        headers = {"Content-Type": "application/json"}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        start_time = time.perf_counter()
        status, body, exc, resp_headers = self._post(url, headers, payload)
        latency = int((time.perf_counter() - start_time) * 1000)

        if status == 200:
            try:
                data = json.loads(body)
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                usage = data.get("usageMetadata", {})
                parsed_json, err_code, err_msg = self._parse_and_validate(text)
                return BenchmarkResult(
                    provider=self.name, model=model, success=(err_code is None),
                    text=text, parsed_json=parsed_json,
                    input_tokens=usage.get("promptTokenCount", 0),
                    output_tokens=usage.get("candidatesTokenCount", 0),
                    latency_ms=latency, error_code=err_code, error_message=err_msg, headers=resp_headers
                )
            except Exception as e:
                return BenchmarkResult(self.name, model, False, latency_ms=latency, error_code="PROVIDER_ERROR", error_message=f"Parse error: {e}, body: {body}", headers=resp_headers)

        err_code, err_msg = self._classify_error(status, body, exc)
        return BenchmarkResult(self.name, model, False, latency_ms=latency, error_code=err_code, error_message=err_msg, headers=resp_headers)

def get_providers() -> List[LLMProvider]:
    return [
        OpenCodeZenProvider([
            "nemotron-3.5-lightning-free",
            "nemotron-3-ultra-free",
            "hy3-free",
            "laguna-s-2.1-free",
            "deepseek-v4-flash-free",
            "mimo-v2.5-free"
        ]),
        GroqProvider([
            "openai/gpt-oss-120b"
        ]),
        OllamaCloudProvider([
            "gpt-oss:120b"
        ]),
        GeminiProvider([
            "gemini-3.7-flash"
        ])
    ]

def get_provider_by_model(model: str) -> Optional[LLMProvider]:
    for p in get_providers():
        if model in p.models:
            return p
    return None


