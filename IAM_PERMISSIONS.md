# IAM Permissions

This document outlines the IAM permissions required for each phase of the SageMaker Studio domain migration process.

## Minimum Required Permissions by Phase

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

### User Assignment Phase
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sagemaker:DescribeDomain",
        "sso-admin:CreateApplicationAssignment",
        "identitystore:GetUserId"
      ],
      "Resource": "*"
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

## Consolidated IAM Policy

A single IAM policy combining all required permissions for the entire migration process:

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
        "identitystore:ListUsers",
        "identitystore:GetUserId"
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

**Note:** Replace `backup-bucket-name` with your actual S3 bucket name.

## Permission Notes

### S3 Bucket Permissions
- The S3 bucket permissions are required for both backup and restoration phases
- Ensure the bucket exists and is accessible from the AWS account running the migration
- Consider using bucket policies for cross-account access if needed

### Identity Center Permissions
- `sso-admin:CreateApplicationAssignment` is required for assigning users to the new domain
- `identitystore:GetUserId` is used to find users by username in the new Identity Center instance
- `identitystore:ListUsers` is used as a fallback search method

### SageMaker Permissions
- Most SageMaker permissions are required across multiple phases
- `sagemaker:CreateStudioLifecycleConfig` is needed for both backup and restoration
- Tag-related permissions are only needed for the retagging phase

### IAM PassRole
- Required for domain creation to pass the execution role to SageMaker
- The condition ensures the role can only be passed to SageMaker service
- Adjust the resource pattern if your SageMaker roles follow a different naming convention