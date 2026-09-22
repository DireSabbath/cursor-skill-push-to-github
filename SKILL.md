---
name: push-to-github
description: >-
  Initialize git if needed, exclude secrets, commit, create a GitHub repo with
  gh, and publish via GitHub API on Windows. Use when the user
  asks to 传到 GitHub, 上传 GitHub, 推到 GitHub, push to GitHub, create a
  GitHub repository, gh repo create, or to put one archive on a new private
  repo Release (上传到 Release). Files at or above 2 GiB are split
  into Release assets automatically.
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

Windows path details and identity env vars: [reference.md](reference.md)

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

This script is also the exclusive publish path for a **TEMP** sanitized public copy. Attach `origin` only to that TEMP git. Never rewrite remotes on the source tree.

## 1b. Release asset (one archive, not a project)

用户给的是单个压缩包或安装包，并要求新建私有仓库、把文件放到 Release 时，走这条，不要在上级目录里 git init。

Use [scripts/publish-release-asset.py](scripts/publish-release-asset.py). Do not reimplement the upload by hand.

```powershell
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-release-asset.py" "<archive>"
```

Optional: `--repo <name>` when the filename has no usable ASCII slug (`tmp`, a single character, or no letters). `--tag` defaults to `v1.0.0`. `--public` only if the user explicitly asked. Default is private.

The script:

- Does not `git init` the parent directory. A shared projects folder is not the repository.
- Does not commit the archive. It writes a TEMP git that contains only a README, commits that, creates the repo with `gh repo create --private --source=. --remote=origin` (no `--push`), then publishes the README with `publish-via-gh-api.py`.
- Uploads each part with one POST to `uploads.github.com`. It does not call `gh release create` (that can try to push a tag) and does not spawn `gh.exe` per chunk.
- A file of at least 8 MiB uses the local HTTP proxy when `127.0.0.1:20221` is listening (a Clash mixed-port). A direct POST of a 413209146-byte archive took about 11 minutes (~0.2–0.6 MB/s). Through that proxy, GitHub transfer was about 2.6 MB/s. When that port is closed, the script uploads direct and does not wait. A later direct upload of a part just under 2 GiB reached about 11 MB/s; two parts totaling about 2.7 GiB finished in about 6 minutes. `http.client` ignores `HTTP_PROXY`; the script sends `CONNECT` itself, does not change the system proxy, and does not read the proxy controller secret. `PUSH_GITHUB_PROXY=direct` forces a direct POST. `PUSH_GITHUB_PROXY=http://127.0.0.1:<port>` selects another local proxy. If CONNECT fails, it falls back to direct. Do not wait on IPv6 if `uploads.github.com` has no AAAA record. JSON calls to `api.github.com` stay direct.
- GitHub strips non-ASCII characters from the asset download name. The script sends an ASCII `name` (`<repo><ext>` when the original name is not ASCII) and sets `label` to the original filename.
- 单个 Release 文件必须小于 2 GiB。达到或超过这个大小时，脚本按原文件的字节范围自动拆成 `.001`、`.002` 再上传，不另存一份，也不把分卷提交进 git。这些分卷不是 zip 或 7z 分卷。
- Each Release file must be under 2 GiB. A file of that size or larger is split into raw byte-range assets named with `.001`, `.002`, and so on. Each part is at most 2 GiB minus 1 byte. The script reads those ranges from the original file. It does not write a second copy, and it does not commit the parts. They are not zip or 7z volumes. The README includes a `copy /b` join command. A later run uploads only missing parts. When every part is already the same size, it prints `release already up to date`.
- Upload progress is printed every 64 MiB, with a rate. A part near 2 GiB is often about 15 minutes at the proxy rate above. A silent upload used to look like a hang.
- Refuses env files, keys, and credential-like filenames. If it stops for that reason, ask the user before uploading.
- If every part is already present at the same size, it prints `release already up to date` and does not create another repo. If the name belongs to some other project, it retries once with a `-pkg` suffix, then stops.
- Deletes the TEMP git after a successful upload. It never deletes the GitHub repo.

Report the repo URL, release URL, each `asset name=`, `asset label=`, and byte size, the original filename and size, `blobs posted=` / `reused=`, and that the archive and any parts were excluded from git.

## 2. Secrets and .gitignore

Before staging, list what would be committed. Ensure `.gitignore` covers:

- dependency dirs, build output
- `.env*`, keys, credential files
- logs and credential files

If a file looks like a secret and is not ignored, **ask before including it**. Never stage-and-push blind.

Write `.gitignore` as UTF-8 via Python on Windows; some editors can corrupt non-ASCII filenames.

## 3. Commit

Never update git config. If `user.name`/`user.email` are missing, use the env-var identity in [reference.md](reference.md).

```powershell
git add -A
git status
git commit -m "<1-2 sentences, why not what>"
```

Skip empty commits. Do not commit `.env`, account ini files, or logs.

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

Return the HTTPS URL (`https://github.com/<login>/<name>`), private/public, what was excluded (secrets, logs), and blob posted vs reused. For a Release asset, also return the release URL, each asset name, label, and size, plus the original filename and size when the upload was split.

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
- Never commit an archive the user asked to put on a Release, or the split parts of that archive
