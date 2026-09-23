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

## Large uploads

`http.client` ignores `HTTP_PROXY`. A direct POST of 413209146 bytes to `uploads.github.com` took about 11 minutes (~0.2–0.6 MB/s). A local HTTP proxy on that same network transferred GitHub data at about 2.6 MB/s.

`publish-release-asset.py` uses one `CONNECT` through `127.0.0.1:20221` when that port is listening, for any file size. It does not change the system proxy and does not read the proxy controller secret. A turned-off system proxy is not used. Set `PUSH_GITHUB_PROXY=direct` to force a direct POST, or `PUSH_GITHUB_PROXY=http://127.0.0.1:<port>` for another local proxy. CONNECT failure falls back to direct. That host had no AAAA record; do not wait on IPv6. Calls to `api.github.com` stay direct.

## Append to an existing Release

```powershell
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-release-asset.py" "<file>" --onto "https://github.com/<owner>/<repo>/releases"
```

Do not create a repo and do not commit the file. Confirm the upload with `GET /repos/<owner>/<repo>/releases/<id>/assets`. Files under 8 MiB wait at most 60 seconds per attempt (three attempts). A 164642-byte direct POST failed once on connect and once on write; the next attempt finished at about 0.10 MB/s.
