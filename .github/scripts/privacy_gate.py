"""Fail the public release when new metadata exposes a personal identity."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PERSONAL_PATH_RE = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+(?:/|$)")
ALLOWED_EMAIL_SUFFIXES = ("@users.noreply.github.com", "@github.com")
PUBLIC_TEXT_ROOTS = ("README.md", "README.zh-CN.md", "LICENSE", "CODE_OF_CONDUCT.md", "docs", "src", "pyproject.toml", ".github")


def _files(root: Path) -> list[Path]:
    result: list[Path] = []
    for name in PUBLIC_TEXT_ROOTS:
        path = root / name
        if path.is_file():
            result.append(path)
        elif path.is_dir():
            result.extend(p for p in path.rglob("*") if p.is_file())
    return result


def _check_commit(root: Path, errors: list[str]) -> None:
    try:
        email = subprocess.check_output(
            ["git", "-C", str(root), "show", "-s", "--format=%ae", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip().lower()
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"commit_identity_unavailable:{exc}")
        return
    if email and not email.endswith(ALLOWED_EMAIL_SUFFIXES):
        errors.append("latest_commit_email_is_not_github_noreply")


def _check_png(path: Path, errors: list[str]) -> None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        errors.append(f"png_read_failed:{path}:{exc}")
        return
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    offset = 8
    sensitive = {"tEXt", "zTXt", "iTXt", "eXIf"}
    while offset + 12 <= len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8].decode("ascii", "replace")
        if kind in sensitive:
            errors.append(f"png_metadata_present:{path}:{kind}")
        offset += 12 + size


def check(root: Path, *, check_commit: bool = True) -> list[str]:
    errors: list[str] = []
    for path in _files(root):
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            if path.suffix.lower() == ".png":
                _check_png(path, errors)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in EMAIL_RE.finditer(text):
            value = match.group(0).lower()
            if not value.endswith(ALLOWED_EMAIL_SUFFIXES):
                errors.append(f"personal_email_pattern:{path}")
                break
        if PERSONAL_PATH_RE.search(text):
            errors.append(f"local_path_pattern:{path}")

    try:
        metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata.get("project", {})
        for author in project.get("authors", []):
            if author.get("email"):
                errors.append("pyproject_author_email_present")
            if "contributors" not in str(author.get("name", "")).lower():
                errors.append("pyproject_author_is_not_project_identity")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"pyproject_unreadable:{exc}")

    if check_commit:
        _check_commit(root, errors)
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    root = Path((argv or sys.argv[1:] or ["."])[0]).resolve()
    errors = check(root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("privacy_gate=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
