---
name: push-to-github
description: >-
  Initialize git if needed, exclude secrets, commit, create a GitHub repo with
  gh, and publish via GitHub API on Windows. Use when the user asks to push to
  GitHub, create a GitHub repository, gh repo create, or to put one archive on
  a new private repo Release — especially when git push to github.com:443 fails.
---

# Push current project to GitHub

Cursor skill for Windows. Uses the logged-in **gh** account. Default visibility is **private**.

On some networks git to GitHub on port 443 fails, so files are written with the GitHub API.

Do not `git push`. Do not `gh repo create --push`. Publish a git tree only with [scripts/publish-via-gh-api.py](scripts/publish-via-gh-api.py). One archive on a Release goes through [scripts/publish-release-asset.py](scripts/publish-release-asset.py), which calls that publisher for the README only.

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
- The path is one file -> section 1b. Do not `git init` its parent.

Default repo name: project folder, lowercase, dashes only. If the folder is a single character or otherwise ambiguous (`1`, `new`, `tmp`), derive a name from the main artifact (e.g. exe/title) or ask once.

For a **TEMP** sanitized public copy, attach `origin` only to that TEMP git. Never rewrite remotes on the source tree.

## 1b. Release asset (one archive, not a project)

Use this when the user points at a single archive or installer and wants a new private repository with that file on a Release. Do not `git init` in the parent directory.

Use [scripts/publish-release-asset.py](scripts/publish-release-asset.py). Do not reimplement the upload by hand.

```powershell
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-release-asset.py" "<archive>"
```

Optional: `--repo <name>` when the filename has no usable ASCII slug (`tmp`, a single character, or no letters). `--tag` defaults to `v1.0.0`. `--public` only if the user explicitly asked. Default is private.

The script:

- Does not `git init` the parent directory. A shared projects folder is not the repository.
- Does not commit the archive. It writes a TEMP git that contains only a README, commits that, creates the repo with `gh repo create --private --source=. --remote=origin` (no `--push`), then publishes the README with `publish-via-gh-api.py`.
- Uploads the file with one POST to `uploads.github.com`. It does not call `gh release create` (that can try to push a tag) and does not spawn `gh.exe` per chunk.
- GitHub strips non-ASCII characters from the asset download name. The script sends an ASCII `name` (`<repo><ext>` when the original name is not ASCII) and sets `label` to the original filename.
- Refuses env files, keys, and credential-like filenames. If it stops for that reason, ask the user before uploading.
- If that repo already has this file at the same size, it prints `release already up to date` and does not create another repo. If the name belongs to some other project, it retries once with a `-pkg` suffix, then stops.
- Deletes the TEMP git after a successful upload. It never deletes the GitHub repo.

Report the repo URL, release URL, `asset name=`, `asset label=`, byte size, `blobs posted=` / `reused=`, and that the archive was excluded from git.

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

Return the HTTPS URL (`https://github.com/<login>/<name>`), private/public, what was excluded (secrets, logs), and blob posted vs reused. For a Release asset, also return the release URL, asset name, label, and size.

## Hard limits

- Never `git config`
- Never `git push` (including `gh repo create --push`)
- Never force-push `main`/`master`
- Never delete GitHub repos
- Never rewrite existing remotes
- Never skip hooks (`--no-verify`)
- Never commit secrets
- Never `git init` the parent of a single archive
- Never `gh release create`
- Never commit an archive the user asked to put on a Release
