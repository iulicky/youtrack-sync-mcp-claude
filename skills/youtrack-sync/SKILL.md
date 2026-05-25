---
name: youtrack-sync
description: >
  Use this skill when the user wants to sync content between local Markdown files
  and YouTrack Knowledge Base articles, or work with YouTrack issues.
  Triggers include: "push to YouTrack", "pull from YouTrack", "sync MD to YouTrack",
  "update YouTrack article", "what changed in YouTrack", "pull YouTrack changes",
  "push feature spec", "compare with YouTrack", "create issue", "update issue",
  "add comment", "change state", "assign issue".
metadata:
  version: "0.3.0"
---

# YouTrack Sync

Work with YouTrack Knowledge Base articles and Issues using the `youtrack` MCP server tools.

## Available tools

### Knowledge Base articles

| Tool | Direction | When to use |
|---|---|---|
| `youtrack_diff` | — | Before any sync — show what changed |
| `youtrack_push_file` | Local → YouTrack | User updated MD locally, wants to publish |
| `youtrack_pull_to_file` | YouTrack → Local | User edited in YouTrack, wants local copy |
| `youtrack_get_article` | Read | Check current YouTrack content |
| `youtrack_get_comments` | Read | Read feedback on article before syncing |
| `youtrack_update_article` | Write | Update article content directly (no local file) |
| `youtrack_list_articles` | Read | Find article IDs in a project or section |

### Issues

| Tool | When to use |
|---|---|
| `youtrack_get_issue` | Read issue detail — summary, state, assignee, custom fields |
| `youtrack_create_issue` | Create a new issue in a project |
| `youtrack_update_issue` | Change state, assignee, summary or description |
| `youtrack_add_comment` | Add a comment to an issue |
| `youtrack_list_project_states` | List available states in a project |

## Workflow — Push article

When the user says "push", "upload", "update YouTrack":

1. Run `youtrack_diff(article_id, file_path)` — show the diff first.
2. Confirm with the user if the diff looks significant.
3. Run `youtrack_push_file(file_path, article_id)`.
4. Report: chars before/after, link to the article.
5. Remind: comments on the article are NOT affected.

## Workflow — Pull article

When the user says "pull", "download", "sync from YouTrack", "what changed":

1. Run `youtrack_get_comments(article_id)` — show any pending comments first.
2. Run `youtrack_diff(article_id, file_path)` — show what changed in YouTrack.
3. Confirm with the user before overwriting the local file.
4. Run `youtrack_pull_to_file(article_id, file_path)`.
5. Report: a timestamped `.bak` backup is created automatically.

## Workflow — Issues

When the user wants to work with an issue:

- **Read**: `youtrack_get_issue(issue_id)` — issue ID is in the URL, e.g. `MYPROJ-677`
- **Create**: `youtrack_create_issue(project_id, summary, ...)` — ask for summary if not given
- **Update state/assignee**: `youtrack_update_issue(issue_id, state="In Progress")`
  - If unsure about available states, run `youtrack_list_project_states(project_id)` first
- **Comment**: `youtrack_add_comment(issue_id, text)`

## Safety rules (articles)

- **Never push without showing a diff first** — the user should see what changes.
- **Never pull without showing comments first** — there may be feedback to review.
- **Comments are safe** — pushing new article content never deletes comments.
- **Always confirm before overwriting** local files (pull direction).
- The server has built-in guards: blocks pushes that shrink content by >70%, or any push <50 chars.
  Use `force=True` to override if intentional.

## Notes

- Article IDs look like `PROJECT-A-101`; issue IDs look like `PROJECT-677`.
- To discover article IDs in a project: `youtrack_list_articles("PROJECT")` or, for a section, `youtrack_list_articles("PROJECT", parent_id="PROJECT-A-10")`.
