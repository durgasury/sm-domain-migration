#!/usr/bin/env python3
"""
Discovery Script for SageMaker Domain Migration

This script captures all configuration details of an existing SageMaker Studio domain,
including domain settings, user profiles, and spaces.

Usage:
    python discover_domain.py --domain-id <domain-id> [--output-dir <path>]
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any

from utils import (
    get_sagemaker_client,
    setup_logging,
    get_logger,
    save_json,
    DOMAIN_CONFIG_SCHEMA,
    USER_PROFILE_CONFIG_SCHEMA,
    SPACE_CONFIG_SCHEMA,
    validate_json_schema
)

logger = get_logger(__name__)


def validate_domain_id(domain_id: str) -> bool:
    """
    Validate domain ID format
    
    Args:
        domain_id: Domain ID to validate
        
    Returns:
        True if valid
        
    Raises:
        ValueError: If domain ID format is invalid
    """
    if not domain_id.startswith('d-') or len(domain_id) < 3:
        raise ValueError(f"Invalid domain ID format: {domain_id}. Expected format: d-xxxxxxxxxxxx")
    return True


def get_domain_details(sagemaker_client, domain_id: str) -> Dict[str, Any]:
    """
    Retrieve domain configuration details
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        
    Returns:
        Domain configuration dictionary
        
    Raises:
        Exception: If domain cannot be retrieved
    """
    try:
        logger.info(f"Retrieving domain details for {domain_id}")
        response = sagemaker_client.describe_domain(DomainId=domain_id)
        
        # Remove metadata fields
        response.pop('ResponseMetadata', None)
        response.pop('CreationTime', None)
        response.pop('LastModifiedTime', None)
        response.pop('Status', None)
        response.pop('FailureReason', None)
        response.pop('Url', None)
        
        logger.info(f"Successfully retrieved domain configuration")
        return response
        
    except sagemaker_client.exceptions.ResourceNotFound:
        logger.error(f"Domain not found: {domain_id}")
        raise ValueError(f"Domain {domain_id} does not exist")
    except Exception as e:
        logger.error(f"Failed to retrieve domain details: {str(e)}")
        raise


def list_user_profiles(sagemaker_client, domain_id: str) -> List[str]:
    """
    List all user profiles in a domain
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        
    Returns:
        List of user profile names
    """
    try:
        logger.info(f"Listing user profiles for domain {domain_id}")
        user_profiles = []
        next_token = None
        
        while True:
            if next_token:
                response = sagemaker_client.list_user_profiles(
                    DomainIdEquals=domain_id,
                    NextToken=next_token
                )
            else:
                response = sagemaker_client.list_user_profiles(
                    DomainIdEquals=domain_id
                )
            
            user_profiles.extend([up['UserProfileName'] for up in response.get('UserProfiles', [])])
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Found {len(user_profiles)} user profiles")
        return user_profiles
        
    except Exception as e:
        logger.error(f"Failed to list user profiles: {str(e)}")
        raise


def get_user_profile_details(sagemaker_client, domain_id: str, user_profile_name: str) -> Dict[str, Any]:
    """
    Get detailed configuration for a user profile
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        user_profile_name: User profile name
        
    Returns:
        User profile configuration dictionary
    """
    try:
        logger.debug(f"Retrieving details for user profile: {user_profile_name}")
        response = sagemaker_client.describe_user_profile(
            DomainId=domain_id,
            UserProfileName=user_profile_name
        )
        
        # Remove metadata fields
        response.pop('ResponseMetadata', None)
        response.pop('CreationTime', None)
        response.pop('LastModifiedTime', None)
        response.pop('Status', None)
        response.pop('FailureReason', None)
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to retrieve user profile {user_profile_name}: {str(e)}")
        raise


def list_spaces(sagemaker_client, domain_id: str) -> List[str]:
    """
    List all spaces in a domain
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        
    Returns:
        List of space names
    """
    try:
        logger.info(f"Listing spaces for domain {domain_id}")
        spaces = []
        next_token = None
        
        while True:
            if next_token:
                response = sagemaker_client.list_spaces(
                    DomainIdEquals=domain_id,
                    NextToken=next_token
                )
            else:
                response = sagemaker_client.list_spaces(
                    DomainIdEquals=domain_id
                )
            
            spaces.extend([space['SpaceName'] for space in response.get('Spaces', [])])
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Found {len(spaces)} spaces")
        return spaces
        
    except Exception as e:
        logger.error(f"Failed to list spaces: {str(e)}")
        raise


def get_space_details(sagemaker_client, domain_id: str, space_name: str) -> Dict[str, Any]:
    """
    Get detailed configuration for a space
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        space_name: Space name
        
    Returns:
        Space configuration dictionary
    """
    try:
        logger.debug(f"Retrieving details for space: {space_name}")
        response = sagemaker_client.describe_space(
            DomainId=domain_id,
            SpaceName=space_name
        )
        
        # Remove metadata fields
        response.pop('ResponseMetadata', None)
        response.pop('CreationTime', None)
        response.pop('LastModifiedTime', None)
        response.pop('Status', None)
        response.pop('FailureReason', None)
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to retrieve space {space_name}: {str(e)}")
        raise


def list_apps(sagemaker_client, domain_id: str) -> List[Dict[str, Any]]:
    """
    List all apps in a domain
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        
    Returns:
        List of app information dictionaries
    """
    try:
        logger.info(f"Listing apps for domain {domain_id}")
        apps = []
        next_token = None
        
        while True:
            if next_token:
                response = sagemaker_client.list_apps(
                    DomainIdEquals=domain_id,
                    NextToken=next_token
                )
            else:
                response = sagemaker_client.list_apps(
                    DomainIdEquals=domain_id
                )
            
            for app in response.get('Apps', []):
                # Only capture JupyterLab and CodeEditor apps that are InService
                if app['AppType'] in ['JupyterLab', 'CodeEditor'] and app['Status'] == 'InService':
                    apps.append({
                        'DomainId': app['DomainId'],
                        'UserProfileName': app.get('UserProfileName'),
                        'SpaceName': app.get('SpaceName'),
                        'AppType': app['AppType'],
                        'AppName': app['AppName']
                    })
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Found {len(apps)} InService JupyterLab/CodeEditor apps")
        return apps
        
    except Exception as e:
        logger.error(f"Failed to list apps: {str(e)}")
        raise


def get_app_details(sagemaker_client, app_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get detailed configuration for an app, including ResourceSpec
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        app_info: App information dictionary
        
    Returns:
        App configuration dictionary with ResourceSpec
    """
    try:
        domain_id = app_info['DomainId']
        user_profile_name = app_info.get('UserProfileName')
        space_name = app_info.get('SpaceName')
        app_type = app_info['AppType']
        app_name = app_info['AppName']
        
        logger.debug(f"Retrieving details for app: {space_name or user_profile_name}/{app_type}/{app_name}")
        
        describe_kwargs = {
            'DomainId': domain_id,
            'AppType': app_type,
            'AppName': app_name
        }
        
        if user_profile_name:
            describe_kwargs['UserProfileName'] = user_profile_name
        if space_name:
            describe_kwargs['SpaceName'] = space_name
        
        response = sagemaker_client.describe_app(**describe_kwargs)
        
        # Extract relevant fields
        app_config = {
            'DomainId': domain_id,
            'UserProfileName': user_profile_name,
            'SpaceName': space_name,
            'AppType': app_type,
            'AppName': app_name,
            'ResourceSpec': response.get('ResourceSpec', {})
        }
        
        return app_config
        
    except Exception as e:
        logger.error(f"Failed to retrieve app details: {str(e)}")
        raise


def discover_domain(domain_id: str, output_dir: str) -> None:
    """
    Main discovery function to capture all domain configuration
    
    Args:
        domain_id: SageMaker domain ID
        output_dir: Directory to save configuration files
    """
    # Validate domain ID format
    validate_domain_id(domain_id)
    
    # Initialize AWS client
    sagemaker_client = get_sagemaker_client()
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Get domain configuration
    logger.info("=" * 60)
    logger.info("Starting domain discovery")
    logger.info("=" * 60)
    
    domain_config = get_domain_details(sagemaker_client, domain_id)
    domain_config_file = output_path / "domain_config.json"
    save_json(domain_config, str(domain_config_file))
    
    # Validate domain configuration
    try:
        validate_json_schema(domain_config, DOMAIN_CONFIG_SCHEMA)
    except ValueError as e:
        logger.warning(f"Domain configuration validation warning: {str(e)}")
    
    # Get user profiles
    user_profile_names = list_user_profiles(sagemaker_client, domain_id)
    user_profiles = []
    
    for user_profile_name in user_profile_names:
        user_profile = get_user_profile_details(sagemaker_client, domain_id, user_profile_name)
        user_profiles.append(user_profile)
    
    user_profiles_data = {"UserProfiles": user_profiles}
    user_profiles_file = output_path / "user_profiles.json"
    save_json(user_profiles_data, str(user_profiles_file))
    
    # Validate user profiles configuration
    try:
        validate_json_schema(user_profiles_data, USER_PROFILE_CONFIG_SCHEMA)
    except ValueError as e:
        logger.warning(f"User profiles configuration validation warning: {str(e)}")
    
    # Get spaces
    space_names = list_spaces(sagemaker_client, domain_id)
    spaces = []
    
    for space_name in space_names:
        space = get_space_details(sagemaker_client, domain_id, space_name)
        spaces.append(space)
    
    spaces_data = {"Spaces": spaces}
    spaces_file = output_path / "spaces.json"
    save_json(spaces_data, str(spaces_file))
    
    # Validate spaces configuration
    try:
        validate_json_schema(spaces_data, SPACE_CONFIG_SCHEMA)
    except ValueError as e:
        logger.warning(f"Spaces configuration validation warning: {str(e)}")
    
    # Get apps and their ResourceSpecs
    app_list = list_apps(sagemaker_client, domain_id)
    apps = []
    
    for app_info in app_list:
        app_details = get_app_details(sagemaker_client, app_info)
        apps.append(app_details)
    
    apps_data = {"Apps": apps}
    apps_file = output_path / "apps.json"
    save_json(apps_data, str(apps_file))
    
    # Summary
    logger.info("=" * 60)
    logger.info("Discovery completed successfully")
    logger.info("=" * 60)
    logger.info(f"Domain ID: {domain_id}")
    logger.info(f"Domain Name: {domain_config.get('DomainName')}")
    logger.info(f"User Profiles: {len(user_profiles)}")
    logger.info(f"Spaces: {len(spaces)}")
    logger.info(f"Apps: {len(apps)}")
    logger.info(f"Configuration saved to: {output_dir}")
    logger.info("=" * 60)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Discover and capture SageMaker Studio domain configuration"
    )
    parser.add_argument(
        '--domain-id',
        required=True,
        help='SageMaker domain ID (e.g., d-xxxxxxxxxxxx)'
    )
    parser.add_argument(
        '--output-dir',
        default='./migration_data',
        help='Output directory for configuration files (default: ./migration_data)'
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(level=args.log_level)
    
    try:
        discover_domain(args.domain_id, args.output_dir)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Discovery failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
