import itertools
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / ".pipelines" / "examples" / "api-ops"
HELPERS = ROOT / ".pipelines" / "helpers" / "api-ops"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def evaluate(expression, variables, dependency="succeeded"):
    """Evaluate only the expression subset used by these example variables."""
    expression = expression.strip()
    if expression.startswith("$["):
        expression = expression[2:-1]
    token_pattern = re.compile(r"variables\['[^']+'\]|'[^']*'|[A-Za-z]+|[(),]")
    tokens = []
    end = 0
    for match in token_pattern.finditer(expression):
        if expression[end:match.start()].strip():
            raise ValueError(f"Unsupported expression: {expression}")
        tokens.append(match.group())
        end = match.end()
    if expression[end:].strip():
        raise ValueError(f"Unsupported expression: {expression}")
    functions = {
        "and": lambda *args: all(args),
        "eq": lambda a, b: a == b,
        "in": lambda value, *choices: value in choices,
        "iif": lambda condition, yes, no: yes if condition else no,
        "not": lambda value: not value,
        "succeeded": lambda: dependency == "succeeded",
        "failed": lambda: dependency == "failed",
        "canceled": lambda: dependency == "canceled",
    }
    position = 0

    def parse():
        nonlocal position
        token = tokens[position]
        position += 1
        if token.startswith("variables["):
            return variables.get(token[11:-2], "")
        if token.startswith("'"):
            return token[1:-1]
        if token in ("true", "false"):
            return token == "true"
        if tokens[position] != "(":
            raise ValueError("Expected opening parenthesis")
        position += 1
        args = []
        while tokens[position] != ")":
            args.append(parse())
            if tokens[position] == ",":
                position += 1
            elif tokens[position] != ")":
                raise ValueError("Expected comma or closing parenthesis")
        position += 1
        return functions[token](*args)

    result = parse()
    if position != len(tokens):
        raise ValueError("Unconsumed expression tokens")
    return result


def select_environment(data, variables):
    definition = next(v for v in data["variables"] if v["name"] == "environment")
    if "value" in definition:
        return evaluate(definition["value"], variables)
    for key, branch in definition.items():
        if key == "${{ else }}":
            return branch["value"]
        match = re.fullmatch(r"\$\{\{ (?:if|elseif) (.+) \}\}", key)
        if match and evaluate(match[1], variables):
            return branch["value"]
    raise ValueError("No matching environment definition")


def target_stage_call():
    wrapper = load(HELPERS / "api-ops-ci.yaml")
    branch = wrapper["stages"][0]["${{ if gt(length(parameters.validationTargets), 0) }}"]
    return branch[0]["${{ each target in parameters.validationTargets }}"][0]


class ApiOpsExamplesTests(unittest.TestCase):
    def test_examples_extend_common_templates_with_resolvable_connections(self):
        for kind in ("ci", "cd"):
            data = load(EXAMPLES / f"azure-pipelines-{kind}.yaml")
            self.assertNotIn("stages", data)
            self.assertNotIn("jobs", data)
            self.assertEqual(data["extends"]["template"],
                             f"/.pipelines/{kind}-template.yaml@templates")
            common = load(ROOT / ".pipelines" / f"{kind}-template.yaml")
            dispatch = common["stages"][0]["${{ each project in parameters.projects }}"]
            api_ops = next(entry["${{ if eq(project.projectType, 'api-ops') }}"]
                           for entry in dispatch
                           if "${{ if eq(project.projectType, 'api-ops') }}" in entry)
            self.assertEqual(api_ops[0]["parameters"]["projectSpecs"],
                             "${{ project.projectSpecs }}")
            projects = data["extends"]["parameters"]["projects"]
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["name"], "apiops")
            self.assertEqual([v["name"] for v in data["variables"]], ["environment"])
            self.assertNotIn("condition", projects[0]["projectSpecs"])
            for project in projects:
                self.assertEqual(project["projectType"], "api-ops")
                self.assertNotIn("$", project["name"])
            if kind == "ci":
                self.assertEqual(
                    api_ops[0]["parameters"]["validationTargets"],
                    "${{ coalesce(project.projectSpecs.validationTargets, parameters.emptyDependencyList) }}",
                )
                specs = projects[0]["projectSpecs"]
                self.assertEqual(specs["environment"], "$(environment)")
                self.assertEqual(specs["resourceGroupName"], "rg-apiops-$(environment)")
                self.assertEqual(specs["apimServiceName"], "apim-apiops-$(environment)")
                self.assertEqual(specs["configurationFilePath"],
                                 "configuration.$(environment).yaml")
                self.assertEqual(specs["validationTargets"], [
                    {"environment": target, "serviceConnectionName": f"sc-apiops-{target}",
                     "planEnvironment": f"apiops-plan-{target}"}
                    for target in ("dev", "stage")
                ])
            else:
                self.assertEqual(projects[0]["name"], "apiops")
                specs = projects[0]["projectSpecs"]
                self.assertNotIn("condition", specs)
                self.assertEqual(specs["environment"], "${{ variables.environment }}")
                self.assertEqual(specs["serviceConnectionName"],
                                 "sc-apiops-${{ variables.environment }}")
                self.assertEqual(specs["resourceGroupName"],
                                 "rg-apiops-${{ variables.environment }}")
                self.assertEqual(specs["apimServiceName"],
                                 "apim-apiops-${{ variables.environment }}")
                self.assertEqual(specs["configurationFilePath"],
                                 "configuration.${{ variables.environment }}.yaml")
                self.assertEqual(specs["planEnvironment"],
                                 "apiops-plan-${{ variables.environment }}")
                self.assertEqual(specs["deployEnvironment"],
                                 "apiops-${{ variables.environment }}")
                self.assertEqual([v["name"] for v in data["variables"]], ["environment"])
            self.assertEqual(data["pr"] if kind == "cd" else data["trigger"], "none")
            branches = data["trigger"] if kind == "cd" else data["pr"]
            self.assertEqual(branches["branches"]["include"], ["dev", "stage"])

    def test_routing_matrix_and_skipped_siblings(self):
        reasons = ("PullRequest", "Manual", "IndividualCI", "BatchedCI",
                   "Schedule", "ResourceTrigger", "BuildCompletion")
        sources = ("refs/heads/dev", "refs/heads/stage", "refs/heads/main",
                   "refs/heads/feature/example", "refs/pull/42/merge")
        destinations = ("", "dev", "stage", "refs/heads/dev",
                        "refs/heads/stage", "refs/heads/main")
        condition = target_stage_call()["parameters"]["target"]["condition"].replace(
            "${{ coalesce(parameters.projectSpecs.condition, 'true') }}", "true")
        for kind in ("ci", "cd"):
            data = load(EXAMPLES / f"azure-pipelines-{kind}.yaml")
            targets = ("dev", "stage") if kind == "ci" else ("dev", "stage", "prod")
            for reason, source, destination in itertools.product(
                    reasons, sources, destinations):
                variables = {
                    "Build.Reason": reason,
                    "Build.SourceBranch": source,
                    "System.PullRequest.TargetBranch": destination,
                }
                expected = "none"
                if kind == "ci" and reason == "PullRequest":
                    for target in targets:
                        if destination in (target, f"refs/heads/{target}"):
                            expected = target
                elif kind == "cd":
                    if reason == "Manual":
                        expected = "prod"
                    elif reason in ("IndividualCI", "BatchedCI"):
                        for target in ("dev", "stage"):
                            if source == f"refs/heads/{target}":
                                expected = target
                variables["environment"] = select_environment(data, variables)
                self.assertEqual(variables["environment"], expected)
                if kind == "cd":
                    specs = data["extends"]["parameters"]["projects"][0]["projectSpecs"]
                    connection = specs["serviceConnectionName"].replace(
                        "${{ variables.environment }}", variables["environment"])
                    self.assertEqual(connection, f"sc-apiops-{expected}")
                    self.assertNotIn("$", connection)
                    continue
                for dependency in ("succeeded", "skipped", "failed", "canceled"):
                    selected = [
                        target for target in targets
                        if evaluate(condition.replace("${{ target.environment }}", target),
                                    variables, dependency)
                    ]
                    wanted = [expected] if (
                        expected != "none" and dependency in ("succeeded", "skipped")
                    ) else []
                    self.assertEqual(selected, wanted,
                                     (kind, reason, source, destination, dependency))

    def test_helper_conditions_preserve_defaults_and_require_successful_plan(self):
        ci = load(HELPERS / "api-ops-ci-stage.yaml")["stages"][0]
        cd = load(HELPERS / "api-ops.yaml")["stages"]
        plan = cd[0]["${{ if eq(parameters.skipPlanStage, false) }}"][0]
        publish = cd[1]
        gate = "${{ coalesce(parameters.target.condition, parameters.projectSpecs.condition, 'succeeded()') }}"
        self.assertEqual(ci["condition"], gate)
        self.assertNotIn("condition", plan)
        self.assertNotIn("condition", publish)
        self.assertEqual(
            publish["${{ if eq(parameters.skipPlanStage, false) }}"]["dependsOn"],
            "${{ coalesce(parameters.planStageName, format('plan_{0}', parameters.name)) }}",
        )
        for dependency in ("succeeded", "skipped", "failed", "canceled"):
            expected = dependency == "succeeded"
            self.assertEqual(evaluate("succeeded()", {}, dependency), expected)

    def test_ci_wrapper_preserves_single_connection_callers(self):
        wrapper = load(HELPERS / "api-ops-ci.yaml")
        defaults = {p["name"]: p.get("default") for p in wrapper["parameters"]}
        self.assertEqual(defaults["validationTargets"], [])
        fallback = wrapper["stages"][1]["${{ else }}"][0]
        self.assertEqual(fallback["template"], "api-ops-ci-stage.yaml")
        for name in ("name", "dependencies", "projectSpecs", "planStageName",
                     "planStageDisplayName", "planEnvironment", "poolName"):
            self.assertEqual(fallback["parameters"][name], "${{ parameters." + name + " }}")
        self.assertNotIn("target", fallback["parameters"])
        stage_template = load(HELPERS / "api-ops-ci-stage.yaml")
        declared = {p["name"]: p for p in stage_template["parameters"]}
        self.assertEqual(declared["target"]["default"], {})
        for call in (fallback, target_stage_call()):
            self.assertLessEqual(set(call["parameters"]), set(declared))
            self.assertLessEqual({name for name, p in declared.items() if "default" not in p},
                                 set(call["parameters"]))
        mapped = target_stage_call()["parameters"]
        self.assertEqual(
            mapped["target"]["serviceConnectionName"], "${{ target.serviceConnectionName }}")
        self.assertEqual(
            mapped["planStageName"],
            "${{ format('{0}_{1}', coalesce(parameters.planStageName, format('plan_{0}', parameters.name)), target.environment) }}",
        )
        job = stage_template["stages"][0]["jobs"][0]
        self.assertEqual(job["environment"],
                         "${{ coalesce(parameters.target.planEnvironment, parameters.projectSpecs.planEnvironment, parameters.planEnvironment) }}")
        plan = job["strategy"]["runOnce"]["deploy"]["steps"][0]
        self.assertEqual(plan["template"], "plan.yaml")
        self.assertEqual(
            plan["parameters"]["serviceConnectionName"],
            "${{ coalesce(parameters.target.serviceConnectionName, parameters.projectSpecs.serviceConnectionName) }}",
        )
        self.assertEqual(
            plan["parameters"]["environment"],
            "${{ coalesce(parameters.target.environment, parameters.projectSpecs.environment, 'dev') }}",
        )


if __name__ == "__main__":
    unittest.main()
