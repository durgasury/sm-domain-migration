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
    Retrieve the Identity Center application ID and instance ARN for the domain
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        sso_admin_client: Boto3 SSO Admin client
        domain_id: SageMaker domain ID
        
    Returns:
        Tuple of (application_arn, instance_arn)
    """
    try:
        logger.info(f"Retrieving Identity Center application for domain {domain_id}")
        
        # Get domain details to find the SSO application ARN
        domain_response = sagemaker_client.describe_domain(DomainId=domain_id)
        
        # The application ARN is in the domain settings for SSO mode
        if 'DefaultUserSettings' in domain_response and 'SecurityGroups' in domain_response['DefaultUserSettings']:
            # List all applications and find the one for this domain
            next_token = None
            
            while True:
                list_params = {}
                if next_token:
                    list_params['NextToken'] = next_token
                
                apps_response = sso_admin_client.list_applications(**list_params)
                
                for app in apps_response.get('Applications', []):
                    # Check if this application is for our domain
                    app_arn = app['ApplicationArn']
                    
                    # Get application details to check if it's for SageMaker
                    try:
                        app_details = sso_admin_client.describe_application(ApplicationArn=app_arn)
                        
                        # Check if this is a SageMaker application for our domain
                        if 'ApplicationProviderArn' in app_details:
                            provider_arn = app_details['ApplicationProviderArn']
                            if 'sagemaker' in provider_arn.lower():
                                # Extract instance ARN from application ARN
                                # Format: arn:aws:sso::account:application/instance/app-id
                                instance_arn = '/'.join(app_arn.split('/')[:-1])
                                logger.info(f"Found application: {app_arn}")
                                return app_arn, instance_arn
                    except Exception as e:
                        logger.debug(f"Error checking application {app_arn}: {str(e)}")
                        continue
                
                next_token = apps_response.get('NextToken')
                if not next_token:
                    break
        
        raise ValueError(f"Could not find Identity Center application for domain {domain_id}")
        
    except Exception as e:
        logger.error(f"Failed to get domain application ID: {str(e)}")
        raise


def lookup_user_identity(identitystore_client, instance_id: str, user_name: str) -> Optional[str]:
    """
    Look up a user's identity in Identity Center
    
    Args:
        identitystore_client: Boto3 Identity Store client
        instance_id: Identity Center instance ID
        user_name: User name to look up
        
    Returns:
        User ID if found, None otherwise
    """
    try:
        logger.debug(f"Looking up user identity: {user_name}")
        
        # Extract identity store ID from instance ARN
        # Instance ARN format: arn:aws:sso:::instance/ssoins-xxxxx
        identity_store_id = instance_id.split('/')[-1]
        
        # List users with filter
        response = identitystore_client.list_users(
            IdentityStoreId=identity_store_id,
            Filters=[
                {
                    'AttributePath': 'UserName',
                    'AttributeValue': user_name
                }
            ]
        )
        
        users = response.get('Users', [])
        if users:
            user_id = users[0]['UserId']
            logger.debug(f"Found user ID: {user_id}")
            return user_id
        
        logger.warning(f"User not found in Identity Center: {user_name}")
        return None
        
    except Exception as e:
        logger.error(f"Failed to lookup user {user_name}: {str(e)}")
        return None


def create_application_assignment(
    sso_admin_client,
    application_arn: str,
    principal_id: str,
    principal_type: str = 'USER'
) -> bool:
    """
    Create an application assignment in Identity Center
    
    Args:
        sso_admin_client: Boto3 SSO Admin client
        application_arn: Application ARN
        principal_id: Principal ID (user or group)
        principal_type: Principal type (USER or GROUP)
        
    Returns:
        True if successful
    """
    try:
        logger.debug(f"Creating application assignment for principal {principal_id}")
        
        sso_admin_client.create_application_assignment(
            ApplicationArn=application_arn,
            PrincipalId=principal_id,
            PrincipalType=principal_type
        )
        
        logger.debug(f"Application assignment created successfully")
        return True
        
    except sso_admin_client.exceptions.ConflictException:
        logger.debug(f"Application assignment already exists for principal {principal_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to create application assignment: {str(e)}")
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
    Recreate all user profiles via SSO application assignments
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        sso_admin_client: Boto3 SSO Admin client
        identitystore_client: Boto3 Identity Store client
        domain_id: New domain ID
        application_arn: Identity Center application ARN
        instance_arn: Identity Center instance ARN
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
            # Look up user identity in Identity Center
            user_id = lookup_user_identity(identitystore_client, instance_arn, user_profile_name)
            
            if not user_id:
                logger.error(f"Could not find user {user_profile_name} in Identity Center")
                failed_profiles.append({
                    'user_profile_name': user_profile_name,
                    'error': 'User not found in Identity Center'
                })
                continue
            
            # Create application assignment
            if not create_application_assignment(sso_admin_client, application_arn, user_id):
                logger.error(f"Failed to create application assignment for {user_profile_name}")
                failed_profiles.append({
                    'user_profile_name': user_profile_name,
                    'error': 'Failed to create application assignment'
                })
                continue
            
            # Wait for user profile to be automatically created
            if not wait_for_user_profile_creation(sagemaker_client, domain_id, user_profile_name):
                logger.error(f"User profile {user_profile_name} was not created automatically")
                failed_profiles.append({
                    'user_profile_name': user_profile_name,
                    'error': 'User profile not created automatically'
                })
                continue
            
            # Update user profile settings if needed
            if not update_user_profile_settings(
                sagemaker_client, domain_id, user_profile_name, original_user_settings, domain_default_role
            ):
                logger.warning(f"Failed to update settings for {user_profile_name}, but profile was created")
            
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
        owner_user_profile = space_config['OwnerUserProfileName']
        
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
        
        if 'Tags' in space_config:
            create_params['Tags'] = space_config['Tags']
        
        # Create the space
        response = sagemaker_client.create_space(**create_params)
        new_space_arn = response['SpaceArn']
        
        logger.info(f"Space creation initiated: {space_name}")
        
        # Wait for space to be ready
        wait_for_space_ready(sagemaker_client, domain_id, space_name)
        
        logger.info(f"Space created successfully: {space_name}")
        return new_space_arn
        
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


def recreate_domain_resources(config_dir: str, new_domain_name: Optional[str] = None) -> None:
    """
    Main recreation function to recreate domain and all resources
    
    Args:
        config_dir: Directory containing configuration files
        new_domain_name: Optional new domain name
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
    
    # Create new domain
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
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(level=args.log_level)
    
    try:
        recreate_domain_resources(args.config_dir, args.new_domain_name)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Recreation failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
