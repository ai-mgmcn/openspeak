import argparse
import os
import sys

import pytest

from openspeak import __main__ as cli
from openspeak import report
from openspeak.web import server


def args(**kw):
    return argparse.Namespace(**({"list": False, "all": False, "session": None, "no_fill": False} | kw))


TALK = [("partner", 0, "Welcome"), ("heard", 1, "I want check in")]


class TestReport:
    def test_list(self, write_log, capsys):
        write_log(TALK)
        assert cli.run_report(args(list=True)) == 0
        out = capsys.readouterr().out
        assert "20260101_120000" in out and "1 turns" in out

    def test_list_marks_only_incomplete_sessions(self, write_log, capsys):
        write_log(TALK, sid="20260101_120000")
        write_log([("heard", 1, "hi", False), "vocab", "session_end"], sid="20260102_120000")
        cli.run_report(args(list=True))
        lines = capsys.readouterr().out.splitlines()
        assert "incomplete" in lines[0] and "incomplete" not in lines[1]

    def test_a_session_that_doesnt_exist_is_an_error(self, write_log, capsys):
        write_log(TALK)
        for what in ("20990101_000000", "/tmp/definitely-not-a-session.jsonl"):
            assert cli.run_report(args(session=what)) == 1
        assert "No such session" in capsys.readouterr().err

    def test_a_session_by_the_id_list_prints(self, write_log):
        path = write_log(TALK, sid="20260101_120000")
        assert cli.run_report(args(session="20260101_120000", no_fill=True)) == 0
        assert os.path.exists(path[:-6] + ".html")

    def test_nothing_on_disk(self, capsys):
        assert cli.run_report(args()) == 1
        assert "No sessions in" in capsys.readouterr().out

    def test_newest_is_completed_and_rendered(self, write_log, llm, capsys):
        old = write_log(TALK, sid="20260101_120000")
        new = write_log(TALK, sid="20260102_120000")
        assert cli.run_report(args()) == 0
        out = capsys.readouterr().out
        assert "regraded 1" in out and "✓" in out
        assert os.path.exists(new[:-6] + ".html") and not os.path.exists(old[:-6] + ".html")

    def test_all_and_no_fill(self, write_log, llm):
        paths = [write_log(TALK, sid=f"2026010{d}_120000") for d in (1, 2)]
        assert cli.run_report(args(all=True, no_fill=True)) == 0
        assert not llm.calls and all(os.path.exists(p[:-6] + ".html") for p in paths)

    def test_a_given_file(self, write_log, llm):
        path = write_log(TALK)
        assert cli.run_report(args(session=path, no_fill=True)) == 0
        assert os.path.exists(path[:-6] + ".html")

    def test_skips_logs_with_nothing_said(self, write_log, capsys):
        write_log([("partner", 0, "Welcome")])
        assert cli.run_report(args()) == 0
        assert "✓" not in capsys.readouterr().out

    def test_skips_a_session_open_in_the_app(self, write_log, other_pid, capsys):
        path = write_log(TALK)
        open(path + ".live", "w").write(str(other_pid))
        assert cli.run_report(args()) == 0
        assert "open in OpenSpeak right now" in capsys.readouterr().out
        assert not os.path.exists(path[:-6] + ".html")

    def test_a_failure_is_reported(self, write_log, monkeypatch, capsys):
        write_log(TALK)

        def build(path):
            raise OSError("disk full")

        monkeypatch.setattr(report, "build", build)
        assert cli.run_report(args(no_fill=True)) == 1
        assert "disk full" in capsys.readouterr().err


class TestServe:
    @pytest.fixture
    def ran(self, monkeypatch):
        import threading

        import uvicorn

        ran = {"opened": []}
        monkeypatch.setattr(uvicorn, "run", lambda app, **kw: ran.update(kw))
        monkeypatch.setattr(server, "allowed_hosts", {"localhost", "127.0.0.1", "[::1]"})
        monkeypatch.setattr(cli, "port_busy", lambda host, port: False)

        class Timer:
            def __init__(self, delay, fn, fn_args):
                self.call = lambda: ran["opened"].append(fn_args[0])

            def start(self):
                self.call()

        monkeypatch.setattr(threading, "Timer", Timer)
        return ran

    def serve(self, host="127.0.0.1", no_browser=True, allow=None):
        cli.serve(argparse.Namespace(host=host, port=9000, no_browser=no_browser, allow_host=allow))

    def test_a_port_in_use_says_so_and_starts_nothing(self, ran, monkeypatch, capsys):
        monkeypatch.setattr(cli, "port_busy", lambda host, port: True)
        assert cli.serve(argparse.Namespace(host="127.0.0.1", port=9000, no_browser=False, allow_host=None)) == 1
        err = capsys.readouterr().err
        assert "already in use" in err and "--port" in err
        assert "host" not in ran and not ran["opened"]

    def test_localhost(self, ran):
        self.serve(no_browser=False)
        assert ran["host"] == "127.0.0.1" and ran["port"] == 9000
        assert ran["opened"] == ["http://localhost:9000"]
        assert server.allowed_hosts == {"localhost", "127.0.0.1", "[::1]"}

    def test_a_chosen_host_is_allowed(self, ran):
        self.serve("192.168.1.5")
        assert "192.168.1.5" in server.allowed_hosts and not ran["opened"]

    def test_all_interfaces_allow_only_this_machines_names(self, ran, capsys, monkeypatch):
        monkeypatch.setattr(cli, "this_machine", lambda: {"mac", "mac.local", "192.168.1.5"})
        monkeypatch.setattr(cli, "in_container", lambda: False)
        self.serve("0.0.0.0", allow=["speak.example.invalid"])
        assert server.allowed_hosts == {"localhost", "127.0.0.1", "[::1]", "mac", "mac.local", "192.168.1.5", "speak.example.invalid"}
        out = capsys.readouterr().out
        assert "anyone on your network" in out and "mac.local" in out

    def test_in_a_container_it_does_not_warn_about_the_network(self, ran, capsys, monkeypatch):
        monkeypatch.setattr(cli, "in_container", lambda: True)
        self.serve("0.0.0.0")
        out = capsys.readouterr().out
        assert "anyone on your network" not in out and "127.0.0.1:8765:8765" in out

    def test_this_machine(self, monkeypatch):
        import socket

        monkeypatch.setattr(socket, "gethostname", lambda: "mac.example.invalid")
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
            (socket.AF_INET, 0, 0, "", ("192.168.1.5", 0)), (socket.AF_INET6, 0, 0, "", ("fe80::1", 0, 0, 0))])
        # the name, its .local form, and the addresses it resolves to, IPv6 in brackets as in a Host header
        assert cli.this_machine() == {"mac.example.invalid", "mac.local", "192.168.1.5", "[fe80::1]"}

    def test_this_machine_without_name_resolution(self, monkeypatch):
        import socket

        def refuse(*a, **k):
            raise socket.gaierror("no resolver")

        monkeypatch.setattr(socket, "gethostname", lambda: "mac")
        monkeypatch.setattr(socket, "getaddrinfo", refuse)
        assert cli.this_machine() == {"mac", "mac.local"}


class TestMain:
    def test_report_command(self, monkeypatch, write_log):
        monkeypatch.setattr(sys, "argv", ["openspeak", "report", "--list"])
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0

    def test_warns_about_a_key_without_its_url(self, monkeypatch, capsys):
        monkeypatch.setenv("OPENSPEAK_API_KEY", "sk-env-not-real")
        monkeypatch.setattr(sys, "argv", ["openspeak", "report", "--list"])
        with pytest.raises(SystemExit):
            cli.main()
        assert "OPENSPEAK_BASE_URL" in capsys.readouterr().err

    def test_moves_data_from_the_former_name_first(self, monkeypatch, tmp_path, capsys):
        from openspeak import config

        old, new = tmp_path / "old", tmp_path / "new"
        (old / "sessions").mkdir(parents=True)
        for name, value in (("OLD_HOME", old), ("HOME", new), ("DEFAULT_HOME", new), ("SESSIONS_DIR", new / "sessions")):
            monkeypatch.setattr(config, name, str(value))
        monkeypatch.setattr(sys, "argv", ["openspeak", "report", "--list"])
        with pytest.raises(SystemExit):
            cli.main()
        assert "Moved your data" in capsys.readouterr().err and (new / "sessions").is_dir()

    def test_default_serves(self, monkeypatch):
        got = []
        monkeypatch.setattr(cli, "serve", lambda a: got.append(a) or 0)
        monkeypatch.setattr(sys, "argv", ["openspeak", "--port", "9001", "--no-browser"])
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        assert got[0].port == 9001 and got[0].no_browser and got[0].cmd is None

    def test_a_failed_start_exits_nonzero(self, monkeypatch):
        monkeypatch.setattr(cli, "serve", lambda a: 1)
        monkeypatch.setattr(sys, "argv", ["openspeak"])
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 1


def test_output_survives_a_console_without_unicode(monkeypatch, write_log):
    import io

    out = io.TextIOWrapper(io.BytesIO(), encoding="ascii")  # like a terminal in a plain-ASCII locale
    monkeypatch.setattr(sys, "stdout", out)
    write_log(TALK)
    monkeypatch.setattr(sys, "argv", ["openspeak", "report", "--no-fill"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    out.flush()
    assert e.value.code == 0 and out.buffer.getvalue().startswith(b"? ")


class TestPortBusy:
    def test_a_taken_port_is_busy_and_a_free_one_isnt(self):
        import socket

        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            port = taken.getsockname()[1]
            assert cli.port_busy("127.0.0.1", port)
        assert not cli.port_busy("127.0.0.1", port)


def test_version(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["openspeak", "--version"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0 and capsys.readouterr().out.startswith("openspeak ")
