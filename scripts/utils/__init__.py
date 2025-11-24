"""Shared utilities for SageMaker domain migration"""

from .aws_clients import get_sagemaker_client, get_s3_client, get_iam_client, get_sso_admin_client, get_identitystore_client
from .logging_config import setup_logging, get_logger
from .json_operations import save_json, load_json, validate_json_schema
from .config_schemas import (
    DOMAIN_CONFIG_SCHEMA,
    USER_PROFILE_CONFIG_SCHEMA,
    SPACE_CONFIG_SCHEMA,
    RESOURCE_MAPPING_SCHEMA,
    STATUS_SCHEMA
)

__all__ = [
    'get_sagemaker_client',
    'get_s3_client',
    'get_iam_client',
    'get_sso_admin_client',
    'get_identitystore_client',
    'setup_logging',
    'get_logger',
    'save_json',
    'load_json',
    'validate_json_schema',
    'DOMAIN_CONFIG_SCHEMA',
    'USER_PROFILE_CONFIG_SCHEMA',
    'SPACE_CONFIG_SCHEMA',
    'RESOURCE_MAPPING_SCHEMA',
    'STATUS_SCHEMA'
]
