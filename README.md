# Ollama Local Chat

Small local-only browser interface for Ollama.

Defaults:

- App: `http://127.0.0.1:8765`
- Ollama: `http://127.0.0.1:11434`
- Model: `gemma4:26b`
- Storage: local SQLite in `data/chat.sqlite3`

No cloud service, no external scripts, no fonts, no CDN, no analytics.

## Install launcher on Linux Mint

```bash
./scripts/install_desktop_launcher.sh
```

Then open **Ollama Local Chat** from the Mint menu.

The launcher uses a dedicated Firefox profile folder inside the app:

```text
data/firefox-profile
```

That keeps it separate from your normal Firefox profile and extensions.

## Run manually

```bash
./scripts/run.sh
```

Then open:

```text
http://127.0.0.1:8765
```

## Use your existing Firefox IT profile (or which ever profile you want)

```bash
./scripts/run_firefox_IT.sh
```

## Stop the local server

```bash
./scripts/stop.sh
```

## Notes

- Normal chats are saved locally in SQLite.
- Private chats are not saved.
- The app asks Ollama for thinking output using `think: true` and shows it live when the model returns it.
- When the final answer starts, the thinking section collapses. You can expand it manually.
- Download `.md` saves the current chat as a Markdown file.
- Clear this chat deletes only messages in the current chat, not all history.
