import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("privacy_gate", ROOT / ".github/scripts/privacy_gate.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    return result.stdout.strip()


def _git_repo() -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    _git(root, "init", "-q")
    (root / "pyproject.toml").write_text(
        '[project]\nname="privacy-test"\nversion="0.0.0"\nauthors=[{name="AI Resource Radar contributors"}]\n',
        encoding="utf-8",
    )
    base = _commit(root, "AI Resource Radar contributors", MODULE.LARRY_EMAIL, "AI Resource Radar contributors", MODULE.LARRY_EMAIL)
    return temporary, root, base


def _commit(root: Path, author_name: str, author_email: str, committer_name: str, committer_email: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": committer_name,
            "GIT_COMMITTER_EMAIL": committer_email,
        }
    )
    _git(root, "commit", "--allow-empty", "-qm", "test commit", env=env)
    return _git(root, "rev-parse", "HEAD")


class PrivacyGateTests(unittest.TestCase):
    def test_current_public_tree_has_no_personal_metadata(self) -> None:
        errors = MODULE.check(ROOT, check_commit=False)
        self.assertNotIn("pyproject_author_email_present", errors)
        self.assertNotIn("pyproject_author_is_not_project_identity", errors)
        self.assertNotIn("personal_email_pattern:pyproject.toml", errors)

    def test_ci_checks_pr_head_instead_of_temporary_merge_commit(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("github.event.pull_request.base.sha || github.event.before", workflow)
        self.assertIn("--base-sha", workflow)
        self.assertIn("--head-sha", workflow)
        self.assertIn("--actor", workflow)
        self.assertIn("github.ref_type", workflow)
        self.assertIn("--ref-type", workflow)
        self.assertIn("--default-branch", workflow)

    def test_rejects_personal_email_and_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("contact person@example.net; local /Users/alice/project\n", encoding="utf-8")
            (root / "pyproject.toml").write_text('[project]\nauthors=[{name="AI Resource Radar contributors"}]\n', encoding="utf-8")
            errors = MODULE.check(root)
            self.assertTrue(any(error.startswith("personal_email_pattern") for error in errors))
            self.assertTrue(any(error.startswith("local_path_pattern") for error in errors))

    def test_correct_larry_identity_is_accepted_for_a_commit_range(self) -> None:
        temporary, root, base = _git_repo()
        self.addCleanup(temporary.cleanup)
        head = _commit(root, "Larry", MODULE.LARRY_EMAIL, "Larry", MODULE.LARRY_EMAIL)

        errors = MODULE.check(root, base_sha=base, head_sha=head, actor="larrynode")

        self.assertEqual([], errors)

    def test_larry_real_email_is_rejected_but_external_real_email_is_allowed(self) -> None:
        temporary, root, base = _git_repo()
        self.addCleanup(temporary.cleanup)
        head = _commit(root, "Larry", "larry@example.net", "Larry", "larry@example.net")
        errors = MODULE.check(root, base_sha=base, head_sha=head, actor="contributor")
        self.assertTrue(any(error.startswith("larry_") for error in errors))

        temporary2, root2, base2 = _git_repo()
        self.addCleanup(temporary2.cleanup)
        head2 = _commit(root2, "External Contributor", "person@example.net", "External Contributor", "person@example.net")
        errors2 = MODULE.check(root2, base_sha=base2, head_sha=head2, actor="external")
        self.assertFalse(any(error.startswith("larry_") for error in errors2))
        self.assertFalse(any(error.startswith("commit_range_unavailable") for error in errors2))

    def test_hillary_is_not_mistaken_for_larry(self) -> None:
        temporary, root, base = _git_repo()
        self.addCleanup(temporary.cleanup)
        head = _commit(root, "Hillary", "hillary@example.net", "Hillary", "hillary@example.net")

        errors = MODULE.check(root, base_sha=base, head_sha=head, actor="external")

        self.assertFalse(any(error.startswith("larry_") for error in errors))

    def test_multi_commit_range_catches_an_earlier_impersonation(self) -> None:
        temporary, root, base = _git_repo()
        self.addCleanup(temporary.cleanup)
        _commit(root, "Larry", "larry@example.net", "Larry", "larry@example.net")
        head = _commit(root, "Larry", MODULE.LARRY_EMAIL, "Larry", MODULE.LARRY_EMAIL)

        errors = MODULE.check(root, base_sha=base, head_sha=head, actor="external")

        self.assertTrue(any(error.startswith("larry_") for error in errors))

    def test_larrynode_actor_requires_larry_committer_on_every_new_commit(self) -> None:
        temporary, root, base = _git_repo()
        self.addCleanup(temporary.cleanup)
        head = _commit(root, "External Contributor", "person@example.net", "Local Machine", "person@example.net")

        errors = MODULE.check(root, base_sha=base, head_sha=head, actor="larrynode")

        self.assertTrue(any(error.startswith("larrynode_committer_identity_mismatch") for error in errors))

    def test_tag_range_with_external_history_does_not_apply_actor_rule_to_history(self) -> None:
        temporary, root, _base = _git_repo()
        self.addCleanup(temporary.cleanup)
        _commit(root, "External Contributor", "person@example.net", "External Contributor", "person@example.net")
        head = _commit(root, "Larry", MODULE.LARRY_EMAIL, "Larry", MODULE.LARRY_EMAIL)

        errors = MODULE.check(root, base_sha="0" * 40, head_sha=head, actor="larrynode", ref_type="tag")

        self.assertFalse(any(error.startswith("larrynode_committer_identity_mismatch") for error in errors))
        self.assertFalse(any(error.startswith("commit_range_unavailable") for error in errors))

    def test_new_branch_range_checks_only_commits_after_default_branch(self) -> None:
        temporary, root, _base = _git_repo()
        self.addCleanup(temporary.cleanup)
        _commit(root, "External Contributor", "person@example.net", "External Contributor", "person@example.net")
        _git(root, "branch", "-M", "main")
        _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
        head = _commit(root, "External Contributor", "person@example.net", "External Contributor", "person@example.net")

        errors = MODULE.check(
            root,
            base_sha="0" * 40,
            head_sha=head,
            actor="larrynode",
            ref_type="branch",
            default_branch="main",
        )

        self.assertTrue(any(error.startswith("larrynode_committer_identity_mismatch") for error in errors))
        self.assertFalse(any(error.startswith("commit_range_unavailable") for error in errors))

    def test_source_and_config_leaks_are_rejected_without_commit_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("contact person@example.net\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src/leak.py").write_text("HOME = '/home/alice/project'\n", encoding="utf-8")
            (root / "setup.cfg").write_text("maintainer_email = owner@example.org\n", encoding="utf-8")
            (root / "pyproject.toml").write_text('[project]\nauthors=[{name="AI Resource Radar contributors"}]\n', encoding="utf-8")

            errors = MODULE.check(root, check_commit=False)

            self.assertTrue(any(error.startswith("personal_email_pattern") for error in errors))
            self.assertTrue(any(error.startswith("local_path_pattern") for error in errors))


if __name__ == "__main__":
    unittest.main()
