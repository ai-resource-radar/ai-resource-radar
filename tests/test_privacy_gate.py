import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("privacy_gate", ROOT / ".github/scripts/privacy_gate.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrivacyGateTests(unittest.TestCase):
    def test_current_public_tree_has_no_personal_metadata(self) -> None:
        errors = MODULE.check(ROOT, check_commit=False)
        self.assertNotIn("pyproject_author_email_present", errors)
        self.assertNotIn("pyproject_author_is_not_project_identity", errors)
        self.assertNotIn("personal_email_pattern:pyproject.toml", errors)

    def test_ci_checks_pr_head_instead_of_temporary_merge_commit(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", workflow)

    def test_rejects_personal_email_and_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("contact person@example.net; local /Users/alice/project\n", encoding="utf-8")
            (root / "pyproject.toml").write_text('[project]\nauthors=[{name="AI Resource Radar contributors"}]\n', encoding="utf-8")
            errors = MODULE.check(root)
            self.assertTrue(any(error.startswith("personal_email_pattern") for error in errors))
            self.assertTrue(any(error.startswith("local_path_pattern") for error in errors))


if __name__ == "__main__":
    unittest.main()
