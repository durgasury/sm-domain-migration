# Troubleshooting Guide

This document provides solutions to common issues encountered during the SageMaker Studio domain migration process.

## Common Issues and Solutions

### Issue: "Domain not found" error during discovery

**Cause:** The domain ID is incorrect or the domain doesn't exist in the current region.

**Solution:**
1. Verify the domain ID is correct: `aws sagemaker list-domains`
2. Ensure you're using the correct AWS region: `aws configure get region`
3. Check that your credentials have access to the domain

### Issue: Apps fail to restart during backup phase

**Cause:** Apps may be in a transitional state or have configuration issues.

**Solution:**
1. Check the `backup_status.json` file for specific error messages
2. Manually delete stuck apps: `aws sagemaker delete-app --domain-id <id> --user-profile-name <name> --app-type <type> --app-name <name>`
3. Wait a few minutes and retry the backup script
4. If persistent, check CloudWatch logs for the app

### Issue: S3 sync fails in lifecycle configuration

**Cause:** The EFS volume contains too much data to sync within the 5-minute timeout.

**Solution:**
1. Use AWS DataSync instead of lifecycle configurations for large data transfers
2. Reduce the amount of data by cleaning up unnecessary files
3. Exclude large directories from the sync using `--exclude` patterns

### Issue: User profiles not created automatically after application assignment

**Cause:** There may be a delay in SageMaker's automatic user profile creation process.

**Solution:**
1. Wait 5-10 minutes for the automatic creation process
2. Check Identity Center to ensure the user assignment was successful
3. Verify the user exists in the new Identity Center instance
4. Manually create the user profile if automatic creation fails after 15 minutes

### Issue: "User not found in Identity Center" during user assignment

**Cause:** The user doesn't exist in the new Identity Center instance or the username format doesn't match.

**Solution:**
1. Verify users exist in the new Identity Center instance
2. Check that usernames match the format expected by the script
3. Verify the identity store ID is correct:
   ```bash
   aws identitystore list-users --identity-store-id d-92679c0362
   ```
4. Find the correct identity store ID in the AWS Identity Center console under "Settings"

### Issue: "Access Denied" errors during recreation

**Cause:** Insufficient IAM permissions or the execution role doesn't exist in the new account.

**Solution:**
1. Verify your IAM permissions match the [consolidated policy](IAM_PERMISSIONS.md#consolidated-iam-policy)
2. Ensure the domain execution role exists in the target account
3. Check that the `iam:PassRole` permission is configured correctly
4. Verify the execution role trust policy allows SageMaker to assume it

### Issue: Tags not updating on resources

**Cause:** Resources may not have the expected tags or the ARN mapping is incomplete.

**Solution:**
1. Check the `recreation_mapping.json` file to verify ARN mappings
2. Manually verify tags on resources: `aws sagemaker list-tags --resource-arn <arn>`
3. Ensure the old domain ID is correct in the retag command
4. Check CloudWatch logs for specific API errors

### Issue: Data not restored to new domain

**Cause:** S3 paths may be incorrect or lifecycle configurations not executing.

**Solution:**
1. Verify the S3 bucket and prefix are correct
2. Check that data exists in S3: `aws s3 ls s3://bucket/prefix/`
3. Review CloudWatch logs for lifecycle configuration execution
4. Manually start an app and check `/var/log/studio/` for lifecycle logs
5. Verify the lifecycle configuration is attached to the domain

### Issue: "ValidationException" during app creation

**Cause:** ResourceSpec configuration is invalid or incompatible with the new domain.

**Solution:**
1. Check the ResourceSpec in the original app configuration
2. Verify that the SageMaker image ARN is valid in the new account/region
3. Update the ResourceSpec to use compatible images
4. Check that the instance type is available in the target region

### Issue: Lifecycle configuration execution timeout

**Cause:** The 5-minute execution limit is exceeded due to large data volumes.

**Solution:**
1. Reduce the amount of data being synced
2. Use `--no-backup-efs` to exclude EFS data if not needed
3. Consider using AWS DataSync for large data transfers
4. Split the sync into multiple smaller operations

### Issue: Identity Center application not found

**Cause:** The domain's SingleSignOnApplicationArn is missing or invalid.

**Solution:**
1. Verify the domain is in SSO authentication mode
2. Check that Identity Center is properly configured
3. Ensure the domain was created with SSO authentication
4. Manually create the Identity Center application if needed

### Issue: Space creation fails with ownership errors

**Cause:** The user profile doesn't exist or the user doesn't have proper permissions.

**Solution:**
1. Ensure user profiles are created before spaces
2. Verify the user exists in the new Identity Center instance
3. Check that the user has been assigned to the domain application
4. Wait for user profile creation to complete before creating spaces

## Checking Logs

### SageMaker Logs
```bash
# List log groups
aws logs describe-log-groups --log-group-name-prefix /aws/sagemaker

# View lifecycle configuration logs
aws logs tail /aws/sagemaker/studio/lifecycle-config --follow
```

### Script Logs

All scripts output logs to the console. To save logs to a file:
```bash
python scripts/discover_domain.py --domain-id d-xxx 2>&1 | tee discovery.log
```

### CloudWatch Logs for Apps

Check individual app logs for detailed error information:
```bash
# List log streams for a specific app
aws logs describe-log-streams \
  --log-group-name /aws/sagemaker/studio \
  --log-stream-name-prefix "domain-id/user-profile-name/app-type/app-name"

# View specific app logs
aws logs get-log-events \
  --log-group-name /aws/sagemaker/studio \
  --log-stream-name "domain-id/user-profile-name/app-type/app-name/lifecycle-config"
```

## Debugging Steps

### 1. Verify Prerequisites
- [ ] AWS credentials are configured correctly
- [ ] IAM permissions are sufficient
- [ ] S3 bucket exists and is accessible
- [ ] Identity Center is configured in the new organization
- [ ] Users exist in the new Identity Center instance

### 2. Check Status Files
Each script generates detailed status files in the `migration_data` directory:
- `backup_status.json` - Backup operation results
- `recreation_mapping.json` - Resource ARN mappings
- `user_assignment_status.json` - User assignment results
- `retagging_status.json` - Retagging operation results
- `restoration_status.json` - Restoration operation results

### 3. Validate Configurations
```bash
# Check domain configuration
aws sagemaker describe-domain --domain-id d-xxxxxxxxxxxx

# Check user profiles
aws sagemaker list-user-profiles --domain-id d-xxxxxxxxxxxx

# Check spaces
aws sagemaker list-spaces --domain-id d-xxxxxxxxxxxx

# Check apps
aws sagemaker list-apps --domain-id d-xxxxxxxxxxxx
```

### 4. Test Individual Components
Test each phase independently to isolate issues:
1. Run discovery on a test domain
2. Test backup with a single user profile
3. Test recreation with minimal configuration
4. Test user assignment with a single user
5. Test restoration with a single space

## Performance Optimization

### Reducing Migration Time
1. **Parallel Processing**: The scripts already use parallel processing where possible
2. **Skip EFS Data**: Use `--no-backup-efs` if EFS data is not needed
3. **Selective Migration**: Migrate only active users and spaces
4. **Pre-cleanup**: Remove unnecessary files before backup

### Handling Large Domains
1. **Batch Processing**: Process users and spaces in smaller batches
2. **Staged Migration**: Migrate users in groups over time
3. **External Tools**: Use AWS DataSync for very large data volumes
4. **Resource Limits**: Monitor API rate limits and adjust delays

## Recovery Procedures

### Rollback Scenarios

#### Before Recreation
- Original domain is intact
- No rollback needed, just fix issues and retry

#### After Recreation
- Both domains exist
- Can revert users to original domain
- Delete new domain if needed

#### After Data Restoration
- Data exists in both domains
- Users can access either domain
- Keep original domain as backup

### Data Recovery
If data is lost or corrupted:
1. Check S3 backup bucket for data integrity
2. Use S3 versioning to recover previous versions
3. Restore from EFS snapshots if available
4. Re-run backup phase if original domain is still available

## Getting Help

If you encounter issues not covered in this troubleshooting guide:

1. **Check Status Files**: Review the detailed status JSON files in the `migration_data` directory
2. **Review CloudWatch Logs**: Check SageMaker and lifecycle configuration logs
3. **Verify Prerequisites**: Ensure all requirements are met
4. **Test in Non-Production**: Validate the process in a development environment
5. **Contact Support**: Reach out to your AWS support team for assistance

## Common Error Messages

### "ResourceNotFoundException"
- **Cause**: Resource (domain, user profile, space) doesn't exist
- **Solution**: Verify resource IDs and ensure they exist in the correct region

### "ValidationException"
- **Cause**: Invalid parameters or configuration
- **Solution**: Check parameter formats and values against AWS API documentation

### "AccessDeniedException"
- **Cause**: Insufficient IAM permissions
- **Solution**: Review and update IAM policies as described in [IAM_PERMISSIONS.md](IAM_PERMISSIONS.md)

### "ConflictException"
- **Cause**: Resource already exists or is in use
- **Solution**: Check resource status and wait for operations to complete

### "ThrottlingException"
- **Cause**: API rate limits exceeded
- **Solution**: Implement exponential backoff or reduce request frequency

### "ServiceUnavailableException"
- **Cause**: AWS service temporarily unavailable
- **Solution**: Wait and retry the operation

## Best Practices for Troubleshooting

1. **Enable Debug Logging**: Use `--log-level DEBUG` for detailed output
2. **Save All Logs**: Redirect script output to files for later analysis
3. **Document Issues**: Keep track of errors and solutions for future reference
4. **Test Incrementally**: Validate each phase before proceeding
5. **Monitor Resources**: Watch AWS console during operations
6. **Backup Everything**: Ensure data is safely backed up before making changes