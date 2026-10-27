"""Download the pinned model files in models.toml into models/, and verify every one.

    uv run python scripts/fetch_models.py           # fetch what is missing, verify all
    uv run python scripts/fetch_models.py --verify  # verify only, download nothing

Only HTTPS, only from huggingface.co and its own CDN hosts (*.hf.co), at the pinned commit.
Redirects are followed by hand, one at a time, after checking the next host. Proxy and netrc
settings from the environment are ignored. A file is written as ``.part`` and renamed only
after its size and hash match the manifest; a mismatch deletes the part file and fails.

Each verified file is printed with its SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "models.toml"
MODELS_DIR = ROOT / "models"
ALLOWED_HOSTS = ("huggingface.co",)
ALLOWED_HOST_SUFFIXES = (".hf.co", ".huggingface.co")
MAX_REDIRECTS = 5
CHUNK = 1 << 20


@dataclass(frozen=True, slots=True)
class PinnedFile:
    model: str
    repo: str
    revision: str
    path: str
    size: int
    sha256: str | None
    git_blob: str | None

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.path}"

    @property
    def local(self) -> Path:
        return MODELS_DIR / self.model / Path(self.path).name


class FetchError(Exception):
    pass


def load_manifest(path: Path = MANIFEST) -> list[PinnedFile]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    files = []
    for model in data["model"]:
        for f in model["file"]:
            files.append(
                PinnedFile(
                    model=model["name"],
                    repo=model["repo"],
                    revision=model["revision"],
                    path=f["path"],
                    size=int(f["size"]),
                    sha256=f.get("sha256"),
                    git_blob=f.get("git_blob"),
                )
            )
    return files


def host_allowed(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (
        host in ALLOWED_HOSTS or any(host.endswith(s) for s in ALLOWED_HOST_SUFFIXES)
    )


@dataclass(frozen=True, slots=True)
class Digests:
    size: int
    sha256: str
    git_blob: str


def digests(path: Path) -> Digests:
    size = path.stat().st_size
    sha256 = hashlib.sha256()
    blob = hashlib.sha1(f"blob {size}\0".encode(), usedforsecurity=False)
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            sha256.update(chunk)
            blob.update(chunk)
    return Digests(size, sha256.hexdigest(), blob.hexdigest())


def check(pinned: PinnedFile, got: Digests) -> None:
    if got.size != pinned.size:
        raise FetchError(f"{pinned.path}: size {got.size}, expected {pinned.size}")
    if pinned.sha256 is not None and got.sha256 != pinned.sha256:
        raise FetchError(f"{pinned.path}: sha256 {got.sha256}, expected {pinned.sha256}")
    if pinned.git_blob is not None and got.git_blob != pinned.git_blob:
        raise FetchError(f"{pinned.path}: git blob {got.git_blob}, expected {pinned.git_blob}")
    if pinned.sha256 is None and pinned.git_blob is None:
        raise FetchError(f"{pinned.path}: the manifest has no published hash for it")


def download(client: httpx.Client, pinned: PinnedFile) -> None:
    part = pinned.local.with_name(pinned.local.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    url = pinned.url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not host_allowed(url):
                raise FetchError(f"{pinned.path}: refused to fetch from {urlsplit(url).hostname}")
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = str(response.url.join(response.headers["location"]))
                    continue
                if response.status_code != 200:
                    raise FetchError(f"{pinned.path}: HTTP {response.status_code}")
                with part.open("wb") as fh:
                    for chunk in response.iter_bytes(CHUNK):
                        fh.write(chunk)
                break
        else:
            raise FetchError(f"{pinned.path}: more than {MAX_REDIRECTS} redirects")
        check(pinned, digests(part))
        part.replace(pinned.local)
    finally:
        part.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="verify only, download nothing")
    args = parser.parse_args(argv)
    files = load_manifest()
    failures = 0
    with httpx.Client(
        follow_redirects=False, trust_env=False, timeout=httpx.Timeout(30.0, read=120.0)
    ) as client:
        for pinned in files:
            try:
                if not pinned.local.exists():
                    if args.verify:
                        raise FetchError(f"{pinned.path}: missing")
                    print(f"fetching {pinned.repo}@{pinned.revision[:12]} {pinned.path}")
                    download(client, pinned)
                got = digests(pinned.local)
                check(pinned, got)
            except (FetchError, httpx.HTTPError) as exc:
                failures += 1
                print(f"FAILED {exc}")
                continue
            kind = "sha256 (published)" if pinned.sha256 else "git blob (published)"
            rel = pinned.local.relative_to(ROOT).as_posix()
            print(f"ok {rel}  {got.size} bytes  sha256 {got.sha256}  checked by {kind}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
