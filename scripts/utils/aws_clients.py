"""AWS client initialization utilities"""

import boto3
from typing import Optional
from botocore.config import Config


def _get_boto_config() -> Config:
    """Get standard boto3 configuration with retry settings"""
    return Config(
        retries={
            'max_attempts': 10,
            'mode': 'adaptive'
        }
    )


def get_sagemaker_client(region_name: Optional[str] = None):
    """
    Initialize and return a SageMaker client
    
    Args:
        region_name: AWS region name (optional, uses default if not provided)
        
    Returns:
        boto3 SageMaker client
    """
    return boto3.client('sagemaker', region_name=region_name, config=_get_boto_config())


def get_s3_client(region_name: Optional[str] = None):
    """
    Initialize and return an S3 client
    
    Args:
        region_name: AWS region name (optional, uses default if not provided)
        
    Returns:
        boto3 S3 client
    """
    return boto3.client('s3', region_name=region_name, config=_get_boto_config())


def get_iam_client(region_name: Optional[str] = None):
    """
    Initialize and return an IAM client
    
    Args:
        region_name: AWS region name (optional, uses default if not provided)
        
    Returns:
        boto3 IAM client
    """
    return boto3.client('iam', region_name=region_name, config=_get_boto_config())


def get_sso_admin_client(region_name: Optional[str] = None):
    """
    Initialize and return an SSO Admin client
    
    Args:
        region_name: AWS region name (optional, uses default if not provided)
        
    Returns:
        boto3 SSO Admin client
    """
    return boto3.client('sso-admin', region_name=region_name, config=_get_boto_config())


def get_identitystore_client(region_name: Optional[str] = None):
    """
    Initialize and return an Identity Store client
    
    Args:
        region_name: AWS region name (optional, uses default if not provided)
        
    Returns:
        boto3 Identity Store client
    """
    return boto3.client('identitystore', region_name=region_name, config=_get_boto_config())
