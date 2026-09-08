---
name: push-to-github
description: >-
  Initialize git if needed, exclude secrets, commit, create a GitHub repo with
  gh, and publish via GitHub API from Windows. Use when the user asks to 传到
  GitHub, 上传 GitHub, 推到 GitHub, push to GitHub, create a GitHub
  repository, or gh repo create — especially when git push to github.com:443
  fails.
---

# Push current project to GitHub

Cursor skill for Windows. Default visibility is **private**.

On some networks `git push` / `git clone` to `github.com:443` is reset. Publish the HEAD tree through the GitHub API instead.

Do not `git push`. Do not `gh repo create --push`. Publish only with [scripts/publish-via-gh-api.py](scripts/publish-via-gh-api.py).

## Install

Copy this folder to:

```text
%USERPROFILE%\.cursor\skills\push-to-github\
```

Keep the folder name `push-to-github` so the paths below match.

## 0. Load tools (every new shell)

```powershell
. "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/ensure-tools.ps1"
```

Confirm `git` and `gh` resolve. Then:

```powershell
gh auth status
```

If not logged in, run `gh auth login` and wait for the browser step. Never ask the user to paste tokens.

Windows PATH notes and commit identity env vars: [reference.md](reference.md).

## 1. Inspect the workspace

```powershell
git rev-parse --is-inside-work-tree
git remote -v
git status --porcelain
```

- Already has `origin` -> commit (if needed) and run the publish script. Do not create another repo. Do not change remotes.
- Not a git repo -> `git init -b main` in the project root.

Default repo name: project folder, lowercase, dashes only. If the folder is a single character or otherwise ambiguous (`1`, `new`, `tmp`), derive a name from the main artifact (e.g. exe/title) or ask once.

## 2. Secrets and .gitignore

Before staging, list what would be committed. Ensure `.gitignore` covers:

- dependency dirs, build output
- `.env*`, keys, credential files
- logs
- files whose names suggest secrets (`*password*`, `*secret*`, `*token*`, or Chinese `*密码*` / `*账号*`)

If a file looks like a secret and is not ignored, **ask before including it**. Never stage-and-push blind.

On Windows, write `.gitignore` as UTF-8 via Python (`encoding='utf-8'`). Some editors corrupt Chinese filenames.

## 3. Commit

Never update git config. If `user.name` / `user.email` are missing, use the env-var identity in [reference.md](reference.md).

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

Do not create a second repo.

## 5. Report

Return the HTTPS URL (`https://github.com/<owner>/<name>` from the logged-in `gh` account), private/public, and what was excluded (secrets, logs).

## Hard limits

- Never `git config`
- Never `git push` (including `gh repo create --push`)
- Never force-push `main`/`master`
- Never delete GitHub repos
- Never rewrite existing remotes
- Never skip hooks (`--no-verify`)
- Never commit secrets
