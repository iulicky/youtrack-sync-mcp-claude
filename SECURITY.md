# Security Policy

## Reporting a vulnerability

If you discover a security issue in `youtrack-sync`, **do not** open a public
GitHub issue. Instead, email the maintainer or open a private security advisory
on GitHub.

Please include:

- A description of the issue and its impact
- Steps to reproduce
- (If applicable) a proof-of-concept

We aim to acknowledge reports within 72 hours.

## Scope

In scope:

- The MCP server (`servers/youtrack_server.py`)
- Credential handling and config-file parsing
- Any URL/path/query handling that takes input from chat

Out of scope:

- Vulnerabilities in YouTrack itself — report those to JetBrains.
- Vulnerabilities in `mcp`, `keyring`, `uv`, or the Python stdlib — report
  those upstream.

## Hardening already applied (0.3.0)

- All YouTrack URL path segments and query values are percent-encoded before
  the request is built, so user-supplied IDs cannot reshape the request.
- HTTP requests use a 30-second timeout.
- The URL from `~/.youtrack.json` is validated to be `http(s)://` before use.
- Keychain access failures are logged to stderr rather than silently falling
  back, so misconfigurations are visible.
- Setup docs use the interactive (`-w` with no value on macOS,
  `Read-Host -AsSecureString` on Windows) forms to avoid leaking tokens
  to shell history.
