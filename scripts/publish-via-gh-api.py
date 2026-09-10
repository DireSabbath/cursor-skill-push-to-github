# -*- coding: utf-8 -*-
"""Publish git HEAD to origin/main using GitHub API only.

Some networks cannot git-push to github.com:443. Do not call git push.
Auth is `gh auth token` once. JSON and blob POSTs use keep-alive HTTPS to
api.github.com. Do not spawn gh.exe per blob.
"""
from __future__ import annotations

import base64
import gzip
import http.client
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

MAX_BLOB_BYTES = 90 * 1024 * 1024
GH_TIMEOUT = 180
RETRIES = 5
API_HOST = "api.github.com"
GH_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\portable-dev-tools\gh\bin\gh.exe"),
    r"C:\Program Files\GitHub CLI\gh.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\GitHub CLI\gh.exe"),
]
PATH_DIRS = [
    r"C:\Program Files\Git\cmd",
    r"C:\Program Files\Git\bin",
    os.path.expandvars(r"%LOCALAPPDATA%\portable-dev-tools\gh\bin"),
    r"C:\Program Files\GitHub CLI",
    os.path.expandvars(r"%LOCALAPPDATA%\GitHub CLI"),
]


def prepend_tool_path() -> None:
    parts = [d for d in PATH_DIRS if d and os.path.isdir(d)]
    if parts:
        os.environ["Path"] = ";".join(parts) + ";" + os.environ.get("Path", "")
    os.environ.setdefault("GH_NO_UPDATE_NOTIFIER", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass


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
    found = shutil.which("gh")
    if found:
        return found
    for p in GH_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    raise SystemExit("gh not found. Source ensure-tools.ps1 first.")


def gh_token() -> str:
    proc = subprocess.run(
        [gh_exe(), "auth", "token"],
        capture_output=True,
        timeout=30,
    )
    token = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode == 0 and token:
        return token
    return ""


class GithubApi:
    """Keep-alive HTTPS client for api.github.com."""

    def __init__(self, token: str) -> None:
        self.token = token
        self._ssl = ssl.create_default_context()
        self._conn: http.client.HTTPSConnection | None = None

    def _headers(self, *, has_body: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "push-to-github",
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept-Encoding": "gzip",
            "Connection": "keep-alive",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _drop(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
        self._conn = None

    def _get_conn(self) -> http.client.HTTPSConnection:
        if self._conn is None:
            self._conn = http.client.HTTPSConnection(API_HOST, timeout=GH_TIMEOUT, context=self._ssl)
        return self._conn

    @staticmethod
    def _read_body(resp: http.client.HTTPResponse) -> bytes:
        return resp.read()

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        allow_http: tuple[int, ...] = (),
    ) -> tuple[int, dict | list | None, str]:
        path = path if path.startswith("/") else "/" + path
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        last_err = "unknown error"
        for attempt in range(1, RETRIES + 1):
            try:
                conn = self._get_conn()
                headers = self._headers(has_body=body is not None)
                if body is not None:
                    headers["Content-Length"] = str(len(body))
                conn.request(method, path, body=body, headers=headers)
                resp = conn.getresponse()
                status = resp.status
                retry_after = resp.getheader("Retry-After")
                encoding = (resp.getheader("Content-Encoding") or "").lower()
                raw = self._read_body(resp)
                if "gzip" in encoding and raw:
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        last_err = f"gzip decompress failed for {method} {path}"
                        self._drop()
                        if attempt < RETRIES:
                            time.sleep(1.2 * attempt)
                            continue
                        raise SystemExit(last_err)
                if status in {429, 500, 502, 503, 504}:
                    self._drop()
                    wait = 1.2 * attempt
                    if retry_after:
                        try:
                            wait = max(wait, float(retry_after))
                        except ValueError:
                            pass
                    last_err = f"HTTP {status} {method} {path}"
                    if attempt < RETRIES:
                        time.sleep(wait)
                        continue
                    raise SystemExit(last_err)
                text = raw.decode("utf-8", errors="replace") if raw else ""
                parsed: dict | list | None = None
                if text.strip():
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        parsed = None
                if status in allow_http:
                    return status, parsed, text
                if status < 200 or status >= 300:
                    err = text[:400]
                    raise SystemExit(f"GitHub API failed: {method} {path} HTTP {status} {err}")
                return status, parsed, text
            except (http.client.HTTPException, OSError, ssl.SSLError, TimeoutError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                self._drop()
                if attempt < RETRIES:
                    time.sleep(1.2 * attempt)
                    continue
                raise SystemExit(f"GitHub API failed: {method} {path} {last_err}")
        raise SystemExit(f"GitHub API failed: {method} {path} {last_err}")


_CLIENT: GithubApi | None = None


def api_client() -> GithubApi:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = GithubApi(gh_token())
    return _CLIENT


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
    _http, parsed, _err = api_client().request(
        "PUT",
        f"/repos/{owner_repo}/contents/{quote(rel, safe='/')}",
        payload={
            "message": message,
            "branch": branch,
            "content": base64.b64encode(raw).decode("ascii"),
        },
    )
    sha = ((parsed or {}).get("commit") or {}).get("sha") if isinstance(parsed, dict) else None
    if not sha:
        raise SystemExit(f"contents PUT for {rel} returned no commit sha")
    print(f"bootstrap {rel} commit={sha}")
    return sha


def post_blob(owner_repo: str, rel: str, abs_path: Path) -> str:
    raw = abs_path.read_bytes()
    if len(raw) > MAX_BLOB_BYTES:
        raise SystemExit(f"{rel} is {len(raw)} bytes; too large for GitHub API.")
    _http, parsed, _err = api_client().request(
        "POST",
        f"/repos/{owner_repo}/git/blobs",
        payload={
            "content": base64.b64encode(raw).decode("ascii"),
            "encoding": "base64",
        },
    )
    sha = (parsed or {}).get("sha") if isinstance(parsed, dict) else None
    if not sha:
        raise SystemExit(f"blob POST for {rel} returned no sha")
    print(f"blob {rel} {sha} ({len(raw)} bytes)")
    return sha


def ref_sha(owner_repo: str, branch: str) -> str | None:
    http, parsed, _err = api_client().request(
        "GET",
        f"/repos/{owner_repo}/git/ref/heads/{quote(branch, safe='')}",
        allow_http=(404, 409),
    )
    if http in (404, 409) or not isinstance(parsed, dict):
        return None
    return (parsed.get("object") or {}).get("sha")


def remote_tree_entries(owner_repo: str, commit_sha: str) -> dict[str, str]:
    _http, parsed, _err = api_client().request(
        "GET",
        f"/repos/{owner_repo}/git/trees/{commit_sha}?recursive=1",
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
    prepend_tool_path()
    root = Path(run_git(["rev-parse", "--show-toplevel"]).stdout.strip())
    os.chdir(root)
    owner_repo = origin_repo()
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if not branch or branch == "HEAD":
        raise SystemExit("detached HEAD; checkout a branch first.")
    message = run_git(["log", "-1", "--format=%B"]).stdout.strip()
    files = head_files(root)
    print(f"repo={owner_repo} branch={branch} files={len(files)}")
    print("method=https api.github.com keep-alive (gh auth token once)")

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
    posted = reused = 0
    for mode, rel, abs_path in files:
        sha = wanted[rel]
        if have.get(rel) == sha:
            reused += 1
        else:
            sha = post_blob(owner_repo, rel, abs_path)
            posted += 1
        tree_items.append({"path": rel, "mode": mode, "type": "blob", "sha": sha})
    print(f"blobs posted={posted} reused={reused}")

    _http, tree, _err = api_client().request(
        "POST",
        f"/repos/{owner_repo}/git/trees",
        payload={"tree": tree_items},
    )
    if not isinstance(tree, dict) or not tree.get("sha"):
        raise SystemExit("create tree failed")
    print(f"tree {tree['sha']}")

    _http, commit, _err = api_client().request(
        "POST",
        f"/repos/{owner_repo}/git/commits",
        payload={
            "message": message,
            "tree": tree["sha"],
            "parents": [parent],
        },
    )
    if not isinstance(commit, dict) or not commit.get("sha"):
        raise SystemExit("create commit failed")
    print(f"commit {commit['sha']}")

    _http, _ref, _err = api_client().request(
        "PATCH",
        f"/repos/{owner_repo}/git/refs/heads/{quote(branch, safe='')}",
        payload={"sha": commit["sha"], "force": False},
    )
    print(f"updated refs/heads/{branch}")
    print(f"https://github.com/{owner_repo}")


if __name__ == "__main__":
    main()
