"""
The silent grader: judges one learner utterance and returns structured mistakes.

Its result goes only into the session log, never into the conversation, so the
learner is never interrupted. What reaches the model when is decided by the Gate:
grading yields to the partner, and a local server gets one grading call at a time.
"""

import asyncio
import contextlib
import re
import unicodedata
import weakref

import httpx

from .. import config
from . import client, prompts

MIN_WORDS = 3  # word-spaced languages
MIN_CHARS = 4  # languages written without spaces

_EN_FILLER = re.compile(
    r"^(?:(?:u+h+|u+m+|e+r+|a+h+|o+h+|h+m+|y+e+a+h+|yes|no|nope|ok+|okay|right|sure|"
    r"thanks|thank you|bye|hello|hi+|hey+|nice|good|cool|wow+|really|exactly|i see|"
    r"got it|of course|no problem|mhm+|yep+)[\s,.!?\-]*)+$",
    re.IGNORECASE,
)

# Things that only exist in writing. Speech has no commas; the grader is told not
# to flag them, but models still do now and then.
_WRITTEN_ONLY = {"punctuation", "capitalization", "capitalisation", "spelling", "comma-splice", "run-on"}


# --------------------------------------------------------------------------
# Settings read from the config
# --------------------------------------------------------------------------


def models(cfg):
    """(partner model, grader model). The grader defaults to the partner's."""
    chat = cfg["llm"]["chat_model"]
    return chat, cfg["llm"].get("grader_model") or chat


def timeout_for(cfg, key="timeout"):
    # Local servers queue requests instead of running them side by side; waiting in
    # that queue isn't failure, so give it room.
    t = float(cfg["coach"][key])
    return t * 3 if client.is_local(cfg["llm"]["base_url"]) else t


def grade_live(cfg):
    """Grade during the conversation, or only once it ends."""
    when = cfg["coach"].get("when", "auto")
    return when == "live" or (when == "auto" and not client.is_local(cfg["llm"]["base_url"]))


def max_concurrent(cfg):
    # A local model server shares one GPU between everything: one at a time.
    return 1 if client.is_local(cfg["llm"]["base_url"]) else int(cfg["coach"]["max_concurrent"])


async def call(cfg, messages, want_json=True, timeout=None, model=None):
    base, key = config.connection(cfg, "llm")
    return await client.chat(
        base, key, model or models(cfg)[1], messages,
        want_json=want_json, timeout=timeout or timeout_for(cfg),
    )


# --------------------------------------------------------------------------
# Who gets the model next
# --------------------------------------------------------------------------


class Gate:
    """
    Shared by every session in one event loop:
      - at most N grading calls at once. A burst of quick turns otherwise fires one
        slow call each, the provider falls behind, and calls start timing out;
      - grading waits while the partner is replying. On a local model they share a
        GPU, and the learner should hear back first; their speaking time is when
        grading runs.
    """

    def __init__(self):
        self._slots = {}  # size -> its semaphore: sessions started under different settings must not swap them
        self._replying = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def slots(self, size):
        return self._slots.setdefault(size, asyncio.Semaphore(size))

    async def partner_idle(self):
        await self._idle.wait()

    @contextlib.contextmanager
    def partner_replying(self):
        self._replying += 1
        self._idle.clear()
        try:
            yield
        finally:
            self._replying -= 1
            if not self._replying:
                self._idle.set()


_gates = weakref.WeakKeyDictionary()  # event loop -> Gate; gone with the loop


def gate():
    """The Gate for the running event loop."""
    loop = asyncio.get_running_loop()
    g = _gates.get(loop)
    if g is None:
        g = _gates[loop] = Gate()
    return g


# --------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------


def should_grade(text, target):
    """Worth grading: long enough, and not just "uh huh, okay"."""
    text = (text or "").strip()
    if not text:
        return False
    if target.get("chars"):
        return len(re.sub(r"[\W_]", "", text)) >= MIN_CHARS
    if len(text.split()) < MIN_WORDS:
        return False
    if target["id"] == "en" and _EN_FILLER.match(text):
        return False
    return True


def _context_text(history):
    lines = []
    for m in history[-6:]:
        who = "Learner" if m["role"] == "user" else "Partner"
        if (m.get("content") or "").strip():
            lines.append(f"{who}: {m['content'].strip()}")
    return "\n".join(lines) or "(start of conversation)"


_GRADE_FIELDS = ("errors", "verdict", "corrected")


def _as_grade(result):
    """A JSON object with none of a grade's fields is an error message or a refusal, not "no mistakes"."""
    if not any(k in result for k in _GRADE_FIELDS):
        raise ValueError("The grader's reply isn't a grade")
    return result


async def grade(cfg, langs, text, history):
    """Grade one utterance, retrying timeouts and malformed JSON before giving up."""
    messages = [
        {"role": "system", "content": prompts.grader_system(langs)},
        {
            "role": "user",
            "content": f"Conversation so far:\n{_context_text(history)}\n\nGrade this utterance by the learner:\n{text}",
        },
    ]
    retries = int(cfg["coach"]["retries"])
    last = None
    g = gate()
    async with g.slots(max_concurrent(cfg)):
        for attempt in range(retries + 1):
            await g.partner_idle()
            try:
                return normalize(_as_grade(client.parse_json(await call(cfg, messages))), langs)
            except (httpx.TransportError, ValueError) as e:  # a timeout or dropped connection; a reply that isn't JSON
                last = e
                if attempt < retries:
                    print(f"grader: attempt {attempt + 1}/{retries + 1} failed ({type(e).__name__}); retrying")
    raise last


def _scripts(text):
    """Unicode script families in a string: LATIN, CJK, CYRILLIC, HANGUL, ..."""
    out = set()
    for ch in text:
        if ch.isalpha():
            try:
                out.add(unicodedata.name(ch).split()[0])
            except ValueError:
                pass
    return out


def _foreign_scripts(langs):
    """Scripts of the learner's own language that the target never uses."""
    if not langs:
        return set()
    return _scripts(langs["native"]["native"]) - _scripts(langs["target"]["native"])


def _bare(text):
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def normalize(result, langs=None):
    # Two checks the prompt alone doesn't hold on smaller local models, which
    # relabel the type to get around it: a "fix" that only changes case or
    # punctuation, and a "mistake" that includes the learner's own-language words
    # (they were stuck, not wrong).
    foreign = _foreign_scripts(langs)
    errors = []
    for e in result.get("errors") or []:
        if not isinstance(e, dict):
            continue
        original = client.text(e.get("original"))
        correction = client.text(e.get("correction"))
        if not original and not correction:
            continue
        sev = client.text(e.get("severity")).lower()
        etype = (client.text(e.get("type")) or "other").lower()
        if etype in _WRITTEN_ONLY or _bare(original) == _bare(correction):
            continue
        if foreign and _scripts(original) & foreign:
            continue
        errors.append(
            {
                "type": etype,
                "original": original,
                "correction": correction,
                "explain": client.text(e.get("explain")),
                "severity": sev if sev in ("high", "medium", "low") else "medium",
            }
        )
    verdict = client.text(result.get("verdict")).lower()
    if not errors:
        verdict = "clean"
    elif verdict not in ("clean", "minor", "errors"):
        verdict = "errors"
    return {
        "verdict": verdict,
        "corrected": client.text(result.get("corrected")),
        "native_version": client.text(result.get("native_version")),
        "errors": errors,
        "good_note": client.text(result.get("good_note")),
    }
