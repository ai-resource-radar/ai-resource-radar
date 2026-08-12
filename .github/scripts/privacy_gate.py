"""Fail the public release when new metadata exposes a personal identity.

The source-tree checks in this module are deliberately independent from the
commit checks.  A contributor may use a real address in commit metadata, but a
personal address or local filesystem path must never be added to public source
or package metadata.  The commit checks are range based so that a push with
several commits cannot hide an earlier identity mistake behind a clean HEAD.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PERSONAL_PATH_RE = re.compile(
    r"(?:/(?:Users|home)/[A-Za-z0-9._-]+(?:/|$)"
    r"|[A-Za-z]:[\\/](?:Users|home)[\\/][A-Za-z0-9._-]+(?:[\\/]|$)"
    r"|/private/var/folders/[A-Za-z0-9._-]+)"
)
LARRY_EMAIL = "115380064+larrynode@users.noreply.github.com"
LARRY_NAMES = ("larry", "larrynode")
GITHUB_NOREPLY_RE = re.compile(
    r"(?:[0-9]+\+)?[A-Za-z0-9._-]+(?:\[bot\])?@users\.noreply\.github\.com$",
    re.IGNORECASE,
)
GITHUB_SYSTEM_EMAILS = {"noreply@github.com", "github-actions@github.com"}
PUBLIC_TEXT_ROOTS = ("README.md", "README.zh-CN.md", "LICENSE", "CODE_OF_CONDUCT.md", "docs", "src", "pyproject.toml", ".github")
PUBLIC_CONFIG_FILES = {
    ".dockerignore",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".pre-commit-config.yaml",
    "Dockerfile",
    "Makefile",
    "MANIFEST.in",
    "package-lock.json",
    "package.json",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "tox.ini",
}
PUBLIC_CONFIG_SUFFIXES = {".cfg", ".ini", ".json", ".lock", ".toml", ".yaml", ".yml"}


def _files(root: Path) -> list[Path]:
    result: set[Path] = set()
    for name in PUBLIC_TEXT_ROOTS:
        path = root / name
        if path.is_file():
            result.add(path)
        elif path.is_dir():
            result.update(p for p in path.rglob("*") if p.is_file())
    for path in root.iterdir():
        if not path.is_file():
            continue
        if path.name in PUBLIC_CONFIG_FILES or path.suffix.lower() in PUBLIC_CONFIG_SUFFIXES:
            result.add(path)
    return sorted(result)


def _git_output(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
        stderr=subprocess.DEVNULL,
    )


def _is_zero_sha(value: str | None) -> bool:
    return not value or not value.strip("0")


def _looks_like_larry(name: str, email: str) -> bool:
    normalized_name = name.strip().casefold()
    normalized_email = email.strip().casefold()
    email_local = normalized_email.partition("@")[0]
    email_login = email_local.rsplit("+", 1)[-1]
    return normalized_name in LARRY_NAMES or email_login == "larrynode"


def _is_github_noreply(email: str) -> bool:
    normalized = email.strip().casefold()
    return normalized == LARRY_EMAIL or normalized in GITHUB_SYSTEM_EMAILS or bool(GITHUB_NOREPLY_RE.fullmatch(normalized))


def _commit_range(root: Path, base_sha: str | None, head_sha: str | None) -> list[tuple[str, str, str, str, str]]:
    """Return (sha, author name, author email, committer name, committer email)."""

    head = head_sha.strip() if head_sha else ""
    if not head:
        head = _git_output(root, "rev-parse", "HEAD").strip()
    # A zero ``before`` SHA means that the ref was created in this push.  In
    # that case every commit reachable from HEAD is newly introduced.
    if base_sha is None:
        # Preserve the local ``check(root)`` contract: without an event base,
        # inspect only the checked-out commit rather than re-auditing history.
        log_args = ["-1", head]
    else:
        # A zero ``before`` SHA means that the ref was created in this push. In
        # that case every commit reachable from HEAD is newly introduced.
        revision = head if _is_zero_sha(base_sha) else f"{base_sha.strip()}..{head}"
        log_args = [revision]
    raw = _git_output(
        root,
        "log",
        "--reverse",
        "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00",
        "-z",
        *log_args,
    )
    records = [record for record in raw.split("\x00\x00") if record]
    commits: list[tuple[str, str, str, str, str]] = []
    for record in records:
        fields = record.split("\x00")
        if len(fields) != 5:
            raise ValueError("unexpected_commit_metadata_shape")
        commits.append(tuple(fields))
    return commits


def _new_branch_base(root: Path, head_sha: str | None, default_branch: str | None) -> str | None:
    """Resolve a new branch against the existing default branch when possible."""

    branch = (default_branch or "main").strip()
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or branch.startswith(("/", "-")) or ".." in branch:
        return None
    head = head_sha.strip() if head_sha else _git_output(root, "rev-parse", "HEAD").strip()
    for candidate in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
        try:
            return _git_output(root, "merge-base", head, candidate).strip() or None
        except (OSError, subprocess.CalledProcessError):
            continue
    return None


def _check_commit(
    root: Path,
    errors: list[str],
    *,
    base_sha: str | None = None,
    head_sha: str | None = None,
    actor: str | None = None,
    ref_type: str | None = None,
    default_branch: str | None = None,
) -> None:
    """Validate all commits introduced by ``base_sha..head_sha``.

    ``base_sha``/``head_sha`` are optional for local use. CI passes the event
    range explicitly; without a base we retain the historical local behaviour
    of checking only HEAD. Tag pushes still inspect their full reachable range,
    while ``ref_type=tag`` disables only the actor-specific committer rule.
    """

    effective_actor = (actor if actor is not None else os.environ.get("GITHUB_ACTOR", "")).strip().casefold()
    effective_ref_type = (ref_type if ref_type is not None else os.environ.get("GITHUB_REF_TYPE", "")).strip().casefold()
    effective_default_branch = default_branch if default_branch is not None else os.environ.get("GITHUB_DEFAULT_BRANCH")
    effective_base = base_sha
    if _is_zero_sha(effective_base) and effective_ref_type == "branch":
        effective_base = _new_branch_base(root, head_sha, effective_default_branch) or effective_base
    try:
        commits = _commit_range(root, effective_base, head_sha)
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"commit_range_unavailable:{exc}")
        return
    except ValueError as exc:
        errors.append(f"commit_range_unavailable:{exc}")
        return

    # A newly created ref reports an all-zero ``before`` SHA. Its full reachable
    # history is inspected for Larry impersonation, but that history is not a
    # reliable set of commits introduced by the actor (it commonly includes the
    # existing main history). Tag refs have the same property even when GitHub
    # supplies a non-zero base. Keep those checks identity-based, not actor-based.
    enforce_actor_committer = (
        effective_actor == "larrynode"
        and effective_ref_type != "tag"
        and not _is_zero_sha(effective_base)
    )
    for sha, author_name, author_email, committer_name, committer_email in commits:
        author_email = author_email.strip().casefold()
        committer_email = committer_email.strip().casefold()
        if _looks_like_larry(author_name, author_email) and author_email != LARRY_EMAIL:
            errors.append(f"larry_author_identity_mismatch:{sha}")
        if _looks_like_larry(committer_name, committer_email) and committer_email != LARRY_EMAIL:
            errors.append(f"larry_committer_identity_mismatch:{sha}")
        if enforce_actor_committer and committer_email != LARRY_EMAIL:
            errors.append(f"larrynode_committer_identity_mismatch:{sha}")


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


def check(
    root: Path,
    *,
    check_commit: bool = True,
    base_sha: str | None = None,
    head_sha: str | None = None,
    actor: str | None = None,
    ref_type: str | None = None,
    default_branch: str | None = None,
) -> list[str]:
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
            if not _is_github_noreply(value):
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
        effective_base = base_sha if base_sha is not None else os.environ.get("GITHUB_BASE_SHA")
        if effective_base is None:
            effective_base = os.environ.get("GITHUB_EVENT_BEFORE")
        effective_head = head_sha if head_sha is not None else os.environ.get("GITHUB_SHA")
        effective_actor = actor if actor is not None else os.environ.get("GITHUB_ACTOR")
        effective_ref_type = ref_type if ref_type is not None else os.environ.get("GITHUB_REF_TYPE")
        effective_default_branch = default_branch if default_branch is not None else os.environ.get("GITHUB_DEFAULT_BRANCH")
        _check_commit(
            root,
            errors,
            base_sha=effective_base,
            head_sha=effective_head,
            actor=effective_actor,
            ref_type=effective_ref_type,
            default_branch=effective_default_branch,
        )
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--base-sha", dest="base_sha")
    parser.add_argument("--head-sha", dest="head_sha")
    parser.add_argument("--actor")
    parser.add_argument("--ref-type", dest="ref_type")
    parser.add_argument("--default-branch", dest="default_branch")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    errors = check(
        root,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        actor=args.actor,
        ref_type=args.ref_type,
        default_branch=args.default_branch,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("privacy_gate=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
