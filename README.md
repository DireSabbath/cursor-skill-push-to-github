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

## One archive on a Release

When the input is a single archive rather than a project directory, do not `git init` in its parent. The archive stays out of git history:

```powershell
python "$env:USERPROFILE/.cursor/skills/push-to-github/scripts/publish-release-asset.py" path\to\archive.7z
```

That command publishes a README-only repository, then uploads the file as a Release asset. Non-ASCII filenames are stored as an ASCII download name, with the original filename in the asset label. Release metadata uses `api.github.com`. The file bytes are one POST to `uploads.github.com`. Do not call `gh release create`.

## Implementation notes

- Call `gh` once for `auth token`; do not spawn `gh.exe` per blob
- Empty repo: Contents API bootstrap, then Git Data API tree + commit
- Reuse remote blob SHAs that already match `git hash-object`
- PATCH ref uses `"force": false`
- Release assets are not git blobs. The download `name` is ASCII; `label` keeps the original filename

Agent flow: [SKILL.md](SKILL.md). Local notes: [reference.md](reference.md).

## License

MIT
