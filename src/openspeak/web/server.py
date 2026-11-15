from .. import privacy  # noqa: F401  first, before anything that imports huggingface

import contextlib
import json
import os
import time
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .. import __version__, config, report
from ..ai import client as llm
from ..ai import speech
from ..languages import all_languages
from ..practice import sessionlog as log
from ..practice.completion import complete
from ..practice.jobs import Jobs
from ..practice.live import Elsewhere, LiveSessions, NotFound
from ..practice.session import Session, SessionClosed

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "static")
DATA = os.path.join(os.path.dirname(HERE), "data")

with open(os.path.join(DATA, "scenes.json"), encoding="utf-8") as f:
    SCENES = json.load(f)
SCENES_BY_ID = {s["id"]: s for s in SCENES}

live = LiveSessions()
jobs = Jobs()

# A log with nothing said in it (only the partner's opening) is removed when its
# session ends; one left behind by a crash is removed after this long.
EMPTY_LOG_MAX_AGE_S = 60 * 60


@contextlib.asynccontextmanager
async def lifespan(app):
    live.start_reaper()
    yield
    await jobs.wait_all(timeout=5)
    await jobs.cancel_all()
    await live.shutdown()


app = FastAPI(title="OpenSpeak", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


class FreshStatic(StaticFiles):
    """Checked on every load (a cheap 304 via the ETag), so an updated app shows on refresh."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", FreshStatic(directory=WEB), name="static")
allowed_hosts = {"localhost", "127.0.0.1", "[::1]"}

# Methods that change something. GETs here have no effect worth forging, and a
# cross-site page can't read what they return.
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# One middleware, not one per check: each extra BaseHTTPMiddleware layer runs the
# route in another task, and coverage loses track of it there.
@app.middleware("http")
async def only_our_page(request: Request, call_next):
    """Who may use this server: our own page, on this machine."""
    # DNS rebinding: a web page can't reach this server through a hostname it
    # controls. `openspeak --host` adds the host you chose.
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if allowed_hosts and host not in allowed_hosts:
        return JSONResponse({"error": "host not allowed"}, status_code=403)
    # Cross-site request forgery: any web page can make the browser POST here
    # (text/plain and form posts need no CORS preflight), and the server would act
    # on it with the saved key: point /api/test at the page's own server, and the
    # key goes there. Browsers say where a request comes from; only our own page
    # may change things. Clients that aren't browsers (curl) send neither header.
    if request.method in UNSAFE_METHODS and not _from_this_page(request):
        return JSONResponse({"error": "cross-site request refused"}, status_code=403)
    response = await call_next(request)
    # Clickjacking: no other site may show this page in a frame and steer clicks on it.
    # Our own page may: it shows the report in one.
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    return response


def _from_this_page(request):
    site = request.headers.get("sec-fetch-site")
    if site is not None and site != "same-origin":
        return False  # cross-site, or same-site: another app on another localhost port
    origin = request.headers.get("origin")
    if origin is not None and urlparse(origin).netloc != request.headers.get("host"):
        return False  # includes "null" (sandboxed frames, file://)
    return True


MAX_JSON_BYTES = 256 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # minutes of speech, however it's encoded


async def _body(request, limit):
    """The request body, refused as soon as it goes past `limit`: nothing buffers a whole oversized upload."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, "That's too large to send.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, "That's too large to send.")
        chunks.append(chunk)
    return b"".join(chunks)


async def _json(request):
    """
    The body as a JSON object, only if it was sent as JSON. request.json() alone
    parses any body, so a cross-site text/plain post would read just the same.
    """
    if not (request.headers.get("content-type") or "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    try:
        body = json.loads(await _body(request, MAX_JSON_BYTES))
    except ValueError:
        raise HTTPException(400, "Invalid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object")
    return body


def _err(e, status=502):
    raise HTTPException(status_code=status, detail=llm.describe_error(e))


def _str(body, name, default=""):
    """A text field of a request body: a string, or a 400. (JSON lets a client send anything.)"""
    value = body.get(name, default)
    if not isinstance(value, str):
        raise HTTPException(400, f"{name!r} must be text")
    return value


def _tab(request):
    """Which browser tab is asking. Each page makes up an id and sends it on every call."""
    return request.headers.get("x-tab") or ""


def _session(sid, request):
    """The live session, if the asking tab owns it."""
    try:
        return live.owned(sid, _tab(request))
    except NotFound:
        raise HTTPException(404, "Session not found. It may have been put away; continue it from History.") from None
    except Elsewhere:
        raise HTTPException(409, detail={"code": "elsewhere", "error": "This session was continued in another tab."}) from None


def _closed():
    raise HTTPException(409, detail={"code": "closed", "error": "This session has ended."})


def _elsewhere():
    raise HTTPException(409, detail={"code": "elsewhere", "error": "This session is open in another tab or window."})


@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB, "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/api/meta")
async def meta():
    cfg = config.load()
    return {
        "version": __version__,
        "config": config.public(cfg),
        "languages": all_languages(),
        "providers": config.PROVIDERS,
        "scenes": SCENES,
        "local_stt": speech.local_available(),
        "data_dir": config.HOME,
    }


@app.post("/api/config")
async def save_config(request: Request):
    update = await _json(request)
    try:
        return {"config": config.public(config.save(update))}
    except ValueError as e:
        _err(e, 400)


@app.get("/api/detect")
async def detect():
    return {"found": await llm.detect_local()}


def _conn_from(body):
    """
    A connection from the settings form, to try before saving. A key typed there
    is used as is; otherwise (blank or masked) the one stored for that URL's
    service, so a changed URL never gets another service's key.
    """
    cfg = config.load()
    base = config.url(body.get("base_url")) or cfg["llm"]["base_url"]
    try:
        key = config.sent_key(body.get("api_key"))
    except ValueError as e:
        _err(e, 400)
    return base, key or config.key_for(cfg, base)


@app.delete("/api/keys")
async def clear_key(request: Request):
    body = await _json(request)
    config.clear_key(body.get("base_url"))
    return {"config": config.public(config.load())}


@app.post("/api/models")
async def models(request: Request):
    base, key = _conn_from(await _json(request))
    try:
        return {"models": await llm.list_models(base, key)}
    except Exception as e:
        _err(e)


@app.post("/api/test")
async def test(request: Request):
    body = await _json(request)
    base, key = _conn_from(body)
    try:
        reply = await llm.chat(
            base, key, body.get("model"),
            [{"role": "user", "content": "Reply with just the word OK."}], timeout=60,
        )
    except Exception as e:
        _err(e)
    return {"ok": True, "reply": reply[:80]}


@app.post("/api/session")
async def start(request: Request):
    body = await _json(request)
    cfg = config.load()
    scene_id = body.get("scene_id")
    if scene_id is not None and not isinstance(scene_id, (int, str)):
        raise HTTPException(400, "'scene_id' must be a number")
    scene = SCENES_BY_ID.get(scene_id)
    if scene_id is not None and not scene:
        raise HTTPException(404, "Unknown scene")
    custom = _str(body, "custom")
    if custom:
        scene = {"id": "custom", "title": {"en": custom[:60]}, "prompt": custom, "hard": None}
    s = Session(cfg, scene=scene, hard=bool(body.get("hard")), tab=_tab(request))
    live.add(s)
    try:
        opening = await s.open()
    except BaseException as e:
        # Never reached the page, so nothing could ever clean it up.
        await live.discard(s)
        log.remove_log(s.path)
        if isinstance(e, Exception):
            _err(e)
        raise
    return {"id": s.id, "tts_lang": s.langs["target"]["tts"], "rtl": s.langs["target"]["rtl"], **opening}


@app.post("/api/session/{sid}/resume")
async def resume(sid: str, request: Request):
    path = _log_path(sid)
    body = await _json(request)
    if jobs.running(sid):
        raise HTTPException(409, detail={"code": "working", "error": "The report is still being written. Try again when it's done."})
    stored = next((r.get("scene") for r in log.read(path) if r["kind"] == "session_start"), None)
    scene = SCENES_BY_ID.get(stored.get("id")) if stored else None
    try:
        s = await live.resume(config.load(), path, sid, scene, _tab(request), take=bool(body.get("take")))
    except (Elsewhere, log.InUse):
        _elsewhere()
    except ValueError:  # deleted between the check above and the read
        raise HTTPException(404, "Session not found.") from None
    try:
        reply = await s.catch_up()
    except Exception as e:
        _err(e)
    return {"id": s.id, "tts_lang": s.langs["target"]["tts"], "rtl": s.langs["target"]["rtl"],
            "scene": s.scene, "transcript": s.transcript(), "reply": reply}


@app.post("/api/session/{sid}/leave")
async def leave(sid: str, request: Request):
    # Sent by navigator.sendBeacon as the tab closes, so the tab id is the body.
    live.leave(sid, (await _body(request, 1024)).decode("utf-8", "replace")[:64])
    return {"ok": True}


@app.post("/api/session/{sid}/audio")
async def audio_turn(sid: str, request: Request):
    s = _session(sid, request)
    if s.closed:
        _closed()
    audio = await _body(request, MAX_AUDIO_BYTES)
    if len(audio) < 1000:
        return {"heard": "", "text": ""}
    heard = None

    async def listen():
        nonlocal heard
        heard = await speech.transcribe(s.cfg, audio, request.headers.get("content-type"), s.langs["target"]["stt"])
        return heard

    try:
        # The turn begins now, not once it's transcribed: End pressed meanwhile still keeps it.
        return await s.say(listen()) or {"heard": "", "text": ""}
    except SessionClosed:
        _closed()
    except Exception as e:
        if not heard:
            _err(e)
        # What was heard is already in the log; tell the UI so it can still show it.
        raise HTTPException(502, detail={"heard": heard, "error": llm.describe_error(e)}) from e


@app.post("/api/session/{sid}/text")
async def text_turn(sid: str, request: Request):
    s = _session(sid, request)
    text = _str(await _json(request), "text")
    try:
        return await s.say(text)
    except SessionClosed:
        _closed()
    except Exception as e:
        _err(e)


@app.post("/api/session/{sid}/help")
async def help_(sid: str, request: Request):
    s = _session(sid, request)
    try:
        return await s.help()
    except SessionClosed:
        _closed()
    except Exception as e:
        _err(e)


@app.get("/api/session/{sid}/status")
async def status(sid: str, request: Request):
    s = _session(sid, request)
    s.touch()  # the page polls this: it doubles as the "tab is still here" heartbeat
    return s.status()


def _outcome(path):
    """What a finished job tells the page: is the report whole, and if not, why."""
    d = report.describe(path)
    return {k: d.get(k) for k in ("complete", "ungraded", "problem")}


def _finish_job(s, kind):
    """End a live session in the background; returns the job."""
    s.ending = True  # refuse new turns from now, not from when the job gets going

    async def work(on_stage):
        try:
            if await s.finish(on_stage) is None:
                return {"empty": True}
            return _outcome(s.path)
        finally:
            live.remove(s)

    return jobs.start(s.id, kind, s.path, s.scene and s.scene.get("title"), work)


@app.post("/api/session/{sid}/finish")
async def finish(sid: str, request: Request):
    return _finish_job(_session(sid, request), "finish").view()


@app.get("/api/jobs")
async def job_list():
    return {"jobs": jobs.views()}


@app.post("/api/tts")
async def tts(request: Request):
    body = await _json(request)
    cfg = config.load()
    text = _str(body, "text")[:1000]
    instructions = body.get("instructions") if isinstance(body.get("instructions"), str) else None
    try:
        audio = await speech.synthesize(cfg, text, instructions)
    except Exception as e:
        _err(e)
    return Response(audio, media_type="audio/mpeg")


def _busy(sid, path):
    """In use: live here, open in another process, or a report job running."""
    return sid in live or jobs.running(sid) or log.in_use_elsewhere(path)


def _drop_if_empty(sid, path, d):
    """Logs with nothing the learner said: nothing to show or keep."""
    if d["turns"] or _busy(sid, path):
        return False
    try:
        old = time.time() - os.path.getmtime(path) > EMPTY_LOG_MAX_AGE_S
    except OSError:
        return True
    if old:
        log.remove_log(path)
        report.forget(path)
    return True


@app.get("/api/history")
async def history():
    def read():
        """Everything that touches the disk: with hundreds of sessions it would stall every other request."""
        paths = report.list_sessions()
        report.prune(paths)
        rows = []
        for p in reversed(paths):
            try:
                rows.append((p, report.describe(p), log.in_use_elsewhere(p)))
            except Exception as e:  # one unreadable log mustn't hide all the others
                print(f"history: skipping {os.path.basename(p)} ({type(e).__name__}: {e})")
        return rows

    out = []
    for p, d, elsewhere in await run_in_threadpool(read):
        sid = d["id"]
        if _drop_if_empty(sid, p, d):
            continue
        s = live.get(sid)
        out.append(d | {
            "live": bool(s and not s.closed) or elsewhere,
            "working": jobs.running(sid) or bool(s and s.ending),
        })
    return {"sessions": out}


_deleting = set()  # sessions being deleted: not to be continued or reported meanwhile


def _log_path(sid):
    if not sid.replace("_", "").isdigit():
        raise HTTPException(400, "bad id")
    path = os.path.join(config.SESSIONS_DIR, f"session_{sid}.jsonl")
    if sid in _deleting or not os.path.exists(path):
        raise HTTPException(404, "No such session")
    return path


@app.post("/api/report/{sid}/repair")
async def repair(sid: str):
    path = _log_path(sid)
    s = live.get(sid)
    if s and not s.closed:
        # Open here but abandoned (a tab closed without End). Grading it from the
        # log would race its own grading tasks; finishing it waits for them.
        return _finish_job(s, "repair").view()
    if log.in_use_elsewhere(path):
        _elsewhere()

    async def work(on_stage):
        if s:
            await s.settled()  # being put away right now
        fixed, added = await complete(config.load(), path, on_stage)
        report.build(path)
        return {"regraded": fixed, "added": added, **_outcome(path)}

    title = report.describe(path).get("scene")
    return jobs.start(sid, "repair", path, title, work).view()


@app.delete("/api/report/{sid}")
async def delete(sid: str):
    """Any session can be deleted: whatever it's doing here is stopped first."""
    path = _log_path(sid)
    if log.in_use_elsewhere(path) or log.locked_elsewhere(path):
        raise HTTPException(409, "This session is open in another OpenSpeak window. Close it there first.")
    _deleting.add(sid)
    try:
        s = live.get(sid)
        if s:
            s.drop()  # before its job is stopped: nothing in flight may write the log back
        await jobs.cancel(sid)
        if s:
            await live.discard(s)
        report.forget(path)
        log.remove_log(path)
    finally:
        _deleting.discard(sid)
    return {"ok": True}


def _rendered(sid, ext):
    """The session's report file of this kind, written first if it's missing or older than the log."""
    path = _log_path(sid)
    out = os.path.splitext(path)[0] + ext
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(path):
        report.build(path)
    return out


@app.get("/report/{sid}.md")
async def view_markdown(sid: str):
    return FileResponse(_rendered(sid, ".md"), media_type="text/markdown", filename=f"openspeak_{sid}.md")


# Registered after the .md route: "{sid}" would otherwise swallow "<id>.md".
@app.get("/report/{sid}", response_class=HTMLResponse)
async def view_report(sid: str):
    return FileResponse(_rendered(sid, ".html"))
