#!/usr/bin/env python3
"""
YouTrack MCP Server — bidirectional sync between local Markdown files and
YouTrack Knowledge Base articles, plus basic Issue operations.

Configuration sources (in priority order):
  1. System keychain (macOS Keychain / Windows Credential Manager / Linux Secret
     Service) via the `keyring` library.
       - service: "youtrack-sync", username: "token"
       - URL is still read from ~/.youtrack.json (the URL is not secret).
  2. ~/.youtrack.json    { "url": "...", "token": "..." }
  3. Environment variables: YOUTRACK_URL, YOUTRACK_TOKEN
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise SystemExit(
        "Missing dependency: mcp. This server is intended to be launched by "
        "`uv run --with mcp --with keyring servers/youtrack_server.py`."
    )

_KEYRING_SERVICE = "youtrack-sync"
_KEYRING_USER = "token"
_HTTP_TIMEOUT = 30  # seconds


def _validate_url(url: str) -> str:
    """Return the URL if it has an http(s) scheme; otherwise empty string."""
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print(
            f"[youtrack-sync] Ignoring invalid YouTrack URL "
            f"(scheme must be http or https): {url!r}",
            file=sys.stderr,
        )
        return ""
    return url.rstrip("/")


def _load_config() -> tuple[str, str]:
    """
    Load configuration in priority order:
      1. Keychain (via `keyring`) — token stored securely by the OS.
      2. ~/.youtrack.json — JSON fallback (token in plaintext).
      3. Environment variables.
    """
    cfg_path = Path.home() / ".youtrack.json"

    # The URL is not secret — read it from ~/.youtrack.json or the environment.
    url = ""
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            url = _validate_url(cfg.get("url", ""))
        except Exception as e:
            print(
                f"[youtrack-sync] Could not parse {cfg_path}: {e}",
                file=sys.stderr,
            )
    if not url:
        url = _validate_url(os.getenv("YOUTRACK_URL", ""))

    # 1. Keychain (requires the `keyring` package — installed via `uv --with keyring`)
    token = ""
    try:
        import keyring  # type: ignore

        token = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER) or ""
    except ImportError:
        print(
            "[youtrack-sync] `keyring` package not available; "
            "falling back to ~/.youtrack.json / environment variables.",
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"[youtrack-sync] Keychain access failed ({e}); "
            f"falling back to ~/.youtrack.json / environment variables.",
            file=sys.stderr,
        )

    if url and token:
        return url, token

    # 2. ~/.youtrack.json (full record, including token)
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            url2 = _validate_url(cfg.get("url", ""))
            token2 = cfg.get("token", "")
            if url2 and token2:
                return url2, token2
        except Exception:
            pass

    # 3. Environment variables
    token = token or os.getenv("YOUTRACK_TOKEN", "")
    return url, token


YOUTRACK_URL, YOUTRACK_TOKEN = _load_config()

mcp = FastMCP("youtrack")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {YOUTRACK_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _encode_path(*parts: str) -> str:
    """Percent-encode each path segment so user-supplied IDs cannot reshape the URL."""
    return "/".join(urllib.parse.quote(p, safe="") for p in parts if p != "")


def _encode_query(params: dict[str, str]) -> str:
    """Build a query string from a dict, percent-encoding both keys and values."""
    # YouTrack expects unencoded `$` in `$top`, so we keep that single char safe.
    return "&".join(
        f"{urllib.parse.quote(str(k), safe='$')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in params.items()
        if v != "" and v is not None
    )


def _build_url(path: str, query: dict[str, str] | None = None) -> str:
    """
    Build a YouTrack API URL.

    `path` is split on '/' and each segment is encoded individually.
    `query` values are percent-encoded.
    """
    encoded_path = _encode_path(*path.split("/"))
    url = f"{YOUTRACK_URL}/api/{encoded_path}"
    if query:
        qs = _encode_query(query)
        if qs:
            url = f"{url}?{qs}"
    return url


def _require_config() -> None:
    if not YOUTRACK_URL or not YOUTRACK_TOKEN:
        raise RuntimeError(
            "YouTrack is not configured. Create ~/.youtrack.json with 'url' "
            "(and optionally 'token'), or store the token in the system "
            "keychain under service 'youtrack-sync', account 'token'."
        )


def _get(path: str, query: dict[str, str] | None = None) -> Any:
    _require_config()
    url = _build_url(path, query)
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read())


def _post(path: str, data: dict, query: dict[str, str] | None = None) -> dict:
    _require_config()
    url = _build_url(path, query)
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers=_headers())
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read())


def _strip_style(text: str) -> str:
    """Strip any inline <style>...</style> blocks from text."""
    return re.sub(r"<style>.*?</style>\s*", "", text, flags=re.DOTALL).strip()


def _http_err(e: urllib.error.HTTPError) -> str:
    try:
        body = e.read().decode()[:400]
    except Exception:
        body = ""
    return f"HTTP {e.code} {e.reason}\n{body}"


# ---------------------------------------------------------------------------
# Safety guards
# ---------------------------------------------------------------------------

_MIN_CONTENT_CHARS = 50          # anything shorter than this is suspicious
_SHRINK_THRESHOLD = 0.30         # new content < 30% of old → block


def _ensure_article_exists(article_id: str) -> tuple[str, str] | str:
    """
    Verify the article exists in YouTrack.

    Returns (title, idReadable) if it does, or an error message string if not.
    Works for any project / naming convention (PROJ-A-101, FOO-B-99, ...).
    """
    try:
        a = _get(f"articles/{article_id.strip()}", {"fields": "id,idReadable,title"})
        return a.get("title") or article_id, a.get("idReadable") or article_id
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return (
                f"Article '{article_id}' does not exist in YouTrack.\n"
                f"   Check the ID — it may be a typo."
            )
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


def _content_shrink_guard(
    new_content: str, old_content: str, article_id: str, force: bool
) -> str | None:
    """
    Block the push if the new content is suspiciously short or much smaller
    than the existing article. Returns an error string, or None if OK.
    """
    new_len = len(new_content.strip())
    old_len = len(old_content.strip())

    if new_len < _MIN_CONTENT_CHARS:
        if force:
            return None
        return (
            f"Content is too short ({new_len} chars) — push blocked.\n"
            f"   You may be uploading the wrong file or empty content.\n"
            f"   If you are sure, call again with force=True."
        )

    if old_len > 0:
        ratio = new_len / old_len
        if ratio < _SHRINK_THRESHOLD:
            if force:
                return None
            return (
                f"New content is only {ratio:.0%} of the existing article "
                f"({new_len} vs {old_len} chars) — push blocked.\n"
                f"   This would delete most of {article_id}.\n"
                f"   Check the source file. If intentional, call with force=True."
            )
    return None


# ---------------------------------------------------------------------------
# Knowledge Base articles
# ---------------------------------------------------------------------------


@mcp.tool()
def youtrack_get_article(article_id: str) -> str:
    """
    Fetch the content and metadata of a YouTrack Knowledge Base article.

    Args:
        article_id: Article ID, e.g. MYPROJ-A-101
    """
    try:
        a = _get(
            f"articles/{article_id}",
            {"fields": "id,title,content,summary,updated"},
        )
        content = a.get("content") or ""
        return (
            f"Title   : {a.get('title', '')}\n"
            f"ID      : {article_id}\n"
            f"Updated : {a.get('updated', '')}\n"
            f"Length  : {len(content)} chars\n"
            f"\n---\n{content}"
        )
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_update_article(
    article_id: str, content: str, force: bool = False, dry_run: bool = False
) -> str:
    """
    Update the content of a YouTrack article. Comments are left untouched.

    Safety guards (bypassable with force=True):
      - Article must exist (force does not bypass this)
      - Content shorter than 50 chars → blocked
      - New content < 30% of existing length → blocked

    Args:
        article_id: Article ID, e.g. MYPROJ-A-101
        content:    New Markdown content
        force:      Bypass content-size guards (does not bypass existence check)
        dry_run:    Only report what would happen; do not write
    """
    check = _ensure_article_exists(article_id)
    if isinstance(check, str):
        return check
    title, readable_id = check

    try:
        current = _get(f"articles/{article_id}", {"fields": "id,content"})
        old_content = current.get("content") or ""
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"

    err = _content_shrink_guard(content, old_content, article_id, force)
    if err:
        return err

    if dry_run:
        return (
            f"DRY RUN — nothing was written.\n"
            f"   Article : {title} ({readable_id})\n"
            f"   Change  : {len(old_content)} → {len(content.strip())} chars"
        )

    try:
        result = _post(
            f"articles/{article_id}",
            {"content": content},
            {"fields": "id,title,content"},
        )
        new_len = len(result.get("content") or "")
        return f"{readable_id} updated. New length: {new_len} chars."
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_list_articles(project_id: str = "", parent_id: str = "") -> str:
    """
    List articles in a project's Knowledge Base.
    If parent_id is given, list only the direct child articles of that section.

    Args:
        project_id: YouTrack project short name, e.g. MYPROJ
        parent_id:  Optional parent article ID (a section), e.g. MYPROJ-A-10.
                    When set, returns only direct children of that section.
    """
    if not project_id and not parent_id:
        return "Provide either project_id or parent_id."

    fields = "id,idReadable,summary,title,updated"
    try:
        if parent_id:
            articles = _get(
                f"articles/{parent_id}/childArticles",
                {"fields": fields, "$top": "100"},
            )
            header = f"Child articles of section {parent_id}:\n"
        else:
            articles = _get(
                "articles",
                {"fields": fields, "query": f"project:{project_id}", "$top": "100"},
            )
            header = f"Articles in project {project_id}:\n"

        if not articles:
            return "No articles found."

        lines = [header]
        for a in articles:
            article_id = a.get("idReadable") or a.get("id", "?")
            # YouTrack uses 'summary' for the article title in some versions.
            title = a.get("summary") or a.get("title") or "(no title)"
            lines.append(f"  {article_id:20s}  {title}")
        return "\n".join(lines)
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_get_comments(article_id: str) -> str:
    """
    Fetch all comments on a YouTrack article.

    Args:
        article_id: Article ID, e.g. MYPROJ-A-101
    """
    try:
        comments = _get(
            f"articles/{article_id}/comments",
            {"fields": "id,text,author(login,fullName),created,updated"},
        )
        if not comments:
            return f"No comments on article {article_id}."
        lines = [f"Comments on {article_id}:\n"]
        for c in comments:
            author = c.get("author", {})
            name = author.get("fullName") or author.get("login", "unknown")
            lines.append(f"── {name}  [{c.get('created', '')}] ──")
            lines.append(c.get("text", ""))
            lines.append("")
        return "\n".join(lines)
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_push_file(
    file_path: str, article_id: str, force: bool = False, dry_run: bool = False
) -> str:
    """
    Read a local Markdown file and upload its content to a YouTrack article.
    Comments on the article are left untouched.

    Safety guards (bypassable with force=True):
      - Article must exist (force does not bypass this)
      - File must exist (force does not bypass this)
      - Content shorter than 50 chars → blocked
      - New content < 30% of existing length → blocked

    Args:
        file_path:  Absolute path to a local .md file
        article_id: Target article ID, e.g. MYPROJ-A-101
        force:      Bypass content-size guards (not the existence checks)
        dry_run:    Only report what would happen; do not write
    """
    check = _ensure_article_exists(article_id)
    if isinstance(check, str):
        return check
    title, readable_id = check

    path = Path(file_path).expanduser()
    if not path.exists():
        return f"File not found: {file_path}"

    content = _strip_style(path.read_text(encoding="utf-8"))

    try:
        current = _get(f"articles/{article_id}", {"fields": "id,content"})
        old_content = current.get("content") or ""
        old_len = len(old_content)
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"

    err = _content_shrink_guard(content, old_content, article_id, force)
    if err:
        return err

    if dry_run:
        diff = len(content.strip()) - old_len
        sign = "+" if diff >= 0 else ""
        return (
            f"DRY RUN — nothing was written.\n"
            f"   File    : {path.name}\n"
            f"   Article : {title} ({readable_id})\n"
            f"   Change  : {old_len} → {len(content.strip())} chars ({sign}{diff})"
        )

    try:
        result = _post(
            f"articles/{article_id}",
            {"content": content},
            {"fields": "id,content"},
        )
        new_len = len(result.get("content") or "")
        diff = new_len - old_len
        sign = "+" if diff >= 0 else ""
        return (
            f"{path.name} → {title} ({readable_id})\n"
            f"   {old_len} → {new_len} chars ({sign}{diff})\n"
            f"   Comments preserved\n"
            f"{YOUTRACK_URL}/articles/{readable_id}"
        )
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_pull_to_file(article_id: str, file_path: str) -> str:
    """
    Download a YouTrack article's content and save it to a local Markdown file.
    Any existing file is backed up to a timestamped .bak before being overwritten.

    Args:
        article_id: Source article ID, e.g. MYPROJ-A-101
        file_path:  Absolute path to the target .md file
    """
    check = _ensure_article_exists(article_id)
    if isinstance(check, str):
        return check

    try:
        a = _get(
            f"articles/{article_id}",
            {"fields": "id,title,content,updated"},
        )
        content = a.get("content") or ""
        title = a.get("title", article_id)

        if not content.strip():
            return f"Article {article_id} is empty. Local file not modified."

        path = Path(file_path).expanduser()
        backup_note = ""
        if path.exists():
            # Timestamped backup so we never silently overwrite a previous .bak.
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            bak = path.with_suffix(path.suffix + f".{ts}.bak")
            bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            backup_note = f"\n   Backup: {bak.name}"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        return (
            f"{title} ({article_id}) → {path.name}\n"
            f"   {len(content)} chars written{backup_note}"
        )
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_diff(article_id: str, file_path: str) -> str:
    """
    Compare a local Markdown file with the content of a YouTrack article.

    Args:
        article_id: Article ID, e.g. MYPROJ-A-101
        file_path:  Absolute path to the local .md file
    """
    check = _ensure_article_exists(article_id)
    if isinstance(check, str):
        return check

    path = Path(file_path).expanduser()
    if not path.exists():
        return f"Local file not found: {file_path}"

    local = _strip_style(path.read_text(encoding="utf-8"))

    try:
        a = _get(
            f"articles/{article_id}",
            {"fields": "id,title,content,updated"},
        )
        # Apply the same normalization to both sides so diffs aren't spurious.
        remote = _strip_style(a.get("content") or "")
        title = a.get("title", article_id)
        updated = a.get("updated", "")
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"

    if local == remote:
        return (
            f"No differences — {path.name} and YouTrack article "
            f"'{title}' are identical."
        )

    diff_lines = list(
        difflib.unified_diff(
            remote.splitlines(keepends=True),
            local.splitlines(keepends=True),
            fromfile=f"YouTrack: {title} (updated {updated})",
            tofile=f"Local: {path.name}",
            n=2,
        )
    )

    added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

    preview = "".join(diff_lines[:80])
    note = "\n[... output truncated]" if len(diff_lines) > 80 else ""

    return (
        f"Diff: {path.name} vs '{title}'\n"
        f"Local: +{added} lines added, -{removed} lines removed\n\n"
        f"{preview}{note}"
    )


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


def _resolve_project_id(project_short_name: str) -> str | None:
    """Return the internal project ID for the given short name (e.g. MYPROJ → 0-0)."""
    try:
        projects = _get(
            "admin/projects",
            {"fields": "id,shortName", "query": f"shortName:{project_short_name}"},
        )
        for p in projects:
            if p.get("shortName", "").upper() == project_short_name.upper():
                return p["id"]
    except Exception:
        pass
    return None


def _format_custom_fields(issue: dict) -> str:
    """Render an issue's custom fields as a readable block."""
    lines = []
    for cf in issue.get("customFields", []):
        name = cf.get("name", "")
        val = cf.get("value")
        if val is None:
            continue
        if isinstance(val, dict):
            display = (
                val.get("name")
                or val.get("login")
                or val.get("fullName")
                or str(val)
            )
        elif isinstance(val, list):
            display = ", ".join(
                v.get("name") or v.get("login") or str(v) for v in val if v
            )
        else:
            display = str(val)
        if display:
            lines.append(f"   {name}: {display}")
    return "\n".join(lines)


@mcp.tool()
def youtrack_get_issue(issue_id: str) -> str:
    """
    Fetch details of a YouTrack issue — summary, description, state,
    assignee, and custom fields.

    Args:
        issue_id: Issue ID, e.g. MYPROJ-677
    """
    try:
        fields = (
            "id,idReadable,summary,description,created,updated,"
            "reporter(login,fullName),"
            "customFields(name,$type,value(name,login,fullName,isResolved))"
        )
        issue = _get(f"issues/{issue_id}", {"fields": fields})
        reporter = issue.get("reporter") or {}
        reporter_name = reporter.get("fullName") or reporter.get("login", "—")
        cf_text = _format_custom_fields(issue)
        out = [
            f"Issue   : {issue.get('idReadable', issue_id)}",
            f"Summary : {issue.get('summary', '—')}",
            f"Reporter: {reporter_name}",
        ]
        if cf_text:
            out += ["", "Custom fields:", cf_text]
        desc = (issue.get("description") or "").strip()
        if desc:
            out += ["", "--- Description ---", desc[:2000]]
            if len(desc) > 2000:
                out.append("[... truncated]")
        return "\n".join(out)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"Issue '{issue_id}' does not exist."
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_create_issue(
    project_id: str,
    summary: str,
    description: str = "",
    state: str = "",
    assignee_login: str = "",
) -> str:
    """
    Create a new issue in a YouTrack project.

    Args:
        project_id:      Project short name, e.g. MYPROJ
        summary:         Issue title (required)
        description:     Issue description (Markdown, optional)
        state:           Initial state, e.g. 'Open' (optional)
        assignee_login:  Assignee login, e.g. 'jane.doe' (optional)
    """
    if not summary.strip():
        return "Summary (title) is required."

    proj_id = _resolve_project_id(project_id)
    if not proj_id:
        return (
            f"Project '{project_id}' not found.\n"
            f"   Check the project short name (e.g. MYPROJ)."
        )

    payload: dict = {
        "project": {"id": proj_id},
        "summary": summary.strip(),
    }
    if description:
        payload["description"] = description

    custom_fields = []
    if state:
        custom_fields.append(
            {
                "$type": "StateIssueCustomField",
                "name": "State",
                "value": {"$type": "StateBundleElement", "name": state},
            }
        )
    if assignee_login:
        custom_fields.append(
            {
                "$type": "SingleUserIssueCustomField",
                "name": "Assignee",
                "value": {"$type": "User", "login": assignee_login},
            }
        )
    if custom_fields:
        payload["customFields"] = custom_fields

    try:
        result = _post("issues", payload, {"fields": "id,idReadable,summary"})
        readable = result.get("idReadable", "?")
        return (
            f"Issue created: {readable}\n"
            f"   {result.get('summary', '')}\n"
            f"{YOUTRACK_URL}/issue/{readable}"
        )
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_update_issue(
    issue_id: str,
    summary: str = "",
    description: str = "",
    state: str = "",
    assignee_login: str = "",
) -> str:
    """
    Update an existing YouTrack issue. Pass only the fields you want to change.

    Args:
        issue_id:        Issue ID, e.g. MYPROJ-677
        summary:         New title (optional)
        description:     New description (optional)
        state:           New state, e.g. 'In Progress' (optional)
        assignee_login:  Assignee login, e.g. 'jane.doe' (optional)
    """
    payload: dict = {}
    if summary:
        payload["summary"] = summary.strip()
    if description:
        payload["description"] = description

    custom_fields = []
    if state:
        custom_fields.append(
            {
                "$type": "StateIssueCustomField",
                "name": "State",
                "value": {"$type": "StateBundleElement", "name": state},
            }
        )
    if assignee_login:
        custom_fields.append(
            {
                "$type": "SingleUserIssueCustomField",
                "name": "Assignee",
                "value": {"$type": "User", "login": assignee_login},
            }
        )
    if custom_fields:
        payload["customFields"] = custom_fields

    if not payload:
        return "No fields provided to update."

    try:
        result = _post(
            f"issues/{issue_id}",
            payload,
            {"fields": "id,idReadable,summary"},
        )
        readable = result.get("idReadable", issue_id)
        return (
            f"Issue {readable} updated.\n"
            f"{YOUTRACK_URL}/issue/{readable}"
        )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"Issue '{issue_id}' does not exist."
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_add_comment(issue_id: str, text: str) -> str:
    """
    Add a comment to a YouTrack issue.

    Args:
        issue_id: Issue ID, e.g. MYPROJ-677
        text:     Comment text (Markdown)
    """
    if not text.strip():
        return "Comment text must not be empty."

    try:
        result = _post(
            f"issues/{issue_id}/comments",
            {"text": text},
            {"fields": "id,text,author(login)"},
        )
        author = (result.get("author") or {}).get("login", "?")
        return (
            f"Comment added to {issue_id} (author: {author})\n"
            f"{YOUTRACK_URL}/issue/{issue_id}"
        )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"Issue '{issue_id}' does not exist."
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


@mcp.tool()
def youtrack_list_project_states(project_id: str) -> str:
    """
    List the states (State values) currently in use in a project.
    States are derived from existing issues, so unused states are not shown.

    Args:
        project_id: Project short name, e.g. MYPROJ
    """
    if not project_id:
        return "project_id is required."

    try:
        issues = _get(
            "issues",
            {
                "fields": "customFields(name,value(name,isResolved))",
                "query": f"project:{project_id}",
                "$top": "100",
            },
        )
        states: dict[str, bool] = {}
        for issue in issues:
            for cf in issue.get("customFields", []):
                if cf.get("name") == "State":
                    val = cf.get("value") or {}
                    name = val.get("name", "")
                    resolved = val.get("isResolved", False)
                    if name:
                        states[name] = resolved

        if not states:
            return (
                f"No states found for project {project_id}.\n"
                f"The project may be empty or the short name may be wrong."
            )

        lines = [f"States in project {project_id}:\n"]
        for name, resolved in sorted(states.items(), key=lambda x: (x[1], x[0])):
            tag = "  [resolved]" if resolved else ""
            lines.append(f"  {name}{tag}")
        lines.append(
            "\nNote: Only states present in existing issues are shown."
        )
        return "\n".join(lines)
    except urllib.error.HTTPError as e:
        return _http_err(e)
    except RuntimeError as e:
        return f"{e}"


if __name__ == "__main__":
    mcp.run()
