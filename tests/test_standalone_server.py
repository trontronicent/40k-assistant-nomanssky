"""The standalone HTTP server: routing, bounds and failure answers."""
import json
import threading
import urllib.request

import pytest

from standalone import server


def _serve(routes):
    """Start the server on a free port in a thread and return its base URL and a stopper."""
    httpd = server.build(routes, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def stop():
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    return f"http://127.0.0.1:{httpd.server_address[1]}", stop


def test_get_route_answers_json():
    """A registered GET returns the handler's object as JSON with a content type the page can read."""
    base, stop = _serve([server.Route("GET", r"/api/view$", lambda req: server.json_response({"ok": 1}))])
    try:
        with urllib.request.urlopen(base + "/api/view", timeout=5) as res:
            assert res.headers["Content-Type"] == "application/json"
            assert json.loads(res.read()) == {"ok": 1}
    finally:
        stop()


def test_path_parameters_reach_the_handler():
    """Action and asset routes carry a name in the path; the capture group must arrive in `path_args`."""
    route = server.Route("POST", r"/api/actions/([a-z_]+)$",
                         lambda req: server.json_response({"id": req.path_args[0]}))
    base, stop = _serve([route])
    try:
        req = urllib.request.Request(base + "/api/actions/rescan", data=b"{}", method="POST")
        with urllib.request.urlopen(req, timeout=5) as res:
            assert json.loads(res.read()) == {"id": "rescan"}
    finally:
        stop()


def test_unknown_path_is_404_json():
    """An unknown path must answer JSON, not an HTML error page: the page shows `detail` in its error
    banner and would otherwise print markup."""
    base, stop = _serve([])
    try:
        with pytest.raises(urllib.request.HTTPError) as err:
            urllib.request.urlopen(base + "/nope", timeout=5)
        assert err.value.code == 404
        assert "detail" in json.loads(err.value.read())
    finally:
        stop()


def test_oversized_body_is_refused():
    """Bodies are bounded before parsing (`MAX_BODY`), because a handler decodes them in a server thread
    and an unbounded read is a memory hole on a port that is open to this machine."""
    base, stop = _serve([server.Route("POST", r"/api/x$", lambda req: server.json_response({}))])
    try:
        req = urllib.request.Request(base + "/api/x", data=b"x" * (server.MAX_BODY + 1), method="POST")
        with pytest.raises(urllib.request.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        assert err.value.code == 413
    finally:
        stop()


def test_invalid_json_body_is_422():
    """Form values and action params are untrusted input; a body that is not a JSON object is refused
    before any plugin code runs."""
    base, stop = _serve([server.Route("POST", r"/api/x$", lambda req: server.json_response(req.body))])
    try:
        req = urllib.request.Request(base + "/api/x", data=b"[1,2]", method="POST")
        with pytest.raises(urllib.request.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        assert err.value.code == 422
    finally:
        stop()


def test_handler_exception_becomes_500_json_and_is_logged(caplog):
    """A crashing handler must answer the page (which shows the failure) and leave a log line - never a
    silent dead request, the recurring bug class in this project."""
    def boom(req):
        raise RuntimeError("kaputt")

    base, stop = _serve([server.Route("GET", r"/api/boom$", boom)])
    try:
        with pytest.raises(urllib.request.HTTPError) as err:
            urllib.request.urlopen(base + "/api/boom", timeout=5)
        assert err.value.code == 500
        assert "kaputt" in caplog.text
    finally:
        stop()


def test_large_answers_are_gzipped_for_a_client_that_accepts_it():
    """The connector's view is ~400 KB of JSON and the page polls it every 5 s; the app gzips it for the
    same reason (and deliberately has no global gzip middleware, which would buffer streams)."""
    payload = {"rows": ["x" * 100 for _ in range(100)]}
    base, stop = _serve([server.Route("GET", r"/api/big$", lambda req: server.json_response(payload))])
    try:
        req = urllib.request.Request(base + "/api/big", headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=5) as res:
            assert res.headers["Content-Encoding"] == "gzip"
            assert res.headers["Vary"] == "Accept-Encoding"
            import gzip
            assert json.loads(gzip.decompress(res.read())) == payload
    finally:
        stop()


def test_a_stream_closes_its_connection():
    """Server-sent events carry neither a length nor chunked framing, so a kept-alive connection leaves
    the browser waiting for a body that never ends."""
    def stream_route(req):
        def stream(write):
            write(b"data: {\"token\": \"hi\"}\n\n")
        return server.Response(stream=stream)

    base, stop = _serve([server.Route("POST", r"/api/chat$", stream_route)])
    try:
        req = urllib.request.Request(base + "/api/chat", data=b"{}", method="POST")
        with urllib.request.urlopen(req, timeout=5) as res:
            assert res.headers["Content-Type"] == "text/event-stream"
            assert res.headers["Connection"] == "close"
            assert b"token" in res.read()
    finally:
        stop()


def test_bind_is_loopback_only():
    """The server binds 127.0.0.1. It runs actions that read the game's memory and can install updates;
    it must never be reachable from the LAN."""
    httpd = server.build([], port=0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.server_close()
