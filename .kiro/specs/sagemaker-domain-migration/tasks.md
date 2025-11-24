# Implementation Plan

- [x] 1. Set up project structure and shared utilities
  - Create directory structure for scripts and configuration files
  - Implement shared utilities for AWS client initialization, logging, and JSON file operations
  - Create configuration file schema definitions
  - _Requirements: 1.4, 2.4, 3.4_

- [ ]* 1.1 Write property test for configuration serialization
  - **Property 1: Configuration persistence round-trip**
  - **Validates: Requirements 1.4, 2.4, 3.4**

- [x] 2. Implement discovery script
  - Create `discover_domain.py` with CLI argument parsing for domain ID and output directory
  - Implement domain configuration retrieval using `describe_domain` API
  - Implement user profile listing and detail retrieval
  - Implement space listing and detail retrieval
  - Save all configuration data to JSON files in structured format
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4_

- [ ]* 2.1 Write property test for domain configuration completeness
  - **Property 2: Domain configuration completeness**
  - **Validates: Requirements 1.1, 1.2, 1.3**

- [ ] 2.2 Write property test for invalid domain rejection
  - **Property 3: Invalid domain rejection**
  - **Validates: Requirements 1.5**

- [ ]* 2.3 Write property test for user profile data completeness
  - **Property 4: User profile data completeness**
  - **Validates: Requirements 2.2, 2.3**

- [ ]* 2.4 Write property test for space data completeness
  - **Property 5: Space data completeness**
  - **Validates: Requirements 3.2, 3.3**

- [x] 3. Implement backup script
  - Create `backup_domain_data.py` with CLI argument parsing for domain ID, S3 bucket, and prefix
  - Generate lifecycle configuration scripts for JupyterLab and CodeEditor that sync data to S3
  - Implement lifecycle configuration creation using `create_studio_lifecycle_config` API
  - Implement lifecycle configuration attachment to domain using `update_domain` API
  - Implement active app listing with filtering for JupyterLab and CodeEditor types
  - Implement app restart logic (delete then create) with status polling
  - Collect and report failed app restarts
  - Save backup status to JSON file
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.4, 5.5_

- [ ]* 3.1 Write property test for lifecycle script generation
  - **Property 6: Lifecycle script generation correctness**
  - **Validates: Requirements 4.2, 4.3**

- [ ]* 3.2 Write property test for app type filtering
  - **Property 7: App type filtering**
  - **Validates: Requirements 5.1**

- [ ]* 3.3 Write property test for app configuration preservation
  - **Property 8: App configuration preservation**
  - **Validates: Requirements 5.2**

- [ ]* 3.4 Write property test for error collection completeness
  - **Property 9: Error collection completeness**
  - **Validates: Requirements 5.4**

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement recreation script
  - Create `recreate_domain.py` with CLI argument parsing for configuration directory and optional new domain name
  - Load domain, user profile, and space configurations from JSON files
  - Implement domain creation using `create_domain` API with original configuration (using JupyterLabAppSettings and CodeEditorAppSettings)
  - Implement Identity Center application ID retrieval for the new domain
  - Implement user identity lookup in Identity Center using `identitystore:ListUsers`
  - Implement application assignment creation for each user using `sso-admin:CreateApplicationAssignment`
  - Implement polling to wait for automatic user profile creation after application assignment
  - Implement user profile settings update using `update_user_profile` API for custom roles and settings
  - Implement space creation with owner and sharing configuration
  - Build and save resource mapping (old ARNs to new ARNs) to JSON file
  - _Requirements: 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 8.1, 8.2, 8.3_

- [ ]* 5.1 Write property test for domain configuration preservation
  - **Property 10: Domain configuration preservation**
  - **Validates: Requirements 6.1, 6.2, 6.3**

- [ ]* 5.2 Write property test for user profile role preservation
  - **Property 11: User profile role preservation**
  - **Validates: Requirements 7.2**

- [ ]* 5.3 Write property test for user profile settings preservation
  - **Property 12: User profile settings preservation**
  - **Validates: Requirements 7.3**

- [ ]* 5.4 Write property test for space ownership preservation
  - **Property 13: Space ownership preservation**
  - **Validates: Requirements 8.1**

- [ ]* 5.5 Write property test for space configuration preservation
  - **Property 14: Space configuration preservation**
  - **Validates: Requirements 8.2, 8.3**

- [x] 6. Implement retagging script
  - Create `retag_resources.py` with CLI argument parsing for configuration directory, old domain ID, and new domain ID
  - Load resource mapping from JSON file
  - Implement resource listing for training jobs, pipelines, and endpoints filtered by domain ID tags
  - Implement tag retrieval using `list_tags` API for each resource
  - Implement ARN mapping logic to translate old ARNs to new ARNs using the mapping
  - Implement tag update logic using `delete_tags` and `add_tags` APIs
  - Save retagging status to JSON file
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9_

- [ ]* 6.1 Write property test for tagged resource identification
  - **Property 15: Tagged resource identification**
  - **Validates: Requirements 9.1, 9.2, 9.3**

- [ ]* 6.2 Write property test for tag transformation correctness
  - **Property 16: Tag transformation correctness**
  - **Validates: Requirements 9.4, 9.5, 9.6**

- [ ]* 6.3 Write property test for ARN mapping completeness
  - **Property 17: ARN mapping completeness**
  - **Validates: Requirements 9.7, 9.8**

- [x] 7. Implement restoration script
  - Create `restore_domain_data.py` with CLI argument parsing for domain ID, S3 bucket, prefix, and configuration directory
  - Generate lifecycle configuration scripts for JupyterLab and CodeEditor that sync data from S3
  - Implement lifecycle configuration creation and attachment to domain
  - Load space configuration from JSON file
  - Implement app creation for all spaces to trigger lifecycle configuration execution
  - Implement status polling to wait for apps to reach running state
  - Collect and report failed space restorations
  - Save restoration status to JSON file
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 11.1, 11.3, 11.4_

- [ ]* 7.1 Write property test for restore script path construction
  - **Property 18: Restore script path construction**
  - **Validates: Requirements 10.2, 10.3**

- [ ]* 7.2 Write property test for S3 backup validation
  - **Property 19: S3 backup validation**
  - **Validates: Requirements 10.5**

- [ ]* 7.3 Write property test for space restoration completeness
  - **Property 20: Space restoration completeness**
  - **Validates: Requirements 11.1, 11.3, 11.4**

- [ ] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Create comprehensive README documentation
  - Document the migration process with step-by-step instructions
  - Document prerequisites (Python version, boto3, AWS credentials, S3 bucket)
  - Document execution order for all scripts with example commands
  - Document limitations (Canvas, Data Wrangler, RStudio, custom file systems, large EFS volumes)
  - Document minimum required IAM permissions for each phase
  - Include consolidated IAM policy document
  - Add troubleshooting section with common issues and solutions
  - Add monitoring and validation guidance
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 13.1, 13.2, 13.3, 13.4, 13.5_

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
