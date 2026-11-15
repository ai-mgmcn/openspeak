# Contributing

Thanks for helping. The aims are few: it stays local-first and free to run, it never sends anything anywhere the user didn't choose, and it stays simple to use.

## Set up

```bash
git clone https://github.com/ai-mgmcn/openspeak.git
cd openspeak
uv sync                      # add --extra local to try real speech recognition
uv run pytest
uv run ruff check src tests scripts
uv run --with playwright pytest tests/browser   # the page in Chrome; skipped if either is missing
uv run openspeak --port 8799 --no-browser     # a copy of your own to try changes on
```

The page is plain HTML, CSS and JavaScript in `src/openspeak/web/static/`. There is no build step: edit, reload.

## Before you send a change

- **Tests pass, and a new behaviour has one.** A test should fail when the behaviour breaks; mocks of the model and the network are in `tests/conftest.py`. Tests never use the network or your real `~/.openspeak` (point `OPENSPEAK_HOME` somewhere temporary if you run the app by hand).
- **The linter is clean**: `uv run ruff check src tests scripts`.
- **Small and in the style around it.** Match the surrounding naming and comment density. Explain *why* in a comment, not *what*.
- **Interface text in all three languages.** Strings live in the `I18N` table at the top of `app.js` (English, Chinese, Japanese); a test checks every language has every string.
- **No new network calls, trackers, fonts or scripts loaded from elsewhere.** Anything that sends data out must be something the user picked, and the README's *Your data and privacy* section must say so.
- **Keep keys out of everything**: code, tests, logs, issue text. Tests use obvious fakes like `sk-test`.

## Reporting a problem

Open an issue with the steps, what you expected, what happened, your system and browser, and any error text. Remove API keys and anything private from logs and screenshots first. For a security problem, see [SECURITY.md](SECURITY.md).
