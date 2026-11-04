from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / ".pipelines" / "helpers" / "api-ops-cli"
TEMPLATES = ("plan.yaml", "publish.yaml")


def inspection_script(template):
    content = yaml.safe_load((HELPERS / template).read_text(encoding="utf-8"))
    step = next(step for step in content["steps"]
                if step.get("displayName") == "Inspect APIM artifacts folder")
    return step["inputs"]["script"]


class FolderInspectionTests(unittest.TestCase):
    def run_inspection(self, template, folders=(), missing=False):
        with tempfile.TemporaryDirectory(prefix="apiops-inspection-") as directory:
            base = Path(directory)
            artifacts = base / "consumer artifacts"
            if not missing:
                artifacts.mkdir()
                (artifacts / "configuration.dev.yaml").write_text("", encoding="utf-8")
                for name in folders:
                    (artifacts / name).mkdir()
            script = inspection_script(template)
            script = script.replace("$(Build.SourcesDirectory)", str(base))
            script = script.replace("${{ parameters.artifactsFolderPath }}", artifacts.name)
            script_path = base / "inspect.ps1"
            script_path.write_text(script, encoding="utf-8")
            return subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script_path)],
                capture_output=True, text=True,
            )

    def test_existing_directory_with_zero_one_or_multiple_subfolders(self):
        for template in TEMPLATES:
            for folders in ((), ("products",), ("products", "apis", "namedValues")):
                with self.subTest(template=template, folders=folders):
                    result = self.run_inspection(template, folders)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, "")
                    self.assertIn("Inspection complete.", result.stdout)
                    listed = [line.strip() for line in result.stdout.splitlines()
                              if line.strip().startswith("- ")]
                    self.assertCountEqual(listed, [f"- {name}" for name in folders])
                    self.assertEqual("No subfolders found under" in result.stdout,
                                     not bool(folders))

    def test_missing_source_directory_fails(self):
        for template in TEMPLATES:
            with self.subTest(template=template):
                result = self.run_inspection(template, missing=True)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Cannot find path", result.stderr)
                self.assertNotIn("No subfolders found under", result.stdout)
                self.assertNotIn("Inspection complete.", result.stdout)


if __name__ == "__main__":
    unittest.main()
