"""Single-instance handling and the port race."""
import json

import pytest

from standalone import instance


def test_the_lock_records_the_port_and_the_pid(tmp_path):
    """A second start must be able to find the first one's page instead of starting a rival host over the
    same data dir - two hosts writing `planet_history.json` would corrupt it."""
    with instance.hold(tmp_path, port=8787):
        recorded = json.loads((tmp_path / instance.LOCK_NAME).read_text(encoding="utf-8"))
    assert recorded["port"] == 8787 and recorded["pid"] > 0


def test_the_lock_is_removed_afterwards(tmp_path):
    """A lock left behind would send the next start to a port nothing is serving."""
    with instance.hold(tmp_path, port=8787):
        pass
    assert not (tmp_path / instance.LOCK_NAME).exists()


def test_the_lock_is_released_on_the_failure_path(tmp_path):
    """Resources are released in `finally` here as everywhere else in this project."""
    with pytest.raises(RuntimeError):
        with instance.hold(tmp_path, port=8787):
            raise RuntimeError("start failed")
    assert not (tmp_path / instance.LOCK_NAME).exists()


def test_a_second_start_finds_the_running_one(tmp_path, monkeypatch):
    """The user clicks the shortcut again; the right answer is to open the page that is already serving,
    not to fail with a port error."""
    with instance.hold(tmp_path, port=8787):
        monkeypatch.setattr(instance, "responds", lambda port: True)
        assert instance.running_port(tmp_path) == 8787


def test_a_stale_lock_is_ignored(tmp_path, monkeypatch):
    """After a crash the lock file is still there. A host that refused to start because of it would need
    the user to delete a file they have never heard of."""
    (tmp_path / instance.LOCK_NAME).write_text(json.dumps({"port": 8787, "pid": 999999}),
                                               encoding="utf-8")
    monkeypatch.setattr(instance, "responds", lambda port: False)
    assert instance.running_port(tmp_path) is None


def test_a_damaged_lock_is_ignored(tmp_path):
    """A half-written lock must not stop the program either."""
    (tmp_path / instance.LOCK_NAME).write_text("{broken", encoding="utf-8")
    assert instance.running_port(tmp_path) is None


def test_no_lock_means_nothing_is_running(tmp_path):
    """The ordinary first start."""
    assert instance.running_port(tmp_path) is None


def test_binding_retries_when_the_port_is_taken_between_probe_and_bind(monkeypatch):
    """`choose_port` probes and then binds, which is a race (and something else may grab the port in
    between). The bind itself must fall forward rather than kill the start."""
    from standalone import __main__ as entry
    attempts = []

    def fake_build(routes, port):
        attempts.append(port)
        if len(attempts) < 3:
            raise OSError("address in use")
        return "server"

    monkeypatch.setattr(entry.server, "build", fake_build)
    monkeypatch.setattr(entry, "port_is_free", lambda port: True)
    served, port = entry.bind_server([], 8787)
    assert served == "server" and port == 8789 and len(attempts) == 3


def test_binding_gives_up_with_a_clear_failure(monkeypatch):
    """Twenty taken ports is a real problem (something is wrong on the machine); the message must say so
    rather than crashing in the socket layer."""
    from standalone import __main__ as entry

    def always_taken(routes, port):
        raise OSError("address in use")

    monkeypatch.setattr(entry.server, "build", always_taken)
    monkeypatch.setattr(entry, "port_is_free", lambda port: True)
    with pytest.raises(RuntimeError, match="no free port"):
        entry.bind_server([], 8787)
