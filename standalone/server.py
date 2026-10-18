"""A small loopback HTTP server for the standalone page.

Threaded on purpose: the connector's event loop must never block on a socket, and every handler reaches
the plugin through `runner.LoopBridge`. stdlib only - the standalone install ships no web framework.
"""
from __future__ import annotations

import dataclasses
import gzip
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from collections.abc import Callable
from urllib.parse import parse_qsl

log = logging.getLogger("nms-standalone.server")

MAX_BODY = 256 * 1024            # the biggest body the page sends is a chat message plus its history
GZIP_MIN = 1024                  # the connector's view is ~400 KB of JSON
DRAIN_LIMIT = 4 * 1024 * 1024    # a refused body is read and discarded up to here (see _drain)


@dataclasses.dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    body: dict
    path_args: tuple[str, ...]
    headers: dict[str, str]


@dataclasses.dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/json"
    headers: dict[str, str] = dataclasses.field(default_factory=dict)
    stream: Callable[[Callable[[bytes], None]], None] | None = None


@dataclasses.dataclass
class Route:
    method: str
    pattern: str
    handler: Callable[[Request], Response]

    def __post_init__(self):
        self.regex = re.compile(self.pattern)


class HttpError(Exception):
    """A handler's refusal, answered as JSON."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def json_response(payload, status: int = 200) -> Response:
    return Response(status=status, body=json.dumps(payload).encode("utf-8"))


def error_response(status: int, detail: str) -> Response:
    return json_response({"detail": detail}, status=status)


def build(routes: list[Route], port: int) -> ThreadingHTTPServer:
    """A server bound to loopback only; `port=0` picks a free one (used by the tests)."""
    class Handler(_Handler):
        pass

    Handler.routes = routes
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


class _Handler(BaseHTTPRequestHandler):
    routes: ClassVar[list[Route]] = []
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):         # the default writes to stderr
        log.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def _dispatch(self, method: str) -> None:
        try:
            response = self._run(method)
        except HttpError as err:
            response = error_response(err.status, err.detail)
        except Exception:                      # noqa: BLE001 - answered and logged, never swallowed
            log.exception("handler failed for %s %s", method, self.path)
            response = error_response(500, "the standalone host failed; see standalone.log")
        self._send(response)

    def _run(self, method: str) -> Response:
        path, _, raw_query = self.path.partition("?")
        for route in self.routes:
            if route.method != method:
                continue
            match = route.regex.match(path)
            if match:
                request = Request(method, path, dict(parse_qsl(raw_query)), self._body(),
                                  match.groups(), dict(self.headers))
                return route.handler(request)
        return error_response(404, f"no route for {method} {path}")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._drain(length)
            raise HttpError(413, "body too large")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw)
        except ValueError:
            raise HttpError(422, "body must be JSON") from None
        if not isinstance(parsed, dict):
            raise HttpError(422, "body must be a JSON object")
        return parsed

    def _drain(self, length: int) -> None:
        """Read and discard a body we are about to refuse.

        Answering before the client finished sending makes Windows reset the connection, so the client
        sees ConnectionReset instead of the 413 (measured by `test_oversized_body_is_refused`). Anything
        bigger than `DRAIN_LIMIT` is not worth reading: the connection is closed after the answer.
        """
        if length > DRAIN_LIMIT:
            self.close_connection = True
            return
        left = length
        while left > 0:
            chunk = self.rfile.read(min(65536, left))
            if not chunk:
                break
            left -= len(chunk)

    def _send(self, response: Response) -> None:
        if response.stream is not None:
            self._send_stream(response)
            return
        body, headers = self._compressed(response)
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _compressed(self, response: Response) -> tuple[bytes, dict[str, str]]:
        body = response.body
        headers = dict(response.headers)
        if len(body) >= GZIP_MIN and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = gzip.compress(body, 6)
            headers["Content-Encoding"] = "gzip"
            headers["Vary"] = "Accept-Encoding"
        return body, headers

    def _send_stream(self, response: Response) -> None:
        """Server-sent events: `data: <json>` lines, the convention the app's chat uses.

        The connection is closed afterwards: with HTTP/1.1 and neither a `Content-Length` nor chunked
        framing, a kept-alive stream leaves the browser waiting for a body that never ends.
        """
        self.close_connection = True
        self.send_response(response.status)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        def write(chunk: bytes) -> None:
            self.wfile.write(chunk)
            self.wfile.flush()

        try:
            response.stream(write)
        except (BrokenPipeError, ConnectionResetError):
            log.debug("the page closed the stream")
