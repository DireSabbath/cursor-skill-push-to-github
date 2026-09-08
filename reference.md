# Windows GitHub publish notes

## Tools

| Tool | Typical path | Notes |
|------|----------------|-------|
| Git | `C:/Program Files/Git/cmd/git.exe` | Local commits only. Often missing from agent PATH |
| GitHub CLI | `%LOCALAPPDATA%/portable-dev-tools/gh/bin/gh.exe` or GitHub CLI install dir | Exclusive publish path (`gh api`) |

On some Windows networks `git` cannot reach `github.com:443`, so files are written with the GitHub API.

Before any `git` / `gh` command in a new shell:

```powershell
. "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/ensure-tools.ps1"
```

Or prepend PATH:

```powershell
$env:Path = "C:\Program Files\Git\cmd;$env:LOCALAPPDATA\portable-dev-tools\gh\bin;" + $env:Path
```

Adjust the `gh` directory if you installed GitHub CLI normally.

## Identity without changing git config

Never run `git config`. If `user.name` / `user.email` are empty, set env vars for that commit only:

```powershell
$login = gh api user --jq .login
$env:GIT_AUTHOR_NAME = $login
$env:GIT_AUTHOR_EMAIL = "$login@users.noreply.github.com"
$env:GIT_COMMITTER_NAME = $env:GIT_AUTHOR_NAME
$env:GIT_COMMITTER_EMAIL = $env:GIT_AUTHOR_EMAIL
```

## Secret patterns to exclude

Always gitignore (do not stage):

- `.env`, `.env.*`, `credentials.json`, `*secret*`, `*token*`
- files whose names contain `密码` / `账号` / `password`
- log directories
- key / pem / p12 files

Write `.gitignore` as UTF-8 (Python `encoding='utf-8'`). Scan before `git add`:

```powershell
git status --porcelain
git diff --cached --stat
```

Unstage credential filenames by matching `密码` / `账号` / `password` via Python + `git rm --cached`.

## Default repo policy

- Visibility: **private** unless the user explicitly asks for public
- Remote name: `origin`
- Branch: `main`
- Do not create a second repo if `origin` already exists
- Do not change existing remotes
- Do not `git push --force` to `main`/`master`
- Do not `git push` at all

## Create repo (no push)

```powershell
gh repo create <name> --private --source=. --remote=origin
```

If the name is taken, suffix a short word (not a number soup) and retry once. Never pass `--push`.

## Publish (exclusive success path)

From the project root, after a local commit:

```powershell
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-via-gh-api.py"
```

The script bootstraps an empty GitHub repo with the Contents API, then writes the HEAD tree with the Git Data API. It never calls `git push`.
