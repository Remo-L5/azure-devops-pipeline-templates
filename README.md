# ALZ Management Templates

Reusable Azure DevOps pipeline templates for deploying Azure Landing Zone (ALZ) infrastructure and applications.

## Overview

This repository provides a modular, template-based approach to CI/CD pipelines for Azure deployments. It supports **Terraform**, **API Operations (APIOps)**, **.NET**, **Node.js**, **React**, **Python**, **Azure Static Web Apps**, and standalone **App Service / Function App** deployments—all orchestrated through a unified pipeline interface.

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
    │   ├── nodejs.yaml       # Install, audit, build, and test Node.js projects
    │   ├── package-functions.yaml # Curated Functions package with production dependencies
    │   └── validate-functions.yaml # Validate Node.js Functions entry points and dependencies
    ├── python/               # Python/Django build and test helper
    │   └── python.yaml       # Test and publish deployment source
    ├── app-service/          # Standalone App Service and Function App deployment
    │   ├── app-service.yaml  # Deployment or CI validation stage
    │   └── deploy.yaml       # Download, validate, archive, and deploy backend artifacts
    ├── common/
    │   └── artifact-deployment-job.yaml # Optional Azure DevOps environment integration
    ├── react/                # React application helpers
    │   └── react.yaml        # Install, audit, build, Playwright setup, and test React projects
    ├── static-web-app/       # Deploy prebuilt React and optional Azure Functions artifacts
    │   ├── static-web-app.yaml # Stage definition, also used for non-deploying CI validation
    │   └── deploy.yaml       # Download/validate artifacts, retrieve deployment key, and deploy
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
| `projectType` | One of: `terraform`, `api-ops`, `api-ops-cli`, `api-center`, `dotnet`, `nodejs`, `react`, `python`, `powershell`, `static-web-app`, `app-service`, `function-app` |
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
- Static Web App artifact configuration/content validation (no Azure login, key retrieval, or deployment)
- Python tests and source packaging
- App Service / Function App artifact validation and ZIP creation (no Azure deployment or Azure DevOps environment approvals)

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
| `installCommand` | `install` | npm install subcommand/arguments; use `ci` for lockfile-reproducible installation |
| `lintScript` | `''` | Optional npm script to run before build |
| `typeCheckScript` | `''` | Optional npm type-check script to run after lint and before build |
| `publishArtifact` | `true` | Whether to publish a pipeline artifact after tests pass |
| `artifactPath` | `./backend/dist` | Path to publish for later deployment stages |
| `artifactName` | Project `name` | Pipeline artifact name |
| `packageFunctions` | `false` | Stage a curated Node.js Functions artifact and install locked production dependencies; overrides `artifactPath` |
| `functionPackageFiles` | `host.json`, `package.json`, `package-lock.json`, `dist` | Explicit relative files/directories included when `packageFunctions` is enabled |

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
| `installCommand` | `install` | npm install subcommand/arguments; use `ci` for lockfile-reproducible installation |
| `lintScript` | `''` | Optional npm lint script to run before build |
| `typeCheckScript` | `''` | Optional npm type-check script to run after lint and before build |
| `publishArtifact` | `true` | Whether to publish a pipeline artifact after tests pass |
| `artifactPath` | `./frontend/dist` | Path to publish for later deployment stages |
| `artifactName` | Project `name` | Pipeline artifact name |

Both JavaScript helpers preserve `npm install` by default; `installCommand: ci`
requires a committed, up-to-date `package-lock.json`. Install, optional lint/type
checks, build, audit, and tests are separate tasks, so an earlier failure cannot
be hidden by a later command succeeding. Playwright behavior is unchanged.

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

### Static Web App Helpers

| Template | Purpose |
|----------|---------|
| `static-web-app.yaml` | Stage consuming artifacts from the existing React and Node.js build helpers |
| `deploy.yaml` | Reusable steps to validate/download current-run artifacts, read the deployment key, and deploy once |

Use `projectType: static-web-app` in CD or CI. Assign `role: app` to exactly one
artifact and `role: api` to at most one optional artifact. `artifactName` must
match the producing helper's `projectSpecs.artifactName` (which defaults to its
project `name`); leave `publishArtifact` enabled. Artifacts are downloaded from
the **current pipeline run**, not another pipeline or a previous run.

The React helper's default `artifactPath: ./frontend/dist` already publishes a
prebuilt site with `index.html` at its root. The Node.js helper defaults to
`./backend/dist`, which typically omits Azure Functions metadata and dependencies.
For a Functions backend, opt into `packageFunctions: true`, as below. After tests,
the Node.js helper stages only the selected deployment files in
`$(Build.ArtifactStagingDirectory)/functions`, runs `npm ci --omit=dev` there, and
validates the package before publishing it. The original source and development
dependencies are not pruned or modified. `artifactPath` is ignored in this mode.
Defaults remain unchanged for non-Functions consumers.

The default package contains `host.json`, `package.json`, `package-lock.json`,
and `dist`; add any required assets or v3 function folders explicitly through
`functionPackageFiles`. Paths must exist and must be explicit, relative paths
without parent traversal or wildcard patterns. Repository metadata, environment
files, `local.settings.json`, and copied `node_modules` are rejected, including
inside selected folders. Runtime dependencies are installed from the lockfile,
not copied from the build's development install. Lifecycle scripts still run
and may require build tools; custom npm configuration, if necessary, must be
supplied by the consuming pipeline without publishing credentials.

Validation requires host version `2.0`, compiled JavaScript matching
`package.json.main` (including wildcard and brace alternatives such as
`dist/src/{index.js,functions/*.js}`), or v3 `function.json` definitions with
existing `scriptFile` targets. Direct production dependencies must be present
under `node_modules`. For custom artifact preparation, the same checks run again
on the downloaded SWA `api` artifact. They do not execute the app or prove all
transitive dependencies, bindings, or hosted runtime compatibility.
Build/install native dependencies on an OS and architecture compatible with
the target runtime; the helpers default to Linux hosted agents. Do not copy
Windows-built native modules into a Linux Functions deployment.

```yaml
extends:
  template: .pipelines/cd-template.yaml
  parameters:
    projects:
      - name: frontend
        projectType: react
        projectSpecs:
          workingDirectory: ./frontend
          installCommand: ci
          lintScript: lint
          typeCheckScript: typecheck
          artifactPath: ./frontend/dist
          artifactName: frontend

      - name: backend
        projectType: nodejs
        projectSpecs:
          workingDirectory: ./backend
          installCommand: ci
          packageFunctions: true
          artifactName: backend

      - name: deploy_site
        projectType: static-web-app
        dependencies:
          - frontend
          - backend
        projectSpecs:
          serviceConnectionName: sc-web-deploy
          resourceGroupName: rg-web-dev
          staticWebAppName: example-web-dev
          azureDevOpsEnvironment: web-dev
          artifacts:
            - artifactName: frontend
              role: app
            - artifactName: backend
              role: api
```

The same projects list works with `ci-template.yaml`: the build helpers publish
their artifacts, then `deploy_site` validates the configuration and artifact
roots without retrieving a key or deploying. For a frontend-only site, omit the
`api` entry and its backend stage/dependency. ZIP files are not extracted; publish
directories through `PublishPipelineArtifact@1`, as the existing helpers do.

| `projectSpecs` property | Default | Description |
|-------------------------|---------|-------------|
| `serviceConnectionName` | Required | Azure Resource Manager service connection scoped to the target subscription |
| `resourceGroupName` | Required | Resource group of the existing Static Web App |
| `staticWebAppName` | Required | Existing Static Web App name |
| `artifacts` | Required | List of `{ artifactName, role }` entries; exactly one `app`, optionally one `api` |
| `deploymentEnvironment` | `''` | Empty deploys production; set a name for a named preview environment |
| `azureDevOpsEnvironment` | `''` | Optional Azure DevOps environment name for deployment history and configured approval/check gates; not a SWA target environment |
| `poolName` | `''` | Optional self-hosted **Linux** pool with Docker, PowerShell 7, and Azure CLI |
| `vmImage` | `ubuntu-latest` | Hosted Linux image when `poolName` is unset |

Top-level `stageName`, `stageDisplayName`, and `dependencies` follow the React
and Node.js stage conventions. For step-level use, call
`.pipelines/helpers/static-web-app/deploy.yaml` with the same required parameters
directly (not nested in `projectSpecs`); `validateOnly: true` disables key
retrieval and deployment.

The service connection must be authorized for the pipeline and allowed
`Microsoft.Web/staticSites/listSecrets/action` on the target Static Web App
(for example, through a suitably scoped Contributor role). The helper calls
`az staticwebapp secrets list`, fails on missing/invalid keys, and registers the
key as a secret, read-only job variable consumed by `AzureStaticWebApp@0`.
No deployment token needs to be stored in YAML or a variable group. When
`azureDevOpsEnvironment` is set, CD uses a deployment job against that existing,
authorized Azure DevOps environment and disables automatic artifact downloads.
Configure its approvals/checks in Azure DevOps; the template does not create
approval policies. With no environment specified, CD retains a normal job.
CI always uses a normal job, even when an environment name is configured.
The task
requires a Linux agent with Docker; Windows agents are rejected.

The `api` artifact is for **Static Web Apps managed Azure Functions**, exposed
under `/api`, not an Express/NestJS server or deployment to an existing Function
App. Use HTTP-triggered functions and a supported managed Functions Node.js
runtime; the build helper's `nodeVersion` does not set the hosted API runtime.
Include `staticwebapp.config.json` in the React build output to configure routes
and `platform.apiRuntime` where needed. Existing standalone servers and
bring-your-own Function Apps need a separate backend deployment.

Local SWA regression checks:
`python -m unittest discover -s tests -p test_static_web_app.py -v`.
An authorized Azure DevOps template preview and deployment are still required
to verify service permissions and hosting behavior.

### Python and Standalone Backend Helpers

Use `projectType: python` to install dependencies, run optional lint, tests, and an
optional build command, then publish an unpacked source artifact. Tests default
to `python -m unittest discover`; Django consumers should specify
`testCommand: python manage.py test` and can use
`buildCommand: python manage.py collectstatic --noinput`. Test/build/lint commands
receive the optional `projectSpecs.env` mapping, including references to pipeline
secret variables. Never put secrets directly in YAML.

| Python `projectSpecs` property | Default | Description |
|-------------------------------|---------|-------------|
| `workingDirectory` | `./backend` | Application source root, also the root of the published artifact |
| `pythonVersion` | `3.11` | Version requested by `UsePythonVersion@0` |
| `requirementsFile` | `requirements.txt` | pip requirements path relative to the application root |
| `lintCommand` | `''` | Optional lint command; required tooling must be in requirements |
| `testCommand` | `python -m unittest discover` | Test command; failure prevents packaging |
| `buildCommand` | `''` | Optional command after tests, e.g. Django static collection |
| `env` | `{}` | Environment variables for lint, test, and build tasks |
| `artifactName` | Project `name` | Current-run pipeline artifact name |
| `publishArtifact` | `true` | Whether to stage/publish the application source |
| `poolName` / `vmImage` | `''` / `ubuntu-latest` | Self-hosted pool or hosted agent image |

Python staging excludes `.git`, `.venv`, `venv`, `__pycache__`, `.pyc`, `.env*`,
`local.settings.json`, `node_modules`, and `db.sqlite3`. This is not a general
secret scanner: keep credentials and other local files out of deployment source.
Dependencies installed during testing are not bundled. For Python App Service,
the example below enables the platform's remote build from the published
`requirements.txt`. Keep the deployed Python runtime consistent with the tested
version. Self-hosted agents need the requested Python version in their tool
cache (or permission/network access to acquire it), PowerShell 7, and ZIP tooling.

Use `projectType: app-service` or `function-app` to deploy to an **existing**
resource. Both download one unpacked current-run pipeline artifact, validate
non-empty content, and create a ZIP without an enclosing root folder.
Function App artifacts additionally require root-level `host.json` with version
`2.0`. Prebuilt Node.js Functions should use `packageFunctions: true` above;
other languages must publish their appropriate complete deployment layout.
ZIP-only artifacts and the .NET helper's legacy Build Artifacts are not accepted
by this pipeline-artifact directory contract.

| Backend `projectSpecs` property | Default | Description |
|--------------------------------|---------|-------------|
| `serviceConnectionName` | Required | Authorized Azure Resource Manager service connection |
| `appName` | Required | Existing App Service or Function App name |
| `artifactName` | Required | Name published by the build project in this pipeline run |
| `appType` | `webAppLinux` / `functionAppLinux` | Must match the project type; `webApp` / `functionApp` select Windows targets |
| `azureDevOpsEnvironment` | `''` | Optional Azure DevOps environment for CD approval gates/history |
| `resourceGroupName` | `''` | Required for slot deployment |
| `slotName` | `''` | Empty targets production; otherwise deploys to an existing slot |
| `isFlexConsumption` | `false` | Function App Flex Consumption deployment; Linux only, no slots |
| `runtimeStack` | `''` | Optional task runtime override; omit to preserve infrastructure configuration; not allowed for Flex |
| `startUpCommand` | `''` | Optional Linux App Service startup command, e.g. Gunicorn |
| `appSettings` | `''` | Optional task-format settings string; prefer infrastructure or pipeline secret references |
| `poolName` / `vmImage` | `''` / `ubuntu-latest` | Self-hosted pool or hosted agent image |

In CI these backend stages only download, validate, and archive artifacts; they
do not call Azure tasks or request environment approvals. Slots are deployed,
not swapped. These helpers do not provision resources, change network settings,
or create/update SWA backend links. Provision the SWA Standard plan, backend,
link, authentication, and runtime through infrastructure. Omit the SWA `api`
artifact when using a linked backend; do not send standalone Python/Express
artifacts to the managed-Functions `api` role.

**React + Django on App Service with a separately provisioned SWA backend link:**

```yaml
extends:
  template: .pipelines/cd-template.yaml
  parameters:
    projects:
      - name: frontend
        projectType: react
        projectSpecs:
          installCommand: ci
          lintScript: lint
          testScript: test
          playwrightInstall: false

      - name: backend
        projectType: python
        projectSpecs:
          workingDirectory: ./api
          testCommand: python manage.py test
          buildCommand: python manage.py collectstatic --noinput
          env:
            DJANGO_SECRET_KEY: $(djangoBuildSecret)
            DJANGO_DEBUG: 'False'
            DJANGO_ALLOWED_HOSTS: localhost

      - name: deploy_backend
        projectType: app-service
        dependencies: [frontend, backend]
        projectSpecs:
          serviceConnectionName: sc-web-deploy
          appName: example-backend-dev
          artifactName: backend
          runtimeStack: PYTHON|3.11
          startUpCommand: gunicorn api.wsgi:application --bind 0.0.0.0:8000 --workers 2
          appSettings: '-SCM_DO_BUILD_DURING_DEPLOYMENT true'
          azureDevOpsEnvironment: backend-dev

      - name: deploy_site
        projectType: static-web-app
        dependencies: [deploy_backend]
        projectSpecs:
          serviceConnectionName: sc-web-deploy
          resourceGroupName: rg-web-dev
          staticWebAppName: example-web-dev
          azureDevOpsEnvironment: web-dev
          artifacts:
            - artifactName: frontend
              role: app
```

For a standalone Node.js Function App, keep the Node.js build with
`packageFunctions: true`, use `projectType: function-app` for deployment, and set
`artifactName` to that build's published artifact name. Choose the supported
runtime in infrastructure, or pass `runtimeStack`, e.g. `NODE|22`. This is
independent of the build helper's `nodeVersion`.

For private-endpoint App Service/Functions deployments, choose `poolName` for
agents that can reach the application's deployment/SCM endpoints and resolve
their private DNS records. An Azure service connection grants authorization,
not private-network reachability. Verify app and SCM DNS resolution, routing,
firewall access, and required artifact/package feed egress from that network.
Runner provisioning and backend link configuration remain separate work.

## Dependencies

**Behavior change for React, Node.js, Python, SWA, and standalone backend stages:**
`dependencies: []` (including an omitted list) now emits `dependsOn: []`, allowing
independent stages to run in parallel, subject to Azure DevOps parallel-job
capacity. If you previously relied on implicit YAML stage order, add explicit
dependencies before adopting this version. Set deployment dependencies to all
required build/test stages so a failed independent build cannot be bypassed.
Existing Terraform/API/PowerShell stage semantics are unchanged.

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

Application-helper regression checks: `python -m unittest discover -s tests -v`.
These require Python with PyYAML, PowerShell 7, Node.js/npm, and Terraform. Tests cover
representative local template expansion and embedded validation scripts; they
are not the Azure DevOps template engine. Before release, use an authorized
Azure DevOps preview and representative hosted/private-network deployments,
including environment approval and frontend/API smoke checks.

When adding new project types:
1. Create a new folder under `.pipelines/helpers/<project-type>/`
2. Add the main stage template (e.g., `<project-type>.yaml`)
3. Add any step-level helper templates
4. Update `cd-template.yaml` to handle the new `projectType`
5. Add its non-deploying CI path to `ci-template.yaml`