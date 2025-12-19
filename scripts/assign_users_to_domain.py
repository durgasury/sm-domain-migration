#!/usr/bin/env python3
"""
User Assignment Script for SageMaker Domain Migration

This script assigns users to the new SageMaker Studio domain by creating
Identity Center application assignments. This should be run after recreate_domain.py.

Key Features:
- Uses IdentityStore get_user_id API to find users by username
- Validates user IDs before creating assignments
- Uses SSO Admin APIs to create application assignments
- Provides detailed logging and error handling
- Includes rate limiting to avoid API throttling

Usage:
    python assign_users_to_domain.py --domain-id <domain-id> --identity-store-id <identity-store-id> [--config-dir <path>]
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
    load_json
)

logger = get_logger(__name__)


def load_user_profiles_config(config_dir: str) -> Dict[str, Any]:
    """
    Load user profiles configuration from JSON file
    
    Args:
        config_dir: Directory containing configuration files
        
    Returns:
        User profiles configuration dictionary
        
    Raises:
        FileNotFoundError: If configuration file is missing
    """
    config_path = Path(config_dir)
    user_profiles_file = config_path / "user_profiles.json"
    
    if not user_profiles_file.exists():
        raise FileNotFoundError(f"User profiles configuration not found: {user_profiles_file}")
    
    logger.info(f"Loading user profiles configuration from {user_profiles_file}")
    user_profiles_data = load_json(str(user_profiles_file))
    
    user_profiles = user_profiles_data.get('UserProfiles', [])
    logger.info(f"Loaded {len(user_profiles)} user profiles")
    
    return user_profiles_data


def get_domain_application_info(sagemaker_client, domain_id: str) -> Tuple[str, str]:
    """
    Get the Identity Center application ARN and instance ARN for the domain
    
    Args:
        sagemaker_client: Boto3 SageMaker client
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
        logger.error(f"Failed to get domain application info: {str(e)}")
        raise


def validate_user_id(user_id: str) -> bool:
    """
    Validate that a user ID has the expected format
    
    Args:
        user_id: User ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not user_id:
        return False
    
    # Identity Center user IDs are typically UUIDs
    # Format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    import re
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    
    if re.match(uuid_pattern, user_id, re.IGNORECASE):
        return True
    
    # Some Identity Center instances might use different formats
    # Accept any non-empty string that looks like an ID
    if len(user_id) > 10 and user_id.replace('-', '').replace('_', '').isalnum():
        return True
    
    return False


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


def get_user_id_from_identity_store(identitystore_client, identity_store_id: str, sso_username: str) -> Optional[str]:
    """
    Get user ID from Identity Center using the get_user_id API with UniqueAttribute
    
    Args:
        identitystore_client: Boto3 Identity Store client
        identity_store_id: Identity Center identity store ID
        sso_username: SSO username to search for
        
    Returns:
        User ID if found, None otherwise
    """
    try:
        logger.debug(f"Getting user ID for '{sso_username}' from Identity Store {identity_store_id}")
        
        # Use get_user_id API with UniqueAttribute for userName
        response = identitystore_client.get_user_id(
            IdentityStoreId=identity_store_id,
            AlternateIdentifier={
                'UniqueAttribute': {
                    'AttributePath': 'userName',
                    'AttributeValue': sso_username
                }
            }
        )
        
        user_id = response.get('UserId')
        if user_id:
            logger.info(f"Found user '{sso_username}' with ID: {user_id}")
            return user_id
        else:
            logger.warning(f"No user ID returned for '{sso_username}'")
            return None
            
    except identitystore_client.exceptions.ResourceNotFoundException:
        logger.warning(f"User '{sso_username}' not found in Identity Center")
        return None
    except Exception as e:
        logger.error(f"Failed to get user ID for '{sso_username}': {str(e)}")
        return None


def create_application_assignment(
    sso_admin_client,
    instance_arn: str,
    application_arn: str,
    user_id: str,
    sso_username: str
) -> bool:
    """
    Create an application assignment for a user using SSO Admin APIs
    
    Args:
        sso_admin_client: Boto3 SSO Admin client
        instance_arn: Identity Center instance ARN
        application_arn: Application ARN
        user_id: User ID in Identity Center
        sso_username: SSO username (for logging)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Creating application assignment for user: {sso_username} (ID: {user_id})")
        
        # Validate inputs
        if not user_id:
            logger.error(f"Invalid user ID for user '{sso_username}': {user_id}")
            return False
            
        if not application_arn:
            logger.error(f"Invalid application ARN: {application_arn}")
            return False
            
        if not instance_arn:
            logger.error(f"Invalid instance ARN: {instance_arn}")
            return False
        
        # Create application assignment using SSO Admin API
        response = sso_admin_client.create_application_assignment(
            # InstanceArn=instance_arn,
            ApplicationArn=application_arn,
            PrincipalId=user_id,
            PrincipalType='USER'
        )
        
        logger.info(f"Successfully created application assignment for user: {sso_username} (ID: {user_id})")
        logger.debug(f"Assignment response: {response}")
        return True
        
    except sso_admin_client.exceptions.ConflictException as e:
        logger.info(f"Application assignment already exists for user: {sso_username} (ID: {user_id})")
        return True
    except sso_admin_client.exceptions.ResourceNotFoundException as e:
        logger.error(f"Resource not found when creating assignment for user '{sso_username}': {str(e)}")
        logger.error(f"Check that the application ARN and instance ARN are correct")
        return False
    except sso_admin_client.exceptions.AccessDeniedException as e:
        logger.error(f"Access denied when creating assignment for user '{sso_username}': {str(e)}")
        logger.error(f"Check that you have the necessary permissions for SSO Admin operations")
        return False
    except sso_admin_client.exceptions.ValidationException as e:
        logger.error(f"Validation error when creating assignment for user '{sso_username}': {str(e)}")
        logger.error(f"Check that the user ID '{user_id}' is valid")
        return False
    except Exception as e:
        logger.error(f"Failed to create application assignment for user '{sso_username}' (ID: {user_id}): {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        return False


def assign_all_users(
    sagemaker_client,
    sso_admin_client,
    identitystore_client,
    domain_id: str,
    identity_store_id: str,
    user_profiles_data: Dict[str, Any]
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Assign all users to the domain application
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        sso_admin_client: Boto3 SSO Admin client
        identitystore_client: Boto3 Identity Store client
        domain_id: SageMaker domain ID
        identity_store_id: Identity Center identity store ID
        user_profiles_data: User profiles configuration
        
    Returns:
        Tuple of (successful_assignments, failed_assignments)
    """
    user_profiles = user_profiles_data.get('UserProfiles', [])
    successful_assignments = []
    failed_assignments = []
    
    if not user_profiles:
        logger.warning("No user profiles found in configuration")
        return successful_assignments, failed_assignments
    
    # Get domain application info
    application_arn, instance_arn = get_domain_application_info(sagemaker_client, domain_id)
    
    logger.info(f"Assigning {len(user_profiles)} users to domain application")
    
    for i, user_profile in enumerate(user_profiles, 1):
        user_profile_name = user_profile['UserProfileName']
        
        logger.info(f"Processing user {i}/{len(user_profiles)}: {user_profile_name}")
        
        try:
            # Extract SSO username from user profile name
            sso_username = extract_sso_username(user_profile_name)
            
            # Get user ID from Identity Center using get_user_id API
            user_id = get_user_id_from_identity_store(identitystore_client, identity_store_id, sso_username)
            
            if not user_id:
                error_msg = f'User not found in Identity Center'
                logger.warning(f"Failed to find user '{sso_username}' (from profile '{user_profile_name}'): {error_msg}")
                failed_assignments.append({
                    'user_profile_name': user_profile_name,
                    'sso_username': sso_username,
                    'error': error_msg
                })
                continue
            
            # Validate user ID format
            if not validate_user_id(user_id):
                error_msg = f'Invalid user ID format: {user_id}'
                logger.error(f"Invalid user ID for '{sso_username}': {error_msg}")
                failed_assignments.append({
                    'user_profile_name': user_profile_name,
                    'sso_username': sso_username,
                    'error': error_msg
                })
                continue
            
            # Create application assignment using SSO Admin APIs
            if create_application_assignment(
                sso_admin_client,
                instance_arn,
                application_arn,
                user_id,
                sso_username
            ):
                successful_assignments.append({
                    'user_profile_name': user_profile_name,
                    'sso_username': sso_username,
                    'user_id': user_id
                })
                logger.info(f"✓ Successfully assigned user {i}/{len(user_profiles)}: {user_profile_name}")
            else:
                error_msg = 'Failed to create application assignment'
                failed_assignments.append({
                    'user_profile_name': user_profile_name,
                    'sso_username': sso_username,
                    'error': error_msg
                })
                logger.error(f"✗ Failed to assign user {i}/{len(user_profiles)}: {user_profile_name} - {error_msg}")
            
            # Small delay to avoid potential rate limiting
            if i < len(user_profiles):  # Don't delay after the last user
                time.sleep(0.5)
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"✗ Failed to assign user {i}/{len(user_profiles)}: {user_profile_name} - {error_msg}")
            failed_assignments.append({
                'user_profile_name': user_profile_name,
                'sso_username': extract_sso_username(user_profile_name),
                'error': error_msg
            })
    
    return successful_assignments, failed_assignments


def assign_users_to_domain(domain_id: str, identity_store_id: str, config_dir: str) -> None:
    """
    Main function to assign users to the domain application
    
    Args:
        domain_id: SageMaker domain ID
        identity_store_id: Identity Center identity store ID
        config_dir: Directory containing configuration files
    """
    # Initialize AWS clients
    sagemaker_client = get_sagemaker_client()
    sso_admin_client = get_sso_admin_client()
    identitystore_client = get_identitystore_client()
    
    # Create output directory
    output_path = Path(config_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)
    logger.info("Starting user assignment process")
    logger.info("=" * 60)
    logger.info(f"Domain ID: {domain_id}")
    logger.info(f"Identity Store ID: {identity_store_id}")
    logger.info("=" * 60)
    
    # Load user profiles configuration
    logger.info("Step 1: Loading user profiles configuration...")
    user_profiles_data = load_user_profiles_config(config_dir)
    
    # Assign all users to the domain application
    logger.info("Step 2: Assigning users to domain application...")
    successful_assignments, failed_assignments = assign_all_users(
        sagemaker_client,
        sso_admin_client,
        identitystore_client,
        domain_id,
        identity_store_id,
        user_profiles_data
    )
    
    # Save assignment status
    logger.info("Step 3: Saving assignment status...")
    assignment_status = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'domain_id': domain_id,
        'identity_store_id': identity_store_id,
        'total_users': len(user_profiles_data.get('UserProfiles', [])),
        'successful_assignments': len(successful_assignments),
        'failed_assignments': len(failed_assignments),
        'successful_users': successful_assignments,
        'failed_users': failed_assignments
    }
    
    status_file = output_path / "user_assignment_status.json"
    save_json(assignment_status, str(status_file))
    
    # Summary
    logger.info("=" * 60)
    logger.info("User assignment process completed")
    logger.info("=" * 60)
    logger.info(f"Total users: {len(user_profiles_data.get('UserProfiles', []))}")
    logger.info(f"Successfully assigned: {len(successful_assignments)}")
    logger.info(f"Failed: {len(failed_assignments)}")
    
    if failed_assignments:
        logger.warning("=" * 60)
        logger.warning("FAILED ASSIGNMENTS:")
        for failed in failed_assignments:
            logger.warning(f"  - {failed['user_profile_name']} ({failed['sso_username']}): {failed['error']}")
    
    logger.info("=" * 60)
    logger.info(f"Assignment status saved to: {status_file}")
    logger.info("=" * 60)
    
    # Raise error if there were failures
    if failed_assignments:
        raise RuntimeError(
            f"User assignment completed with {len(failed_assignments)} failure(s). "
            "Please check the logs and user_assignment_status.json for details."
        )


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Assign users to SageMaker Studio domain via Identity Center"
    )
    parser.add_argument(
        '--domain-id',
        required=True,
        help='SageMaker domain ID (e.g., d-xxxxxxxxxxxx)'
    )
    parser.add_argument(
        '--identity-store-id',
        required=True,
        help='Identity Center identity store ID (e.g., d-92679c0362)'
    )
    parser.add_argument(
        '--config-dir',
        default='./migration_data',
        help='Directory containing configuration files (default: ./migration_data)'
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
        assign_users_to_domain(args.domain_id, args.identity_store_id, args.config_dir)
        sys.exit(0)
    except Exception as e:
        logger.error(f"User assignment failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()