# -*- coding: utf-8 -*-
"""Publish git HEAD to origin/main using GitHub API only.

Some networks cannot git-push to github.com:443. Do not call git push.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

MAX_BLOB_BYTES = 90 * 1024 * 1024


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def gh_exe() -> str:
    env = os.environ.get("GH")
    if env:
        return env
    from shutil import which

    found = which("gh")
    if not found:
        raise SystemExit("gh not found. Source ensure-tools.ps1 first.")
    return found


def gh_api(
    method: str,
    path: str,
    payload: dict | None = None,
    input_file: Path | None = None,
    allow_http: tuple[int, ...] = (),
) -> tuple[int, dict | list | None, str]:
    cmd = [gh_exe(), "api", "--method", method, path]
    if input_file is not None:
        cmd += ["--input", str(input_file)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    elif payload is not None:
        cmd += ["--input", "-"]
        result = subprocess.run(
            cmd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    else:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

    body = result.stdout.strip()
    parsed: dict | list | None = None
    if body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None

    err = result.stderr.strip()
    http = 0
    match = re.search(r"HTTP\s+(\d+)", err)
    if match:
        http = int(match.group(1))
    if result.returncode != 0:
        if http in allow_http:
            return http, parsed, err
        sys.stderr.write(err + "\n")
        raise SystemExit(f"gh api failed: {method} {path}")
    return http or 200, parsed, err


def origin_repo() -> str:
    url = run_git(["remote", "get-url", "origin"]).stdout.strip()
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if "github.com" not in url.lower():
        raise SystemExit(f"origin is not GitHub: {url}")
    normalized = url.replace(":", "/").replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    owner, name = parts[-2], parts[-1]
    return f"{owner}/{name}"


def head_files(root: Path) -> list[tuple[str, str, Path]]:
    """Return (mode, repo_path, abs_path) for tracked files at HEAD."""
    out = run_git(["ls-tree", "-r", "-z", "HEAD"]).stdout
    files: list[tuple[str, str, Path]] = []
    for entry in out.split("\0"):
        if not entry:
            continue
        meta, rel = entry.split("\t", 1)
        mode, _typ, _sha = meta.split(" ", 2)
        if _typ != "blob":
            continue
        files.append((mode, rel.replace("\\", "/"), root / rel))
    if not files:
        raise SystemExit("HEAD has no files to publish.")
    return files


def put_contents(owner_repo: str, rel: str, abs_path: Path, message: str, branch: str) -> str:
    raw = abs_path.read_bytes()
    if len(raw) > MAX_BLOB_BYTES:
        raise SystemExit(f"{rel} is {len(raw)} bytes; too large for GitHub API.")
    tmp = Path(tempfile.mkdtemp(prefix="gh-contents-")) / "payload.json"
    tmp.write_text(
        json.dumps(
            {
                "message": message,
                "branch": branch,
                "content": base64.b64encode(raw).decode("ascii"),
            }
        ),
        encoding="utf-8",
    )
    try:
        _http, parsed, _err = gh_api(
            "PUT",
            f"repos/{owner_repo}/contents/{quote(rel, safe='/')}",
            input_file=tmp,
        )
    finally:
        tmp.unlink(missing_ok=True)
        try:
            tmp.parent.rmdir()
        except OSError:
            pass
    sha = ((parsed or {}).get("commit") or {}).get("sha") if isinstance(parsed, dict) else None
    if not sha:
        raise SystemExit(f"contents PUT for {rel} returned no commit sha")
    print(f"bootstrap {rel} commit={sha}")
    return sha


def post_blob(owner_repo: str, rel: str, abs_path: Path) -> str:
    raw = abs_path.read_bytes()
    if len(raw) > MAX_BLOB_BYTES:
        raise SystemExit(f"{rel} is {len(raw)} bytes; too large for GitHub API.")
    tmp = Path(tempfile.mkdtemp(prefix="gh-blob-")) / "payload.json"
    tmp.write_text(
        json.dumps(
            {
                "content": base64.b64encode(raw).decode("ascii"),
                "encoding": "base64",
            }
        ),
        encoding="utf-8",
    )
    try:
        _http, parsed, _err = gh_api(
            "POST",
            f"repos/{owner_repo}/git/blobs",
            input_file=tmp,
        )
    finally:
        tmp.unlink(missing_ok=True)
        try:
            tmp.parent.rmdir()
        except OSError:
            pass
    sha = (parsed or {}).get("sha") if isinstance(parsed, dict) else None
    if not sha:
        raise SystemExit(f"blob POST for {rel} returned no sha")
    print(f"blob {rel} {sha} ({len(raw)} bytes)")
    return sha


def ref_sha(owner_repo: str, branch: str) -> str | None:
    http, parsed, _err = gh_api(
        "GET",
        f"repos/{owner_repo}/git/ref/heads/{branch}",
        allow_http=(404, 409),
    )
    if http in (404, 409) or not isinstance(parsed, dict):
        return None
    return (parsed.get("object") or {}).get("sha")


def remote_tree_entries(owner_repo: str, commit_sha: str) -> dict[str, str]:
    _http, parsed, _err = gh_api(
        "GET",
        f"repos/{owner_repo}/git/trees/{commit_sha}?recursive=1",
    )
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, str] = {}
    for item in parsed.get("tree") or []:
        if item.get("type") == "blob":
            out[item["path"]] = item["sha"]
    return out


def local_blob_sha(abs_path: Path) -> str:
    return run_git(["hash-object", "--", str(abs_path)]).stdout.strip()


def main() -> None:
    root = Path(run_git(["rev-parse", "--show-toplevel"]).stdout.strip())
    os.chdir(root)
    owner_repo = origin_repo()
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if not branch or branch == "HEAD":
        raise SystemExit("detached HEAD; checkout a branch first.")
    message = run_git(["log", "-1", "--format=%B"]).stdout.strip()
    files = head_files(root)
    print(f"repo={owner_repo} branch={branch} files={len(files)}")

    parent = ref_sha(owner_repo, branch)
    if parent is None:
        bootstrap_rel = min(files, key=lambda item: item[2].stat().st_size)[1]
        bootstrap_abs = root / bootstrap_rel
        parent = put_contents(owner_repo, bootstrap_rel, bootstrap_abs, message, branch)

    wanted = {rel: local_blob_sha(abs_path) for _mode, rel, abs_path in files}
    have = remote_tree_entries(owner_repo, parent)
    if have == wanted:
        print("already up to date")
        print(f"https://github.com/{owner_repo}")
        return

    tree_items = []
    for mode, rel, abs_path in files:
        sha = post_blob(owner_repo, rel, abs_path)
        tree_items.append({"path": rel, "mode": mode, "type": "blob", "sha": sha})

    _http, tree, _err = gh_api(
        "POST",
        f"repos/{owner_repo}/git/trees",
        payload={"tree": tree_items},
    )
    if not isinstance(tree, dict) or not tree.get("sha"):
        raise SystemExit("create tree failed")
    print(f"tree {tree['sha']}")

    _http, commit, _err = gh_api(
        "POST",
        f"repos/{owner_repo}/git/commits",
        payload={
            "message": message,
            "tree": tree["sha"],
            "parents": [parent],
        },
    )
    if not isinstance(commit, dict) or not commit.get("sha"):
        raise SystemExit("create commit failed")
    print(f"commit {commit['sha']}")

    _http, _ref, _err = gh_api(
        "PATCH",
        f"repos/{owner_repo}/git/refs/heads/{branch}",
        payload={"sha": commit["sha"], "force": False},
    )
    print(f"updated refs/heads/{branch}")
    print(f"https://github.com/{owner_repo}")


if __name__ == "__main__":
    main()
