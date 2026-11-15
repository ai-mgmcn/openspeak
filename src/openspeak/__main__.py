"""
    openspeak                     start the app and open it in your browser
    openspeak --port 9000 --no-browser
    openspeak --host 0.0.0.0 [--allow-host NAME]    reachable from the network
    openspeak --version
    openspeak report              finish + re-render the newest session
    openspeak report --all        every session
    openspeak report --list       what's on disk
    openspeak report --no-fill    render only; don't call the model
    openspeak report <id or file.jsonl>
"""

import argparse
import asyncio
import os
import sys
import threading
import webbrowser

from . import __version__


def this_machine():
    """The names and addresses other devices on the network may reach this one by."""
    import socket

    name = socket.gethostname()
    names = {name, name.split(".")[0] + ".local"}
    try:
        names |= {a[4][0] for a in socket.getaddrinfo(name, None)}
    except OSError:
        pass
    return {f"[{n}]" if ":" in n else n for n in names}


def in_container():
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def port_busy(host, port):
    """Whether something already listens on this address."""
    import socket

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family) as s:
        try:
            s.bind((host, port))
        except OSError:
            return True
    return False


def serve(args):
    import uvicorn

    from .web import server

    if port_busy(args.host, args.port):
        # Most often OpenSpeak itself, still running from before.
        print(f"Port {args.port} is already in use: is OpenSpeak already running? "
              f"Open http://localhost:{args.port}, or start this one on another port with --port.", file=sys.stderr)
        return 1

    extra = set(args.allow_host or ())
    if args.host in ("0.0.0.0", "::"):
        # Still only names that are this machine's: any name at all would let a web
        # page reach the server through a hostname it controls (DNS rebinding).
        server.allowed_hosts |= this_machine() | extra
        if in_container():
            # "All interfaces" is the container's own; who can reach it is decided by how the port is published.
            print("Running in a container. Publish the port to this computer only with -p 127.0.0.1:8765:8765.")
        else:
            print("Listening on all interfaces: anyone on your network can use OpenSpeak, with your saved keys, "
                  f"by these names: {', '.join(sorted(server.allowed_hosts))}. Add others with --allow-host. "
                  "Browsers only allow the microphone on localhost or HTTPS, so other devices need an HTTPS proxy.")
    elif args.host not in ("127.0.0.1", "localhost"):
        server.allowed_hosts |= {args.host} | extra
    url = f"http://localhost:{args.port}"
    print(f"OpenSpeak → {url}")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, (url,)).start()
    uvicorn.run(server.app, host=args.host, port=args.port, log_level="warning")
    return 0


def run_report(args):
    from . import config, report
    from .practice import sessionlog
    from .practice.completion import complete

    paths = report.list_sessions()
    if args.list:
        for p in paths:
            d = report.describe(p)
            flag = "" if d["complete"] or not d["turns"] else "  (incomplete — run `openspeak report` on it)"
            print(f'{d["id"]}  {d["at"] or "?":<20} {d["turns"]:>3} turns {d["errors"]:>3} mistakes{flag}')
        return 0
    targets = paths if args.all else paths[-1:]
    if args.session:
        # A path, or an id as `--list` prints it.
        by_id = os.path.join(config.SESSIONS_DIR, f"session_{args.session}.jsonl")
        found = next((p for p in (args.session, by_id) if os.path.isfile(p)), None)
        if not found:
            print(f"No such session: {args.session}. See `openspeak report --list`.", file=sys.stderr)
            return 1
        targets = [found]
    if not targets:
        print(f"No sessions in {config.SESSIONS_DIR}")
        return 1
    cfg = config.load()
    failures = 0
    for p in targets:
        if not sessionlog.has_talk(sessionlog.read(p)):
            continue
        if sessionlog.in_use_elsewhere(p):
            print(f"- {p}: open in OpenSpeak right now; end it there first")
            continue
        try:
            if not args.no_fill:
                fixed, added = asyncio.run(complete(cfg, p))
                if fixed or added:
                    print(f"  regraded {fixed}, added {', '.join(added) or 'nothing'}")
            out = report.build(p)
            print(f"✓ {out['html']}")
        except Exception as e:
            failures += 1
            print(f"✗ {p}: {e}", file=sys.stderr)
    return 1 if failures else 0


def main():
    # A terminal or redirected output in a plain-ASCII locale (a container, LANG=C)
    # has no ✓ or →: print a ? rather than fail.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # None under pythonw
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="openspeak")
    parser.add_argument("--version", action="version", version=f"openspeak {__version__}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--allow-host", action="append", metavar="NAME",
                        help="another hostname the app may be opened by (with --host); repeatable")
    sub = parser.add_subparsers(dest="cmd")
    r = sub.add_parser("report", help="finish and re-render session reports")
    r.add_argument("session", nargs="?")
    r.add_argument("--all", action="store_true")
    r.add_argument("--list", action="store_true")
    r.add_argument("--no-fill", action="store_true", help="render only; don't call the model")
    args = parser.parse_args()
    from . import config

    for note in filter(None, [config.move_old_home(), *config.env_warnings()]):
        print(note, file=sys.stderr)
    if args.cmd == "report":
        sys.exit(run_report(args))
    sys.exit(serve(args))


if __name__ == "__main__":
    main()
