import os
import stat

import pytest

from openspeak import fsutil


class TestPidAlive:
    def test_running_and_gone(self, other_pid, dead_pid):
        assert fsutil.pid_alive(os.getpid()) and fsutil.pid_alive(other_pid)
        assert not fsutil.pid_alive(dead_pid)

    @pytest.mark.parametrize("raised, alive", [(PermissionError, True), (ProcessLookupError, False), (None, True)])
    def test_the_check_by_what_the_system_says(self, monkeypatch, raised, alive):
        # Someone else's process refuses the signal but exists; a missing one doesn't.
        def kill(pid, sig):
            if raised:
                raise raised()

        monkeypatch.setattr(os, "kill", kill)
        assert fsutil.pid_alive(4242) is alive


class TestRemoveAndReplace:
    def test_already_gone_is_fine(self, tmp_path):
        fsutil.remove(str(tmp_path / "nothing"))

    def test_replace(self, tmp_path):
        (tmp_path / "new").write_text("new")
        (tmp_path / "old").write_text("old")
        fsutil.replace(str(tmp_path / "new"), str(tmp_path / "old"))
        assert (tmp_path / "old").read_text() == "new"


class TestPrivate:
    def test_a_written_file_appears_whole_and_leaves_nothing_beside_it(self, tmp_path):
        folder = tmp_path / "out"
        folder.mkdir()
        target = folder / "report.html"
        fsutil.write_private(str(target), "old")
        fsutil.write_private(str(target), "new" * 10000)
        assert target.read_text() == "new" * 10000 and [p.name for p in folder.iterdir()] == ["report.html"]

    def test_a_directory_made_or_found_is_owner_only(self, tmp_path):
        found = tmp_path / "found"
        found.mkdir(mode=0o755)
        fsutil.private_dir(str(found))
        fsutil.private_dir(str(tmp_path / "made" / "deep"))
        assert all(stat.S_IMODE(os.stat(p).st_mode) == 0o700 for p in (found, tmp_path / "made" / "deep"))

    def test_a_file_written_or_rewritten_is_owner_only(self, tmp_path):
        p = tmp_path / "r.html"
        p.write_text("old")
        os.chmod(p, 0o644)
        fsutil.write_private(str(p), "new")
        assert p.read_text() == "new" and stat.S_IMODE(os.stat(p).st_mode) == 0o600
