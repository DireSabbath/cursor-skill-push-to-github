---
name: push-to-github
description: >-
  Initialize git if needed, exclude secrets, commit, create a GitHub repo with
  gh, and publish via GitHub API on Windows. Use when the user asks to push to
  GitHub, create a GitHub repository, gh repo create, or to add one file to an
  existing GitHub Release — especially when git push to github.com:443 fails.
---

# Push current project to GitHub

Cursor skill for Windows. Uses the logged-in **gh** account. Default visibility is **private**.

On some networks git to GitHub on port 443 fails, so files are written with the GitHub API.

Do not `git push`. Do not `gh repo create --push`. Publish only with [scripts/publish-via-gh-api.py](scripts/publish-via-gh-api.py).

Same lesson as github-partial-download: `gh auth token` once, then keep-alive HTTPS to `api.github.com`. Do **not** spawn `gh.exe` per blob. Unchanged blobs are reused by SHA.

## Install

Copy this folder to:

```text
%USERPROFILE%\.cursor\skills\push-to-github\
```

## 0. Load tools (every new shell)

```powershell
. "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/ensure-tools.ps1"
```

Confirm `git` and `gh` resolve. Then:

```powershell
gh auth status
```

If not logged in, run `gh auth login` and wait for the browser step. Never ask the user to paste tokens.

`ensure-tools.ps1` sets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`.

Windows PATH notes and identity env vars: [reference.md](reference.md).

## 1. Inspect the workspace

```powershell
git rev-parse --is-inside-work-tree
git remote -v
git status --porcelain
```

- Already has `origin` -> commit (if needed) and run the publish script. Do not create another repo. Do not change remotes.
- Not a git repo, and the path is a project directory -> `git init -b main` in the project root.
- One archive for a new private repo -> [scripts/publish-release-asset.py](scripts/publish-release-asset.py). Do not `git init` its parent.
- An existing releases URL plus one file to add -> the same script with `--onto`. Do not `git init`. Do not create a repo.

Default repo name: project folder, lowercase, dashes only. If the folder is a single character or otherwise ambiguous (`1`, `new`, `tmp`), derive a name from the main artifact (e.g. exe/title) or ask once.

For a **TEMP** sanitized public copy, attach `origin` only to that TEMP git. Never rewrite remotes on the source tree.

## Append one file to an existing Release

The user gave an existing releases URL and one file already on disk (an image, an archive, or any other single file). Add it to that release. Do not create a repository.

```powershell
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-release-asset.py" "<file>" --onto "https://github.com/<owner>/<repo>/releases"
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-release-asset.py" "<file>" --onto "https://github.com/<owner>/<repo>/releases/tag/<tag>"
```

Optional `--name <ascii>` when the filename has no usable ASCII slug. `--tag` overrides a tag in the URL. No tag means the latest release. If that release does not exist, stop. Do not create a release.

- Do not `git init`. Do not commit the file. Do not `gh release create`. Do not change visibility. Do not replace other assets.
- Same download name and same byte size: `release already up to date`. Same name and a different size: stop.
- ASCII `name`, original filename in `label`. Letters and digits already in a non-ASCII filename become the slug (`20240102_3.jpg` becomes `20240102-3.jpg`). Do not use the repository name as the download name.
- Append one bullet to the release notes. Leave the existing notes and the release title in place.
- Content-Type follows jpeg, png, gif, webp, and pdf. Other files stay `application/octet-stream`.
- Confirm with `GET /repos/<owner>/<repo>/releases/<id>/assets`. The `assets` array embedded on the release object can omit a file that was just uploaded.
- A direct POST of 164642 bytes to `uploads.github.com` failed once with WinError 10060 and once with a write timeout; the next attempt finished at about 0.10 MB/s. A file under 8 MiB waits at most 60 seconds per attempt, three attempts.
- When `127.0.0.1:20221` is listening, use that proxy for every upload, including a small file. When the port is closed, upload direct. Do not use a system proxy that is turned off.

Report the repo URL, release URL, asset name, label, byte size, content type, original filename and size, `blobs posted=0 reused=0`, and that the file was not committed.

## 2. Secrets and .gitignore

Before staging, list what would be committed. Ensure `.gitignore` covers:

- dependency dirs, build output
- `.env*`, keys, credential files, logs

If a file looks like a secret and is not ignored, **ask before including it**. Never stage-and-push blind.

Write `.gitignore` as UTF-8 via Python on Windows; some editors can corrupt non-ASCII filenames.

## 3. Commit

Never update git config. If `user.name`/`user.email` are missing, use the env-var identity in [reference.md](reference.md).

```powershell
git add -A
git status
git commit -m "<1-2 sentences, why not what>"
```

Skip empty commits. Do not commit `.env`, credential files, or logs.

## 4. Create the GitHub repo (if needed) and publish

Only when there is no `origin`:

```powershell
gh repo create <name> --private --source=. --remote=origin
```

No `--push`. Public only if the user explicitly asked. If the name is taken, retry once with a short word suffix.

Then from the project root (also when `origin` already exists):

```powershell
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-via-gh-api.py"
```

The script bootstraps an empty GitHub repo with Contents API, then writes the HEAD tree with Git Data API. Unchanged files are not re-POSTed (`blobs posted=` / `reused=`). It never calls `git push`.

Do not create a second repo.

## Large uploads to uploads.github.com

`http.client` does not use `HTTP_PROXY`. On a network where a direct POST was slow, a 413209146-byte archive took about 11 minutes (~0.2–0.6 MB/s). Through a local HTTP proxy, GitHub transfer was about 2.6 MB/s.

[scripts/publish-release-asset.py](scripts/publish-release-asset.py) sends one POST to `uploads.github.com`. If `127.0.0.1:20221` is listening (a Clash mixed-port), it opens `CONNECT` to `uploads.github.com:443` and uploads through that tunnel, including files under 8 MiB. It does not change the system proxy and does not read the proxy controller secret. A turned-off system proxy is not used. `PUSH_GITHUB_PROXY=direct` forces a direct POST. `PUSH_GITHUB_PROXY=http://127.0.0.1:<port>` selects another local proxy. If CONNECT fails, it falls back to direct.

`uploads.github.com` had no AAAA record on that network. Do not wait on IPv6. JSON calls to `api.github.com` stay direct. Do not abort an upload that has already finished just to retry on the faster path.

## 5. Report

Return the HTTPS URL (`https://github.com/<login>/<name>`), private/public, what was excluded (secrets, logs), and blob posted vs reused.

## Hard limits

- Never `git config`
- Never `git push` (including `gh repo create --push`)
- Never force-push `main`/`master`
- Never delete GitHub repos
- Never rewrite existing remotes
- Never skip hooks (`--no-verify`)
- Never commit secrets
- Never `git init` the parent of a single file that belongs on a Release
- Never `gh release create`
- Never create a repo when `--onto` names an existing Release
- Never overwrite a Release asset that has a different size
- Never replace existing Release notes when appending a file
