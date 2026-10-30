# ALZ Management Templates

Reusable Azure DevOps pipeline templates for deploying Azure Landing Zone (ALZ) infrastructure and applications.

## Overview

This repository provides a modular, template-based approach to CI/CD pipelines for Azure deployments. It supports multiple project types including **Terraform**, **API Operations (APIOps)**, **.NET**, **Node.js**, and **React** applications—all orchestrated through a unified pipeline interface.

## Repository Structure

```
.pipelines/
├── cd-template.yaml          # Continuous Deployment template (main entry point)
├── ci-template.yaml          # Continuous Integration template
└── helpers/
    ├── api-ops/              # API Management Operations helpers
    │   ├── api-ops.yaml      # Stage definition for APIOps
    │   └── publish.yaml      # API publishing steps
    ├── dotnet/               # .NET application helpers
    │   └── dotnet.yaml       # Build and publish .NET projects
    ├── nodejs/               # Node.js application helpers
    │   └── nodejs.yaml       # Install, audit, build, and test Node.js projects
    ├── react/                # React application helpers
    │   └── react.yaml        # Install, audit, build, Playwright setup, and test React projects
    ├── powershell/           # Azure CLI-authenticated PowerShell helpers
    │   ├── azure-cli-powershell-check-apply.yaml # Check/apply stage workflow
    │   └── azure-cli-powershell-script.yaml      # Run a PowerShell script with an Azure service connection
    └── terraform/            # Terraform infrastructure helpers
        ├── terraform.yaml                  # Main Terraform stage (plan + apply)
        ├── terraform-init.yaml             # Backend initialization
        ├── terraform-plan.yaml             # Plan execution
        ├── terraform-apply.yaml            # Apply execution
        ├── terraform-workspace.yaml        # Workspace management
        ├── terraform-installer.yaml        # CLI installation
        ├── terraform-var-file-download.yaml# Variable file handling
        └── az-storage-table-get-record.yaml# Subscription vending support
```

## Templates

### CD Template (`cd-template.yaml`)

The main deployment orchestrator. Accepts a `projects` array parameter where each project specifies:

| Property | Description |
|----------|-------------|
| `name` | Unique project identifier |
| `projectType` | One of: `terraform`, `api-ops`, `api-ops-cli`, `api-center`, `dotnet`, `nodejs`, `react`, `powershell` |
| `dependencies` | Array of Azure DevOps stage names this project depends on |
| `projectSpecs` | Type-specific configuration (see below) |

**Example Usage:**

```yaml
extends:
  template: .pipelines/cd-template.yaml
  parameters:
    projects:
      - name: 'lz-shared'
        projectType: 'terraform'
        dependencies: []
        projectSpecs:
          terraformAction: 'apply'
          terraformWorkspace: 'dev'
          applyStageName: 'lz_shared'
          serviceConnectionNameTfPlan: 'sc-alz-mgmt-plan'
          serviceConnectionNameTfApply: 'sc-alz-mgmt-apply'
      - name: 'function-dev'
        projectType: 'dotnet'
        projectSpecs:
          dotnetStageDependsOn:
            - lz_shared
          webAppProjectsPath: '**/*.csproj'
          zipArtifactName: 'function-app-artifact'
```

### CI Template (`ci-template.yaml`)

Validation-focused template for pull requests. Uses the same `projects` array structure as `cd-template.yaml`, but runs non-deploying validation stages:
- Terraform format/init/validate and plan
- API Ops dry-run plan
- API Ops CLI dry-run plan
- API Center validation
- PowerShell check mode
- .NET, Node.js, and React build/test stages

## Helpers

### Terraform Helpers

| Template | Purpose |
|----------|---------|
| `terraform.yaml` | Full deployment stage (plan → apply) with workspace support |
| `terraform-init.yaml` | Initialize Terraform with Azure backend |
| `terraform-plan.yaml` | Generate and save execution plan |
| `terraform-apply.yaml` | Apply the saved plan |
| `terraform-workspace.yaml` | Select or create Terraform workspace |
| `terraform-installer.yaml` | Install specified Terraform CLI version |
| `az-storage-table-get-record.yaml` | Fetch subscription vending records from Azure Table Storage |

**Key Terraform Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `terraformAction` | `apply` | Action to perform |
| `terraformWorkspace` | `dev` | Workspace name |
| `terraformCliVersion` | `latest` | Terraform version |
| `rootModuleFolderRelativePath` | `.` | Path to Terraform module |
| `serviceConnectionNameTfPlan` | `sc-alz-mgmt-plan` | Plan service connection |
| `serviceConnectionNameTfApply` | `sc-alz-mgmt-apply` | Apply service connection |
| `backendStateVariableGroup` | `alz-mgmt` | Variable group with backend config |
| `subscriptionVendingRun` | `false` | Enable subscription vending mode |
| `terraformSecureFiles` | `{}` | Mapping of Terraform string variable names to Azure DevOps Library Secure File names (plan only) |

#### Terraform Secure Files

Configure the same optional mapping in CD or CI `projectSpecs` (or directly on
`terraform.yaml` / `terraform-plan.yaml`):

```yaml
projectSpecs:
  terraformSecureFiles:
    backend_root_certificate_path: backend-root.cer
    secondary_root_certificate_path: secondary-root.cer
```

Upload the files to **Pipelines > Library > Secure files** and authorize the
consuming pipeline, including any required approvals/checks. Keys must match
`[A-Za-z_][A-Za-z0-9_]*` and be unique ignoring case; values must be non-empty
Secure File names. Do not configure the same variable in `terraformOverrideVars`.
An empty mapping preserves existing behavior and adds no download tasks.

Declare each mapped Terraform input as a required string variable (without a
default file path), then use `filebase64(var.backend_root_certificate_path)` in
the module's certificate configuration. `DownloadSecureFile@1` downloads each
file in the plan deployment job and the helper passes its absolute path as a
`-var` argument, after all variable-file arguments. This works with CLI overrides,
subscription-vending variable files, and additional variable files; mapped paths
take precedence over values in those files. Existing behavior that ignores
`terraformOverrideVars` when `terraformVarFileName` is set is unchanged.

The CI format/init/validate job needs no download: `terraform validate` checks the
configuration with required input values unknown. The CI plan job downloads the
files just like CD. This does not support hard-coded file paths or file reads that
require a known default during validation.

Raw downloads stay in `Agent.TempDirectory`, outside `Pipeline.Workspace`, and
are removed by the Azure DevOps task at job completion. The helper fails if a
download is missing or located inside the artifact source workspace. It does not
print file contents or add the mapped paths to its command log. **This is not a
secret-redaction mechanism:** Terraform diagnostics, plan output, saved plans,
and state can contain file data. Use this feature for public CA certificates,
protect plan artifacts and state, and do not use it to deliver private keys.

For `filebase64()` evaluated during planning, the certificate data is captured in
the saved plan, so apply uses `tfplan` without downloading the file again. This
feature does not provide files for apply-time provisioners or deferred file reads.
Existing consumers must use a release containing this change. An Azure
DevOps-hosted mirror pinned to an older tag (such as `v1.1.0`) must first be
updated/mirrored and its pipeline configuration adapted to the current
`projects` / camelCase interface; this change does not update that mirror or pin.

Local regression checks: `python -m unittest discover -s tests -v`
(requires Python with PyYAML, PowerShell 7, and Terraform). These checks are not a
substitute for Azure DevOps template preview and an authorized pipeline run.

### PowerShell Helpers

| Template | Purpose |
|----------|---------|
| `azure-cli-powershell-check-apply.yaml` | Run a PowerShell script in a check stage, then run it again in an apply stage after check succeeds |
| `azure-cli-powershell-script.yaml` | Run a PowerShell script through `AzureCLI@2` using an Azure DevOps service connection |

Use this helper for PowerShell scripts that rely on the Azure CLI login established by a service connection, including scripts that call `az` or `az rest`.

**Step-level example: grant Azure Files Microsoft Entra Kerberos admin consent**

```yaml
steps:
  - template: .pipelines/helpers/powershell/azure-cli-powershell-script.yaml
    parameters:
      displayName: Grant Azure Files Entra Kerberos admin consent
      serviceConnectionName: sc-alz-mgmt-apply
      scriptPath: scripts/Grant-AzureFilesEntraKerberosAdminConsent.ps1
      scriptArguments: >
        -SubscriptionId "$(subscriptionId)"
        -ResourceGroupSuffix "$(resourceGroupSuffix)"
        -Mode Check
```

**CD project example: run Check after Terraform apply, then Apply after Check succeeds**

```yaml
extends:
  template: .pipelines/cd-template.yaml
  parameters:
    projects:
      - name: 'lz-shared'
        projectType: 'terraform'
        projectSpecs:
          applyStageName: lz_shared
          serviceConnectionNameTfPlan: sc-alz-mgmt-plan
          serviceConnectionNameTfApply: sc-alz-mgmt-apply

      - name: 'azure_files_admin_consent'
        projectType: 'powershell'
        dependencies:
          - lz_shared
        projectSpecs:
          serviceConnectionName: sc-alz-mgmt-apply
          scriptPath: scripts/Grant-AzureFilesEntraKerberosAdminConsent.ps1
          scriptArguments: >
            -SubscriptionId "$(subscriptionId)"
            -ResourceGroupSuffix "$(resourceGroupSuffix)"
          modeArgumentName: Mode
          checkModeValue: Check
          applyModeValue: Apply
```

`dependencies` values must be Azure DevOps stage names. In this example, the PowerShell check stage depends on the Terraform apply stage named `lz_shared`, then the PowerShell apply stage depends on its check stage.

For scripts that use a Boolean switch instead of `-Mode Check`/`-Mode Apply`, set explicit mode arguments so PowerShell receives native Boolean values:

```yaml
projectSpecs:
  checkModeArguments: '-CheckMode:$true'
  applyModeArguments: '-CheckMode:$false'
```

**Key PowerShell Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `serviceConnectionName` | - | Azure DevOps service connection used by `AzureCLI@2` |
| `scriptPath` | - | Path to the PowerShell script in the pipeline workspace |
| `scriptArguments` | `''` | Arguments passed directly to the script before the check/apply mode argument |
| `modeArgumentName` | `Mode` | Argument name appended by the check/apply workflow |
| `checkModeValue` | `Check` | Value used in the check stage |
| `applyModeValue` | `Apply` | Value used in the apply stage |
| `checkModeArguments` | `-Mode Check` | Full mode argument override for the check stage |
| `applyModeArguments` | `-Mode Apply` | Full mode argument override for the apply stage |
| `displayName` | `Run Azure PowerShell script` | Task display name |
| `workingDirectory` | `''` | Optional working directory for the task |

### API Ops Helpers

| Template | Purpose |
|----------|---------|
| `api-ops.yaml` | Stage definition for API Management operations |
| `publish.yaml` | Publish APIs to Azure API Management |

**Key APIOps Parameters:**

| Parameter | Description |
|-----------|-------------|
| `serviceConnectionName` | Azure service connection |
| `apimServiceOutputFolderPath` | Path to APIM artifacts |
| `environment` | Target environment |
| `resourceGroupName` | APIM resource group |
| `apiManagementServiceBaseName` | APIM instance name |
| `condition` | Optional `projectSpecs` stage condition for API Ops CI/CD; defaults to `succeeded()`. Publish also requires a successful dependency (the plan stage unless skipped). |

#### Consuming-repository CI and CD examples

Copy [azure-pipelines-ci.yaml](.pipelines/examples/api-ops/azure-pipelines-ci.yaml)
and [azure-pipelines-cd.yaml](.pipelines/examples/api-ops/azure-pipelines-cd.yaml)
into the consuming repository and register them as separate Azure Pipelines.
They extend the common `.pipelines/ci-template.yaml` and
`.pipelines/cd-template.yaml`. All environment-selection and routing expressions
live in the consuming pipeline's `variables` block; the common templates own
the plan/publish stages.

| Pipeline event | `environment` variable | Action |
|----------------|------------------------|--------|
| PR targeting `dev` | `dev` | CI dry-run only |
| PR targeting `stage` | `stage` | CI dry-run only |
| Merge into `dev` (`IndividualCI` or `BatchedCI`) | `dev` | CD dry-run, then publish to dev |
| Merge into `stage` (`IndividualCI` or `BatchedCI`) | `stage` | CD dry-run, then publish to stage |
| Manual CD run (`Manual`) | `prod` | CD dry-run, then publish to production |
| Any other reason or branch | `none` | All API Ops stages are skipped |

CI checks `System.PullRequest.TargetBranch`, accepting both `refs/heads/dev`
and `dev` (and the corresponding stage forms) for Azure Repos/GitHub compatibility.
After a merge, CD checks `Build.SourceBranch`, not PR variables: a completed PR
produces a branch CI run, not a `PullRequest` run.

The root `environment` variable uses a runtime expression (`$[...]`) because
the PR target branch is not available during template expansion. Each project's
`projectSpecs.environment` passes it through as `$(environment)`, not
`${{ variables.environment }}`. Separate project entries keep service connections
and Azure Pipelines environments literal so Azure DevOps can resolve and
authorize them before execution. Do not construct service-connection names from
the runtime-selected environment.

The `devCondition`, `stageCondition`, and `prodCondition` variables contain
condition expressions, passed unchanged through `projectSpecs.condition` to
the API Ops stage helpers. They allow skipped sibling stages without continuing
after a failure or cancellation. Publish additionally requires its plan stage to
succeed. When no condition is supplied, existing helpers retain their normal
`succeeded()` behavior, including when `skipPlanStage` is enabled.

Before using the examples:

- Replace the GitHub repository service connection `github-template-connection`,
  agent pool, Azure service connections, resource groups, and APIM names with
  your own. The template repository uses `main` for illustration; pin a reviewed
  release tag for controlled adoption. The referenced revision must include
  the API Ops `projectSpecs.condition` support shown here; an older revision
  would ignore these gates.
- Commit the APIOps artifacts under `artifacts` with the applicable publisher
  configuration files: `configuration.dev.yaml`, `configuration.stage.yaml`,
  and `configuration.prod.yaml`. Adjust the paths if your layout differs.
- Create/authorize the `apiops-plan-dev`, `apiops-plan-stage`, `apiops-plan-prod`,
  `apiops-dev`, `apiops-stage`, and `apiops-prod` Azure Pipelines environments.
  Add approval checks to `apiops-prod` and restrict production service-connection
  access. PR validation is a dry-run, but still authenticates to Azure; authorize
  credentials only for trusted PRs.
- Protect `dev` and `stage` with required PR reviews and CI build validation,
  and disallow direct pushes/bypasses. Branch filters do not enforce protection
  or distinguish a merge from a direct push. For Azure Repos Git, configure
  build-validation branch policies; YAML `pr` triggers are not supported there.
- Run CD manually only when intending a production deployment: **every manual CD
  run targets prod**, even when `dev` or `stage` is selected in the run dialog.
  It publishes the selected branch/revision, not an automatically promoted
  artifact from an earlier run. Restrict allowed production source branches with
  environment branch-control checks as appropriate.

The CD pipeline is triggered by the merged commit itself, not by CI pipeline
completion, so PR validation never directly triggers deployment.

### .NET Helpers

| Template | Purpose |
|----------|---------|
| `dotnet.yaml` | Build, publish, and package .NET applications |

**Key .NET Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `webAppProjectsPath` | `**/*.csproj` | Path pattern to .NET projects |
| `dotnetVersion` | `8.x` | .NET SDK version |
| `zipArtifactName` | - | Name for published artifact |

### Node.js Helpers

| Template | Purpose |
|----------|---------|
| `nodejs.yaml` | Install Node.js, run npm install/build, audit dependencies, and run tests |

**Key Node.js Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `workingDirectory` | `./backend` | Node.js project folder |
| `nodeVersion` | `24.x` | Node.js version installed by `UseNode@1` |
| `auditLevel` | `high` | Minimum vulnerability level that fails `npm audit` |
| `testScript` | `test:ci` | npm script name run by the test step |
| `publishArtifact` | `true` | Whether to publish a pipeline artifact after tests pass |
| `artifactPath` | `./backend` | Path to publish for later deployment stages |
| `artifactName` | Project `name` | Pipeline artifact name |

### React Helpers

| Template | Purpose |
|----------|---------|
| `react.yaml` | Install Node.js, run npm install/build, audit dependencies, install Playwright, and run tests |

**Key React Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `workingDirectory` | `./frontend` | React project folder |
| `nodeVersion` | `24.x` | Node.js version installed by `UseNode@1` |
| `auditLevel` | `high` | Minimum vulnerability level that fails `npm audit` |
| `playwrightInstall` | `true` | Whether to run `npx playwright install --with-deps` before tests |
| `testScript` | `test:ci` | npm script name run by the test step |
| `publishArtifact` | `true` | Whether to publish a pipeline artifact after tests pass |
| `artifactPath` | `./frontend/dist` | Path to publish for later deployment stages |
| `artifactName` | Project `name` | Pipeline artifact name |

**Node.js with React example:**

```yaml
extends:
  template: .pipelines/cd-template.yaml
  parameters:
    projects:
      - name: frontend
        projectType: react
        projectSpecs:
          workingDirectory: './frontend'
          nodeVersion: '24.x'
          artifactPath: './frontend/dist'
          artifactName: 'frontend'

      - name: backend
        projectType: nodejs
        dependencies:
          - frontend
        projectSpecs:
          workingDirectory: './backend'
          nodeVersion: '24.x'
          artifactPath: './backend'
          artifactName: 'backend'

      - name: app-infra
        projectType: terraform
        dependencies:
          - frontend
          - backend
        projectSpecs:
          planArtifactDownload:
            enabled: true
            artifactName: 'frontend'
            targetPath: '$(Pipeline.Workspace)/frontend'
```

## Dependencies

Projects that expose `dependencies` should declare Azure DevOps stage names, not project names. For example, if a Terraform project sets `applyStageName: lz_shared`, downstream stages should depend on `lz_shared`.

```yaml
- name: 'api-publisher'
  projectType: 'api-ops'
  dependencies:
    - dotnet
    - lz_shared
```

## Prerequisites

- Azure DevOps organization with self-hosted agent pool (`ado-devops-pool`)
- Service connections configured for Terraform and APIOps
- Variable groups with backend storage configuration:
  - `BACKEND_AZURE_RESOURCE_GROUP_NAME`
  - `BACKEND_AZURE_STORAGE_ACCOUNT_NAME`
  - `BACKEND_AZURE_STORAGE_ACCOUNT_CONTAINER_NAME`
- Environments configured: `alz-mgmt-plan`, `alz-mgmt-apply`

## Contributing

When adding new project types:
1. Create a new folder under `.pipelines/helpers/<project-type>/`
2. Add the main stage template (e.g., `<project-type>.yaml`)
3. Add any step-level helper templates
4. Update `cd-template.yaml` to handle the new `projectType`