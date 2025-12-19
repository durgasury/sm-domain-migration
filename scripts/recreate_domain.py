#!/usr/bin/env python3
"""
Recreation Script for SageMaker Domain Migration

This script recreates a SageMaker Studio domain, user profiles, and spaces
in a new organizational context using saved configuration files.

Usage:
    python recreate_domain.py [--config-dir <path>] [--new-domain-name <name>]
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from utils import (
    get_sagemaker_client,
    get_sso_admin_client,
    get_identitystore_client,
    setup_logging,
    get_logger,
    save_json,
    load_json,
    RESOURCE_MAPPING_SCHEMA,
    validate_json_schema
)

logger = get_logger(__name__)


def load_configurations(config_dir: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Load domain, user profile, and space configurations from JSON files
    
    Args:
        config_dir: Directory containing configuration files
        
    Returns:
        Tuple of (domain_config, user_profiles_data, spaces_data)
        
    Raises:
        FileNotFoundError: If configuration files are missing
    """
    config_path = Path(config_dir)
    
    logger.info(f"Loading configurations from {config_dir}")
    
    domain_config_file = config_path / "domain_config.json"
    user_profiles_file = config_path / "user_profiles.json"
    spaces_file = config_path / "spaces.json"
    
    if not domain_config_file.exists():
        raise FileNotFoundError(f"Domain configuration not found: {domain_config_file}")
    if not user_profiles_file.exists():
        raise FileNotFoundError(f"User profiles configuration not found: {user_profiles_file}")
    if not spaces_file.exists():
        raise FileNotFoundError(f"Spaces configuration not found: {spaces_file}")
    
    domain_config = load_json(str(domain_config_file))
    user_profiles_data = load_json(str(user_profiles_file))
    spaces_data = load_json(str(spaces_file))
    
    logger.info("Successfully loaded all configuration files")
    
    return domain_config, user_profiles_data, spaces_data


def create_domain(sagemaker_client, domain_config: Dict[str, Any], new_domain_name: Optional[str] = None) -> str:
    """
    Create a new SageMaker domain with the original configuration
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_config: Original domain configuration
        new_domain_name: Optional new domain name (defaults to original with timestamp)
        
    Returns:
        New domain ID
    """
    try:
        # Determine new domain name
        if new_domain_name:
            domain_name = new_domain_name
        else:
            original_name = domain_config['DomainName']
            timestamp = int(time.time())
            domain_name = f"{original_name}-migrated-{timestamp}"
        
        logger.info(f"Creating new domain: {domain_name}")
        
        # Build create domain parameters from original config
        create_params = {
            'DomainName': domain_name,
            'AuthMode': domain_config['AuthMode'],
            'DefaultUserSettings': domain_config['DefaultUserSettings'],
            'SubnetIds': domain_config['SubnetIds'],
            'VpcId': domain_config['VpcId']
        }
        
        # Add optional parameters if present
        if 'DomainSettings' in domain_config:
            create_params['DomainSettings'] = domain_config['DomainSettings']
        
        if 'DefaultSpaceSettings' in domain_config:
            create_params['DefaultSpaceSettings'] = domain_config['DefaultSpaceSettings']
        
        if 'AppNetworkAccessType' in domain_config:
            create_params['AppNetworkAccessType'] = domain_config['AppNetworkAccessType']
        
        if 'Tags' in domain_config:
            create_params['Tags'] = domain_config['Tags']
        
        # Create the domain
        response = sagemaker_client.create_domain(**create_params)
        new_domain_id = response['DomainId']
        new_domain_arn = response['DomainArn']
        
        logger.info(f"Domain creation initiated: {new_domain_id}")
        
        # Wait for domain to be ready
        logger.info("Waiting for domain to be InService...")
        wait_for_domain_ready(sagemaker_client, new_domain_id)
        
        logger.info(f"Domain created successfully: {new_domain_id}")
        return new_domain_id
        
    except Exception as e:
        logger.error(f"Failed to create domain: {str(e)}")
        raise


def wait_for_domain_ready(sagemaker_client, domain_id: str, max_wait_seconds: int = 1800) -> bool:
    """
    Wait for domain to reach InService status
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID
        max_wait_seconds: Maximum time to wait in seconds
        
    Returns:
        True if domain is ready, False if timeout or failed
    """
    start_time = time.time()
    
    while time.time() - start_time < max_wait_seconds:
        try:
            response = sagemaker_client.describe_domain(DomainId=domain_id)
            status = response['Status']
            
            if status == 'InService':
                return True
            elif status in ['Failed', 'Delete_Failed']:
                logger.error(f"Domain entered {status} state")
                return False
            
            logger.debug(f"Domain status: {status}, waiting...")
            time.sleep(30)
            
        except Exception as e:
            logger.warning(f"Error checking domain status: {str(e)}")
            time.sleep(30)
    
    logger.error(f"Timeout waiting for domain to be ready")
    return False


def get_domain_application_id(sagemaker_client, sso_admin_client, domain_id: str) -> Tuple[str, str]:
    """
    Retrieve the Identity Center application ARN and instance ARN for the domain
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        sso_admin_client: Boto3 SSO Admin client (unused, kept for compatibility)
        domain_id: SageMaker domain ID
        
    Returns:
        Tuple of (application_arn, instance_arn)
    """
    try:
        logger.info(f"Retrieving Identity Center application for domain {domain_id}")
        
        # Get domain details to find the SSO application ARN
        domain_response = sagemaker_client.describe_domain(DomainId=domain_id)
        
        # Extract the SingleSignOnApplicationArn from the domain response
        if 'SingleSignOnApplicationArn' not in domain_response:
            raise ValueError(
                f"Domain {domain_id} does not have a SingleSignOnApplicationArn. "
                "Ensure the domain is in SSO authentication mode."
            )
        
        application_arn = domain_response['SingleSignOnApplicationArn']
        
        # Extract instance ARN from application ARN
        # Application ARN format: arn:aws:sso::account-id:application/ssoins-xxxxx/apl-xxxxx
        # Instance ARN format: arn:aws:sso:::instance/ssoins-xxxxx
        arn_parts = application_arn.split('/')
        if len(arn_parts) >= 2:
            instance_id = arn_parts[-2]  # Get the ssoins-xxxxx part
            instance_arn = f"arn:aws:sso:::instance/{instance_id}"
        else:
            raise ValueError(f"Invalid application ARN format: {application_arn}")
        
        logger.info(f"Found application ARN: {application_arn}")
        logger.info(f"Extracted instance ARN: {instance_arn}")
        
        return application_arn, instance_arn
        
    except Exception as e:
        logger.error(f"Failed to get domain application ID: {str(e)}")
        raise


def extract_sso_username(user_profile_name: str) -> str:
    """
    Extract SSO username from user profile name by removing suffix after last hyphen
    
    Handles formats:
    1. Legacy: 'surydurg-ff0' -> 'surydurg'
    2. Email-based: 'priv-rekapall-med-usc-edu-abc' -> 'priv.rekapall@med.usc.edu'
    
    Args:
        user_profile_name: User profile name
        
    Returns:
        SSO username
    """
    # Remove everything after the last hyphen (suffix)
    if '-' in user_profile_name:
        base_name = user_profile_name.rsplit('-', 1)[0]
    else:
        logger.warning(f"No hyphen found in user profile name '{user_profile_name}'")
        return user_profile_name
    
    # Check if this looks like an email format (multiple hyphens remaining)
    if base_name.count('-') >= 2:
        # Convert to email format: replace hyphens with dots, add @ before domain
        # Example: 'priv-rekapall-med-usc-edu' -> 'priv.rekapall@med.usc.edu'
        parts = base_name.split('-')
        
        if len(parts) >= 4:
            # Assume first 2 parts are username, rest is domain
            username_parts = parts[:2]
            domain_parts = parts[2:]
        else:
            # Fallback: first part is username, rest is domain
            username_parts = parts[:1]
            domain_parts = parts[1:]
        
        username = '.'.join(username_parts)
        domain = '.'.join(domain_parts)
        sso_username = f"{username}@{domain}"
        
        logger.debug(f"Extracted SSO username '{sso_username}' from user profile name '{user_profile_name}' (email format)")
        return sso_username
    else:
        # Simple format: just return the base name
        logger.debug(f"Extracted SSO username '{base_name}' from user profile name '{user_profile_name}' (simple format)")
        return base_name


def create_user_profile_with_sso(
    sagemaker_client,
    domain_id: str,
    user_profile_name: str,
    user_settings: Dict[str, Any]
) -> bool:
    """
    Create a user profile with SSO identity
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID
        user_profile_name: User profile name
        user_settings: User settings from original configuration
        
    Returns:
        True if successful
    """
    try:
        # Extract SSO username from user profile name
        sso_username = extract_sso_username(user_profile_name)
        
        logger.info(f"Creating user profile: {user_profile_name} (SSO user: {sso_username})")
        
        # Build create user profile parameters
        create_params = {
            'DomainId': domain_id,
            'UserProfileName': user_profile_name,
            'SingleSignOnUserIdentifier': 'UserName',
            'SingleSignOnUserValue': sso_username
        }
        
        # Add user settings if provided
        if user_settings:
            create_params['UserSettings'] = user_settings
        
        # Create the user profile
        sagemaker_client.create_user_profile(**create_params)
        logger.info(f"User profile creation initiated: {user_profile_name}")
        
        return True
        
    except sagemaker_client.exceptions.ResourceInUse:
        logger.info(f"User profile {user_profile_name} already exists, skipping creation")
        return True
    except Exception as e:
        logger.error(f"Failed to create user profile {user_profile_name}: {str(e)}")
        return False


def wait_for_user_profile_creation(
    sagemaker_client,
    domain_id: str,
    user_profile_name: str,
    max_wait_seconds: int = 600
) -> bool:
    """
    Wait for user profile to be automatically created after application assignment
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID
        user_profile_name: User profile name
        max_wait_seconds: Maximum time to wait in seconds
        
    Returns:
        True if user profile is created, False if timeout
    """
    start_time = time.time()
    
    logger.info(f"Waiting for user profile creation: {user_profile_name}")
    
    while time.time() - start_time < max_wait_seconds:
        try:
            response = sagemaker_client.describe_user_profile(
                DomainId=domain_id,
                UserProfileName=user_profile_name
            )
            
            status = response.get('Status')
            if status == 'InService':
                logger.info(f"User profile created: {user_profile_name}")
                return True
            elif status in ['Failed', 'Delete_Failed']:
                logger.error(f"User profile {user_profile_name} entered {status} state")
                return False
            
            logger.debug(f"User profile {user_profile_name} status: {status}, waiting...")
            time.sleep(10)
            
        except sagemaker_client.exceptions.ResourceNotFound:
            logger.debug(f"User profile {user_profile_name} not yet created, waiting...")
            time.sleep(10)
        except Exception as e:
            logger.warning(f"Error checking user profile status: {str(e)}")
            time.sleep(10)
    
    logger.error(f"Timeout waiting for user profile {user_profile_name} to be created")
    return False


def update_user_profile_settings(
    sagemaker_client,
    domain_id: str,
    user_profile_name: str,
    original_user_settings: Dict[str, Any],
    domain_default_role: str
) -> bool:
    """
    Update user profile with custom settings if they differ from domain defaults
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID
        user_profile_name: User profile name
        original_user_settings: Original user settings from configuration
        domain_default_role: Domain's default execution role
        
    Returns:
        True if successful
    """
    try:
        # Check if user has custom execution role
        user_role = original_user_settings.get('ExecutionRole')
        
        if user_role and user_role != domain_default_role:
            logger.info(f"Updating user profile {user_profile_name} with custom role: {user_role}")
            
            # Update user profile with custom settings
            update_params = {
                'DomainId': domain_id,
                'UserProfileName': user_profile_name,
                'UserSettings': original_user_settings
            }
            
            sagemaker_client.update_user_profile(**update_params)
            logger.info(f"User profile {user_profile_name} updated successfully")
        else:
            logger.debug(f"User profile {user_profile_name} uses domain default role, no update needed")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to update user profile {user_profile_name}: {str(e)}")
        return False


def recreate_user_profiles(
    sagemaker_client,
    sso_admin_client,
    identitystore_client,
    domain_id: str,
    application_arn: str,
    instance_arn: str,
    user_profiles_data: Dict[str, Any],
    domain_default_role: str
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Recreate all user profiles using create_user_profile with SSO identity
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        sso_admin_client: Boto3 SSO Admin client (unused, kept for compatibility)
        identitystore_client: Boto3 Identity Store client (unused, kept for compatibility)
        domain_id: New domain ID
        application_arn: Identity Center application ARN (unused, kept for compatibility)
        instance_arn: Identity Center instance ARN (unused, kept for compatibility)
        user_profiles_data: User profiles configuration
        domain_default_role: Domain's default execution role
        
    Returns:
        Tuple of (successful_profiles, failed_profiles)
    """
    user_profiles = user_profiles_data.get('UserProfiles', [])
    successful_profiles = []
    failed_profiles = []
    
    logger.info(f"Recreating {len(user_profiles)} user profiles")
    
    for user_profile in user_profiles:
        user_profile_name = user_profile['UserProfileName']
        original_user_settings = user_profile.get('UserSettings', {})
        
        try:
            # Create user profile with SSO identity
            if not create_user_profile_with_sso(
                sagemaker_client, domain_id, user_profile_name, original_user_settings
            ):
                logger.error(f"Failed to create user profile {user_profile_name}")
                failed_profiles.append({
                    'user_profile_name': user_profile_name,
                    'error': 'Failed to create user profile'
                })
                continue
            
            # Wait for user profile to be ready
            if not wait_for_user_profile_creation(sagemaker_client, domain_id, user_profile_name):
                logger.error(f"User profile {user_profile_name} did not reach InService status")
                failed_profiles.append({
                    'user_profile_name': user_profile_name,
                    'error': 'User profile did not reach InService status'
                })
                continue
            
            # Get new user profile ARN
            new_profile_response = sagemaker_client.describe_user_profile(
                DomainId=domain_id,
                UserProfileName=user_profile_name
            )
            new_profile_arn = new_profile_response['UserProfileArn']
            
            successful_profiles.append({
                'user_profile_name': user_profile_name,
                'old_arn': user_profile['UserProfileArn'],
                'new_arn': new_profile_arn
            })
            
            logger.info(f"Successfully recreated user profile: {user_profile_name}")
            
        except Exception as e:
            logger.error(f"Failed to recreate user profile {user_profile_name}: {str(e)}")
            failed_profiles.append({
                'user_profile_name': user_profile_name,
                'error': str(e)
            })
    
    return successful_profiles, failed_profiles


def create_space(
    sagemaker_client,
    domain_id: str,
    space_config: Dict[str, Any]
) -> Optional[str]:
    """
    Create a space with owner and sharing configuration
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID
        space_config: Original space configuration
        
    Returns:
        New space ARN if successful, None otherwise
    """
    try:
        space_name = space_config['SpaceName']
        
        # Get owner user profile name from OwnershipSettings
        if 'OwnershipSettings' not in space_config or 'OwnerUserProfileName' not in space_config['OwnershipSettings']:
            raise ValueError(f"Could not find OwnershipSettings.OwnerUserProfileName for space {space_name}")
        
        owner_user_profile = space_config['OwnershipSettings']['OwnerUserProfileName']
        
        logger.info(f"Creating space: {space_name} (owner: {owner_user_profile})")
        
        # Build create space parameters
        create_params = {
            'DomainId': domain_id,
            'SpaceName': space_name,
            'OwnershipSettings': {
                'OwnerUserProfileName': owner_user_profile
            }
        }
        
        # Add optional parameters
        if 'SpaceSharingSettings' in space_config:
            create_params['SpaceSharingSettings'] = space_config['SpaceSharingSettings']
        
        if 'SpaceSettings' in space_config:
            create_params['SpaceSettings'] = space_config['SpaceSettings']
        
        # Filter out SageMaker system tags (tags starting with 'sagemaker:')
        if 'Tags' in space_config:
            filtered_tags = [
                tag for tag in space_config['Tags']
                if not tag.get('Key', '').startswith('sagemaker:')
            ]
            if filtered_tags:
                create_params['Tags'] = filtered_tags
                logger.debug(f"Filtered {len(space_config['Tags']) - len(filtered_tags)} SageMaker system tags")
        
        # Create the space
        try:
            response = sagemaker_client.create_space(**create_params)
            new_space_arn = response['SpaceArn']
            
            logger.info(f"Space creation initiated: {space_name}")
            
            # Wait for space to be ready
            wait_for_space_ready(sagemaker_client, domain_id, space_name)
            
            logger.info(f"Space created successfully: {space_name}")
            return new_space_arn
            
        except sagemaker_client.exceptions.ResourceInUse:
            logger.info(f"Space {space_name} already exists, getting existing ARN")
            
            # Get existing space ARN
            existing_response = sagemaker_client.describe_space(
                DomainId=domain_id,
                SpaceName=space_name
            )
            existing_space_arn = existing_response['SpaceArn']
            
            # Wait for space to be ready if it's not already
            wait_for_space_ready(sagemaker_client, domain_id, space_name)
            
            logger.info(f"Using existing space: {space_name}")
            return existing_space_arn
        
    except Exception as e:
        logger.error(f"Failed to create space {space_config.get('SpaceName')}: {str(e)}")
        return None


def wait_for_space_ready(
    sagemaker_client,
    domain_id: str,
    space_name: str,
    max_wait_seconds: int = 600
) -> bool:
    """
    Wait for space to reach InService status
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID
        space_name: Space name
        max_wait_seconds: Maximum time to wait in seconds
        
    Returns:
        True if space is ready, False if timeout or failed
    """
    start_time = time.time()
    
    while time.time() - start_time < max_wait_seconds:
        try:
            response = sagemaker_client.describe_space(
                DomainId=domain_id,
                SpaceName=space_name
            )
            status = response.get('Status')
            
            if status == 'InService':
                return True
            elif status in ['Failed', 'Delete_Failed']:
                logger.error(f"Space {space_name} entered {status} state")
                return False
            
            logger.debug(f"Space {space_name} status: {status}, waiting...")
            time.sleep(10)
            
        except Exception as e:
            logger.warning(f"Error checking space status: {str(e)}")
            time.sleep(10)
    
    logger.error(f"Timeout waiting for space {space_name} to be ready")
    return False


def recreate_spaces(
    sagemaker_client,
    domain_id: str,
    spaces_data: Dict[str, Any]
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Recreate all spaces in the new domain
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: New domain ID
        spaces_data: Spaces configuration
        
    Returns:
        Tuple of (successful_spaces, failed_spaces)
    """
    spaces = spaces_data.get('Spaces', [])
    successful_spaces = []
    failed_spaces = []
    
    logger.info(f"Recreating {len(spaces)} spaces")
    
    for space_config in spaces:
        space_name = space_config['SpaceName']
        
        try:
            new_space_arn = create_space(sagemaker_client, domain_id, space_config)
            
            if new_space_arn:
                successful_spaces.append({
                    'space_name': space_name,
                    'old_arn': space_config['SpaceArn'],
                    'new_arn': new_space_arn
                })
                logger.info(f"Successfully recreated space: {space_name}")
            else:
                failed_spaces.append({
                    'space_name': space_name,
                    'error': 'Failed to create space'
                })
                
        except Exception as e:
            logger.error(f"Failed to recreate space {space_name}: {str(e)}")
            failed_spaces.append({
                'space_name': space_name,
                'error': str(e)
            })
    
    return successful_spaces, failed_spaces


def build_resource_mapping(
    old_domain_id: str,
    new_domain_id: str,
    successful_profiles: List[Dict[str, str]],
    successful_spaces: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Build mapping of old ARNs to new ARNs
    
    Args:
        old_domain_id: Original domain ID
        new_domain_id: New domain ID
        successful_profiles: List of successfully created user profiles
        successful_spaces: List of successfully created spaces
        
    Returns:
        Resource mapping dictionary
    """
    mapping = {
        'domain': {
            'old': old_domain_id,
            'new': new_domain_id
        },
        'user_profiles': {},
        'spaces': {}
    }
    
    # Build user profile mapping
    for profile in successful_profiles:
        mapping['user_profiles'][profile['old_arn']] = profile['new_arn']
    
    # Build space mapping
    for space in successful_spaces:
        mapping['spaces'][space['old_arn']] = space['new_arn']
    
    logger.info(f"Built resource mapping: {len(successful_profiles)} user profiles, {len(successful_spaces)} spaces")
    
    return mapping


def recreate_domain_resources(config_dir: str, new_domain_name: Optional[str] = None, resume_domain_id: Optional[str] = None) -> None:
    """
    Main recreation function to recreate domain and all resources
    
    Args:
        config_dir: Directory containing configuration files
        new_domain_name: Optional new domain name
        resume_domain_id: Optional existing domain ID to resume from
    """
    # Initialize AWS clients
    sagemaker_client = get_sagemaker_client()
    sso_admin_client = get_sso_admin_client()
    identitystore_client = get_identitystore_client()
    
    # Create output directory
    output_path = Path(config_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)
    logger.info("Starting domain recreation process")
    logger.info("=" * 60)
    
    # Load configurations
    domain_config, user_profiles_data, spaces_data = load_configurations(config_dir)
    old_domain_id = domain_config['DomainId']
    
    logger.info(f"Original domain ID: {old_domain_id}")
    logger.info(f"User profiles to recreate: {len(user_profiles_data.get('UserProfiles', []))}")
    logger.info(f"Spaces to recreate: {len(spaces_data.get('Spaces', []))}")
    logger.info("=" * 60)
    
    # Create new domain or use existing one
    if resume_domain_id:
        logger.info("Step 1: Resuming with existing domain...")
        new_domain_id = resume_domain_id
        logger.info(f"Using existing domain ID: {new_domain_id}")
        
        # Verify domain exists and is accessible
        try:
            domain_response = sagemaker_client.describe_domain(DomainId=new_domain_id)
            domain_status = domain_response.get('Status')
            logger.info(f"Domain status: {domain_status}")
            
            if domain_status != 'InService':
                logger.warning(f"Domain is not in InService status: {domain_status}")
                if domain_status in ['Failed', 'Delete_Failed']:
                    raise ValueError(f"Cannot resume from domain in {domain_status} status")
                
                # Wait for domain to be ready if it's still being created
                logger.info("Waiting for domain to be InService...")
                if not wait_for_domain_ready(sagemaker_client, new_domain_id):
                    raise ValueError("Domain failed to reach InService status")
        except sagemaker_client.exceptions.ResourceNotFound:
            raise ValueError(f"Domain {new_domain_id} not found")
        except Exception as e:
            raise ValueError(f"Failed to access domain {new_domain_id}: {str(e)}")
    else:
        logger.info("Step 1: Creating new domain...")
        new_domain_id = create_domain(sagemaker_client, domain_config, new_domain_name)
        logger.info(f"New domain ID: {new_domain_id}")
    
    # Get domain application ID
    logger.info("Step 2: Retrieving Identity Center application...")
    application_arn, instance_arn = get_domain_application_id(
        sagemaker_client, sso_admin_client, new_domain_id
    )
    
    # Get domain default execution role
    domain_default_role = domain_config['DefaultUserSettings'].get('ExecutionRole', '')
    
    # Recreate user profiles
    logger.info("Step 3: Recreating user profiles...")
    successful_profiles, failed_profiles = recreate_user_profiles(
        sagemaker_client,
        sso_admin_client,
        identitystore_client,
        new_domain_id,
        application_arn,
        instance_arn,
        user_profiles_data,
        domain_default_role
    )
    
    # Recreate spaces
    logger.info("Step 4: Recreating spaces...")
    successful_spaces, failed_spaces = recreate_spaces(
        sagemaker_client,
        new_domain_id,
        spaces_data
    )
    
    # Build and save resource mapping
    logger.info("Step 5: Building resource mapping...")
    resource_mapping = build_resource_mapping(
        old_domain_id,
        new_domain_id,
        successful_profiles,
        successful_spaces
    )
    
    mapping_file = output_path / "recreation_mapping.json"
    save_json(resource_mapping, str(mapping_file))
    
    # Validate mapping schema
    try:
        validate_json_schema(resource_mapping, RESOURCE_MAPPING_SCHEMA)
    except ValueError as e:
        logger.warning(f"Resource mapping validation warning: {str(e)}")
    
    # Summary
    logger.info("=" * 60)
    logger.info("Recreation process completed")
    logger.info("=" * 60)
    logger.info(f"New domain ID: {new_domain_id}")
    logger.info(f"User profiles created: {len(successful_profiles)}/{len(user_profiles_data.get('UserProfiles', []))}")
    logger.info(f"Spaces created: {len(successful_spaces)}/{len(spaces_data.get('Spaces', []))}")
    
    if failed_profiles:
        logger.warning("=" * 60)
        logger.warning("FAILED USER PROFILES:")
        for failed in failed_profiles:
            logger.warning(f"  - {failed['user_profile_name']}: {failed['error']}")
    
    if failed_spaces:
        logger.warning("=" * 60)
        logger.warning("FAILED SPACES:")
        for failed in failed_spaces:
            logger.warning(f"  - {failed['space_name']}: {failed['error']}")
    
    logger.info("=" * 60)
    logger.info(f"Resource mapping saved to: {mapping_file}")
    logger.info("=" * 60)
    
    # Raise error if there were failures
    if failed_profiles or failed_spaces:
        raise RuntimeError(
            f"Recreation completed with failures: "
            f"{len(failed_profiles)} user profile(s), {len(failed_spaces)} space(s) failed. "
            "Please check the logs for details."
        )


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Recreate SageMaker Studio domain in new organizational context"
    )
    parser.add_argument(
        '--config-dir',
        default='./migration_data',
        help='Directory containing configuration files (default: ./migration_data)'
    )
    parser.add_argument(
        '--new-domain-name',
        help='New domain name (optional, defaults to original name with timestamp)'
    )
    parser.add_argument(
        '--resume-domain-id',
        help='Resume from existing domain ID instead of creating new domain'
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
    
    # Validate arguments
    if args.new_domain_name and args.resume_domain_id:
        logger.error("Cannot specify both --new-domain-name and --resume-domain-id")
        sys.exit(1)
    
    try:
        recreate_domain_resources(args.config_dir, args.new_domain_name, args.resume_domain_id)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Recreation failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
