"""Repository rules: pinned models, recorded licenses, ignored files, no audio tracked."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from scripts.fetch_models import (
    Digests,
    FetchError,
    PinnedFile,
    check,
    host_allowed,
    load_manifest,
)

ROOT = Path(__file__).resolve().parent.parent
LICENSES = (ROOT / "docs" / "licenses.md").read_text(encoding="utf-8")


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [p for p in out.split("\0") if p]


# --- models ----------------------------------------------------------------------------------


def test_every_model_file_is_pinned_and_hashed() -> None:
    files = load_manifest()
    assert files
    for f in files:
        assert re.fullmatch(r"[0-9a-f]{40}", f.revision), f.path
        assert f.sha256 is not None or f.git_blob is not None, f.path
        assert f.url.startswith(f"https://huggingface.co/{f.repo}/resolve/{f.revision}/")


def test_every_model_is_in_the_license_record() -> None:
    for f in load_manifest():
        assert f.repo in LICENSES
        assert f.revision in LICENSES
        if f.sha256:
            assert f.sha256 in LICENSES


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://huggingface.co/Systran/x/resolve/abc/model.bin", True),
        ("https://cdn-lfs.hf.co/repos/x", True),
        ("https://cas-bridge.xethub.hf.co/x", True),
        ("http://huggingface.co/x", False),
        ("https://huggingface.co.evil.example/x", False),
        ("https://evilhf.co/x", False),
        ("https://example.org/model.bin", False),
    ],
)
def test_downloads_only_over_https_from_hugging_face(url: str, ok: bool) -> None:
    assert host_allowed(url) is ok


def pinned(**kw: object) -> PinnedFile:
    base: dict[str, object] = {
        "model": "m",
        "repo": "r",
        "revision": "0" * 40,
        "path": "f",
        "size": 3,
        "sha256": "a" * 64,
        "git_blob": None,
    }
    return PinnedFile(**{**base, **kw})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "got",
    [
        Digests(size=4, sha256="a" * 64, git_blob="b" * 40),
        Digests(size=3, sha256="c" * 64, git_blob="b" * 40),
    ],
)
def test_a_hash_or_size_mismatch_is_refused(got: Digests) -> None:
    with pytest.raises(FetchError):
        check(pinned(), got)


def test_a_git_blob_mismatch_is_refused() -> None:
    with pytest.raises(FetchError):
        check(pinned(sha256=None, git_blob="b" * 40), Digests(3, "a" * 64, "d" * 40))
    check(pinned(sha256=None, git_blob="b" * 40), Digests(3, "a" * 64, "b" * 40))


# --- licenses --------------------------------------------------------------------------------


def test_every_locked_package_has_a_recorded_license() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    names = {p["name"] for p in lock["package"] if p["name"] != "voice-agent"}
    recorded = {m.lower() for m in re.findall(r"^\| `([A-Za-z0-9_.-]+)` \|", LICENSES, re.M)}
    missing = sorted(n for n in names if n.lower() not in recorded)
    assert missing == []


def test_the_repository_is_gpl() -> None:
    assert "GNU GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "GPL-3.0-or-later"


# --- what may be tracked ---------------------------------------------------------------------

FORBIDDEN = re.compile(
    r"\.(wav|mp3|flac|ogg|oga|opus|m4a|aac|webm|pcm|raw|onnx|bin|gguf|safetensors|pt|ckpt)$"
    r"|(^|/)\.env($|\.)|\.env$|(^|/)models/"
)


def test_no_audio_model_or_env_file_is_tracked() -> None:
    assert [p for p in tracked() if FORBIDDEN.search(p)] == []


@pytest.mark.parametrize(
    "path",
    ["a.wav", "x/b.mp3", ".env", ".env.local", "gateway.env", "models/m/model.bin", "v.onnx"],
)
def test_gitignore_covers(path: str) -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT, check=False
    )
    assert ignored.returncode == 0
