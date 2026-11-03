import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from template_preview import ROOT, expand


HELPERS = ROOT / ".pipelines" / "helpers"


def script(path, index=0):
    template = yaml.safe_load(path.read_text(encoding="utf-8"))
    return template["steps"][index]["inputs"]["script"]


def run_ps(content, env):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "test.ps1"
        path.write_text(content, encoding="utf-8")
        return subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(path)], capture_output=True,
            text=True, env={**os.environ, **env},
        )


def job_steps(job):
    return job.get("steps") or job["strategy"]["runOnce"]["deploy"]["steps"]


class ApplicationTemplateTests(unittest.TestCase):
    def projects(self, environment="", packaging=True):
        return [
            {"name": "frontend", "projectType": "react", "projectSpecs": {
                "installCommand": "ci", "lintScript": "lint", "typeCheckScript": "typecheck",
            }},
            {"name": "backend", "projectType": "nodejs", "projectSpecs": {
                "packageFunctions": packaging, "installCommand": "ci",
            }},
            {"name": "deploy_site", "projectType": "static-web-app",
             "dependencies": ["frontend", "backend"], "projectSpecs": {
                 "serviceConnectionName": "test-sc", "staticWebAppName": "test-site",
                 "resourceGroupName": "test-rg", "azureDevOpsEnvironment": environment,
                 "artifacts": [{"role": "app", "artifactName": "frontend"},
                               {"role": "api", "artifactName": "backend"}],
             }},
        ]

    def test_expanded_parallel_build_and_join_contract(self):
        for entry in ("ci-template.yaml", "cd-template.yaml"):
            for environment in ("", "production"):
                with self.subTest(entry=entry, environment=environment):
                    pipeline = expand(ROOT / ".pipelines" / entry,
                                      {"projects": self.projects(environment)})
                    stages = pipeline["stages"]
                    self.assertEqual([stage["dependsOn"] for stage in stages],
                                     [[], [], ["frontend", "backend"]])
                    steps = stages[0]["jobs"][0]["steps"]
                    commands = [step["script"] for step in steps if "script" in step]
                    self.assertEqual(commands[:4],
                                     ["npm ci\n", "npm run lint", "npm run typecheck",
                                      "npm run build\n"])
                    node_steps = stages[1]["jobs"][0]["steps"]
                    publish = next(step for step in node_steps
                                   if step.get("task") == "PublishPipelineArtifact@1")
                    self.assertEqual(publish["inputs"]["targetPath"],
                                     "$(Build.ArtifactStagingDirectory)/functions")
                    self.assertIn("npm ci --omit=dev",
                                  [step.get("script") for step in node_steps])
                    job = stages[2]["jobs"][0]
                    deploy = entry.startswith("cd-")
                    self.assertEqual("deployment" in job, bool(environment) and deploy)
                    if environment and deploy:
                        self.assertEqual(job["environment"], environment)
                        self.assertEqual(job_steps(job)[0], {"download": "none"})
                    tasks = [step.get("task") for step in job_steps(job)]
                    self.assertEqual("AzureStaticWebApp@0" in tasks, deploy)
                    self.assertEqual("AzureCLI@2" in tasks, deploy)
                    self.assertIn("Validate Node.js Functions package",
                                  [step.get("displayName") for step in job_steps(job)])

    def test_existing_build_defaults_and_explicit_dependencies(self):
        for helper, artifact in (("react", "./frontend/dist"), ("nodejs", "./backend/dist")):
            stage = expand(HELPERS / helper / f"{helper}.yaml", {
                "name": helper, "dependencies": ["infra"],
            })["stages"][0]
            self.assertEqual(stage["dependsOn"], ["infra"])
            steps = stage["jobs"][0]["steps"]
            self.assertEqual(next(step["script"] for step in steps if "script" in step),
                             "npm install\n")
            self.assertEqual(steps[-1]["inputs"]["targetPath"], artifact)
            self.assertFalse(any(step.get("displayName", "").endswith(("lint", "type check"))
                                 for step in steps))

    def test_custom_functions_files_and_flex_deployment(self):
        projects = self.projects(environment="production")
        projects[1]["projectSpecs"]["functionPackageFiles"] = [
            "host.json", "package.json", "package-lock.json", "dist", "assets",
        ]
        projects.append({
            "name": "standalone", "projectType": "function-app",
            "dependencies": ["backend"], "projectSpecs": {
                "serviceConnectionName": "sc", "appName": "function-app",
                "artifactName": "backend", "isFlexConsumption": True,
            },
        })
        stages = expand(ROOT / ".pipelines" / "cd-template.yaml",
                        {"projects": projects})["stages"]
        staging = next(step for step in stages[1]["jobs"][0]["steps"]
                       if step.get("displayName") == "Stage Node.js Functions package")
        self.assertIn("assets", json.loads(staging["env"]["FUNCTIONS_FILES"]))
        job = stages[-1]["jobs"][0]
        inputs = next(step["inputs"] for step in job_steps(job)
                      if step.get("task") == "AzureFunctionApp@2")
        self.assertTrue(inputs["isFlexConsumption"])
        self.assertNotIn("deployToSlotOrASE", inputs)
        self.assertNotIn("runtimeStack", inputs)

    def test_build_publish_toggles_and_custom_artifact_paths(self):
        for helper in ("react", "nodejs"):
            for publish in (True, False):
                with self.subTest(helper=helper, publish=publish):
                    stage = expand(HELPERS / helper / f"{helper}.yaml", {
                        "name": helper, "projectSpecs": {
                            "publishArtifact": publish, "artifactPath": "./custom-output",
                            "artifactName": "custom-name", "buildDisplayName": "Custom build",
                            "playwrightInstall": False,
                        },
                    })["stages"][0]
                    steps = stage["jobs"][0]["steps"]
                    artifacts = [step for step in steps
                                 if step.get("task") == "PublishPipelineArtifact@1"]
                    self.assertEqual(len(artifacts), int(publish))
                    if publish:
                        self.assertEqual(artifacts[0]["inputs"]["targetPath"], "./custom-output")
                        self.assertEqual(artifacts[0]["inputs"]["artifact"], "custom-name")
                    self.assertIn("Custom build", [step.get("displayName") for step in steps])
                    self.assertNotIn("Install Playwright", [step.get("displayName") for step in steps])

    def test_python_and_standalone_backend_cd_ci(self):
        projects = [
            {"name": "python_build", "projectType": "python", "projectSpecs": {
                "testCommand": "python manage.py test",
                "buildCommand": "python manage.py collectstatic --noinput",
                "env": {"DJANGO_DEBUG": "False"},
            }},
        ]
        for kind in ("app-service", "function-app"):
            projects.append({
                "name": kind.replace("-", "_"), "projectType": kind,
                "dependencies": ["python_build"], "projectSpecs": {
                    "serviceConnectionName": "sc", "appName": "example-app",
                    "artifactName": "python_build", "azureDevOpsEnvironment": "production",
                    "resourceGroupName": "example-rg", "slotName": "staging",
                    "poolName": "private-network",
                },
            })
        for entry, deploy in (("cd-template.yaml", True), ("ci-template.yaml", False)):
            stages = expand(ROOT / ".pipelines" / entry, {"projects": projects})["stages"]
            build_steps = stages[0]["jobs"][0]["steps"]
            test = next(step for step in build_steps if step.get("displayName") == "Python - test")
            self.assertEqual(test["env"], {"DJANGO_DEBUG": "False"})
            self.assertEqual(build_steps[-1]["inputs"]["artifact"], "python_build")
            self.assertIn("!**/.env*", build_steps[-2]["inputs"]["Contents"])
            for stage, task in zip(stages[1:], ("AzureWebApp@1", "AzureFunctionApp@2")):
                self.assertEqual(stage["dependsOn"], ["python_build"])
                self.assertEqual(stage["pool"], {"name": "private-network"})
                job = stage["jobs"][0]
                tasks = [step.get("task") for step in job_steps(job)]
                self.assertEqual(task in tasks, deploy)
                self.assertEqual("deployment" in job, deploy)
                archive = next(step for step in job_steps(job) if step.get("task") == "ArchiveFiles@2")
                self.assertFalse(archive["inputs"]["includeRootFolder"])
                if deploy:
                    inputs = next(step["inputs"] for step in job_steps(job)
                                  if step.get("task") == task)
                    self.assertEqual(inputs["slotName"], "staging")
                    self.assertTrue(inputs["deployToSlotOrASE"])
        default = expand(HELPERS / "python" / "python.yaml", {"name": "python"})
        self.assertEqual(default["stages"][0]["dependsOn"], [])
        self.assertEqual(default["stages"][0]["jobs"][0]["steps"][2]["env"], {})


class FunctionsPackageTests(unittest.TestCase):
    def fixture(self, root, main="dist/functions/*.js", dependency=True):
        (root / "dist" / "functions").mkdir(parents=True)
        (root / "dist" / "functions" / "hello.js").write_text("module.exports = {}")
        (root / "host.json").write_text('{"version":"2.0"}')
        (root / "package.json").write_text(json.dumps({
            "main": main, "dependencies": {"@azure/functions": "4.0.0"} if dependency else {},
        }))
        (root / "package-lock.json").write_text("{}")
        dep = root / "node_modules" / "@azure" / "functions"
        dep.mkdir(parents=True)
        (dep / "package.json").write_text('{"version":"4.0.0"}')

    def test_functions_layout_v4_globs_and_v3(self):
        validator = script(HELPERS / "nodejs" / "validate-functions.yaml")
        for main in ("dist/functions/*.js", "dist/{index.js,functions/*.js}", None):
            with self.subTest(main=main), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root, main)
                if main is None:
                    function = root / "hello"
                    function.mkdir()
                    (function / "function.json").write_text(
                        '{"scriptFile":"../dist/functions/hello.js"}')
                result = run_ps(validator, {"FUNCTIONS_DIRECTORY": directory})
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_dependencies_entrypoints_and_invalid_metadata_fail(self):
        validator = script(HELPERS / "nodejs" / "validate-functions.yaml")
        for invalid in ("entrypoint", "dependency", "host", "manifest", "traversal", "typescript"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                if invalid == "entrypoint":
                    (root / "dist" / "functions" / "hello.js").unlink()
                elif invalid == "dependency":
                    (root / "node_modules" / "@azure" / "functions" / "package.json").unlink()
                elif invalid == "host":
                    (root / "host.json").write_text("{}")
                elif invalid == "manifest":
                    (root / "package.json").write_text("invalid json")
                elif invalid == "traversal":
                    (root / "package.json").write_text('{"main":"../outside.js"}')
                else:
                    (root / "package.json").write_text('{"main":"dist/functions/*.ts"}')
                    (root / "dist" / "functions" / "hello.ts").write_text("export {}")
                result = run_ps(validator, {"FUNCTIONS_DIRECTORY": directory})
                self.assertNotEqual(result.returncode, 0)

    def test_curated_staging_excludes_development_inputs(self):
        staging = script(HELPERS / "nodejs" / "package-functions.yaml")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, output = base / "source", base / "output"
            self.fixture(source)
            (source / "local.settings.json").write_text('{"local":true}')
            (source / ".env").write_text("LOCAL_ONLY=yes")
            (source / "tests").mkdir()
            (source / "tests" / "test.js").write_text("test")
            output.mkdir()
            files = ["host.json", "package.json", "package-lock.json", "dist"]
            result = run_ps(staging, {
                "FUNCTIONS_SOURCE": str(source), "BUILD_ARTIFACTSTAGINGDIRECTORY": str(output),
                "FUNCTIONS_FILES": json.dumps(files),
            })
            self.assertEqual(result.returncode, 0, result.stderr)
            packaged = sorted(str(path.relative_to(output / "functions")).replace("\\", "/")
                              for path in (output / "functions").rglob("*") if path.is_file())
            self.assertEqual(packaged, [
                "dist/functions/hello.js", "host.json", "package-lock.json", "package.json",
            ])
            self.assertTrue((source / "node_modules" / "@azure" / "functions" / "package.json").exists())
            for invalid in (["."], ["../source"], ["local.settings.json"], ["missing"],
                            ["node_modules"], ["dist", ".env"], []):
                result = run_ps(staging, {
                    "FUNCTIONS_SOURCE": str(source), "BUILD_ARTIFACTSTAGINGDIRECTORY": str(output),
                    "FUNCTIONS_FILES": json.dumps(invalid),
                })
                self.assertNotEqual(result.returncode, 0, invalid)

    def test_real_locked_production_install_and_load(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, output = base / "source", base / "output"
            self.fixture(source, main="dist/functions/hello.js", dependency=False)
            for name in ("runtime-fixture", "dev-fixture"):
                vendor = source / "vendor" / name
                vendor.mkdir(parents=True)
                (vendor / "package.json").write_text(json.dumps({
                    "name": name, "version": "1.0.0", "main": "index.js",
                }))
                (vendor / "index.js").write_text("module.exports = 42;")
            (source / "package.json").write_text(json.dumps({
                "name": "functions-fixture", "version": "1.0.0",
                "main": "dist/functions/hello.js",
                "dependencies": {"runtime-fixture": "file:vendor/runtime-fixture"},
                "devDependencies": {"dev-fixture": "file:vendor/dev-fixture"},
            }))
            (source / "package-lock.json").unlink()
            (source / "dist" / "functions" / "hello.js").write_text(
                "if (require('runtime-fixture') !== 42) process.exit(1);")
            env = {"FUNCTIONS_SOURCE": str(source),
                   "BUILD_ARTIFACTSTAGINGDIRECTORY": str(output),
                   "FUNCTIONS_FILES": json.dumps([
                       "host.json", "package.json", "package-lock.json", "dist", "vendor",
                   ])}
            result = run_ps("""
Set-Location -LiteralPath $env:FUNCTIONS_SOURCE
npm install --package-lock-only --ignore-scripts --offline --audit=false --fund=false
exit $LASTEXITCODE
""", env)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run_ps(script(HELPERS / "nodejs" / "package-functions.yaml"), env)
            self.assertEqual(result.returncode, 0, result.stderr)
            package = output / "functions"
            result = run_ps("""
Set-Location -LiteralPath $env:FUNCTIONS_DIRECTORY
npm ci --omit=dev --offline --audit=false --fund=false
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node dist/functions/hello.js
exit $LASTEXITCODE
""", {"FUNCTIONS_DIRECTORY": str(package)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((package / "node_modules" / "dev-fixture").exists())
            result = run_ps(script(HELPERS / "nodejs" / "validate-functions.yaml"),
                            {"FUNCTIONS_DIRECTORY": str(package)})
            self.assertEqual(result.returncode, 0, result.stderr)


class BackendRuntimeTests(unittest.TestCase):
    def test_configuration_rejects_incompatible_targets_before_cleanup(self):
        validation = script(HELPERS / "app-service" / "deploy.yaml")
        cases = [
            ({}, True),
            ({"BACKEND_FUNCTION_APP": "True", "BACKEND_APP_TYPE": "functionAppLinux"}, True),
            ({"BACKEND_SLOT": "staging", "BACKEND_RESOURCE_GROUP": "rg"}, True),
            ({"BACKEND_APP_NAME": ""}, False),
            ({"BACKEND_FUNCTION_APP": "True"}, False),
            ({"BACKEND_SLOT": "staging"}, False),
            ({"BACKEND_FLEX": "True"}, False),
            ({"BACKEND_FUNCTION_APP": "True", "BACKEND_APP_TYPE": "functionAppLinux",
              "BACKEND_STARTUP": "node server.js"}, False),
            ({"BACKEND_APP_TYPE": "webApp", "BACKEND_RUNTIME": "NODE|22-lts"}, False),
            ({"BACKEND_FUNCTION_APP": "True", "BACKEND_APP_TYPE": "functionAppLinux",
              "BACKEND_FLEX": "True", "BACKEND_SLOT": "staging",
              "BACKEND_RESOURCE_GROUP": "rg"}, False),
        ]
        for changes, valid in cases:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                stale = Path(directory) / "backend-deploy" / "stale.txt"
                stale.parent.mkdir()
                stale.write_text("stale")
                result = run_ps(validation, {
                    "PIPELINE_WORKSPACE": directory, "BACKEND_SERVICE_CONNECTION": "sc",
                    "BACKEND_APP_NAME": "app", "BACKEND_ARTIFACT": "backend",
                    "BACKEND_APP_TYPE": "webAppLinux", "BACKEND_FUNCTION_APP": "False",
                    "BACKEND_FLEX": "False", "BACKEND_SLOT": "", "BACKEND_RESOURCE_GROUP": "",
                    "BACKEND_STARTUP": "", "BACKEND_RUNTIME": "", **changes,
                })
                self.assertEqual(result.returncode == 0, valid, result.stderr)
                self.assertEqual(stale.exists(), not valid)

    def test_artifact_layout_and_function_host(self):
        validation = script(HELPERS / "app-service" / "deploy.yaml", 2)
        for files, functions, valid in [
            ({}, False, False), ({"app.zip": "zip"}, False, False),
            ({"manage.py": "# app", "requirements.txt": ""}, False, True),
            ({"host.json": '{"version":"2.0"}', "index.js": ""}, True, True),
            ({"dist/host.json": '{"version":"2.0"}'}, True, False),
            ({"host.json": "{}"}, True, False),
        ]:
            with self.subTest(files=files), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "backend-deploy" / "content"
                root.mkdir(parents=True)
                for name, content in files.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                result = run_ps(validation, {
                    "PIPELINE_WORKSPACE": directory, "BACKEND_FUNCTION_APP": str(functions),
                })
                self.assertEqual(result.returncode == 0, valid, result.stderr)


if __name__ == "__main__":
    unittest.main()
