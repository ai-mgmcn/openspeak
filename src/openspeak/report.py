"""
Turn a session log into a study report: one self-contained HTML file (opens
offline; print it for a PDF) plus a Markdown copy.

HTML instead of a PDF library: the browser already renders every script and
right-to-left language correctly, and there's no font hunting or layout engine
to ship.
"""

import html
import os
import re
from datetime import datetime

from . import config, fsutil
from .practice import sessionlog as log
from .languages import label

# Report chrome in a few languages; the content itself is written by the model in
# whatever report language was chosen. Anything else falls back to English.
L = {
    "en": {
        "title": "Speaking report", "free": "Free conversation", "duration": "Duration",
        "turns": "Turns", "graded": "Graded", "clean": "Clean", "errors": "Mistakes",
        "summary": "Summary", "level": "Level", "patterns": "Recurring patterns",
        "priorities": "Next time, focus on", "encouragement": "What went well",
        "by_type": "Mistakes by type", "vocab": "Words & phrases to keep",
        "dialogue": "Conversation review", "you": "You", "partner": "Partner",
        "corrected": "Correct", "natural": "Natural", "turn": "Turn",
        "sev": {"high": "high", "medium": "medium", "low": "low"},
        "skipped": "too short to grade", "failed": "grading failed — run `openspeak report` to retry",
        "pending": "not graded", "none": "No mistakes logged. Nice.",
        "help": "Asked for help", "print": "Save as PDF", "listen": "Listen",
        "src": {"partner": "heard", "correction": "correction", "learner": "yours"},
        "practice": "Practising", "feedback": "Feedback in",
        "empty": "Nothing was said in this session.",
    },
    "zh": {
        "title": "口语练习报告", "free": "自由对话", "duration": "时长",
        "turns": "说了", "graded": "已批改", "clean": "全对", "errors": "错误",
        "summary": "总评", "level": "水平", "patterns": "反复出现的问题",
        "priorities": "下次重点练", "encouragement": "做得好的地方",
        "by_type": "按类型归纳的错误", "vocab": "值得记下的词和表达",
        "dialogue": "对话回顾", "you": "你", "partner": "陪练",
        "corrected": "正确", "natural": "地道", "turn": "第 {n} 句",
        "sev": {"high": "严重", "medium": "中等", "low": "轻微"},
        "skipped": "太短，未批改", "failed": "批改失败 — 运行 `openspeak report` 可补批",
        "pending": "未批改", "none": "没有记录到错误，很棒。",
        "help": "求助", "print": "保存为 PDF", "listen": "朗读",
        "src": {"partner": "对方用过", "correction": "纠错", "learner": "你的"},
        "practice": "练习语言", "feedback": "报告语言",
        "empty": "这次练习没有说话内容。",
    },
    "ja": {
        "title": "スピーキングレポート", "free": "フリートーク", "duration": "時間",
        "turns": "発話", "graded": "採点済み", "clean": "正確", "errors": "間違い",
        "summary": "総評", "level": "レベル", "patterns": "繰り返し出た問題",
        "priorities": "次回の重点", "encouragement": "よかった点",
        "by_type": "種類別の間違い", "vocab": "覚えておきたい語句",
        "dialogue": "会話の振り返り", "you": "あなた", "partner": "相手",
        "corrected": "正しい形", "natural": "自然な言い方", "turn": "{n} 回目",
        "sev": {"high": "重大", "medium": "中程度", "low": "軽微"},
        "skipped": "短すぎるため未採点", "failed": "採点失敗 — `openspeak report` で再採点",
        "pending": "未採点", "none": "間違いは記録されませんでした。",
        "help": "ヘルプ", "print": "PDFで保存", "listen": "聞く",
        "src": {"partner": "相手の表現", "correction": "訂正", "learner": "自分の表現"},
        "practice": "練習言語", "feedback": "レポート言語",
        "empty": "この回は発話がありませんでした。",
    },
}

TYPE_LABELS = {
    "zh": {
        "tense": "时态", "aspect": "体（完成/进行）", "agreement": "主谓一致", "conjugation": "动词变位",
        "gender": "性", "case": "格", "article": "冠词", "particle": "助词", "preposition": "介词",
        "plural": "单复数", "word-order": "语序", "word-choice": "用词", "missing-word": "漏词",
        "extra-word": "多余的词", "pronoun": "代词", "register": "语体/礼貌", "countability": "可数/不可数",
        "collocation": "搭配", "l1-transfer": "母语直译", "other": "其他",
    },
    "ja": {
        "tense": "時制", "aspect": "相", "agreement": "一致", "conjugation": "活用", "gender": "性",
        "case": "格", "article": "冠詞", "particle": "助詞", "preposition": "前置詞", "plural": "単数・複数",
        "word-order": "語順", "word-choice": "語の選択", "missing-word": "語の脱落", "extra-word": "余分な語",
        "pronoun": "代名詞", "register": "敬語・文体", "countability": "可算・不可算",
        "collocation": "コロケーション", "l1-transfer": "母語の直訳", "other": "その他",
    },
}

SEV_RANK = {"high": 0, "medium": 1, "low": 2}


def _ui(report_lang):
    code = report_lang["id"].split("-")[0]
    return code if code in L else "en", L.get(code, L["en"])


def _type_label(code, t):
    local = TYPE_LABELS.get(code, {}).get(t)
    return f"{local} · {t}" if local else t


def _esc(s):
    return html.escape(s or "", quote=True)


def _highlight(sentence, spans):
    """
    Underline each wrong span inside the sentence. Ranges are found on the raw text
    first and escaped once afterwards, so a span can never match inside markup.
    """
    taken = []
    for span in sorted({s for s in spans if s}, key=len, reverse=True):
        start = 0
        while True:
            i = sentence.find(span, start)
            if i < 0:
                break
            j = i + len(span)
            if all(j <= a or i >= b for a, b in taken):
                taken.append((i, j))
                break
            start = i + 1
    out, pos = [], 0
    for a, b in sorted(taken):
        out.append(_esc(sentence[pos:a]))
        out.append(f"<mark>{_esc(sentence[a:b])}</mark>")
        pos = b
    out.append(_esc(sentence[pos:]))
    return "".join(out)


def _collect(records):
    start = next((r for r in records if r.get("kind") == "session_start"), {})
    end = next((r for r in reversed(records) if r.get("kind") == "session_end"), None)
    heard = {r["turn"]: r for r in records if r.get("kind") == "heard"}
    graded = {}
    for r in records:
        if r.get("kind") == "turn":
            graded[r["turn"]] = r  # a later regrade wins
    # Meant to be graded, no result yet: failed, cut off, or still to be repaired.
    failed = {t for t, h in heard.items() if h.get("graded")} - set(graded)
    # Logs are append-only, so the newest summary/vocab is the one to show.
    summary = next((r for r in reversed(records) if r.get("kind") == "summary"), None)
    vocab = next((r.get("items") for r in reversed(records) if r.get("kind") == "vocab"), None) or []
    return start, end, heard, graded, failed, summary, vocab


def _timeline(records, heard, graded):
    """Partner and learner lines in spoken order."""
    items = []
    for r in records:
        k = r.get("kind")
        if k == "partner":
            items.append((r.get("turn", 0), 1, r))
        elif k == "help":
            items.append((r.get("turn", 0), 2, r))
    for turn, h in heard.items():
        items.append((turn, 0, graded.get(turn, h) | {"kind": "you", "said": h["said"], "graded_flag": h.get("graded")}))
    return [r for _, _, r in sorted(items, key=lambda x: (x[0], x[1]))]


def _duration(start, end):
    try:
        a = datetime.fromisoformat(start["at"])
        b = datetime.fromisoformat(end["at"]) if end else None
    except (KeyError, TypeError, ValueError):
        return "–"
    if not b:
        return "–"
    mins = max(1, round((b - a).total_seconds() / 60))
    return f"{mins} min"


CSS = """
:root{--bg:#fff;--fg:#1c1b1f;--mute:#6b6b76;--line:#e7e5ee;--card:#f7f6fb;--acc:#5b4bdb;--bad:#c62828;--mid:#b26a00;--ok:#2e7d32;--mark:#ffe3e3}
@media(prefers-color-scheme:dark){:root{--bg:#141318;--fg:#ece9f3;--mute:#9a97a6;--line:#2b2934;--card:#1d1c23;--acc:#9d90ff;--mark:#5a2323}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,"PingFang SC","Hiragino Sans","Noto Sans",sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 20px 64px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.meta{color:var(--mute);font-size:13px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:20px 0}
.stat{background:var(--card);border-radius:12px;padding:12px 14px}.stat b{display:block;font-size:22px}.stat span{color:var(--mute);font-size:12px}
.card{background:var(--card);border-radius:12px;padding:14px 16px;margin:10px 0}ul{margin:6px 0;padding-left:20px}
.type{display:flex;align-items:center;gap:8px;margin:18px 0 6px;font-weight:600}.count{background:var(--acc);color:#fff;border-radius:99px;padding:0 8px;font-size:12px}
.err{border-left:3px solid var(--line);padding:6px 12px;margin:8px 0}.err.high{border-color:var(--bad)}.err.medium{border-color:var(--mid)}
.err .from{text-decoration:line-through;color:var(--bad)}.err .to{color:var(--ok);font-weight:600}.small{color:var(--mute);font-size:12.5px}
mark{background:var(--mark);color:inherit;border-radius:3px;padding:0 2px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:var(--mute);font-weight:600}
.line{margin:12px 0;display:flex;flex-direction:column}.line .who{font-size:12px;color:var(--mute)}.bubble{padding:10px 14px;border-radius:14px;max-width:88%}
.line.partner .bubble{background:var(--card);align-self:flex-start}.line.you{align-items:flex-end}.line.you .bubble{background:color-mix(in srgb,var(--acc) 12%,var(--bg));border:1px solid color-mix(in srgb,var(--acc) 25%,transparent)}
.fix{margin-top:6px;font-size:14px}.fix div{margin-top:2px}.aid{font-size:13px;color:var(--mute);margin-top:4px}
.say{border:0;background:none;cursor:pointer;color:var(--acc);font-size:13px;padding:0 4px}
.help{align-self:center;font-size:13px;color:var(--mute);background:var(--card);border-radius:10px;padding:6px 12px}
.bar{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.btn{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:10px;padding:8px 14px;cursor:pointer;font:inherit}
.mute .say{display:none}
@media print{.say,.btn{display:none}body{font-size:12px}main{padding:0}.card,.stat,.bubble{break-inside:avoid}h2{break-after:avoid}}
@media(max-width:600px){.stats{grid-template-columns:repeat(2,1fr)}}
"""

# 🔊 uses offline voices only, as the app does by itself: an online one (Chrome's
# "Google …") would send the line to Google. With none for the language, no 🔊.
JS = """
function voice(){const l=(document.body.dataset.tts||'').toLowerCase(),base=l.split('-')[0];if(!l||!window.speechSynthesis)return null;
const vs=speechSynthesis.getVoices().filter(v=>v.localService&&v.lang.toLowerCase().replace('_','-').split('-')[0]===base);
return vs.find(v=>v.lang.toLowerCase().replace('_','-')===l)||vs[0]||null}
function show(){document.body.classList.toggle('mute',!voice())}
if(window.speechSynthesis){speechSynthesis.addEventListener('voiceschanged',show)}show();
function say(t){const v=voice();if(!v)return;speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(t);u.voice=v;u.lang=v.lang;u.rate=.95;speechSynthesis.speak(u)}
document.addEventListener('click',e=>{const b=e.target.closest('.say');if(b)say(b.dataset.t)});
"""


def build(path):
    records = log.read(path)
    start, end, heard, graded, failed, summary, vocab = _collect(records)
    langs = log.session_langs(records)
    code, t = _ui(langs["report"])
    target = langs["target"]
    scene = start.get("scene")
    scene_title = (scene["title"].get(code) or scene["title"].get("en")) if scene else t["free"]

    turns = list(graded.values())
    all_errors = [e | {"turn": g["turn"]} for g in turns for e in g.get("errors", [])]
    by_type = {}
    for e in all_errors:
        by_type.setdefault(e["type"], []).append(e)
    clean = sum(1 for g in turns if g.get("verdict") == "clean")

    def say_btn(text):
        return f'<button class="say" data-t="{_esc(text)}" title="{_esc(t["listen"])}">🔊</button>'

    def turn_label(n):
        return t["turn"].format(n=n) if "{n}" in t["turn"] else f'{t["turn"]} {n}'

    parts = []
    started = (start.get("at") or "").replace("T", " ")
    parts.append(
        f'<div class="bar"><div><h1>{_esc(scene_title)}</h1>'
        f'<div class="meta">{_esc(t["title"])} · {_esc(started)} · {_esc(t["duration"])} {_duration(start, end)}<br>'
        f'{_esc(t["practice"])}: {_esc(label(target))} · {_esc(t["feedback"])}: {_esc(label(langs["report"]))}</div></div>'
        f'<button class="btn" onclick="print()">{_esc(t["print"])}</button></div>'
    )
    parts.append(
        '<div class="stats">'
        + "".join(
            f'<div class="stat"><b>{v}</b><span>{_esc(k)}</span></div>'
            for k, v in ((t["turns"], len(heard)), (t["graded"], len(turns)), (t["clean"], clean), (t["errors"], len(all_errors)))
        )
        + "</div>"
    )

    if not heard:
        parts.append(f'<p class="small">{_esc(t["empty"])}</p>')

    if summary:
        block = []
        if summary.get("level"):
            block.append(f'<p><b>{_esc(t["level"])}</b> — {_esc(summary["level"])}</p>')
        for key in ("patterns", "priorities"):
            if summary.get(key):
                block.append(f'<p><b>{_esc(t[key])}</b></p><ul>' + "".join(f"<li>{_esc(x)}</li>" for x in summary[key]) + "</ul>")
        if summary.get("encouragement"):
            block.append(f'<p><b>{_esc(t["encouragement"])}</b> — {_esc(summary["encouragement"])}</p>')
        parts.append(f'<h2>{_esc(t["summary"])}</h2><div class="card">{"".join(block)}</div>')

    if turns:
        parts.append(f'<h2>{_esc(t["by_type"])}</h2>')
        if not all_errors:
            parts.append(f'<p class="small">{_esc(t["none"])}</p>')
        for et, errs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
            parts.append(f'<div class="type">{_esc(_type_label(code, et))} <span class="count">{len(errs)}</span></div>')
            for e in sorted(errs, key=lambda e: (SEV_RANK.get(e["severity"], 1), e["turn"])):
                parts.append(
                    f'<div class="err {_esc(e["severity"])}"><span class="from">{_esc(e["original"])}</span> → '
                    f'<span class="to">{_esc(e["correction"])}</span>'
                    f'<div>{_esc(e["explain"])}</div>'
                    f'<div class="small">{_esc(turn_label(e["turn"]))} · {_esc(t["sev"].get(e["severity"], e["severity"]))}</div></div>'
                )

    if vocab:
        rows = "".join(
            f'<tr><td><b>{_esc(v["term"])}</b> {say_btn(v["term"])}<div class="small">{_esc(v.get("pos"))}</div></td>'
            f'<td>{_esc(v.get("meaning"))}<div class="small">{_esc(v.get("note"))}</div></td>'
            f'<td>{_esc(v.get("example"))}</td><td class="small">{_esc(t["src"].get(v.get("source"), ""))}</td></tr>'
            for v in vocab
        )
        parts.append(f'<h2>{_esc(t["vocab"])}</h2><table><tbody>{rows}</tbody></table>')

    if heard:
        parts.append(f'<h2>{_esc(t["dialogue"])}</h2>')
        for r in _timeline(records, heard, graded):
            if r["kind"] == "partner":
                aid = f'<div class="aid">{_esc(r.get("aid"))}</div>' if r.get("aid") else ""
                parts.append(
                    f'<div class="line partner"><span class="who">{_esc(t["partner"])}</span>'
                    f'<div class="bubble">{_esc(r["said"])} {say_btn(r["said"])}{aid}</div></div>'
                )
            elif r["kind"] == "help":
                says = " / ".join(r.get("say") or [])
                parts.append(f'<div class="help">💡 {_esc(t["help"])}: {_esc(r.get("hint"))} {_esc(says)}</div>')
            else:
                turn = r["turn"]
                if turn in graded:
                    g = graded[turn]
                    body = _highlight(r["said"], [e["original"] for e in g.get("errors", [])])
                    fix = ""
                    if g.get("errors") and g.get("corrected"):
                        fix += f'<div><b>{_esc(t["corrected"])}</b> {_esc(g["corrected"])} {say_btn(g["corrected"])}</div>'
                    if g.get("native_version") and g.get("native_version") != g.get("corrected"):
                        fix += f'<div><b>{_esc(t["natural"])}</b> {_esc(g["native_version"])} {say_btn(g["native_version"])}</div>'
                    if g.get("good_note"):
                        fix += f'<div class="small">👍 {_esc(g["good_note"])}</div>'
                    fix = f'<div class="fix">{fix}</div>' if fix else ""
                else:
                    body = _esc(r["said"])
                    why = t["failed"] if turn in failed else t["skipped"] if r.get("graded_flag") is False else t["pending"]
                    fix = f'<div class="small">{_esc(why)}</div>'
                parts.append(
                    f'<div class="line you"><span class="who">{_esc(t["you"])} · {_esc(turn_label(turn))}</span>'
                    f'<div class="bubble">{body}{fix}</div></div>'
                )

    doc = (
        f'<!doctype html><html lang="{_esc(langs["report"]["id"])}" dir="{"rtl" if langs["report"]["rtl"] else "ltr"}">'
        f'<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(scene_title)} · {_esc(started)}</title><style>{CSS}</style></head>"
        f'<body data-tts="{_esc(target.get("tts") or "")}"><main>{"".join(parts)}</main><script>{JS}</script></body></html>'
    )
    base = os.path.splitext(path)[0]
    fsutil.write_private(base + ".html", doc)
    fsutil.write_private(base + ".md", _markdown(t, code, scene_title, started, heard, all_errors, by_type, summary, vocab, records, graded))
    return {"html": base + ".html", "md": base + ".md"}


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|~])")


def _md(value):
    """Text for Markdown: one line, with nothing in it taken for markup or a table cell."""
    return _MD_SPECIAL.sub(r"\\\1", " ".join(str(value if value is not None else "").split()))


def _markdown(t, code, title, started, heard, all_errors, by_type, summary, vocab, records, graded):
    out = [f"# {_md(title)}", "", f"{t['title']} · {_md(started)}", ""]
    out.append(f"{t['turns']} {len(heard)} · {t['graded']} {len(graded)} · {t['errors']} {len(all_errors)}")
    if summary:
        out += ["", f"## {t['summary']}", ""]
        if summary.get("level"):
            out.append(f"**{t['level']}** — {_md(summary['level'])}")
        for key in ("patterns", "priorities"):
            if summary.get(key):
                out += ["", f"**{t[key]}**"] + [f"- {_md(x)}" for x in summary[key]]
        if summary.get("encouragement"):
            out += ["", f"**{t['encouragement']}** — {_md(summary['encouragement'])}"]
    if all_errors:
        out += ["", f"## {t['by_type']}"]
        for et, errs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
            out += ["", f"### {_md(_type_label(code, et))} ({len(errs)})"]
            out += [f"- ~~{_md(e['original'])}~~ → **{_md(e['correction'])}** — {_md(e['explain'])}" for e in errs]
    if vocab:
        out += ["", f"## {t['vocab']}", "", "| | | |", "|---|---|---|"]
        out += [f"| **{_md(v['term'])}** | {_md(v.get('meaning', ''))} | {_md(v.get('example', ''))} |" for v in vocab]
    if heard:
        out += ["", f"## {t['dialogue']}", ""]
        for r in _timeline(records, heard, graded):
            if r["kind"] == "partner":
                out.append(f"**{t['partner']}:** {_md(r['said'])}")
            elif r["kind"] == "you":
                out.append(f"**{t['you']}:** {_md(r['said'])}")
                g = graded.get(r["turn"])
                if g and g.get("errors") and g.get("corrected"):
                    out.append(f"> {t['corrected']}: {_md(g['corrected'])}")
            out.append("")
    return "\n".join(out) + "\n"


def list_sessions():
    if not os.path.isdir(config.SESSIONS_DIR):
        return []
    return sorted(
        os.path.join(config.SESSIONS_DIR, f)
        for f in os.listdir(config.SESSIONS_DIR)
        if f.endswith(".jsonl")
    )


# path -> ((mtime, size), summary). Logs are append-only, so an unchanged mtime and
# size means an unchanged session and the history drawer needn't re-read it.
_described = {}


def describe(path):
    """One line of metadata for the history drawer."""
    st = os.stat(path)
    key = (st.st_mtime_ns, st.st_size)
    cached = _described.get(path)
    if not cached or cached[0] != key:
        cached = _described[path] = (key, _describe(path))
    # The report file can appear or vanish without the log changing.
    return cached[1] | {"has_report": os.path.exists(os.path.splitext(path)[0] + ".html")}


def _describe(path):
    records = log.read(path)
    start, end, heard, graded, failed, summary, vocab = _collect(records)
    errors = sum(len(g.get("errors", [])) for g in graded.values())
    scene = start.get("scene")
    langs = log.session_langs(records)
    return {
        "id": os.path.basename(path)[len("session_"):-len(".jsonl")],
        "at": start.get("at"),
        "scene": scene["title"] if scene else None,
        "target": langs["target"]["id"],
        "turns": len(heard),
        "errors": errors,
        **_completeness(records, graded, failed),
    }


def _completeness(records, graded, failed):
    """
    "complete": nothing left that completing could add. A summary needs at least one
    graded turn, so a session of only "hello" is complete without one.
    "problem": why it's still incomplete after a try, for the history to show.
    """
    missing = log.outdated(records) & {"summary"} if graded else set()
    problem = ""
    if failed or missing:
        errors = [r for r in records if r["kind"] in ("turn_error", "fill_error")]
        if errors:
            problem = errors[-1].get("error") or ""
    return {
        "complete": not failed and not missing,
        "ended": log.ended(records),
        "ungraded": len(failed),
        "problem": problem,
    }


def forget(path):
    _described.pop(path, None)


def prune(paths):
    """Drop cached summaries for logs that no longer exist (deleted by hand)."""
    for p in set(_described) - set(paths):
        _described.pop(p, None)
