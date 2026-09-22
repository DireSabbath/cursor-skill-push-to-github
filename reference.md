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
- credential files
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

Keep-alive to `api.github.com` (do not spawn `gh.exe` per blob — same regression as spawning `gh api` per download). Bootstraps an empty repo with Contents API, then Git Data API. Reuses remote blob SHAs that already match `git hash-object`. Never `git push`. PATCH ref uses `"force": false`.

## Release asset (one file)

Do not `git init` the parent of a single archive. Run:

```powershell
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-release-asset.py" "<archive>"
```

- TEMP README only, then `publish-via-gh-api.py`
- File bytes: one POST per part to `uploads.github.com` (not a git blob, not `gh release create`)
- At least 8 MiB: `CONNECT` through `127.0.0.1:20221` when that port is listening. Direct was ~0.2–0.6 MB/s (413209146 bytes, about 11 minutes); the proxy path was about 2.6 MB/s. When that port is closed, direct upload is used. A later direct part just under 2 GiB reached about 11 MB/s (about 2.7 GiB in two parts, about 6 minutes). Override with `PUSH_GITHUB_PROXY=direct` or `PUSH_GITHUB_PROXY=http://127.0.0.1:<port>`. Do not change the system proxy. Do not read the proxy secret. Do not wait on IPv6 if `uploads.github.com` has no AAAA record. `api.github.com` stays direct.
- Asset `name` is ASCII. The original filename goes in `label`, because GitHub drops non-ASCII from the download name
- Cap: each Release file must be under 2 GiB. At or above that, the script uploads raw `.001`, `.002`, ... parts (at most 2 GiB minus 1 byte) read from the original file. It does not write a second copy and does not commit the parts. They are not zip or 7z volumes. Join with `copy /b`. Progress prints every 64 MiB. The same part sizes again print `release already up to date`. The git publisher still refuses blobs over 90 MB
- The same file and size again prints `release already up to date` and does not create a second repo
- A name owned by another project retries once as `<name>-pkg`, then stops
- `--public` only when the user asked. Do not upload into an existing public repo by default
