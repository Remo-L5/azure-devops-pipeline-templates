import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / ".pipelines" / "helpers"
APP = [{"artifactName": "frontend", "role": "app"}]
BOTH = APP + [{"artifactName": "backend", "role": "api"}]
DEPLOY_CONDITION = "${{ if eq(parameters.validateOnly, false) }}"
ARTIFACT_LOOP = "${{ each artifact in parameters.artifacts }}"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class StaticWebAppTests(unittest.TestCase):
    def setUp(self):
        self.template = load(HELPERS / "static-web-app" / "deploy.yaml")
        self.steps = self.template["steps"]

    def run_script(self, script, env=None, prefix=""):
        with tempfile.TemporaryDirectory(prefix="swa-script-") as directory:
            path = Path(directory) / "test.ps1"
            path.write_text(prefix + script, encoding="utf-8")
            return subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(path)],
                env={**os.environ, **(env or {})},
                capture_output=True, text=True,
            )

    def configuration(self, artifacts, **changes):
        with tempfile.TemporaryDirectory(prefix="swa-config-") as directory:
            workspace = Path(directory)
            stale = workspace / "static-web-app" / "api" / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale", encoding="utf-8")
            unrelated = workspace / "unrelated.txt"
            unrelated.write_text("keep", encoding="utf-8")
            env = {
                "PIPELINE_WORKSPACE": str(workspace),
                "SWA_ARTIFACTS": json.dumps(artifacts),
                "SWA_SERVICE_CONNECTION": "test-connection",
                "SWA_NAME": "test-site",
                "SWA_RESOURCE_GROUP": "test-rg",
                "MOCK_LINUX": "true",
                **changes,
            }
            script = self.steps[0]["inputs"]["script"].replace(
                "if (-not $IsLinux)", "if ($env:MOCK_LINUX -ne 'true')"
            )
            result = self.run_script(script, env)
            self.assertTrue(unrelated.exists())
            return result, stale.exists()

    def test_artifact_roles_and_stale_cleanup(self):
        for artifacts in (APP, BOTH, list(reversed(BOTH))):
            with self.subTest(artifacts=artifacts):
                result, stale_exists = self.configuration(artifacts)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(stale_exists)

    def test_invalid_configuration_does_not_clean_workspace(self):
        invalid = [
            [], {}, None, "frontend", APP * 2, BOTH + APP,
            [{"artifactName": "backend", "role": "api"}],
            [{"artifactName": "", "role": "app"}],
            [{"artifactName": 42, "role": "app"}],
            [{"artifactName": "frontend", "role": "APP"}],
            [{"artifactName": "frontend", "role": "../app"}],
            [{"artifactName": "frontend"}],
            ["frontend"],
        ]
        for artifacts in invalid:
            with self.subTest(artifacts=artifacts):
                result, stale_exists = self.configuration(artifacts)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(stale_exists)
        for changes in ({"SWA_NAME": ""}, {"SWA_RESOURCE_GROUP": " "},
                        {"SWA_SERVICE_CONNECTION": ""}, {"MOCK_LINUX": "false"}):
            with self.subTest(changes=changes):
                result, stale_exists = self.configuration(APP, **changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(stale_exists)

    def test_prebuilt_artifact_layout(self):
        cases = [
            (APP, ["app/index.html"], True),
            (BOTH, ["app/index.html", "api/host.json", "api/package.json"], True),
            (APP, ["app/dist/index.html"], False),
            (BOTH, ["app/index.html", "api/package.json"], False),
            (BOTH, ["app/index.html", "api/host.json"], False),
            (BOTH, ["app/index.html", "api/dist/host.json",
                    "api/dist/package.json"], False),
        ]
        for artifacts, files, success in cases:
            with self.subTest(files=files), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "static-web-app"
                for name in files:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("{}", encoding="utf-8")
                result = self.run_script(self.steps[2]["inputs"]["script"], {
                    "PIPELINE_WORKSPACE": directory,
                    "SWA_ARTIFACTS": json.dumps(artifacts),
                })
                self.assertEqual(result.returncode == 0, success, result.stderr)

    def test_secret_lookup_and_failure_handling(self):
        script = self.steps[3][DEPLOY_CONDITION][0]["inputs"]["inlineScript"]
        prefix = """
$ErrorActionPreference = 'Stop'
function az {
    ConvertTo-Json -InputObject @($args) -Compress | Set-Content $env:CAPTURE
    $global:LASTEXITCODE = [int]$env:MOCK_AZ_EXIT
    if ($env:MOCK_TOKEN) { $env:MOCK_TOKEN }
}
"""
        for token, exit_code, success in [
            ("synthetic%token", 0, True), ("", 0, False),
            (" ", 0, False), ("bad`nkey", 0, True),
            ("bad\nkey", 0, False), ("synthetic-token", 7, False),
        ]:
            with self.subTest(token=token, exit_code=exit_code):
                with tempfile.TemporaryDirectory() as directory:
                    capture = Path(directory) / "args.json"
                    # Quotes and shell syntax must remain literal CLI arguments.
                    name = "test-site'; throw 'injected"
                    result = self.run_script(script, {
                        "SWA_NAME": name, "SWA_RESOURCE_GROUP": "test rg",
                        "MOCK_AZ_EXIT": str(exit_code), "MOCK_TOKEN": token,
                        "CAPTURE": str(capture),
                    }, prefix)
                    self.assertEqual(result.returncode == 0, success, result.stderr)
                    args = json.loads(capture.read_text(encoding="utf-8-sig"))
                    self.assertEqual(args, [
                        "staticwebapp", "secrets", "list", "--name", name,
                        "--resource-group", "test rg", "--query", "properties.apiKey",
                        "--output", "tsv", "--only-show-errors",
                    ])
                    if success:
                        lines = [line for line in result.stdout.splitlines() if line.strip()]
                        self.assertEqual(lines, [
                            "##vso[task.setvariable variable=staticWebAppDeploymentToken;"
                            "issecret=true;isReadOnly=true]" + token.replace("%", "%AZP25")
                        ])
                    else:
                        self.assertNotIn("##vso[task.setvariable", result.stdout)
                        self.assertNotIn("synthetic-token", result.stdout + result.stderr)

    def test_template_wiring_and_existing_publish_contracts(self):
        for filename, validate_only in (("cd-template.yaml", False),
                                        ("ci-template.yaml", True)):
            pipeline = load(ROOT / ".pipelines" / filename)
            projects = pipeline["stages"][0]["${{ each project in parameters.projects }}"]
            call = next(branch["${{ if eq(project.projectType, 'static-web-app') }}"][0]
                        for branch in projects
                        if "${{ if eq(project.projectType, 'static-web-app') }}" in branch)
            self.assertEqual(call["template"], "helpers/static-web-app/static-web-app.yaml")
            self.assertEqual(call["parameters"].get("validateOnly", False), validate_only)
            self.assertEqual(call["parameters"]["projectSpecs"], "${{ project.projectSpecs }}")
            self.assertIn("project.dependencies", call["parameters"]["dependencies"])

        stage = load(HELPERS / "static-web-app" / "static-web-app.yaml")
        job = stage["stages"][0]["jobs"][0]
        self.assertEqual(job["steps"][0], {"checkout": "none"})
        self.assertEqual(job["steps"][1]["parameters"]["validateOnly"],
                         "${{ parameters.validateOnly }}")
        self.assertEqual(job["steps"][1]["parameters"]["artifacts"],
                         "${{ parameters.projectSpecs.artifacts }}")
        download = self.steps[1][ARTIFACT_LOOP][0]
        self.assertEqual(download["task"], "DownloadPipelineArtifact@2")
        self.assertEqual(download["inputs"], {
            "buildType": "current",
            "artifactName": "${{ artifact.artifactName }}",
            "targetPath": "$(Pipeline.Workspace)/static-web-app/${{ artifact.role }}",
        })
        deploy_steps = self.steps[3][DEPLOY_CONDITION]
        self.assertEqual([step["task"] for step in deploy_steps],
                         ["AzureCLI@2", "AzureStaticWebApp@0"])
        self.assertEqual(deploy_steps[0]["inputs"]["azureSubscription"],
                         "${{ parameters.serviceConnectionName }}")
        inputs = deploy_steps[1]["inputs"]
        self.assertTrue(inputs["skip_app_build"])
        self.assertTrue(inputs["skip_api_build"])
        self.assertEqual(inputs["output_location"], "")
        self.assertEqual(inputs["app_location"], "app")
        self.assertEqual(inputs["azure_static_web_apps_api_token"],
                         "$(staticWebAppDeploymentToken)")
        self.assertNotIn("api_location", inputs)
        self.assertEqual(inputs[ARTIFACT_LOOP]["${{ if eq(artifact.role, 'api') }}"],
                         {"api_location": "api"})
        self.assertEqual(inputs["deployment_environment"],
                         "${{ parameters.deploymentEnvironment }}")
        for helper, default_path in (("react", "./frontend/dist"),
                                     ("nodejs", "./backend/dist")):
            build = load(HELPERS / helper / f"{helper}.yaml")
            steps = build["stages"][0]["jobs"][0]["steps"]
            publish = steps[-1][
                "${{ if ne(coalesce(parameters.projectSpecs.publishArtifact, true), false) }}"
            ][0]
            self.assertEqual(publish["task"], "PublishPipelineArtifact@1")
            self.assertEqual(publish["inputs"]["targetPath"],
                             "${{ coalesce(parameters.projectSpecs.artifactPath, '"
                             + default_path + "') }}")
            self.assertEqual(publish["inputs"]["artifact"],
                             "${{ coalesce(parameters.projectSpecs.artifactName, parameters.name) }}")


if __name__ == "__main__":
    unittest.main()
