from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.application.http import HttpClient, HttpResponse

# Cloudflare-fronted providers (e.g. Groq) block urllib's default
# "Python-urllib/<version>" User-Agent as a bot signature (surfaces as a bare
# "error code: 1010" with no JSON body, before the request ever reaches the provider's
# own API). Sending a normal, identifiable User-Agent avoids that block. Callers can still
# override it by passing their own "User-Agent" in `headers`.
_DEFAULT_HEADERS = {"User-Agent": "gold-intelligence-platform/0.1.0"}


class UrlLibHttpClient(HttpClient):
    def __init__(self, retry_attempts: int = 2, retry_delay_seconds: float = 0.25) -> None:
        self._retry_attempts = retry_attempts
        self._retry_delay_seconds = retry_delay_seconds

    def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> HttpResponse:
        full_url = self._with_query(url, params)
        last_error: Exception | None = None
        for attempt in range(self._retry_attempts + 1):
            try:
                request = Request(
                    full_url,
                    headers={**_DEFAULT_HEADERS, **(headers or {})},
                    method="GET",
                )
                with urlopen(request, timeout=timeout_seconds) as response:
                    body = _decode_response_body(response.read(), response.headers)
                    response_headers = {key: value for key, value in response.headers.items()}
                    return HttpResponse(
                        status_code=response.status,
                        body=body,
                        headers=response_headers,
                    )
            except HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                if 400 <= error.code < 500:
                    return HttpResponse(status_code=error.code, body=body)
                last_error = error
            except (TimeoutError, URLError) as error:
                last_error = error

            if attempt < self._retry_attempts:
                sleep(self._retry_delay_seconds)

        detail = str(last_error) if last_error else "unknown HTTP error"
        return HttpResponse(status_code=599, body=detail)

    def post(
        self,
        url: str,
        body: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> HttpResponse:
        full_url = self._with_query(url, params)
        last_error: Exception | None = None
        for attempt in range(self._retry_attempts + 1):
            try:
                request = Request(
                    full_url,
                    data=body.encode("utf-8"),
                    headers={**_DEFAULT_HEADERS, **(headers or {})},
                    method="POST",
                )
                with urlopen(request, timeout=timeout_seconds) as response:
                    response_body = _decode_response_body(response.read(), response.headers)
                    response_headers = {key: value for key, value in response.headers.items()}
                    return HttpResponse(
                        status_code=response.status,
                        body=response_body,
                        headers=response_headers,
                    )
            except HTTPError as error:
                response_body = error.read().decode("utf-8", errors="replace")
                if 400 <= error.code < 500:
                    return HttpResponse(status_code=error.code, body=response_body)
                last_error = error
            except (TimeoutError, URLError) as error:
                last_error = error

            if attempt < self._retry_attempts:
                sleep(self._retry_delay_seconds)

        detail = str(last_error) if last_error else "unknown HTTP error"
        return HttpResponse(status_code=599, body=detail)

    def _with_query(self, url: str, params: dict[str, str] | None) -> str:
        if not params:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{urlencode(params)}"


def _decode_response_body(body: bytes, headers) -> str:
    charset = headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")
