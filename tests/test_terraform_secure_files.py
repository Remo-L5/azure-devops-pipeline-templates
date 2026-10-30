import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / ".pipelines" / "helpers" / "terraform"


def load(name):
    return yaml.safe_load((HELPERS / name).read_text(encoding="utf-8"))


class SecureFilesTests(unittest.TestCase):
    def test_template_wiring(self):
        plan = load("terraform-plan.yaml")
        cd = load("terraform.yaml")
        ci = load("terraform-ci.yaml")
        for template in (plan, cd):
            parameter = next(p for p in template["parameters"]
                             if p["name"] == "terraformSecureFiles")
            self.assertEqual(parameter["default"], {})
        loop = plan["steps"][0]["${{ each secureFile in parameters.terraformSecureFiles }}"]
        task = loop[0]
        self.assertEqual(task["task"], "DownloadSecureFile@1")
        self.assertEqual(task["inputs"]["secureFile"], "${{ secureFile.value }}")
        mapping = {"root_path": "root file.cer", "other_path": "other.cer"}
        # Check the literal substitution contract, not Azure DevOps' template engine.
        refs = [task["name"].replace("${{ secureFile.key }}", key) for key in mapping]
        self.assertEqual(refs, ["tfSecureFile_root_path", "tfSecureFile_other_path"])
        self.assertEqual(len(set(refs)), 2)
        env = plan["steps"][1]["env"]
        self.assertEqual(
            env["${{ each secureFile in parameters.terraformSecureFiles }}"],
            {"TF_SECURE_FILE_${{ secureFile.key }}":
             "$(tfSecureFile_${{ secureFile.key }}.secureFilePath)"},
        )
        for template in (cd, ci):
            steps = template["stages"][0]["jobs"][-1 if template is ci else 0][
                "strategy"]["runOnce"]["deploy"]["steps"]
            call = next(s for s in steps if s.get("template") == "terraform-plan.yaml")
            self.assertIn("terraformSecureFiles", call["parameters"])
        self.assertNotIn("DownloadSecureFile", yaml.safe_dump(cd["stages"][1]))

    def run_plan(self, mapping=None, overrides=None, var_file="", additional=False,
                 missing=False, inside_workspace=False, terraform_exit=0):
        with tempfile.TemporaryDirectory(prefix="secure-files-test-") as directory:
            base = Path(directory)
            workspace = base / "workspace"
            module = workspace / "src"
            module.mkdir(parents=True)
            temp = base / "agent temp"
            temp.mkdir()
            capture = base / "args.json"
            env = os.environ.copy()
            env.update(
                PIPELINE_WORKSPACE=str(workspace), AGENT_TEMPDIRECTORY=str(temp),
                TERRAFORM_SECURE_FILES=json.dumps({} if mapping is None else mapping),
                TERRAFORM_OVERRIDE_VARS=json.dumps(overrides or {}),
                TERRAFORM_VAR_FILE_NAME=var_file, TERRAFORM_ACTION="apply",
                ADDITIONAL_VAR_FILES_DIRECTORY="extra" if additional else "",
                ADDITIONAL_VAR_FILES_PATTERN="*.tfvars", CAPTURE=str(capture),
                MOCK_TERRAFORM_EXIT=str(terraform_exit),
            )
            if isinstance(mapping, dict):
                for index, key in enumerate(mapping):
                    path = (module if inside_workspace else temp) / f"input {index}.txt"
                    if not missing:
                        path.write_text("synthetic public test data", encoding="utf-8")
                    env[f"TF_SECURE_FILE_{key}"] = str(path)
            if var_file:
                (module / var_file).write_text("", encoding="utf-8")
            if additional:
                (module / "extra").mkdir()
                (module / "extra" / "b.tfvars").write_text("", encoding="utf-8")
                (module / "extra" / "a.tfvars").write_text("", encoding="utf-8")
            script = load("terraform-plan.yaml")["steps"][1]["inputs"]["inlineScript"]
            script = script.replace("${{ parameters.rootModuleFolderRelativePath }}", ".")
            script = """
$ErrorActionPreference = 'Stop'
function az { '{"user":{"name":"test"},"id":"test","tenantId":"test"}' }
function terraform {
  ConvertTo-Json -InputObject @($args | ForEach-Object { $_ }) -Compress | Set-Content $env:CAPTURE
  $global:LASTEXITCODE = [int]$env:MOCK_TERRAFORM_EXIT
}
""" + script
            script_path = base / "plan.ps1"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script_path)],
                env=env, capture_output=True, text=True,
            )
            arguments = json.loads(capture.read_text(encoding="utf-8-sig")) if capture.exists() else None
            return result, arguments

    def test_empty_mapping_preserves_cli_overrides(self):
        result, args = self.run_plan(overrides={"enabled": True})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-var=enabled=true", args)
        result, args = self.run_plan(overrides={"enabled": True}, var_file="selected.tfvars")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("-var=enabled=true", args)
        self.assertIn("-var-file=selected.tfvars", args)

    def test_multiple_files_all_variable_modes(self):
        for var_file in ("", "selected.tfvars", "vending.auto.tfvars"):
            with self.subTest(var_file=var_file):
                result, args = self.run_plan(
                    {"root_path": "root.cer", "other_path": "other.cer"},
                    {"enabled": True}, var_file, additional=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(args[-2].startswith("-var=root_path=") or
                                args[-2].startswith("-var=other_path="))
                secure_args = args[-2:]
                self.assertEqual({arg.split("=")[1] for arg in secure_args},
                                 {"root_path", "other_path"})
                self.assertTrue(all("agent temp" in arg for arg in secure_args))
                self.assertTrue(any("a.tfvars" in arg for arg in args))
                self.assertTrue(any("b.tfvars" in arg for arg in args))
                self.assertEqual("-var=enabled=true" in args, not bool(var_file))
                if var_file == "selected.tfvars":
                    self.assertIn("-var-file=selected.tfvars", args)
                self.assertLess(
                    next(i for i, arg in enumerate(args) if "a.tfvars" in arg),
                    next(i for i, arg in enumerate(args) if "b.tfvars" in arg),
                )
                self.assertNotIn("synthetic public test data", result.stdout)
                self.assertNotIn("input 0.txt", result.stdout)
                self.assertNotIn("input 1.txt", result.stdout)

    def test_invalid_configuration_fails_before_terraform(self):
        cases = [
            {"mapping": ["root.cer"]},
            {"mapping": {"bad-key": "root.cer"}},
            {"mapping": {"root": ""}},
            {"mapping": {"root": 42}},
            {"mapping": {"root": "a", "ROOT": "b"}},
            {"mapping": {"root": "a"}, "overrides": {"root": "duplicate"}},
            {"mapping": {"root": "a"}, "missing": True},
            {"mapping": {"root": "a"}, "inside_workspace": True},
        ]
        for case in cases:
            with self.subTest(case=case):
                result, args = self.run_plan(**case)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(args)

    def test_terraform_failure_propagates(self):
        result, _ = self.run_plan(terraform_exit=7)
        self.assertEqual(result.returncode, 7)

    def test_real_terraform_validate_and_saved_plan_filebase64(self):
        with tempfile.TemporaryDirectory(prefix="terraform-filebase64-") as directory:
            base = Path(directory)
            data = base / "public input.txt"
            data.write_text("public test data", encoding="utf-8")
            (base / "main.tf").write_text(
                'variable "root_path" { type = string }\n'
                'output "encoded" { value = filebase64(var.root_path) }\n',
                encoding="utf-8",
            )

            def terraform(*args):
                result = subprocess.run(
                    ["terraform", f"-chdir={base}", *args],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            terraform("init", "-backend=false", "-input=false")
            terraform("validate")
            terraform("plan", "-input=false", "-out=tfplan", f"-var=root_path={data}")
            data.unlink()
            terraform("apply", "-input=false", "tfplan")
            self.assertEqual(json.loads(terraform("output", "-json"))["encoded"]["value"],
                             "cHVibGljIHRlc3QgZGF0YQ==")


if __name__ == "__main__":
    unittest.main()
