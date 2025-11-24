# Design Document

## Overview

The SageMaker Studio Domain Migration tool is a collection of Python scripts that automate the process of migrating a SageMaker Studio domain from one AWS Organization to another. The migration is necessary when an AWS account moves between organizations, which breaks SSO-based authentication due to Identity Center instance changes.

The tool follows a five-phase approach:
1. **Discovery Phase**: Capture all configuration details of the existing domain
2. **Backup Phase**: Sync user data from EBS volumes to S3
3. **Recreation Phase**: Recreate the domain and all associated resources in the new organizational context
4. **Retagging Phase**: Update resource tags to reference new domain, user profiles, and spaces
5. **Restoration Phase**: Sync user data from S3 back to the new domain

The design emphasizes idempotency, error handling, and clear separation of concerns with independent scripts for each major phase.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Migration Orchestration                   │
│                  (User executes scripts in order)            │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐      ┌──────────────┐     ┌──────────────┐
│   Discovery  │      │    Backup    │     │  Recreation  │
│    Script    │      │    Script    │     │    Script    │
└──────────────┘      └──────────────┘     └──────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐      ┌──────────────┐     ┌──────────────┐
│  Retagging   │      │ Restoration  │     │    README    │
│    Script    │      │    Script    │     │ Documentation│
└──────────────┘      └──────────────┘     └──────────────┘
```

### Component Architecture

Each script operates independently and communicates through:
- **Configuration files** (JSON) stored on disk
- **AWS SageMaker API** for domain operations
- **AWS S3** for data backup and restoration
- **Lifecycle Configuration scripts** for data synchronization

### Technology Stack

- **Language**: Python 3.8+
- **AWS SDK**: boto3
- **Configuration Format**: JSON
- **Logging**: Python logging module
- **CLI**: argparse for command-line interface

## Components and Interfaces

### 1. Discovery Script (`discover_domain.py`)

**Purpose**: Capture all configuration details of the existing SageMaker Studio domain.

**Inputs**:
- Domain ID (required)
- Output directory path (optional, defaults to `./migration_data`)

**Outputs**:
- `domain_config.json`: Domain configuration including VPC, subnets, security groups, lifecycle configurations, custom images
- `user_profiles.json`: List of user profiles with IAM roles and settings
- `spaces.json`: List of spaces with owners and sharing configurations

**Key Functions**:
- `get_domain_details(domain_id)`: Retrieves domain configuration via `describe_domain` API
- `list_user_profiles(domain_id)`: Lists all user profiles via `list_user_profiles` API
- `get_user_profile_details(domain_id, user_profile_name)`: Gets user profile details via `describe_user_profile` API
- `list_spaces(domain_id)`: Lists all spaces via `list_spaces` API
- `get_space_details(domain_id, space_name)`: Gets space details via `describe_space` API
- `save_configuration(data, filename)`: Persists configuration to JSON file

**AWS APIs Used**:
- `sagemaker:DescribeDomain`
- `sagemaker:ListUserProfiles`
- `sagemaker:DescribeUserProfile`
- `sagemaker:ListSpaces`
- `sagemaker:DescribeSpace`

### 2. Backup Script (`backup_domain_data.py`)

**Purpose**: Create and attach lifecycle configurations to sync user data to S3, then restart apps to trigger the backup.

**Inputs**:
- Domain ID (required)
- S3 bucket name (required)
- S3 prefix (optional)
- Configuration directory (optional, defaults to `./migration_data`)

**Outputs**:
- Lifecycle configurations created and attached to domain
- Apps restarted with backup LCC applied
- `backup_status.json`: Status of backup operations including failed apps

**Key Functions**:
- `create_backup_lifecycle_config(app_type, s3_bucket, s3_prefix)`: Creates LCC for JupyterLab or CodeEditor
- `attach_lifecycle_config_to_domain(domain_id, lcc_arn)`: Attaches LCC to domain
- `list_active_apps(domain_id)`: Lists all active JupyterLab and CodeEditor apps
- `restart_app(domain_id, user_profile_name, app_type, app_name, space_name)`: Deletes and recreates app
- `wait_for_app_ready(domain_id, user_profile_name, app_type, app_name, space_name)`: Polls app status until running
- `validate_backup_completion()`: Checks all apps restarted successfully

**Lifecycle Configuration Script Logic**:
```bash
#!/bin/bash
# Sync user data to S3
USER_PROFILE_NAME=$(echo $SAGEMAKER_USER_PROFILE_NAME)
SPACE_NAME=$(echo $SAGEMAKER_SPACE_NAME)
S3_PATH="s3://${S3_BUCKET}/${S3_PREFIX}/${USER_PROFILE_NAME}/${SPACE_NAME}"
aws s3 sync /home/sagemaker-user $S3_PATH --exclude ".cache/*"
```

**AWS APIs Used**:
- `sagemaker:CreateStudioLifecycleConfig`
- `sagemaker:UpdateDomain`
- `sagemaker:ListApps`
- `sagemaker:DeleteApp`
- `sagemaker:CreateApp`
- `sagemaker:DescribeApp`

### 3. Recreation Script (`recreate_domain.py`)

**Purpose**: Recreate the SageMaker Studio domain, user profiles, and spaces in the new organizational context.

**Inputs**:
- Configuration directory (optional, defaults to `./migration_data`)
- New domain name (optional, defaults to original name with timestamp suffix)

**Outputs**:
- New domain created with same configuration
- All user profiles recreated via SSO application assignments
- All spaces recreated
- `recreation_mapping.json`: Mapping of old to new resource ARNs

**Key Functions**:
- `create_domain(domain_config)`: Creates new domain with original configuration
- `get_domain_application_id(domain_id)`: Retrieves the Identity Center application ID for the domain
- `create_application_assignment(application_arn, principal_id, principal_type)`: Creates SSO application assignment for user
- `wait_for_user_profile_creation(domain_id, user_profile_name)`: Waits for user profile to be automatically created after application assignment
- `create_space(domain_id, space_config)`: Creates space with owner and sharing settings
- `build_resource_mapping(old_resources, new_resources)`: Creates mapping for ARN translation

**SSO User Profile Creation Flow**:
1. Create the new SageMaker domain
2. Retrieve the Identity Center application ID associated with the domain
3. For each user, create an application assignment in Identity Center
4. Wait for SageMaker to automatically create the user profile
5. Update user profile settings if they differ from domain defaults

**AWS APIs Used**:
- `sagemaker:CreateDomain`
- `sagemaker:DescribeDomain`
- `sagemaker:DescribeUserProfile`
- `sagemaker:UpdateUserProfile`
- `sagemaker:CreateSpace`
- `sagemaker:DescribeSpace`
- `sso-admin:ListApplications`
- `sso-admin:CreateApplicationAssignment`
- `identitystore:ListUsers` (to map user identities)

### 4. Retagging Script (`retag_resources.py`)

**Purpose**: Update tags on SageMaker resources to reference the new domain, user profiles, and spaces.

**Inputs**:
- Configuration directory (optional, defaults to `./migration_data`)
- Old domain ID (required)
- New domain ID (required)

**Outputs**:
- Updated tags on all SageMaker jobs, pipelines, and endpoints
- `retagging_status.json`: Status of retagging operations

**Key Functions**:
- `list_tagged_resources(domain_id)`: Lists all resources tagged with domain ID
- `get_resource_tags(resource_arn)`: Retrieves current tags for a resource
- `update_resource_tags(resource_arn, old_tags, new_tags, mapping)`: Updates tags with new ARNs
- `map_arn(old_arn, mapping)`: Translates old ARN to new ARN using mapping

**AWS APIs Used**:
- `sagemaker:ListTrainingJobs`
- `sagemaker:ListPipelines`
- `sagemaker:ListEndpoints`
- `sagemaker:DescribeTrainingJob`
- `sagemaker:DescribePipeline`
- `sagemaker:DescribeEndpoint`
- `sagemaker:ListTags`
- `sagemaker:AddTags`
- `sagemaker:DeleteTags`

### 5. Restoration Script (`restore_domain_data.py`)

**Purpose**: Create and attach lifecycle configurations to sync data from S3 back to user EBS volumes, then start all spaces.

**Inputs**:
- Domain ID (required)
- S3 bucket name (required)
- S3 prefix (optional)
- Configuration directory (optional, defaults to `./migration_data`)

**Outputs**:
- Lifecycle configurations created and attached to domain
- All spaces started with restore LCC applied
- `restoration_status.json`: Status of restoration operations including failed spaces

**Key Functions**:
- `create_restore_lifecycle_config(app_type, s3_bucket, s3_prefix)`: Creates LCC for data restoration
- `attach_lifecycle_config_to_domain(domain_id, lcc_arn)`: Attaches LCC to domain
- `start_all_spaces(domain_id, spaces_config)`: Creates apps for all spaces
- `wait_for_app_ready(domain_id, user_profile_name, app_type, app_name, space_name)`: Polls app status
- `validate_restoration_completion()`: Checks all spaces started successfully

**Lifecycle Configuration Script Logic**:
```bash
#!/bin/bash
# Sync data from S3 to user volume
USER_PROFILE_NAME=$(echo $SAGEMAKER_USER_PROFILE_NAME)
SPACE_NAME=$(echo $SAGEMAKER_SPACE_NAME)
S3_PATH="s3://${S3_BUCKET}/${S3_PREFIX}/${USER_PROFILE_NAME}/${SPACE_NAME}"
aws s3 sync $S3_PATH /home/sagemaker-user --exclude ".cache/*"
```

**AWS APIs Used**:
- `sagemaker:CreateStudioLifecycleConfig`
- `sagemaker:UpdateDomain`
- `sagemaker:CreateApp`
- `sagemaker:DescribeApp`

## Data Models

### Domain Configuration

```json
{
  "DomainId": "d-xxxxxxxxxxxx",
  "DomainName": "my-studio-domain",
  "DomainArn": "arn:aws:sagemaker:region:account:domain/d-xxxxxxxxxxxx",
  "HomeEfsFileSystemId": "fs-xxxxxxxxxxxx",
  "SubnetIds": ["subnet-xxxxx", "subnet-yyyyy"],
  "VpcId": "vpc-xxxxxxxxxxxx",
  "SecurityGroupIds": ["sg-xxxxxxxxxxxx"],
  "AuthMode": "SSO",
  "DefaultUserSettings": {
    "ExecutionRole": "arn:aws:iam::account:role/SageMakerExecutionRole",
    "SecurityGroups": ["sg-xxxxxxxxxxxx"],
    "JupyterLabAppSettings": {
      "DefaultResourceSpec": {
        "InstanceType": "ml.t3.medium",
        "SageMakerImageArn": "arn:aws:sagemaker:region:account:image/jupyter-lab-3"
      },
      "LifecycleConfigArns": [],
      "CodeRepositories": []
    },
    "CodeEditorAppSettings": {
      "DefaultResourceSpec": {
        "InstanceType": "ml.t3.medium",
        "SageMakerImageArn": "arn:aws:sagemaker:region:account:image/code-editor-1"
      },
      "LifecycleConfigArns": []
    }
  },
  "DomainSettings": {
    "SecurityGroupIds": ["sg-xxxxxxxxxxxx"]
  },
  "AppNetworkAccessType": "VpcOnly"
}
```

### User Profile Configuration

```json
{
  "UserProfiles": [
    {
      "UserProfileName": "user1",
      "UserProfileArn": "arn:aws:sagemaker:region:account:user-profile/d-xxxxxxxxxxxx/user1",
      "DomainId": "d-xxxxxxxxxxxx",
      "UserSettings": {
        "ExecutionRole": "arn:aws:iam::account:role/User1ExecutionRole",
        "SecurityGroups": ["sg-xxxxxxxxxxxx"]
      }
    }
  ]
}
```

### Space Configuration

```json
{
  "Spaces": [
    {
      "SpaceName": "shared-workspace",
      "SpaceArn": "arn:aws:sagemaker:region:account:space/d-xxxxxxxxxxxx/shared-workspace",
      "DomainId": "d-xxxxxxxxxxxx",
      "OwnerUserProfileName": "user1",
      "SpaceSharingSettings": {
        "SharingType": "Private"
      },
      "SpaceSettings": {
        "JupyterServerAppSettings": {
          "DefaultResourceSpec": {
            "InstanceType": "system"
          }
        }
      }
    }
  ]
}
```

### Resource Mapping

```json
{
  "domain": {
    "old": "d-xxxxxxxxxxxx",
    "new": "d-yyyyyyyyyyyy"
  },
  "user_profiles": {
    "arn:aws:sagemaker:region:account:user-profile/d-xxxxxxxxxxxx/user1": "arn:aws:sagemaker:region:account:user-profile/d-yyyyyyyyyyyy/user1"
  },
  "spaces": {
    "arn:aws:sagemaker:region:account:space/d-xxxxxxxxxxxx/shared-workspace": "arn:aws:sagemaker:region:account:space/d-yyyyyyyyyyyy/shared-workspace"
  }
}
```

### Backup/Restoration Status

```json
{
  "timestamp": "2025-11-23T10:30:00Z",
  "domain_id": "d-xxxxxxxxxxxx",
  "s3_bucket": "my-backup-bucket",
  "s3_prefix": "sagemaker-migration",
  "total_apps": 15,
  "successful_apps": 14,
  "failed_apps": [
    {
      "user_profile_name": "user2",
      "app_type": "JupyterLab",
      "app_name": "default",
      "space_name": null,
      "error": "App failed to start after 10 minutes"
    }
  ]
}
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Configuration persistence round-trip

*For any* domain configuration retrieved from AWS, saving it to disk and then loading it back should produce an equivalent configuration object.
**Validates: Requirements 1.4, 2.4, 3.4**

### Property 2: Domain configuration completeness

*For any* valid domain ID, the retrieved configuration should contain all required fields: networking settings, subnets, VPC configuration, security groups, lifecycle configurations, and custom images.
**Validates: Requirements 1.1, 1.2, 1.3**

### Property 3: Invalid domain rejection

*For any* non-existent or invalid domain ID, the system should reject the request with an appropriate error before attempting AWS API calls.
**Validates: Requirements 1.5**

### Property 4: User profile data completeness

*For any* user profile in a domain, the retrieved data should contain the IAM execution role and all user-specific settings.
**Validates: Requirements 2.2, 2.3**

### Property 5: Space data completeness

*For any* space in a domain, the retrieved data should contain the owner user profile and sharing type configuration.
**Validates: Requirements 3.2, 3.3**

### Property 6: Lifecycle script generation correctness

*For any* S3 bucket and prefix combination, the generated backup lifecycle script should reference the correct S3 path with user profile name and space name appended.
**Validates: Requirements 4.2, 4.3**

### Property 7: App type filtering

*For any* domain, when identifying apps for restart, only apps with type JupyterLab or CodeEditor should be included in the result set.
**Validates: Requirements 5.1**

### Property 8: App configuration preservation

*For any* app being restarted, the new app instance should have the same configuration parameters as the original app instance.
**Validates: Requirements 5.2**

### Property 9: Error collection completeness

*For any* set of app restart operations with failures, all failed app instances should be collected and included in the failure report.
**Validates: Requirements 5.4**

### Property 10: Domain configuration preservation

*For any* original domain configuration, the newly created domain should have the same networking, subnets, security settings, lifecycle configurations, and custom images.
**Validates: Requirements 6.1, 6.2, 6.3**

### Property 11: User profile role preservation

*For any* user profile with a custom IAM execution role (different from domain default), the recreated user profile should have the same IAM role.
**Validates: Requirements 7.2**

### Property 12: User profile settings preservation

*For any* user profile, the recreated profile should have the same user-specific settings and configurations as the original.
**Validates: Requirements 7.3**

### Property 13: Space ownership preservation

*For any* space, the recreated space should have the same owner user profile as the original space.
**Validates: Requirements 8.1**

### Property 14: Space configuration preservation

*For any* space, the recreated space should have the same sharing type and space-specific settings as the original.
**Validates: Requirements 8.2, 8.3**

### Property 15: Tagged resource identification

*For any* domain ID, the system should identify all SageMaker jobs, pipelines, and endpoints that have tags referencing that domain ID.
**Validates: Requirements 9.1, 9.2, 9.3**

### Property 16: Tag transformation correctness

*For any* resource tag containing an old domain ID, user profile ARN, or space ARN, the updated tag should contain the corresponding new domain ID, user profile ARN, or space ARN from the mapping.
**Validates: Requirements 9.4, 9.5, 9.6**

### Property 17: ARN mapping completeness

*For any* set of original user profiles and spaces, the mapping should contain bidirectional entries for all user profile ARNs and space ARNs.
**Validates: Requirements 9.7, 9.8**

### Property 18: Restore script path construction

*For any* user profile and space name combination, the restore lifecycle script should construct the S3 path by combining the bucket, prefix, user profile name, and space name.
**Validates: Requirements 10.2, 10.3**

### Property 19: S3 backup validation

*For any* S3 backup location (bucket and prefix), the system should verify the location exists and is accessible before attempting restoration.
**Validates: Requirements 10.5**

### Property 20: Space restoration completeness

*For any* set of spaces, app instances should be created for all spaces, and any failures should be collected and reported in the restoration summary.
**Validates: Requirements 11.1, 11.3, 11.4**

## Error Handling

### Error Categories

1. **AWS API Errors**
   - Domain not found
   - Insufficient permissions
   - Rate limiting / throttling
   - Service unavailable

2. **Configuration Errors**
   - Invalid domain ID format
   - Missing required configuration files
   - Malformed JSON configuration

3. **Resource State Errors**
   - App failed to start
   - App failed to delete
   - Domain creation failed
   - User profile creation failed

4. **Data Transfer Errors**
   - S3 bucket not accessible
   - S3 sync failed in lifecycle configuration
   - Insufficient storage space

### Error Handling Strategies

**Validation Errors**: Fail fast with clear error messages before making AWS API calls.

**Transient Errors**: Implement exponential backoff retry logic for rate limiting and temporary service issues.

**Resource State Errors**: Collect all failures and provide detailed reports to the user. For critical operations (backup, restoration), halt the process if failures occur.

**Partial Failures**: For operations on multiple resources (restarting apps, creating user profiles), continue processing remaining resources and report all failures at the end.

### Logging Strategy

- **INFO level**: Progress updates, successful operations
- **WARNING level**: Retryable errors, partial failures
- **ERROR level**: Fatal errors, operation failures
- **DEBUG level**: AWS API request/response details, detailed state information

All logs should include:
- Timestamp
- Operation context (domain ID, user profile name, etc.)
- Error details with AWS error codes when applicable

## Testing Strategy

### Unit Testing

Unit tests will verify specific functionality of individual components:

- **Configuration parsing**: Test JSON serialization/deserialization with various domain configurations
- **ARN mapping**: Test mapping logic with sample old/new ARN pairs
- **Path construction**: Test S3 path building with various user profile and space name combinations
- **Error handling**: Test validation logic with invalid inputs
- **Filtering logic**: Test app type filtering with mixed app lists

### Property-Based Testing

Property-based tests will verify universal properties across many randomly generated inputs:

- **Property testing framework**: Use `hypothesis` library for Python
- **Test configuration**: Each property test should run a minimum of 100 iterations
- **Test tagging**: Each property-based test must include a comment with the format: `# Feature: sagemaker-domain-migration, Property X: [property description]`

Property-based tests will cover:

1. **Configuration round-trip properties** (Properties 1, 2, 4, 5): Generate random domain configurations and verify serialization preserves all data
2. **Preservation properties** (Properties 8, 10, 11, 12, 13, 14): Generate random configurations and verify recreation preserves all settings
3. **Transformation properties** (Properties 6, 16, 18): Generate random inputs and verify output transformations are correct
4. **Completeness properties** (Properties 9, 17, 20): Generate random resource sets and verify all items are processed

### Integration Testing

Integration tests will verify end-to-end workflows with mocked AWS services:

- **Discovery workflow**: Mock SageMaker API responses and verify configuration files are created correctly
- **Backup workflow**: Mock app restart operations and verify lifecycle configurations are attached
- **Recreation workflow**: Mock domain/user/space creation and verify resource mapping is built correctly
- **Retagging workflow**: Mock resource listing and tag updates, verify all resources are processed
- **Restoration workflow**: Mock app creation and verify restoration status is reported correctly

### Test Data Generation

For property-based testing, generators will create:

- **Valid domain IDs**: Format `d-` followed by 12 alphanumeric characters
- **ARNs**: Properly formatted AWS ARNs with valid region, account, and resource identifiers
- **Configuration objects**: Nested dictionaries matching AWS API response structures
- **S3 paths**: Valid bucket names and prefixes
- **User/space names**: Alphanumeric strings with hyphens, matching SageMaker naming constraints

## Security Considerations

### IAM Permissions

The migration tool requires extensive permissions across SageMaker, S3, and IAM services. The principle of least privilege should be applied:

- **Read permissions**: Required for discovery phase
- **Write permissions**: Required for backup, recreation, and restoration phases
- **Tag permissions**: Required for retagging phase

### Data Security

- **In-transit encryption**: All S3 transfers should use HTTPS
- **At-rest encryption**: S3 bucket should have encryption enabled
- **Access logging**: Enable S3 access logging for audit trail
- **Temporary credentials**: Use IAM roles with temporary credentials rather than long-term access keys

### Sensitive Data Handling

- Configuration files may contain sensitive information (IAM role ARNs, VPC IDs)
- Store configuration files in a secure location with appropriate file permissions
- Consider encrypting configuration files at rest
- Do not log sensitive data (IAM credentials, user data content)

## Performance Considerations

### Scalability

- **Large domains**: Domains with 100+ user profiles and spaces may take significant time to process
- **Parallel processing**: Consider parallelizing independent operations (user profile creation, space creation)
- **Rate limiting**: Implement backoff strategies to avoid AWS API throttling

### Data Transfer

- **Large EFS volumes**: Lifecycle configurations have execution time limits (5 minutes for startup scripts)
- **S3 sync performance**: Depends on number of files and total size
- **Recommendation**: For volumes > 10GB, consider alternative backup strategies (EFS backup, snapshots)

### Optimization Strategies

- **Batch operations**: Use batch APIs where available
- **Caching**: Cache domain configuration to avoid repeated API calls
- **Incremental processing**: Support resuming from failures rather than restarting entire process

## Deployment and Operations

### Prerequisites

- Python 3.8 or higher
- boto3 library installed
- AWS credentials configured with required permissions
- S3 bucket created for backup storage

### Execution Order

1. Run `discover_domain.py` to capture existing domain configuration
2. Run `backup_domain_data.py` to sync user data to S3
3. **Manual step**: Move AWS account to new organization
4. Run `recreate_domain.py` to create new domain and resources
5. Run `retag_resources.py` to update resource tags
6. Run `restore_domain_data.py` to sync data back from S3

### Monitoring and Validation

- Check status JSON files after each phase for failures
- Verify domain, user profiles, and spaces are created correctly in AWS console
- Validate that apps start successfully after restoration
- Confirm users can access their data in the new domain

### Rollback Strategy

- **Before recreation**: Original domain still exists, no rollback needed
- **After recreation**: Both domains exist temporarily, can revert to original if issues found
- **After deletion**: No automated rollback, must rely on S3 backups for data recovery

## Limitations and Constraints

### Unsupported Features

1. **Canvas applications**: Not supported in this migration tool
2. **Data Wrangler applications**: Not supported in this migration tool
3. **RStudio applications**: Not supported in this migration tool
4. **Custom file systems**: Only default EFS volumes are supported

### Known Limitations

1. **Large EFS volumes**: Volumes containing multiple gigabytes of data may cause S3 sync failures in lifecycle configurations due to execution time limits
2. **Lifecycle configuration timeout**: Startup scripts have a 5-minute execution limit
3. **Manual organization migration**: The AWS account must be manually moved between organizations
4. **Identity Center mapping**: User identities must exist in the new Identity Center instance

### Workarounds

- For large data volumes, consider using AWS DataSync or EFS-to-EFS replication instead of lifecycle configuration scripts
- For unsupported app types, manually migrate those resources separately
- Test the migration process in a non-production environment first

## Minimum Required IAM Permissions

The following IAM permissions are required for the migration process:

### Discovery Phase
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sagemaker:DescribeDomain",
        "sagemaker:ListUserProfiles",
        "sagemaker:DescribeUserProfile",
        "sagemaker:ListSpaces",
        "sagemaker:DescribeSpace"
      ],
      "Resource": "*"
    }
  ]
}
```

### Backup Phase
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sagemaker:CreateStudioLifecycleConfig",
        "sagemaker:UpdateDomain",
        "sagemaker:ListApps",
        "sagemaker:DescribeApp",
        "sagemaker:DeleteApp",
        "sagemaker:CreateApp"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::backup-bucket-name",
        "arn:aws:s3:::backup-bucket-name/*"
      ]
    }
  ]
}
```

### Recreation Phase
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sagemaker:CreateDomain",
        "sagemaker:DescribeDomain",
        "sagemaker:DescribeUserProfile",
        "sagemaker:UpdateUserProfile",
        "sagemaker:CreateSpace",
        "sagemaker:DescribeSpace"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sso-admin:ListApplications",
        "sso-admin:CreateApplicationAssignment",
        "identitystore:ListUsers"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "iam:PassRole"
      ],
      "Resource": "arn:aws:iam::*:role/*SageMaker*"
    }
  ]
}
```

### Retagging Phase
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sagemaker:ListTrainingJobs",
        "sagemaker:DescribeTrainingJob",
        "sagemaker:ListPipelines",
        "sagemaker:DescribePipeline",
        "sagemaker:ListEndpoints",
        "sagemaker:DescribeEndpoint",
        "sagemaker:ListTags",
        "sagemaker:AddTags",
        "sagemaker:DeleteTags"
      ],
      "Resource": "*"
    }
  ]
}
```

### Restoration Phase
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sagemaker:CreateStudioLifecycleConfig",
        "sagemaker:UpdateDomain",
        "sagemaker:CreateApp",
        "sagemaker:DescribeApp"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::backup-bucket-name",
        "arn:aws:s3:::backup-bucket-name/*"
      ]
    }
  ]
}
```

### Consolidated Minimum Policy

A single IAM policy combining all required permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SageMakerDomainMigration",
      "Effect": "Allow",
      "Action": [
        "sagemaker:DescribeDomain",
        "sagemaker:CreateDomain",
        "sagemaker:UpdateDomain",
        "sagemaker:ListUserProfiles",
        "sagemaker:DescribeUserProfile",
        "sagemaker:UpdateUserProfile",
        "sagemaker:ListSpaces",
        "sagemaker:DescribeSpace",
        "sagemaker:CreateSpace",
        "sagemaker:ListApps",
        "sagemaker:DescribeApp",
        "sagemaker:CreateApp",
        "sagemaker:DeleteApp",
        "sagemaker:CreateStudioLifecycleConfig",
        "sagemaker:ListTrainingJobs",
        "sagemaker:DescribeTrainingJob",
        "sagemaker:ListPipelines",
        "sagemaker:DescribePipeline",
        "sagemaker:ListEndpoints",
        "sagemaker:DescribeEndpoint",
        "sagemaker:ListTags",
        "sagemaker:AddTags",
        "sagemaker:DeleteTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IdentityCenterAccess",
      "Effect": "Allow",
      "Action": [
        "sso-admin:ListApplications",
        "sso-admin:CreateApplicationAssignment",
        "identitystore:ListUsers"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3BackupAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::backup-bucket-name",
        "arn:aws:s3:::backup-bucket-name/*"
      ]
    },
    {
      "Sid": "IAMPassRole",
      "Effect": "Allow",
      "Action": [
        "iam:PassRole"
      ],
      "Resource": "arn:aws:iam::*:role/*SageMaker*",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "sagemaker.amazonaws.com"
        }
      }
    }
  ]
}
```

**Note**: Replace `backup-bucket-name` with your actual S3 bucket name. The `iam:PassRole` permission is required to assign execution roles to domains and user profiles.
