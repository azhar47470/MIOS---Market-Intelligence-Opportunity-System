import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.infrastructure.http.urllib_http_client import UrlLibHttpClient


class _EchoHandler(BaseHTTPRequestHandler):
    """Replies with the headers it received, so tests can inspect what was actually sent."""

    def _reply(self) -> None:
        body = json.dumps({"headers": dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._reply()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self._reply()

    def log_message(self, *args: object) -> None:
        pass


def _start_echo_server() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _EchoHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_post_sends_an_identifiable_user_agent_instead_of_the_blockable_urllib_default():
    # Cloudflare-fronted providers (Groq and similar) block urllib's default
    # "Python-urllib/<version>" User-Agent with a bare "error code: 1010" before the request
    # ever reaches the provider's own API. This guards against that regressing silently.
    server = _start_echo_server()
    try:
        port = server.server_address[1]
        client = UrlLibHttpClient()

        response = client.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            body="{}",
            headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"},
        )

        headers = json.loads(response.body)["headers"]
        assert "python-urllib" not in headers["User-Agent"].lower()
        assert headers["User-Agent"] == "gold-intelligence-platform/0.1.0"
        # The caller's own headers must still pass through untouched.
        assert headers["Authorization"] == "Bearer test-key"
        assert headers["Content-Type"] == "application/json"
    finally:
        server.shutdown()


def test_caller_supplied_user_agent_overrides_the_default():
    server = _start_echo_server()
    try:
        port = server.server_address[1]
        client = UrlLibHttpClient()

        response = client.get(
            f"http://127.0.0.1:{port}/",
            headers={"User-Agent": "custom-client/2.0"},
        )

        headers = json.loads(response.body)["headers"]
        assert headers["User-Agent"] == "custom-client/2.0"
    finally:
        server.shutdown()
