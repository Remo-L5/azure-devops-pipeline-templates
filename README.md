# ALZ Management Templates

Reusable Azure DevOps pipeline templates for deploying Azure Landing Zone (ALZ) infrastructure and applications.

## Overview

This repository provides a modular, template-based approach to CI/CD pipelines for Azure deployments. It supports multiple project types including **Terraform**, **API Operations (APIOps)**, and **.NET** applications—all orchestrated through a unified pipeline interface.

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
| `projectType` | One of: `terraform`, `api-ops`, `api-ops-cli`, `api-center`, `dotnet`, `powershell` |
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

Validation-focused template for pull requests. Runs:
- Terraform format check
- Terraform init (backend=false)
- Terraform validate
- Terraform plan (for review)

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