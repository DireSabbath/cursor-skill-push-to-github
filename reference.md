# Windows GitHub publish notes

## Tools

| Tool | Typical path | Notes |
|------|----------------|-------|
| Git | `C:/Program Files/Git/cmd/git.exe` | Local commits only. Often missing from agent PATH |
| GitHub CLI | `%LOCALAPPDATA%/portable-dev-tools/gh/bin/gh.exe` or GitHub CLI install dir | `gh auth token` only. Publish is keep-alive to api.github.com |

On some networks git to github.com:443 fails, so files are written with the GitHub API.

Before any `git`/`gh` command in a new shell:

```powershell
. "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/ensure-tools.ps1"
```

Or prepend PATH:

```powershell
$env:Path = "C:\Program Files\Git\cmd;$env:LOCALAPPDATA\portable-dev-tools\gh\bin;" + $env:Path
```

`ensure-tools.ps1` also sets `PYTHONUTF8` / `PYTHONIOENCODING=utf-8`.

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
- log directories
- key/pem/p12 files

Write `.gitignore` as UTF-8 (Python `encoding='utf-8'`). Scan before `git add`:

```powershell
git status --porcelain
git diff --cached --stat
```

## Default repo policy

- Visibility: **private** unless the user explicitly asks for public
- Remote name: `origin`
- Branch: `main`
- Do not create a second repo if `origin` already exists
- Do not change existing remotes
- Do not `git push --force` to `main`/`master`
- Do not `git push` at all
- TEMP public copies: `origin` only on the TEMP git

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

Keep-alive to `api.github.com` (do not spawn `gh.exe` per blob). Bootstraps an empty repo with Contents API, then Git Data API. Reuses remote blob SHAs that already match `git hash-object`. Never `git push`. PATCH ref uses `"force": false`.

## Release asset (one file)

Do not `git init` the parent of a single archive. Run:

```powershell
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-release-asset.py" "<archive>"
```

- TEMP README only, then `publish-via-gh-api.py`
- File bytes: one POST to `uploads.github.com` (not a git blob, not `gh release create`)
- Asset `name` is ASCII. The original filename goes in `label`, because GitHub drops non-ASCII from the download name
- Cap: 2 GiB. The git publisher still refuses blobs over 90 MB
- The same file and size again prints `release already up to date` and does not create a second repo
- A name owned by another project retries once as `<name>-pkg`, then stops
- `--public` only when the user asked. Do not upload into an existing public repo by default
