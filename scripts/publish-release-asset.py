# -*- coding: utf-8 -*-
"""Put one archive on a new private GitHub Release.

The archive's parent is never git-init'd. The git tree is a TEMP README
published by publish-via-gh-api.py. Each part is one POST to
uploads.github.com. A file that is not under 2 GiB is sent as raw
byte-range parts of the original file. Do not git push. Do not gh release create.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import importlib.util
import json
import os
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

# GitHub: each Release file must be under 2 GiB. 2 GiB itself is rejected.
MAX_RELEASE_BYTES = 2 * 1024 * 1024 * 1024
PART_LIMIT = MAX_RELEASE_BYTES - 1
PROXY_MIN_BYTES = 8 * 1024 * 1024
UPLOAD_BLOCK = 1024 * 1024
PROGRESS_BYTES = 64 * 1024 * 1024
UPLOAD_HOST = "uploads.github.com"
DEFAULT_PROXY = "127.0.0.1:20221"
MARKER = "<!-- push-to-github-release-asset -->"
SAFE_ASSET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
SAFE_REPO = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SAFE_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
AMBIGUOUS_REPOS = {"1", "new", "tmp"}
DOUBLE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz")
CREDENTIAL_NAME = "\u8d26\u53f7\u5bc6\u7801"
PASSWORD_NAME = "\u5bc6\u7801"


def load_publisher():
    path = Path(__file__).with_name("publish-via-gh-api.py")
    spec = importlib.util.spec_from_file_location("publish_via_gh_api", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repo_slug_from_stem(stem: str) -> str | None:
    parts = re.findall(r"[A-Za-z0-9]+", stem)
    slug = "-".join(part.lower() for part in parts)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if len(slug) < 2 or len(slug) > 80 or slug in AMBIGUOUS_REPOS:
        return None
    return slug


def split_suffix(filename: str) -> str:
    lower = filename.lower()
    for ext in DOUBLE_SUFFIXES:
        if lower.endswith(ext):
            return ext
    suffix = Path(filename).suffix
    if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix or ""):
        return suffix.lower()
    return ".bin"


def asset_names(original_name: str, repo: str) -> tuple[str, str]:
    """Return (ascii download name, original label).

    GitHub drops non-ASCII characters from an asset name. Send an explicit
    ASCII name and keep the original filename in label.
    """
    label = original_name
    if original_name.isascii() and SAFE_ASSET.fullmatch(original_name):
        return original_name, label
    name = f"{repo}{split_suffix(original_name)}"
    if not SAFE_ASSET.fullmatch(name):
        name = f"release-asset{split_suffix(original_name)}"
    return name, label


class AssetPart:
    def __init__(
        self,
        index: int,
        count: int,
        start: int,
        size: int,
        download: str,
        label: str,
    ) -> None:
        self.index = index
        self.count = count
        self.start = start
        self.size = size
        self.download = download
        self.label = label
        self.sha256 = ""


def part_asset_names(original_name: str, repo: str, index: int) -> tuple[str, str]:
    """ASCII download name plus a label that still names the original file."""
    suffix = f".{index:03d}"
    label = f"{original_name}{suffix}"
    candidates: list[str] = []
    if original_name.isascii():
        candidates.append(original_name + suffix)
    candidates.append(f"{repo}{split_suffix(original_name)}{suffix}")
    candidates.append(f"{repo}.part{index:03d}")
    for name in candidates:
        if SAFE_ASSET.fullmatch(name):
            return name, label
    return f"release-asset.part{index:03d}", label


def plan_parts(original_name: str, total: int, repo: str) -> list[AssetPart]:
    """One asset when the file is under 2 GiB, otherwise raw byte-range parts.

    Parts are not zip or 7z volumes. Each one is at most 2 GiB - 1 byte.
    """
    if total <= 0:
        raise SystemExit("archive is empty")
    if total < MAX_RELEASE_BYTES:
        download, label = asset_names(original_name, repo)
        return [AssetPart(1, 1, 0, total, download, label)]
    count = (total + PART_LIMIT - 1) // PART_LIMIT
    if count > 1000:
        raise SystemExit(f"{count} parts exceeds the 1000-asset Release limit")
    parts: list[AssetPart] = []
    offset = 0
    for index in range(1, count + 1):
        size = min(PART_LIMIT, total - offset)
        download, label = part_asset_names(original_name, repo, index)
        parts.append(AssetPart(index, count, offset, size, download, label))
        offset += size
    if offset != total:
        raise SystemExit("split plan does not cover the archive")
    names = [part.download for part in parts]
    if len(names) != len(set(names)):
        raise SystemExit("split asset names are not unique")
    return parts


def fill_sha256(archive: Path, parts: list[AssetPart]) -> None:
    print("hashing archive for part checksums", flush=True)
    for part in parts:
        sha = hashlib.sha256()
        sent = 0
        next_mark = PROGRESS_BYTES
        started = time.time()
        with archive.open("rb") as handle:
            handle.seek(part.start)
            left = part.size
            while left:
                buf = handle.read(min(UPLOAD_BLOCK, left))
                if not buf:
                    raise SystemExit(f"short read hashing {part.download}")
                sha.update(buf)
                left -= len(buf)
                sent += len(buf)
                if sent >= next_mark or left == 0:
                    elapsed = time.time() - started
                    rate = sent / elapsed / 1_000_000 if elapsed else 0
                    print(
                        f"hash {part.download} {sent}/{part.size} {rate:.1f} MB/s",
                        flush=True,
                    )
                    while next_mark <= sent:
                        next_mark += PROGRESS_BYTES
        part.sha256 = sha.hexdigest()
        print(f"sha256 {part.download} {part.sha256}", flush=True)


class SliceReader:
    """Read one byte range from the original archive. No second copy is written."""

    def __init__(self, path: Path, start: int, length: int, label: str) -> None:
        self._fh = path.open("rb")
        self._fh.seek(start)
        self._left = length
        self._sent = 0
        self._length = length
        self._label = label
        self._next = PROGRESS_BYTES
        self._started = time.time()
        self.sha256 = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        if self._left <= 0:
            return b""
        if size is None or size < 0 or size > self._left:
            size = self._left
        data = self._fh.read(size)
        if not data:
            return b""
        self._left -= len(data)
        self._sent += len(data)
        self.sha256.update(data)
        if self._sent >= self._next or self._left == 0:
            elapsed = time.time() - self._started
            rate = self._sent / elapsed / 1_000_000 if elapsed else 0
            print(
                f"upload {self._label} {self._sent}/{self._length} {rate:.2f} MB/s",
                flush=True,
            )
            while self._next <= self._sent:
                self._next += PROGRESS_BYTES
        return data

    def close(self) -> None:
        self._fh.close()


def looks_secret(path: Path) -> str | None:
    name = path.name
    lower = name.lower()
    if lower == ".env" or lower.startswith(".env."):
        return "env file"
    if lower in {"credentials.json", "id_rsa", "id_dsa"} or lower.endswith(
        (".pem", ".p12", ".pfx", ".key")
    ):
        return "credential file"
    if re.search(r"(secret|token|password)", lower):
        return "credential filename"
    if CREDENTIAL_NAME in name or PASSWORD_NAME in name:
        return "credential filename"
    return None


def self_check() -> None:
    assert repo_slug_from_stem("SMTNetwork") == "smtnetwork"
    assert repo_slug_from_stem("SMT\u5feb\u901fNetwork") == "smt-network"
    assert repo_slug_from_stem("tmp") is None
    assert repo_slug_from_stem("1") is None
    assert repo_slug_from_stem("a") is None
    assert split_suffix("pkg.tar.gz") == ".tar.gz"
    name, label = asset_names("Setup-1.2.exe", "setup-1-2")
    assert (name, label) == ("Setup-1.2.exe", "Setup-1.2.exe")
    original = "\u53d1\u5e03\u5305Network.7z"
    name, label = asset_names(original, "network")
    assert name == "network.7z" and label == original
    assert looks_secret(Path("notes.txt")) is None
    assert looks_secret(Path(".env")) == "env file"
    assert looks_secret(Path("id_rsa.pem")) == "credential file"
    assert looks_secret(Path(CREDENTIAL_NAME + ".txt")) == "credential filename"
    assert parse_proxy("direct") is None
    assert parse_proxy("off") is None
    assert parse_proxy("http://127.0.0.1:20221") == ("127.0.0.1", 20221)
    assert want_proxy(100, "direct", True) is None
    assert want_proxy(100, None, True) is None
    assert want_proxy(PROXY_MIN_BYTES, None, False) is None
    assert want_proxy(PROXY_MIN_BYTES, None, True) == ("127.0.0.1", 20221)
    assert want_proxy(100, "http://127.0.0.1:9", False) == ("127.0.0.1", 9)
    assert connect_established(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    assert not connect_established(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
    one = plan_parts("Setup-1.2.exe", 100, "setup-1-2")
    assert len(one) == 1 and one[0].download == "Setup-1.2.exe" and one[0].size == 100
    under = plan_parts("a.bin", PART_LIMIT, "a-bin")
    assert len(under) == 1 and under[0].size == PART_LIMIT
    boundary = plan_parts("a.bin", MAX_RELEASE_BYTES, "a-bin")
    assert len(boundary) == 2
    assert boundary[0].size == PART_LIMIT and boundary[1].size == 1
    assert boundary[0].download == "a.bin.001" and boundary[1].start == PART_LIMIT
    wide = (PART_LIMIT * 2) + 3
    three = plan_parts("Archive.ipa", wide, "archive-ipa")
    assert [part.download for part in three] == [
        "Archive.ipa.001",
        "Archive.ipa.002",
        "Archive.ipa.003",
    ]
    assert three[0].size == PART_LIMIT and three[2].size == 3
    assert three[0].size + three[1].size + three[2].size == wide
    split_original = "\u53d1\u5e03\u5305Network.7z"
    split_parts = plan_parts(split_original, MAX_RELEASE_BYTES + 10, "network")
    assert split_parts[0].download == "network.7z.001"
    assert split_parts[0].label == split_original + ".001"
    assert split_parts[1].download == "network.7z.002"
    joined = join_hint(split_original, split_parts)
    assert "copy /b" in joined and "network.7z.001" in joined
    note = readme_text("owner/network", "v1.0.0", split_original, MAX_RELEASE_BYTES + 10, split_parts)
    assert MARKER in note and "copy /b" in note and "not zip or 7z" in note
    single_note = readme_text("owner/setup-1-2", "v1.0.0", "Setup-1.2.exe", 100, one)
    assert "Download name: `Setup-1.2.exe`" in single_note and "copy /b" not in single_note
    sample = Path(tempfile.mkdtemp())
    try:
        blob = sample / "blob.bin"
        blob.write_bytes(b"abcdefghijklmnopqrstuvwxyz")
        hashed = plan_parts("blob.bin", 26, "blob-bin")
        fill_sha256(blob, hashed)
        assert hashed[0].sha256 == hashlib.sha256(b"abcdefghijklmnopqrstuvwxyz").hexdigest()
        reader = SliceReader(blob, 4, 6, "blob.bin")
        assert reader.read(2) == b"ef"
        assert reader.read(100) == b"ghij"
        assert reader.read(1) == b""
        assert reader.sha256.hexdigest() == hashlib.sha256(b"efghij").hexdigest()
        reader.close()
    finally:
        remove_tree(sample)
    print("check ok")


def remove_tree(path: Path) -> None:
    def onerror(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=onerror)


def run_git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout


def author_env(login: str) -> dict[str, str]:
    env = os.environ.copy()
    email = f"{login}@users.noreply.github.com"
    env["GIT_AUTHOR_NAME"] = login
    env["GIT_AUTHOR_EMAIL"] = email
    env["GIT_COMMITTER_NAME"] = login
    env["GIT_COMMITTER_EMAIL"] = email
    env["GH_PROMPT_DISABLED"] = "1"
    return env


def join_hint(original_name: str, parts: list[AssetPart]) -> str:
    joined = "+".join(f'"{part.download}"' for part in parts)
    return f'copy /b {joined} "{original_name}"'


def readme_text(
    owner_repo: str,
    tag: str,
    original_name: str,
    total: int,
    parts: list[AssetPart],
) -> str:
    if len(parts) == 1:
        part = parts[0]
        return (
            f"{MARKER}\n\n"
            f"# {owner_repo.split('/')[-1]}\n\n"
            "The archive is a Release asset, not a git blob.\n\n"
            f"- Release: https://github.com/{owner_repo}/releases/tag/{tag}\n"
            f"- Download name: `{part.download}`\n"
            f"- Original filename: `{original_name}`\n"
            f"- Size: {total} bytes\n"
        )
    lines = [
        MARKER,
        "",
        f"# {owner_repo.split('/')[-1]}",
        "",
        "The archive is a Release asset, not a git blob.",
        "",
        f"- Release: https://github.com/{owner_repo}/releases/tag/{tag}",
        f"- Original filename: `{original_name}`",
        f"- Size: {total} bytes",
        "",
        "GitHub requires each Release file to be under 2 GiB, so this file is stored as raw byte ranges.",
        "These parts are not zip or 7z volumes. Join them in order to rebuild the original bytes.",
        "",
        "Windows:",
        "",
        "```bat",
        join_hint(original_name, parts),
        "```",
        "",
        "Python:",
        "",
        "```python",
        "from pathlib import Path",
        f"parts = [{', '.join(repr(part.download) for part in parts)}]",
        f"destination = Path({original_name!r})",
        "with destination.open('wb') as target:",
        "    for name in parts:",
        "        with Path(name).open('rb') as source:",
        "            while True:",
        "                chunk = source.read(1024 * 1024)",
        "                if not chunk:",
        "                    break",
        "                target.write(chunk)",
        "```",
        "",
        "Parts:",
    ]
    for part in parts:
        digest = f" sha256 `{part.sha256}`" if part.sha256 else ""
        lines.append(
            f"- `{part.download}` label `{part.label}` offset {part.start} size {part.size} bytes{digest}"
        )
    lines.append("")
    return "\n".join(lines)


def release_body(original_name: str, total: int, parts: list[AssetPart]) -> str:
    lines = [
        "Archive published as a Release asset so the binary stays out of git history.",
        "",
        f"Original filename: {original_name}",
        f"Size: {total} bytes",
    ]
    if len(parts) == 1:
        lines.append(f"Download name: {parts[0].download}")
        if parts[0].sha256:
            lines.append(f"sha256: {parts[0].sha256}")
        return "\n".join(lines) + "\n"
    lines.append("")
    lines.append("Split into raw byte ranges because each Release file must be under 2 GiB.")
    lines.append("These parts are not zip or 7z volumes. Join them in order.")
    lines.append("")
    lines.append("Windows:")
    lines.append(join_hint(original_name, parts))
    lines.append("")
    for part in parts:
        digest = f" sha256 {part.sha256}" if part.sha256 else ""
        lines.append(
            f"- {part.download} offset {part.start} size {part.size}{digest}"
        )
    return "\n".join(lines) + "\n"


def write_stage(
    stage: Path,
    owner_repo: str,
    tag: str,
    original_name: str,
    total: int,
    parts: list[AssetPart],
) -> None:
    (stage / "README.md").write_text(
        readme_text(owner_repo, tag, original_name, total, parts),
        encoding="utf-8",
        newline="\n",
    )
    (stage / ".gitignore").write_text(
        "\n".join(
            [
                ".env",
                ".env.*",
                "*.pem",
                "*.p12",
                "*.pfx",
                "*.key",
                "*.7z",
                "*.zip",
                "*.rar",
                "*.exe",
                "*.msi",
                "*.iso",
                "*.dmg",
                "*.tar",
                "*.gz",
                "*.ipa",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def placed_asset(release: dict, part: AssetPart) -> dict | None:
    for asset in release.get("assets") or []:
        if asset.get("state") not in (None, "uploaded"):
            continue
        if asset.get("name") != part.download and asset.get("label") != part.label:
            continue
        if int(asset.get("size") or -1) != part.size:
            continue
        return asset
    return None


def reject_size_conflict(release: dict, part: AssetPart) -> None:
    for asset in release.get("assets") or []:
        if asset.get("state") not in (None, "uploaded"):
            continue
        if asset.get("name") != part.download and asset.get("label") != part.label:
            continue
        if int(asset.get("size") or -1) != part.size:
            raise SystemExit(
                f"asset {part.download} exists with size {asset.get('size')} != {part.size}"
            )


def parts_uploaded(release: dict, parts: list[AssetPart]) -> bool:
    return all(placed_asset(release, part) is not None for part in parts)


def readme_matches(
    client,
    owner_repo: str,
    original_name: str,
    total: int,
    parts: list[AssetPart],
) -> bool:
    status, parsed, _text = client.request(
        "GET",
        f"/repos/{owner_repo}/contents/README.md",
        allow_http=(404,),
    )
    if status != 200 or not isinstance(parsed, dict):
        return False
    raw = parsed.get("content") or ""
    try:
        text = base64.b64decode(raw).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return False
    if MARKER not in text or original_name not in text or str(total) not in text:
        return False
    return all(part.download in text and str(part.size) in text for part in parts)


def classify(
    client,
    owner_repo: str,
    tag: str,
    original_name: str,
    total: int,
    parts: list[AssetPart],
) -> str:
    status, repo, _text = client.request("GET", f"/repos/{owner_repo}", allow_http=(404,))
    if status == 404:
        return "create"
    if status != 200 or not isinstance(repo, dict):
        raise SystemExit(f"could not read repo {owner_repo}")
    if repo.get("default_branch") not in (None, "main"):
        return "unrelated"
    description = repo.get("description") or ""
    ours = description.startswith("Release asset. Original file:") and original_name in description
    status, release, _text = client.request(
        "GET",
        f"/repos/{owner_repo}/releases/tags/{quote(tag, safe='')}",
        allow_http=(404,),
    )
    if status == 200 and isinstance(release, dict) and parts_uploaded(release, parts):
        return "uptodate"
    if readme_matches(client, owner_repo, original_name, total, parts):
        return "reuse"
    if ours and int(repo.get("size") or 0) == 0:
        return "reuse"
    return "unrelated"


def decide(
    client,
    login: str,
    base_name: str,
    tag: str,
    original_name: str,
    size: int,
    public: bool,
) -> tuple[str, str, list[AssetPart]]:
    names = [base_name] if base_name.endswith("-pkg") else [base_name, f"{base_name}-pkg"]
    blocked: list[str] = []
    for name in names:
        parts = plan_parts(original_name, size, name)
        owner_repo = f"{login}/{name}"
        kind = classify(client, owner_repo, tag, original_name, size, parts)
        print(f"name {name}: {kind}")
        if kind in {"reuse", "uptodate"}:
            _status, repo, _text = client.request("GET", f"/repos/{owner_repo}")
            if isinstance(repo, dict):
                visibility_ok(repo, public)
        if kind in {"create", "reuse", "uptodate"}:
            if name != base_name:
                print(f"name taken, using {name}")
            return kind, name, parts
        blocked.append(name)
    raise SystemExit(
        "repo name belongs to another project: " + ", ".join(f"{login}/{item}" for item in blocked)
    )


def visibility_ok(repo: dict, public: bool) -> None:
    is_private = bool(repo.get("private"))
    if public and is_private:
        raise SystemExit("existing repo is private; not changing visibility")
    if not public and not is_private:
        raise SystemExit("existing repo is public; not uploading this archive there")


def create_repo(stage: Path, env: dict[str, str], name: str, public: bool, label: str) -> None:
    desc = f"Release asset. Original file: {label}"[:350]
    cmd = [
        "gh",
        "repo",
        "create",
        name,
        "--public" if public else "--private",
        "--source=.",
        "--remote=origin",
        "--description",
        desc,
    ]
    proc = subprocess.run(cmd, cwd=stage, env=env, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"gh repo create failed: {err[:500]}")
    if proc.stdout.strip():
        print(proc.stdout.strip())


def parse_blobs(output: str) -> tuple[str, str]:
    match = re.search(r"blobs posted=(\d+) reused=(\d+)", output)
    if not match:
        return "0", "0"
    return match.group(1), match.group(2)


class ProxyConnectError(OSError):
    """Local proxy CONNECT failed before any asset bytes were sent."""


def parse_proxy(raw: str | None) -> tuple[str, int] | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text or text.lower() in {"0", "off", "direct"}:
        return None
    text = text.removeprefix("http://").removeprefix("https://")
    text = text.split("/", 1)[0]
    host, sep, port_s = text.rpartition(":")
    if not sep:
        raise SystemExit("PUSH_GITHUB_PROXY must be host:port or http://host:port")
    try:
        port = int(port_s)
    except ValueError as exc:
        raise SystemExit("PUSH_GITHUB_PROXY port is not an integer") from exc
    if not host or port <= 0 or port > 65535:
        raise SystemExit("PUSH_GITHUB_PROXY host or port is invalid")
    return host, port


def want_proxy(size: int, env_value: str | None, listening: bool) -> tuple[str, int] | None:
    """Pick a local HTTP proxy for a Release upload.

    Unset env: only files of at least 8 MiB, and only when the default
    Clash mixed-port is open. ``direct`` / ``off`` stays on a direct POST.
    An explicit proxy is used even for a small file.
    """
    if env_value is not None and env_value.strip().lower() in {"0", "off", "direct"}:
        return None
    if env_value is not None and env_value.strip():
        return parse_proxy(env_value)
    if size < PROXY_MIN_BYTES or not listening:
        return None
    return parse_proxy(DEFAULT_PROXY)


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def connect_established(buf: bytes) -> bool:
    status = buf.split(b"\r\n", 1)[0]
    return b" 200 " in status


def choose_upload_proxy(size: int) -> tuple[str, int] | None:
    env_value = os.environ.get("PUSH_GITHUB_PROXY")
    if env_value is not None and env_value.strip().lower() in {"0", "off", "direct"}:
        return None
    if env_value is not None and env_value.strip():
        proxy = parse_proxy(env_value)
        if proxy is None or not port_open(*proxy):
            raise SystemExit(f"PUSH_GITHUB_PROXY is not listening: {env_value.strip()}")
        return proxy
    return want_proxy(size, None, port_open("127.0.0.1", 20221))


def open_direct(timeout: int) -> http.client.HTTPSConnection:
    conn = http.client.HTTPSConnection(
        UPLOAD_HOST,
        timeout=timeout,
        context=ssl.create_default_context(),
    )
    conn.blocksize = UPLOAD_BLOCK
    return conn


def open_proxied(timeout: int, proxy: tuple[str, int]) -> http.client.HTTPSConnection:
    host, port = proxy
    raw = None
    try:
        raw = socket.create_connection((host, port), timeout=20)
        raw.settimeout(20)
        raw.sendall(
            f"CONNECT {UPLOAD_HOST}:443 HTTP/1.1\r\nHost: {UPLOAD_HOST}:443\r\n\r\n".encode("ascii")
        )
        buf = bytearray()
        while b"\r\n\r\n" not in buf:
            chunk = raw.recv(4096)
            if not chunk:
                raise ProxyConnectError("proxy closed during CONNECT")
            buf += chunk
            if len(buf) > 65536:
                raise ProxyConnectError("proxy CONNECT response too large")
        head, _, rest = bytes(buf).partition(b"\r\n\r\n")
        if rest:
            raise ProxyConnectError("proxy sent unexpected bytes after CONNECT")
        if not connect_established(head):
            status = head.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
            raise ProxyConnectError(f"proxy CONNECT failed: {status[:160]}")
        ssock = ssl.create_default_context().wrap_socket(raw, server_hostname=UPLOAD_HOST)
        raw = None
        ssock.settimeout(timeout)
        conn = http.client.HTTPSConnection(
            UPLOAD_HOST,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        conn.sock = ssock
        conn.blocksize = UPLOAD_BLOCK
        return conn
    except ProxyConnectError:
        if raw is not None:
            raw.close()
        raise
    except (OSError, ssl.SSLError, TimeoutError) as exc:
        if raw is not None:
            raw.close()
        raise ProxyConnectError(str(exc)) from exc


def drop_incomplete(client, owner_repo: str, release: dict, part: AssetPart) -> None:
    kept = []
    for item in release.get("assets") or []:
        same = item.get("name") == part.download or item.get("label") == part.label
        if same and item.get("state") not in (None, "uploaded"):
            asset_id = item.get("id")
            print(
                f"deleting incomplete asset {part.download} state={item.get('state')}",
                flush=True,
            )
            if asset_id:
                client.request(
                    "DELETE",
                    f"/repos/{owner_repo}/releases/assets/{asset_id}",
                    allow_http=(404,),
                )
            continue
        kept.append(item)
    release["assets"] = kept


def upload_asset(
    token: str,
    owner_repo: str,
    release_id: int,
    part: AssetPart,
    archive: Path,
) -> dict:
    query = f"name={quote(part.download)}&label={quote(part.label)}"
    path = f"/repos/{owner_repo}/releases/{release_id}/assets?{query}"
    timeout = max(600, (part.size // (256 * 1024)) + 120)
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "push-to-github",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(part.size),
        "Accept-Encoding": "identity",
    }
    proxy = choose_upload_proxy(part.size)
    direct_only = proxy is None
    if proxy:
        print(f"upload via proxy {proxy[0]}:{proxy[1]}", flush=True)
    else:
        print("upload direct", flush=True)
    last = "unknown"
    for attempt in range(1, 4):
        conn = None
        reader = None
        try:
            conn = open_direct(timeout) if direct_only else open_proxied(timeout, proxy)
            reader = SliceReader(archive, part.start, part.size, part.download)
            conn.request("POST", path, body=reader, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            if reader._sent != part.size:
                raise SystemExit(f"short upload {part.download}: {reader._sent} != {part.size}")
            digest = reader.sha256.hexdigest()
            if part.sha256 and digest != part.sha256:
                raise SystemExit(f"checksum mismatch while uploading {part.download}")
            if resp.status in {429, 500, 502, 503, 504}:
                last = f"HTTP {resp.status} {text[:200]}"
                print(f"upload retry {attempt} {last}", flush=True)
                continue
            if resp.status == 422 and "already_exists" in text:
                return {"already_exists": True}
            if resp.status < 200 or resp.status >= 300:
                raise SystemExit(f"upload failed HTTP {resp.status} {text[:500]}")
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise SystemExit("upload returned no asset")
            remote = parsed.get("digest") or ""
            if isinstance(remote, str) and remote.startswith("sha256:"):
                if remote.split(":", 1)[1].lower() != digest:
                    raise SystemExit(f"GitHub digest mismatch for {part.download}")
            parsed["_sha256"] = digest
            return parsed
        except ProxyConnectError as exc:
            last = f"ProxyConnectError: {exc}"
            print(f"proxy connect failed; falling back to direct: {exc}", flush=True)
            direct_only = True
            proxy = None
        except (http.client.HTTPException, OSError, ssl.SSLError, TimeoutError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            print(f"upload retry {attempt} {last}", flush=True)
        finally:
            if reader is not None:
                reader.close()
            if conn is not None:
                conn.close()
    raise SystemExit(f"upload failed: {last}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish one archive as a GitHub Release asset.")
    parser.add_argument("archive", nargs="?", help="archive, installer, or other single file")
    parser.add_argument("--repo", help="repository name (lowercase, dashes). Owner is the logged-in user.")
    parser.add_argument("--tag", default="v1.0.0")
    parser.add_argument("--public", action="store_true", help="create a public repo. Default is private.")
    parser.add_argument("--check", action="store_true", help="run offline name and secret checks")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; do not create a repo or upload")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass

    if args.check:
        self_check()
        return 0
    if not args.archive:
        raise SystemExit("archive path required")
    if not SAFE_TAG.fullmatch(args.tag):
        raise SystemExit(f"tag must match {SAFE_TAG.pattern}")

    archive = Path(args.archive).expanduser().resolve()
    if not archive.is_file():
        raise SystemExit(f"not a file: {archive}")
    secret = looks_secret(archive)
    if secret:
        raise SystemExit(f"refusing {archive.name}: {secret}. Ask before uploading a credential file.")
    size = archive.stat().st_size
    if size <= 0:
        raise SystemExit("archive is empty")

    repo = args.repo or repo_slug_from_stem(archive.stem)
    if not repo or not SAFE_REPO.fullmatch(repo):
        raise SystemExit("could not derive a repo name; pass --repo (lowercase, dashes) once")
    parts = plan_parts(archive.name, size, repo)
    print(f"archive={archive}")
    print(f"bytes={size}")
    print(f"parent not initialized: {archive.parent}")
    print(f"repo={repo} tag={args.tag} visibility={'public' if args.public else 'private'}")
    print(f"parts={len(parts)}")
    for part in parts:
        print(
            f"part {part.index}/{part.count} offset={part.start} bytes={part.size} "
            f"asset name={part.download} label={part.label}"
        )
    if len(parts) > 1:
        print("note: not under 2 GiB; raw byte-range parts, not zip or 7z volumes")
        print(join_hint(archive.name, parts))
    if size > 90 * 1024 * 1024:
        print("note: above the git blob cap; Release upload only")
    if args.dry_run:
        print("dry-run: no repo created, no upload")
        return 0

    publisher = load_publisher()
    publisher.prepend_tool_path()
    token = publisher.gh_token()
    if not token:
        raise SystemExit("gh auth token failed")
    client = publisher.GithubApi(token)
    _status, user, _text = client.request("GET", "/user")
    if not isinstance(user, dict) or not user.get("login"):
        raise SystemExit("could not read the logged-in user")
    login = user["login"]
    env = author_env(login)

    kind, repo, parts = decide(
        client, login, repo, args.tag, archive.name, size, args.public
    )
    owner_repo = f"{login}/{repo}"
    if kind == "uptodate":
        print("release already up to date")
        print("blobs posted=0 reused=0")
        print(f"https://github.com/{owner_repo}")
        print(f"https://github.com/{owner_repo}/releases/tag/{args.tag}")
        for part in parts:
            print(f"asset name={part.download} label={part.label} size={part.size}")
        print(f"original={archive.name} size={size} parts={len(parts)}")
        print("visibility checked; archive was not uploaded again")
        return 0

    if len(parts) > 1:
        fill_sha256(archive, parts)

    stage = Path(tempfile.mkdtemp(prefix="push-release-"))
    published = False
    try:
        write_stage(stage, owner_repo, args.tag, archive.name, size, parts)
        run_git(["init", "-b", "main"], stage, env)
        run_git(["add", "-A"], stage, env)
        status = run_git(["status", "--porcelain"], stage, env).strip()
        print(status)
        run_git(
            ["commit", "-m", "Keep the archive on a Release instead of in git history."],
            stage,
            env,
        )
        if kind == "create":
            create_repo(stage, env, repo, args.public, archive.name)
        else:
            _status, existing, _text = client.request("GET", f"/repos/{owner_repo}")
            if isinstance(existing, dict):
                visibility_ok(existing, args.public)
            run_git(
                ["remote", "add", "origin", f"https://github.com/{owner_repo}.git"],
                stage,
                env,
            )
        remote = run_git(["remote", "get-url", "origin"], stage, env).strip()
        print(f"origin={remote}")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("publish-via-gh-api.py"))],
            cwd=stage,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.stdout:
            print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            raise SystemExit(f"README publish failed: {err[:500]}")
        posted, reused = parse_blobs(proc.stdout or "")

        status, release, text = client.request(
            "POST",
            f"/repos/{owner_repo}/releases",
            payload={
                "tag_name": args.tag,
                "target_commitish": "main",
                "name": archive.name[:120],
                "body": release_body(archive.name, size, parts),
                "draft": False,
                "prerelease": False,
            },
            allow_http=(422,),
        )
        if status == 422:
            status, release, get_text = client.request(
                "GET",
                f"/repos/{owner_repo}/releases/tags/{quote(args.tag, safe='')}",
                allow_http=(404,),
            )
            if status == 404:
                raise SystemExit(f"create release failed: {text[:400]}")
            text = get_text
        if not isinstance(release, dict) or not release.get("id"):
            raise SystemExit(f"create release failed: {text[:400]}")

        for part in parts:
            drop_incomplete(client, owner_repo, release, part)
            reject_size_conflict(release, part)
            existing = placed_asset(release, part)
            if existing:
                print(f"asset exists {part.download} size={part.size}", flush=True)
                continue
            print(
                f"uploading {part.download} offset={part.start} size={part.size}",
                flush=True,
            )
            asset = upload_asset(token, owner_repo, int(release["id"]), part, archive)
            if asset.get("already_exists"):
                _status, release, _text = client.request(
                    "GET",
                    f"/repos/{owner_repo}/releases/tags/{quote(args.tag, safe='')}",
                )
                if not isinstance(release, dict):
                    raise SystemExit("could not re-read the release")
                existing = placed_asset(release, part)
                if existing is None:
                    raise SystemExit("asset name already exists and does not match this archive")
                continue
            if asset.get("name") != part.download or asset.get("label") != part.label:
                _status, patched, _text = client.request(
                    "PATCH",
                    f"/repos/{owner_repo}/releases/assets/{asset['id']}",
                    payload={"name": part.download, "label": part.label},
                )
                if isinstance(patched, dict):
                    asset = patched
            if asset.get("name") != part.download:
                raise SystemExit(f"asset name mismatch: {asset.get('name')}")
            if int(asset.get("size") or -1) != part.size:
                raise SystemExit(f"asset size mismatch: {asset.get('size')} != {part.size}")
            release.setdefault("assets", []).append(asset)

        try:
            client.request(
                "PATCH",
                f"/repos/{owner_repo}/releases/{release['id']}",
                payload={
                    "name": archive.name[:120],
                    "body": release_body(archive.name, size, parts),
                },
            )
        except SystemExit as exc:
            print(f"release notes were not updated: {exc}")

        _status, confirmed, _text = client.request("GET", f"/repos/{owner_repo}")
        wanted_private = not args.public
        if not isinstance(confirmed, dict) or bool(confirmed.get("private")) != wanted_private:
            raise SystemExit("repository visibility does not match the request")
        _status, release, _text = client.request(
            "GET",
            f"/repos/{owner_repo}/releases/tags/{quote(args.tag, safe='')}",
        )
        if not isinstance(release, dict) or not parts_uploaded(release, parts):
            raise SystemExit("release is missing one or more parts after upload")
        published = True
        print(f"blobs posted={posted} reused={reused}")
        print("visibility=" + ("private" if confirmed.get("private") else "public"))
        for part in parts:
            digest = f" sha256={part.sha256}" if part.sha256 else ""
            print(f"asset name={part.download} label={part.label} size={part.size}{digest}")
        print(f"original={archive.name} size={size} parts={len(parts)}")
        print(f"https://github.com/{owner_repo}")
        print(release.get("html_url") or f"https://github.com/{owner_repo}/releases/tag/{args.tag}")
        if len(parts) > 1:
            print(join_hint(archive.name, parts))
            print(
                "excluded from git: the archive and its parts; "
                "parts were byte ranges of the original file, not copies"
            )
        else:
            print("excluded from git: the archive; no env, credential, or log files were staged")
        return 0
    finally:
        if published:
            remove_tree(stage)
            print("staging deleted")
        else:
            print(f"staging kept: {stage}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
