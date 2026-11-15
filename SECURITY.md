# Security

OpenSpeak runs on your own computer and listens on `127.0.0.1` only unless you start it with `--host`. It stores API keys in `~/.openspeak/config.json` with owner-only permissions, never shows them to the page in full, and sends each only to the service it was entered for.

## Reporting a vulnerability

Please don't open a public issue. Use the repository's **Security → Report a vulnerability** (GitHub private reporting). Say what you found, how to reproduce it, and what it lets someone do. You'll get an answer as soon as someone can look.

Things worth reporting: a way for another website or another user on the machine to read or use saved keys or sessions, to make OpenSpeak send a key somewhere other than its own service, to run code, or to read files outside `~/.openspeak/`.

## Good practice for users

- Keep the default `127.0.0.1`. With `--host 0.0.0.0`, anyone on your network can use OpenSpeak with your saved keys.
- To keep a key off disk, pass it as `OPENSPEAK_API_KEY` with `OPENSPEAK_BASE_URL` instead of saving it in Settings.
- Treat the files in `~/.openspeak/sessions/` as private: they hold everything you said.
