---
name: push-to-github
description: >-
  Initialize git if needed, exclude secrets, commit, create a GitHub repo with
  gh, and publish via GitHub API on Windows. Use when the user asks to push to
  GitHub, create a GitHub repository, or gh repo create — especially when git
  push to github.com:443 fails.
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
- Not a git repo -> `git init -b main` in the project root.

Default repo name: project folder, lowercase, dashes only. If the folder is a single character or otherwise ambiguous (`1`, `new`, `tmp`), derive a name from the main artifact (e.g. exe/title) or ask once.

For a **TEMP** sanitized public copy, attach `origin` only to that TEMP git. Never rewrite remotes on the source tree.

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
