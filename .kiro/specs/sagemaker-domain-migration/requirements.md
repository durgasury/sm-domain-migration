# Requirements Document

## Introduction

This document specifies the requirements for a SageMaker Studio domain migration tool that enables moving a SageMaker Studio domain from one AWS Organization to another. The migration is necessary when an AWS account moves between organizations, which breaks SSO-based SageMaker Studio domains due to Identity Center instance changes. The tool automates the process of capturing the existing domain configuration, backing up user data, recreating the domain in the new organization context, and restoring all data and configurations.

## Glossary

- **SageMaker Studio Domain**: An AWS SageMaker resource that provides a collaborative environment for machine learning development
- **SSO Mode**: Single Sign-On authentication mode that integrates with AWS Identity Center
- **Identity Center**: AWS service that provides centralized access management across AWS accounts and applications
- **User Profile**: A SageMaker Studio entity representing an individual user with associated IAM roles and settings
- **Space**: A collaborative workspace within SageMaker Studio that can be shared among users
- **EBS Volume**: Elastic Block Store volume attached to SageMaker Studio apps for persistent storage
- **Lifecycle Configuration (LCC)**: Scripts that run automatically when SageMaker Studio apps start or stop
- **App**: A running instance of a SageMaker Studio application (JupyterLab, CodeEditor, etc.)
- **Domain Execution Role**: The default IAM role used by user profiles within a domain
- **Organization (Org)**: An AWS Organizations entity that groups multiple AWS accounts

## Requirements

### Requirement 1

**User Story:** As a cloud administrator, I want to capture all configuration details of an existing SageMaker Studio domain, so that I can recreate it accurately in a new organizational context.

#### Acceptance Criteria

1. WHEN provided with a domain ID, THE system SHALL retrieve all domain configuration parameters including networking settings, subnets, VPC configuration, and security groups
2. WHEN retrieving domain details, THE system SHALL capture all lifecycle configurations attached to the domain
3. WHEN retrieving domain details, THE system SHALL capture all custom images registered with the domain
4. WHEN domain details are retrieved, THE system SHALL persist the configuration data to disk in a structured format
5. THE system SHALL validate that the domain ID exists before attempting to retrieve configuration details

### Requirement 2

**User Story:** As a cloud administrator, I want to capture all user profiles and their associated configurations, so that I can recreate the user access structure in the new domain.

#### Acceptance Criteria

1. WHEN listing user profiles, THE system SHALL retrieve all user profiles associated with the specified domain
2. WHEN retrieving user profile details, THE system SHALL capture the IAM execution role associated with each user profile
3. WHEN retrieving user profile details, THE system SHALL capture any user-specific settings and configurations
4. WHEN user profile data is collected, THE system SHALL persist the data to disk in a structured format that maps user profiles to their configurations

### Requirement 3

**User Story:** As a cloud administrator, I want to capture all spaces and their ownership details, so that I can recreate the collaborative workspace structure in the new domain.

#### Acceptance Criteria

1. WHEN listing spaces, THE system SHALL retrieve all spaces associated with the specified domain
2. WHEN retrieving space details, THE system SHALL capture the owner user profile for each space
3. WHEN retrieving space details, THE system SHALL capture the sharing type configuration for each space
4. WHEN space data is collected, THE system SHALL persist the data to disk in a structured format that maps spaces to their owners and configurations

### Requirement 4

**User Story:** As a cloud administrator, I want to back up all user data from EBS volumes to S3, so that no data is lost during the domain migration process.

#### Acceptance Criteria

1. WHEN creating backup lifecycle scripts, THE system SHALL generate two distinct scripts for JupyterLab and CodeEditor app types
2. WHEN a backup lifecycle script executes, THE system SHALL sync all user data from the EBS volume to the specified S3 bucket and prefix
3. WHEN syncing data to S3, THE system SHALL append the user profile name and space name to the S3 prefix to maintain data organization
4. WHEN attaching lifecycle scripts, THE system SHALL associate the backup scripts with the existing domain
5. THE system SHALL accept S3 bucket name and optional prefix as input parameters for the backup operation

### Requirement 5

**User Story:** As a cloud administrator, I want to restart all active apps to apply the backup lifecycle configuration, so that user data is synchronized to S3 before domain deletion.

#### Acceptance Criteria

1. WHEN restarting apps, THE system SHALL identify all active apps with type JupyterLab or CodeEditor
2. WHEN restarting an app, THE system SHALL delete the existing app instance and create a new app instance with the same configuration
3. WHEN apps are restarted, THE system SHALL wait for each app to reach a running state before proceeding
4. WHEN app restart failures occur, THE system SHALL collect and report all failed app instances
5. IF any app fails to restart, THEN THE system SHALL terminate the backup process and report the failures to the user

### Requirement 6

**User Story:** As a cloud administrator, I want to recreate the SageMaker Studio domain in the new organization, so that users can continue their work after the account migration.

#### Acceptance Criteria

1. WHEN creating the new domain, THE system SHALL use the same configuration parameters as the original domain including networking, subnets, and security settings
2. WHEN creating the new domain, THE system SHALL attach the same lifecycle configurations that were present in the original domain
3. WHEN creating the new domain, THE system SHALL register the same custom images that were present in the original domain
4. THE system SHALL validate that the new domain is created successfully before proceeding to user profile creation

### Requirement 7

**User Story:** As a cloud administrator, I want to recreate all user profiles in the new domain, so that users retain their access and role configurations.

#### Acceptance Criteria

1. WHEN creating user profiles, THE system SHALL retrieve the Identity Center application ID associated with the new domain
2. WHEN creating user profiles, THE system SHALL create application assignments in Identity Center for each user
3. WHEN a user profile is automatically created by SageMaker after application assignment, THE system SHALL update the profile with the same IAM execution role as the original profile if it differs from the domain default execution role
4. WHEN updating a user profile, THE system SHALL apply the same user-specific settings and configurations as the original profile
5. THE system SHALL validate that each user profile is created and updated successfully before proceeding to the next profile

### Requirement 8

**User Story:** As a cloud administrator, I want to recreate all spaces in the new domain, so that collaborative workspaces are preserved.

#### Acceptance Criteria

1. WHEN creating spaces, THE system SHALL create each space with the same owner user profile as the original space
2. WHEN creating a space, THE system SHALL configure the same sharing type as the original space
3. WHEN creating a space, THE system SHALL apply the same space-specific settings as the original space
4. THE system SHALL validate that each space is created successfully before proceeding to the next space

### Requirement 9

**User Story:** As a cloud administrator, I want to update SageMaker resource tags to reference the new domain, so that resource associations remain accurate.

#### Acceptance Criteria

1. WHEN updating tags, THE system SHALL identify all SageMaker jobs tagged with the original domain ID
2. WHEN updating tags, THE system SHALL identify all SageMaker pipelines tagged with the original domain ID
3. WHEN updating tags, THE system SHALL identify all SageMaker endpoints tagged with the original domain ID
4. WHEN updating resource tags, THE system SHALL replace the original domain ID with the new domain ID in the tags
5. WHEN updating resource tags, THE system SHALL map and replace original user profile ARNs with corresponding new user profile ARNs
6. WHEN updating resource tags, THE system SHALL map and replace original space ARNs with corresponding new space ARNs
7. THE system SHALL maintain a mapping between original and new user profile ARNs for tag updates
8. THE system SHALL maintain a mapping between original and new space ARNs for tag updates
9. THE system SHALL validate that tag updates are applied successfully to all identified resources

### Requirement 10

**User Story:** As a cloud administrator, I want to restore all user data from S3 back to the new domain, so that users can access their files and work in the new environment.

#### Acceptance Criteria

1. WHEN creating restore lifecycle scripts, THE system SHALL generate two distinct scripts for JupyterLab and CodeEditor app types
2. WHEN a restore lifecycle script executes, THE system SHALL sync data from the S3 backup location to the EBS volume
3. WHEN syncing data from S3, THE system SHALL use the user profile name and space name to locate the correct backup data
4. WHEN attaching restore lifecycle scripts, THE system SHALL associate the scripts with the new domain
5. THE system SHALL validate that the S3 backup location exists and is accessible before attempting restoration

### Requirement 11

**User Story:** As a cloud administrator, I want to start all spaces to trigger data restoration, so that user data is available in the new domain.

#### Acceptance Criteria

1. WHEN starting spaces, THE system SHALL create app instances for all spaces to trigger lifecycle configuration execution
2. WHEN creating app instances, THE system SHALL wait for each app to reach a running state
3. WHEN app creation failures occur, THE system SHALL collect and report all failed space instances
4. THE system SHALL provide a summary of successfully restored spaces and any failures

### Requirement 12

**User Story:** As a cloud administrator, I want clear documentation of migration limitations, so that I can assess whether this tool is appropriate for my use case.

#### Acceptance Criteria

1. THE system documentation SHALL explicitly state that Canvas applications are not supported
2. THE system documentation SHALL explicitly state that Data Wrangler applications are not supported
3. THE system documentation SHALL explicitly state that RStudio applications are not supported
4. THE system documentation SHALL explicitly state that custom file systems are not supported
5. THE system documentation SHALL warn that EFS volumes containing multiple gigabytes of data may cause S3 sync failures in lifecycle configurations

### Requirement 13

**User Story:** As a cloud administrator, I want to know the minimum IAM permissions required for migration, so that I can grant appropriate access without over-provisioning.

#### Acceptance Criteria

1. THE system documentation SHALL list all SageMaker API actions required for the migration process
2. THE system documentation SHALL list all S3 API actions required for the migration process
3. THE system documentation SHALL list all IAM API actions required for the migration process
4. THE system documentation SHALL provide a consolidated IAM policy document with minimum required permissions
5. THE system documentation SHALL specify which permissions are required for each phase of the migration
