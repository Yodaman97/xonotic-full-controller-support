"""Real Git fixtures: dependency patches must be repeatable and preserve work."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "misc/tools/prepare-controller-deps.py"
spec = importlib.util.spec_from_file_location("prepare_deps", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "dependency"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Dependency test")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / "file.txt").write_text("before\n")
        self.git("add", "file.txt")
        self.git("commit", "-qm", "base")
        revision = self.git("rev-parse", "HEAD").strip()
        (self.repo / "file.txt").write_text("after\n")
        (self.repo / "new.txt").write_text("new module\n")
        self.git("add", "-N", "new.txt")
        patch = subprocess.check_output(["git", "-C", str(self.repo), "diff", "--binary", "--full-index", "HEAD"])
        # These resets affect only this test's disposable fixture.
        self.git("reset", "--hard", "HEAD")
        self.patch = self.root / "change.patch"
        self.patch.write_bytes(patch)
        self.dependency = dict(path="dependency", url=str(self.repo), revision=revision,
                               patch=str(self.patch), patch_sha256=hashlib.sha256(patch).hexdigest())

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def test_apply_then_verify_and_repeat(self):
        module.prepare(self.root, self.dependency, False)
        self.assertEqual((self.repo / "new.txt").read_text(), "new module\n")
        module.prepare(self.root, self.dependency, True)
        module.prepare(self.root, self.dependency, False)

    def test_refuse_modified_tracked_file(self):
        (self.repo / "file.txt").write_text("user work\n")
        with self.assertRaisesRegex(ValueError, "existing changes"):
            module.prepare(self.root, self.dependency, False)
        self.assertEqual((self.repo / "file.txt").read_text(), "user work\n")

    def test_refuse_untracked_file(self):
        (self.repo / "user.txt").write_text("preserve me\n")
        with self.assertRaisesRegex(ValueError, "untracked"):
            module.prepare(self.root, self.dependency, False)
        self.assertTrue((self.repo / "user.txt").exists())

    def test_refuse_bad_checksum(self):
        self.patch.write_bytes(self.patch.read_bytes() + b"corrupted")
        with self.assertRaisesRegex(ValueError, "checksum"):
            module.prepare(self.root, self.dependency, False)
        self.assertEqual((self.repo / "file.txt").read_text(), "before\n")

    def test_check_does_not_apply(self):
        with self.assertRaisesRegex(ValueError, "not been applied"):
            module.prepare(self.root, self.dependency, True)
        self.assertEqual((self.repo / "file.txt").read_text(), "before\n")

    def test_refuse_other_revision(self):
        self.git("commit", "--allow-empty", "-qm", "user commit")
        with self.assertRaisesRegex(ValueError, "differs from locked"):
            module.prepare(self.root, self.dependency, False)

    def test_fresh_clone(self):
        destination = self.root / "fresh"
        module.prepare(destination, self.dependency, False)
        module.prepare(destination, self.dependency, True)
        self.assertEqual((destination / "dependency/new.txt").read_text(), "new module\n")


class PatchStorageTests(unittest.TestCase):
    def test_locked_patch_bytes_survive_git_clean_filters(self):
        project = SCRIPT.parents[2]
        manifest = json.loads((project / "controller-dependencies.json").read_text())
        for entry in manifest["dependencies"]:
            if not entry.get("patch"):
                continue
            data = (project / entry["patch"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["patch_sha256"])
            stored = subprocess.check_output(
                ["git", "-C", str(project), "hash-object", "--stdin", "--path", entry["patch"]], input=data)
            raw = subprocess.check_output(
                ["git", "-C", str(project), "hash-object", "--stdin", "--no-filters"], input=data)
            self.assertEqual(stored, raw, "Git would change the locked patch bytes")


if __name__ == "__main__":
    unittest.main()
