# Script Reference

This document provides detailed information about each script in the SageMaker Studio domain migration toolkit, including usage, features, and required IAM permissions.

## discover_domain.py

Captures all configuration details of an existing SageMaker Studio domain.

**Usage:**
```bash
python scripts/discover_domain.py --domain-id <domain-id> [--output-dir <path>]
```

**Key Features:**
- Captures all JupyterLab and CodeEditor apps regardless of status
- Detailed status reporting (InService, Failed, Deleted, etc.)
- Captures ResourceSpecs for use in backup and restore operations
- Comprehensive logging of app states

**Required IAM Permissions:**
- `sagemaker:DescribeDomain`
- `sagemaker:ListUserProfiles`
- `sagemaker:DescribeUserProfile`
- `sagemaker:ListSpaces`
- `sagemaker:DescribeSpace`
- `sagemaker:ListApps`
- `sagemaker:DescribeApp`

## backup_domain_data.py

Creates lifecycle configurations to backup user data to S3 and restarts InService apps.

**Usage:**
```bash
python scripts/backup_domain_data.py \
  --domain-id <domain-id> \
  --s3-bucket <bucket-name> \
  [--s3-prefix <prefix>] \
  [--config-dir <path>] \
  [--backup-efs] \
  [--no-backup-efs]
```

**Key Features:**
- Only processes InService apps (skips Failed, Deleted, Deleting apps)
- Parallel app creation with throttling to avoid API limits
- Optional EFS data exclusion for faster backups
- Detailed status reporting by app state

**Required IAM Permissions:**
- `sagemaker:CreateStudioLifecycleConfig`
- `sagemaker:UpdateDomain`
- `sagemaker:ListApps`
- `sagemaker:DescribeApp`
- `sagemaker:DeleteApp`
- `sagemaker:CreateApp`
- `s3:PutObject`
- `s3:GetObject`
- `s3:ListBucket`

## recreate_domain.py

Recreates the domain, user profiles, and spaces in the new organizational context.

**Usage:**
```bash
python scripts/recreate_domain.py \
  [--config-dir <path>] \
  [--new-domain-name <name>] \
  [--resume-domain-id <domain-id>]
```

**Key Features:**
- Resume functionality for failed recreations
- Enhanced SSO username extraction for email-based formats
- Handles existing user profiles and spaces gracefully
- Validates domain status before proceeding

**Required IAM Permissions:**
- `sagemaker:CreateDomain`
- `sagemaker:DescribeDomain`
- `sagemaker:DescribeUserProfile`
- `sagemaker:UpdateUserProfile`
- `sagemaker:CreateSpace`
- `sagemaker:DescribeSpace`
- `sso-admin:ListApplications`
- `sso-admin:CreateApplicationAssignment`
- `identitystore:ListUsers`
- `iam:PassRole`

## assign_users_to_domain.py

Assigns users to the new SageMaker Studio domain by creating Identity Center application assignments.

**Usage:**
```bash
python scripts/assign_users_to_domain.py \
  --domain-id <domain-id> \
  --identity-store-id <identity-store-id> \
  [--config-dir <path>]
```

**Parameters:**
- `--domain-id` (required): The ID of the new domain
- `--identity-store-id` (required): Identity Center identity store ID
- `--config-dir` (optional): Directory containing configuration files (default: `./migration_data`)
- `--log-level` (optional): Logging level (default: INFO)

**Key Features:**
- Uses IdentityStore get_user_id API to find users by username
- Validates user IDs before creating assignments
- Uses SSO Admin APIs to create application assignments
- Provides detailed logging and error handling
- Includes rate limiting to avoid API throttling

**Required IAM Permissions:**
- `sso-admin:CreateApplicationAssignment`
- `identitystore:GetUserId`
- `sagemaker:DescribeDomain`

**Use Cases:**
- Assigning users to the new domain after recreation
- Ensuring all users have proper access to the migrated domain
- Bulk user assignment with comprehensive error reporting

**Example:**
```bash
python scripts/assign_users_to_domain.py \
  --domain-id d-xyz789ghi012 \
  --identity-store-id d-92679c0362
```

## retag_resources.py

Updates tags on SageMaker resources to reference the new domain.

**Usage:**
```bash
python scripts/retag_resources.py \
  --old-domain-id <old-id> \
  --new-domain-id <new-id> \
  [--config-dir <path>]
```

**Required IAM Permissions:**
- `sagemaker:ListTrainingJobs`
- `sagemaker:DescribeTrainingJob`
- `sagemaker:ListPipelines`
- `sagemaker:DescribePipeline`
- `sagemaker:ListEndpoints`
- `sagemaker:DescribeEndpoint`
- `sagemaker:ListTags`
- `sagemaker:AddTags`
- `sagemaker:DeleteTags`

## restore_domain_data.py

Creates lifecycle configurations to restore user data from S3 and starts all spaces.

**Usage:**
```bash
python scripts/restore_domain_data.py \
  --domain-id <domain-id> \
  --s3-bucket <bucket-name> \
  [--s3-prefix <prefix>] \
  [--config-dir <path>] \
  [--backup-efs] \
  [--no-backup-efs]
```

**Key Features:**
- Parallel app creation with throttling to avoid API limits
- Filters out ResourceSpecs from failed apps in original domain
- Optional EFS data exclusion (must match backup settings)
- Comprehensive status reporting

**Required IAM Permissions:**
- `sagemaker:CreateStudioLifecycleConfig`
- `sagemaker:UpdateDomain`
- `sagemaker:CreateApp`
- `sagemaker:DescribeApp`
- `s3:GetObject`
- `s3:ListBucket`

## delete_domain_apps.py

Deletes all JupyterLab and CodeEditor apps in a domain for cost savings.

**Usage:**
```bash
python scripts/delete_domain_apps.py \
  --domain-id <domain-id> \
  [--dry-run] \
  [--config-dir <path>]
```

**Parameters:**
- `--domain-id` (required): The ID of the domain
- `--dry-run` (optional): Show what would be deleted without actually deleting
- `--config-dir` (optional): Directory for output files (default: `./migration_data`)
- `--log-level` (optional): Logging level (default: INFO)

**Required IAM Permissions:**
- `sagemaker:ListApps`
- `sagemaker:DeleteApp`

**Use Cases:**
- Cost savings during account migration when apps are not actively being used
- Cleaning up apps before domain deletion
- Forcing all users to restart apps with new configurations

**Example:**
```bash
# Preview what would be deleted
python scripts/delete_domain_apps.py --domain-id d-abc123def456 --dry-run

# Actually delete all apps
python scripts/delete_domain_apps.py --domain-id d-abc123def456
```

## Common Parameters

Most scripts share these common optional parameters:

- `--config-dir` (optional): Directory containing configuration files (default: `./migration_data`)
- `--log-level` (optional): Logging level - DEBUG, INFO, WARNING, ERROR (default: INFO)

## Output Files

Each script generates status files in the `migration_data` directory:

- **discover_domain.py**: `domain_config.json`, `user_profiles.json`, `spaces.json`
- **backup_domain_data.py**: `backup_status.json`
- **recreate_domain.py**: `recreation_mapping.json`
- **assign_users_to_domain.py**: `user_assignment_status.json`
- **retag_resources.py**: `retagging_status.json`
- **restore_domain_data.py**: `restoration_status.json`
- **delete_domain_apps.py**: `deletion_status.json`

## Error Handling

All scripts include:
- Comprehensive error handling and logging
- Detailed status reporting in JSON format
- Graceful handling of API rate limits
- Validation of input parameters
- Clear error messages with suggested solutions

## Best Practices

1. **Run with DEBUG logging** for detailed troubleshooting: `--log-level DEBUG`
2. **Save script output** to files for later analysis: `python script.py ... 2>&1 | tee script.log`
3. **Check status files** after each script execution for detailed results
4. **Test in non-production** environments before running on production domains
5. **Verify prerequisites** before running each script (IAM permissions, resource existence, etc.)