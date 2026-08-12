#!/usr/bin/env python3
"""Read-only maintainer preflight for a future signed release.

The script deliberately never logs in, writes credentials, creates tags, pushes,
or publishes.  Local checks are the default.  ``--online`` adds read-only GitHub
and PyPI checks, while ``--full`` runs the repository's deterministic test suite.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path


EXPECTED_LOGIN = "larrynode"
EXPECTED_NAME = "Larry"
EXPECTED_EMAIL = "115380064+larrynode@users.noreply.github.com"
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True)
class Check:
    id: str
    status: str
    summary: str
    remediation: str = ""


def _run(root: Path, *command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        check=check,
        text=True,
        capture_output=True,
    )


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = _run(root, "git", *args, check=check)
    return result.stdout.strip()


def _config(root: Path, key: str) -> str:
    return _git(root, "config", "--local", "--get", key, check=False)


def package_version(root: Path) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = str(project["version"])
    if not VERSION_RE.fullmatch(version):
        raise ValueError("package_version_is_not_semver")
    return version


def facade_version(root: Path) -> str:
    text = (root / "src/ai_resource_radar/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        raise ValueError("facade_version_missing")
    return match.group(1)


def local_checks(root: Path) -> tuple[str, list[Check]]:
    version = package_version(root)
    tag = f"v{version}"
    checks: list[Check] = []

    status = _git(root, "status", "--porcelain")
    checks.append(
        Check(
            "worktree",
            "pass" if not status else "fail",
            "working tree is clean" if not status else "working tree has uncommitted changes",
            "Commit or intentionally discard the changes before releasing.",
        )
    )
    branch = _git(root, "branch", "--show-current")
    checks.append(
        Check(
            "branch",
            "pass" if branch == "main" else "fail",
            f"current branch is {branch or 'detached HEAD'}",
            "Run the release from the protected main branch.",
        )
    )
    facade = facade_version(root)
    checks.append(
        Check(
            "version",
            "pass" if facade == version else "fail",
            f"package={version}, facade={facade}",
            "Make pyproject.toml and ai_resource_radar.__version__ identical.",
        )
    )

    identity = (_config(root, "user.name"), _config(root, "user.email"))
    checks.append(
        Check(
            "identity",
            "pass" if identity == (EXPECTED_NAME, EXPECTED_EMAIL) else "fail",
            "Larry noreply identity is configured" if identity == (EXPECTED_NAME, EXPECTED_EMAIL) else "unexpected Git identity",
            "Set the repository-local Larry name and GitHub noreply email.",
        )
    )
    signing_key = Path(_config(root, "user.signingkey")).expanduser()
    signing_ok = (
        _config(root, "gpg.format") == "ssh"
        and _config(root, "commit.gpgsign").casefold() == "true"
        and _config(root, "tag.gpgsign").casefold() == "true"
        and signing_key.is_file()
        and signing_key.suffix == ".pub"
    )
    checks.append(
        Check(
            "signing",
            "pass" if signing_ok else "fail",
            "SSH commit and tag signing are enforced" if signing_ok else "SSH signing configuration is incomplete",
            "Configure gpg.format=ssh, commit.gpgsign=true, tag.gpgsign=true, and a public signing-key path.",
        )
    )
    verified = _run(root, "git", "verify-commit", "HEAD", check=False).returncode == 0
    checks.append(
        Check(
            "head_signature",
            "pass" if verified else "fail",
            "HEAD signature verifies" if verified else "HEAD signature did not verify",
            "Create the release commit with the Larry SSH signing key.",
        )
    )
    local_tag = _git(root, "tag", "--list", tag)
    checks.append(
        Check(
            "local_tag",
            "pass" if not local_tag else "fail",
            f"{tag} is available locally" if not local_tag else f"{tag} already exists locally",
            "Bump the package version; never overwrite a published tag.",
        )
    )
    return tag, checks


def online_checks(root: Path, tag: str) -> list[Check]:
    checks: list[Check] = []
    if not shutil.which("gh"):
        return [Check("github_auth", "fail", "GitHub CLI is unavailable", "Install gh and authenticate once with larrynode.")]

    user = _run(root, "gh", "api", "user", "--jq", ".login", check=False)
    login = user.stdout.strip() if user.returncode == 0 else ""
    checks.append(
        Check(
            "github_auth",
            "pass" if login == EXPECTED_LOGIN else "fail",
            "GitHub CLI uses larrynode from the keyring" if login == EXPECTED_LOGIN else "GitHub CLI is not authenticated as larrynode",
            "Run gh auth login once and keep the credential in the macOS keyring.",
        )
    )

    head = _git(root, "rev-parse", "HEAD")
    remote = _git(root, "ls-remote", "origin", "refs/heads/main", check=False).split()
    remote_head = remote[0] if remote else ""
    checks.append(
        Check(
            "remote_main",
            "pass" if remote_head == head else "fail",
            "origin/main matches HEAD" if remote_head == head else "origin/main does not match HEAD",
            "Push main and wait for CI before creating the release tag.",
        )
    )
    remote_tag = _git(root, "ls-remote", "--tags", "origin", f"refs/tags/{tag}", check=False)
    checks.append(
        Check(
            "remote_tag",
            "pass" if not remote_tag else "fail",
            f"{tag} is available on GitHub" if not remote_tag else f"{tag} already exists on GitHub",
            "Bump the package version; never overwrite a published tag.",
        )
    )

    version = tag.removeprefix("v")
    url = f"https://pypi.org/pypi/ai-resource-radar/{version}/json"
    request = urllib.request.Request(url, headers={"User-Agent": "AIResourceRadar release-preflight"})
    try:
        with urllib.request.urlopen(request, timeout=15):
            exists = True
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        exists = False
    checks.append(
        Check(
            "pypi_version",
            "pass" if not exists else "fail",
            f"{version} is available on PyPI" if not exists else f"{version} already exists on PyPI",
            "Bump the package version; PyPI files cannot be replaced.",
        )
    )
    return checks


def run_full_checks(root: Path) -> list[Check]:
    commands: list[tuple[str, tuple[str, ...]]] = [
        ("python_tests", (sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py")),
        ("compileall", (sys.executable, "-m", "compileall", "-q", "src")),
    ]
    javascript = sorted(
        p for directory in ("web", "public_web", "frontend_shared")
        for p in (root / "src/ai_resource_radar" / directory).rglob("*.js")
    )
    if javascript and not shutil.which("node"):
        return [Check("javascript", "fail", "Node.js is unavailable", "Install Node.js for syntax checks.")]
    commands.extend((f"javascript:{path.relative_to(root)}", ("node", "--check", str(path))) for path in javascript)

    checks: list[Check] = []
    for identifier, command in commands:
        result = _run(root, *command, check=False)
        checks.append(
            Check(
                identifier,
                "pass" if result.returncode == 0 else "fail",
                "check passed" if result.returncode == 0 else "check failed",
                (result.stderr or result.stdout)[-400:].strip() if result.returncode else "",
            )
        )
        if result.returncode:
            break
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--online", action="store_true", help="read-only GitHub and PyPI checks")
    parser.add_argument("--full", action="store_true", help="run the complete deterministic test suite")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.repository.expanduser().resolve()

    try:
        tag, checks = local_checks(root)
        if args.online:
            checks.extend(online_checks(root, tag))
        if args.full:
            checks.extend(run_full_checks(root))
    except (OSError, ValueError, subprocess.SubprocessError, urllib.error.URLError) as exc:
        checks = [Check("preflight", "fail", type(exc).__name__, str(exc))]
        tag = "unknown"

    payload = {
        "status": "pass" if checks and all(item.status == "pass" for item in checks) else "fail",
        "target_tag": tag,
        "online": args.online,
        "full": args.full,
        "checks": [asdict(item) for item in checks],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"release_preflight={payload['status']} target={tag}")
        for item in checks:
            print(f"{item.status:>4}  {item.id}: {item.summary}")
            if item.status != "pass" and item.remediation:
                print(f"      remediation: {item.remediation}")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
