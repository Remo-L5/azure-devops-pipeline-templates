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
| `projectType` | One of: `terraform`, `api-ops`, `dotnet` |
| `dependencies` | Array of project names this project depends on |
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
          serviceConnectionNameTfPlan: 'sc-alz-mgmt-plan'
          serviceConnectionNameTfApply: 'sc-alz-mgmt-apply'
      - name: 'function-dev'
        projectType: 'dotnet'
        dependencies:
          - lz-shared
        projectSpecs:
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

Projects can declare dependencies on other projects using the `dependencies` array. The CD template respects these dependencies and ensures proper execution order using Azure DevOps stage dependencies.

```yaml
- name: 'api-publisher'
  projectType: 'api-ops'
  dependencies:
    - function-dev      # Waits for function-dev to complete
    - lz-shared         # Also waits for lz-shared
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