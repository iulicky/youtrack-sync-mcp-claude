# youtrack-sync

A Claude Code / Cowork plugin that bridges local Markdown files and YouTrack —
sync Knowledge Base articles in both directions, and operate on Issues
(create, update state/assignee, comment) from chat.

> **Status:** 0.3.0 · MIT-licensed · macOS / Windows / Linux

---

## Why

YouTrack's Knowledge Base is a great place to *publish* documentation, but a
poor place to *write* it — there's no proper diff, no local editor, no git.
This plugin keeps the authoring loop local (write Markdown in your editor of
choice, version it in git) while keeping YouTrack as the source of truth for
readers.

Issue operations are included so the same plugin can drive the full
spec → ticket → status workflow without leaving chat.

---

## Features

- **Articles**
  - `push_file` — upload a local `.md` to a YouTrack article (comments preserved)
  - `pull_to_file` — download an article into a local file (creates a timestamped `.bak`)
  - `diff` — unified diff between local file and article
  - `get_article`, `get_comments`, `list_articles`, `update_article`
- **Issues**
  - `get_issue`, `create_issue`, `update_issue`, `add_comment`, `list_project_states`
- **Safety**
  - Shows a diff before any push.
  - Blocks pushes that shrink content by more than 70%, or are under 50 chars
    (`force=True` to override).
  - Dry-run mode (`dry_run=True`) for push and update.
  - Article existence is verified before any write.
- **Security posture**
  - Token can be stored in the OS keychain (macOS Keychain / Windows Credential
    Manager / Linux Secret Service) — `~/.youtrack.json` then contains only the URL.
  - All YouTrack URL components are percent-encoded before requests.
  - 30-second HTTP timeout.
  - URL scheme is validated; only `http(s)://` accepted.

---

## Quick start

1. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/).
2. Create a YouTrack permanent token (Profile → Authentication → Permanent tokens).
3. Configure credentials — see [`docs/SETUP.md`](docs/SETUP.md) for the full
   walkthrough on each OS.
4. Install `youtrack-sync.plugin` in Claude Code (drag-and-drop, then restart).
5. Try: *"List articles in project MYPROJ"*.

---

## Repository layout

```
.claude-plugin/plugin.json     Plugin manifest
.mcp.json                      MCP server registration (uv + keyring)
servers/youtrack_server.py     The MCP server itself (single file)
skills/youtrack-sync/SKILL.md  Skill instructions Claude reads
docs/SETUP.md                  Full installation & configuration guide
youtrack-sync.plugin           Pre-built ZIP for drag-and-drop install
```

---

## Building the plugin from source

The `.plugin` file is just a ZIP. To rebuild after editing:

```bash
zip -r youtrack-sync.plugin \
    .claude-plugin .mcp.json servers skills docs/SETUP.md \
    -x "*.DS_Store" -x "**/__pycache__/*"
```

(Or use the prebuilt `youtrack-sync.plugin` checked into the repo.)

---

## Security notes

- Each user creates their own YouTrack token; tokens are never shared.
- The plugin can only access articles and issues the token has access to.
- Use Option A (system keychain) wherever possible — see `docs/SETUP.md`.
- When storing the token via `security add-generic-password` (macOS) or
  `cmdkey` (Windows), use the **interactive** form documented in `docs/SETUP.md`
  to avoid the token landing in your shell history.
- If you find a security issue, please open a private issue or email the
  maintainer — do not file it publicly until it has been triaged.

---

## Contributing

Pull requests welcome. Please:

- Keep the server a single-file `urllib`-only implementation (no extra
  runtime deps beyond `mcp` and `keyring`, both injected via `uv --with`).
- Keep all user-facing strings, comments, and docstrings in English.
- Don't add hardcoded project/article IDs in code or skill files.

---

## License

MIT — see [`LICENSE`](LICENSE).
