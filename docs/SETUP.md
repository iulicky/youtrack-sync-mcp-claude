# YouTrack Sync Plugin — Setup Guide

> **Plugin version:** 0.3.0
> Works on **macOS, Windows, and Linux**.

---

## What the plugin does

`youtrack-sync` is a Claude Code / Cowork plugin that lets you sync local Markdown
files with YouTrack Knowledge Base articles and work with YouTrack Issues — directly
from chat, without opening a browser or running scripts manually.

**Example usage:**
- *"Push feature.md to YouTrack MYPROJ-A-101"*
- *"What changed between local features_registry.md and MYPROJ-A-85?"*
- *"Change the state of MYPROJ-677 to In Progress"*
- *"Add a comment to MYPROJ-677: spec is done, starting implementation"*

---

## Prerequisites

| What | Where to get it |
|---|---|
| **Claude Code / Claude Desktop** with plugin support | [claude.ai/download](https://claude.ai/download) |
| **uv** — Python package manager | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| **YouTrack API token** | YouTrack → Profile → Authentication → Permanent tokens |
| File `youtrack-sync.plugin` | this repository |

---

## Step 1 — Install `uv`

The plugin runs via `uv` — a lightweight Python runner that requires no virtual environments.

### macOS / Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen your terminal, then verify:

```bash
uv --version
```

### Windows

Open **PowerShell** (not cmd) and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell, then verify:

```powershell
uv --version
```

---

## Step 2 — Configure credentials

The plugin needs your YouTrack instance URL and an API token. You have two options:

- **Option A** stores the token in the system keychain **(recommended)**.
- **Option B** stores it in a file on disk (simpler, but less secure).

> **Where to find your token:**
> YouTrack → click your name (top right) → **Profile** → **Authentication** tab
> → **Permanent tokens** → **New token** → copy the value starting with `perm-`

---

### Option A — System keychain (recommended)

The token is stored in **macOS Keychain**, **Windows Credential Manager**, or **Linux
Secret Service** — not in a plain-text file. `.youtrack.json` will only contain the URL.

#### macOS

**1. Create `.youtrack.json` with the URL only:**

```bash
cat > ~/.youtrack.json << 'EOF'
{
  "url": "https://youtrack.your-company.com"
}
EOF
```

**2. Store the token in macOS Keychain — interactive prompt (does not leak to history):**

```bash
security add-generic-password -s "youtrack-sync" -a "token" -w
# You will be prompted twice for the token. Paste it; it is not echoed.
```

> ⚠️ Do **not** pass the token after `-w` on the command line — it would land in your
> shell history and be visible in `ps`. The `-w` flag with no value prompts you instead.

Verify it was saved:

```bash
security find-generic-password -s "youtrack-sync" -a "token" -w
```

To update the token later, use `-U` (update flag):

```bash
security add-generic-password -U -s "youtrack-sync" -a "token" -w
```

The entry is visible in the **Keychain Access** app under the name `youtrack-sync`.

#### Windows

**1. Create `.youtrack.json` with the URL only:**

```powershell
'{"url": "https://youtrack.your-company.com"}' |
  Set-Content -Path "$env:USERPROFILE\.youtrack.json" -Encoding UTF8
```

**2. Store the token in Windows Credential Manager — read it securely from a prompt:**

```powershell
$tok = Read-Host "YouTrack token" -AsSecureString
$plain = [System.Net.NetworkCredential]::new("", $tok).Password
cmdkey /generic:youtrack-sync /user:token /pass:$plain | Out-Null
Remove-Variable plain
```

> ⚠️ Do **not** type the token directly into a `cmdkey /pass:TOKEN` command — it would
> be saved to your PowerShell history. The snippet above reads it from a hidden prompt.

Verify in **Control Panel → Credential Manager → Windows Credentials** — look for `youtrack-sync`.

To update the token, run the snippet again (it overwrites automatically).

#### Linux

Requires a Secret Service provider (GNOME Keyring, KWallet, or KeePassXC's Secret Service
integration). On a fresh server without a desktop, use Option B instead.

**1. Create `.youtrack.json` with the URL only:**

```bash
cat > ~/.youtrack.json << 'EOF'
{
  "url": "https://youtrack.your-company.com"
}
EOF
```

**2. Store the token via `keyring` (installed by `uv`):**

```bash
uv run --with keyring -- python -c "import keyring, getpass; \
keyring.set_password('youtrack-sync', 'token', getpass.getpass('YouTrack token: '))"
```

The token is prompted hidden and stored in your Secret Service keyring.

---

### Option B — `.youtrack.json` file

#### macOS / Linux

```bash
cat > ~/.youtrack.json << 'EOF'
{
  "url": "https://youtrack.your-company.com",
  "token": "YOUR_TOKEN_HERE"
}
EOF
chmod 600 ~/.youtrack.json
```

#### Windows

```powershell
$config = @{
    url   = "https://youtrack.your-company.com"
    token = "YOUR_TOKEN_HERE"
} | ConvertTo-Json

$config | Set-Content -Path "$env:USERPROFILE\.youtrack.json" -Encoding UTF8
```

> ⚠️ The token is stored as plain text — **do not** add this file to a git repository.
> The included `.gitignore` already excludes it; double-check before committing.

---

## Step 3 — Install the plugin in Claude

1. Open **Claude Code** (or Claude Desktop with plugin support).
2. Click the **plugins icon** (puzzle piece) in the left panel.
3. Click **Install plugin** or drag `youtrack-sync.plugin` into the window.
4. The plugin will appear in the list as **youtrack-sync**.
5. **Restart Claude** (Quit + reopen) — the MCP server starts on launch.

---

## Step 4 — Verify it works

Open a new chat and type:

> *List articles in project MYPROJ*

(Substitute your project's short name.) Claude should respond with a list of
Knowledge Base articles from YouTrack. If you see a configuration error, recheck Step 2.

---

## Example commands

### Knowledge Base articles

| What you want | What to tell Claude |
|---|---|
| Show diff before pushing | *"Compare feature.md with MYPROJ-A-85"* |
| Push local file to YouTrack | *"Push feature.md to YouTrack MYPROJ-A-101"* |
| Pull article to local file | *"Pull MYPROJ-A-101 into feature.md"* |
| Show article comments | *"What comments are on MYPROJ-A-85?"* |
| List articles in project | *"List articles in project MYPROJ"* |
| List articles in a section | *"List articles in section MYPROJ-A-10"* |

> **Tip:** Claude shows a diff before pushing — articles are not overwritten without
> your confirmation, and an automatic timestamped `.bak` is created on pull.

### Issues

The issue ID is in the URL: `https://youtrack.your-company.com/issue/MYPROJ-677/...` → ID is `MYPROJ-677`

| What you want | What to tell Claude |
|---|---|
| Show issue detail | *"Show issue MYPROJ-677"* |
| Create a new issue | *"Create issue in MYPROJ: Implement access request workflow"* |
| Change state | *"Change state of MYPROJ-677 to In Progress"* |
| Assign issue | *"Assign MYPROJ-677 to jane.doe"* |
| Add a comment | *"Add comment to MYPROJ-677: Spec is done, starting implementation"* |
| List available states | *"What states are available in project MYPROJ?"* |

---

## Troubleshooting

**`uv: command not found` (macOS / Linux)**
`uv` was installed but is not in PATH. Open a new terminal. If that doesn't help:
```bash
export PATH="$HOME/.local/bin:$PATH"
```
Add this line to `~/.zshrc` (macOS) or `~/.bashrc` (Linux) to make it permanent.

**`YouTrack is not configured`**
The `~/.youtrack.json` file is missing or has incorrect format, and no token is in the
keychain. Repeat Step 2.

**`HTTP 401 Unauthorized`**
The token is invalid or expired. Create a new token in YouTrack (Step 2 above).

**`urlopen error [SSL]` (Windows)**
A corporate proxy is intercepting TLS. Contact your network administrator or use a VPN.

**Plugin not appearing in Claude**
Make sure you fully restarted Claude after installing the plugin (Quit, don't just close the window).

---

## Security

- Each team member creates their own token in their YouTrack profile — tokens are never shared.
- **Option A:** the token stays in the system keychain — `.youtrack.json` contains only the URL and is safe to share among the team.
- **Option B:** `.youtrack.json` contains the token as plain text — **do not** add it to git. The file should be `chmod 600` on POSIX systems.
- The plugin only reads and writes articles/issues the token has access to.
- All YouTrack URL components are percent-encoded before requests, so article/issue IDs received from chat cannot reshape requests.
- HTTP requests have a 30-second timeout.

---

## Change Log

| Version | Change |
|---|---|
| 0.3.0 | English-only code & docs; URL-encoding for all API paths; HTTP timeout; timestamped `.bak`; Linux keyring support; removed hardcoded project defaults |
| 0.2.0 | Added Issues operations: create, update, comment, list states |
| 0.1.0 | Initial release — Knowledge Base sync |
