# cursor-skill-push-to-github

Cursor Agent Skill: commit a local project and publish it to GitHub **without** `git push`.

On some networks `git push` to `github.com:443` fails. This skill uses a logged-in GitHub CLI token, then keep-alive HTTPS to `api.github.com`. Unchanged blobs are reused by SHA. **Do not** `git push` or `gh repo create --push`.

## Install

Copy this repository to:

```text
%USERPROFILE%\.cursor\skills\push-to-github\
```

## Requirements

- Git for Windows (local commits only)
- [GitHub CLI](https://cli.github.com/) (`gh auth login`)
- Python 3

Agent shells often lack `git`/`gh` on PATH. Run:

```powershell
. "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/ensure-tools.ps1"
```

## Usage

1. Inspect remotes; `git init -b main` if needed
2. Ignore secrets; write `.gitignore` as UTF-8 via Python
3. Commit with env-var identity if `user.name` is unset (never `git config`)
4. `gh repo create <name> --private --source=. --remote=origin` (no `--push`) only when `origin` is missing
5. `python .../publish-via-gh-api.py`
6. One archive goes on a Release via `scripts/publish-release-asset.py`, not into git

## Implementation notes

- Call `gh` once for `auth token`; do not spawn `gh.exe` per blob
- Empty repo: Contents API bootstrap, then Git Data API tree + commit
- Reuse remote blob SHAs that already match `git hash-object`
- PATCH ref uses `"force": false`
- Each Release file must be under 2 GiB. A larger file is uploaded as raw `.001`, `.002`, ... byte ranges of the original. Those parts are not committed and are not zip or 7z volumes. Join them with `copy /b`.
- Release assets of at least 8 MiB use `CONNECT` through `127.0.0.1:20221` when that port is open. A direct 413209146-byte upload was about 11 minutes (~0.2-0.6 MB/s); the proxy path was about 2.6 MB/s. When that port is closed, a later direct upload of a part just under 2 GiB reached about 11 MB/s (about 2.7 GiB in two parts, about 6 minutes). Override with `PUSH_GITHUB_PROXY`

Agent flow: [SKILL.md](SKILL.md). Notes: [reference.md](reference.md).

## License

MIT
