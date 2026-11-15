"""
Start the installed `openspeak` for real and check it serves its page and data.
Run by CI against the built wheel, in a clean environment, so a file left out of
the package (the page, the scenes) shows up here and not on a user's machine:

    python scripts/smoke.py
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def main():
    exe = shutil.which("openspeak")
    assert exe, "the openspeak command isn't installed"
    port = free_port()
    home = tempfile.mkdtemp(prefix="openspeak-smoke-")
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENSPEAK_")} | {"OPENSPEAK_HOME": home}
    proc = subprocess.Popen([exe, "--no-browser", "--port", str(port)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            if proc.poll() is not None:
                sys.exit(f"openspeak exited early ({proc.returncode}):\n{proc.stdout.read()}")
            try:
                get(base + "/")
                break
            except OSError:
                time.sleep(0.5)
        else:
            sys.exit("openspeak didn't start within 30 s")
        status, page = get(base + "/")
        assert status == 200 and "OpenSpeak" in page, "the page isn't served"
        for asset in ("/static/app.js", "/static/app.css"):
            assert get(base + asset)[0] == 200, asset
        meta = json.loads(get(base + "/api/meta")[1])
        assert len(meta["scenes"]) >= 50 and len(meta["languages"]) >= 30, "the built-in data is missing"
        assert meta["config"]["setup_done"] is False, "a fresh home should start the setup"
        print(f"ok: {len(meta['scenes'])} scenes, {len(meta['languages'])} languages")
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
