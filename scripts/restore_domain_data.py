#!/usr/bin/env python3
"""
Restoration Script for SageMaker Domain Migration

This script creates lifecycle configurations to sync data from S3 back to user volumes,
attaches them to the domain, and starts all spaces to trigger the restoration.

Usage:
    python restore_domain_data.py --domain-id <domain-id> --s3-bucket <bucket> [--s3-prefix <prefix>] [--config-dir <path>]
"""

import argparse
import sys
import time
import base64
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from utils import (
    get_sagemaker_client,
    get_s3_client,
    setup_logging,
    get_logger,
    save_json,
    load_json
)

logger = get_logger(__name__)


def generate_restore_lifecycle_script(s3_bucket: str, s3_prefix: str) -> str:
    """
    Generate lifecycle configuration script for restoring data from S3
    
    Args:
        s3_bucket: S3 bucket name
        s3_prefix: S3 prefix (optional)
        
    Returns:
        Bash script content as string
    """
    script = f"""#!/bin/bash
set -e

# Get user profile and space information from environment
USER_PROFILE_NAME=${{SAGEMAKER_USER_PROFILE_NAME:-"unknown"}}
SPACE_NAME=${{SAGEMAKER_SPACE_NAME:-"unknown"}}

# Construct S3 path
S3_BUCKET="{s3_bucket}"
S3_PREFIX="{s3_prefix}"

# Build full S3 path with user profile and space
if [ -n "$S3_PREFIX" ] && [ "$S3_PREFIX" != "" ]; then
    S3_PATH="s3://${{S3_BUCKET}}/${{S3_PREFIX}}/${{USER_PROFILE_NAME}}/${{SPACE_NAME}}"
else
    S3_PATH="s3://${{S3_BUCKET}}/${{USER_PROFILE_NAME}}/${{SPACE_NAME}}"
fi

echo "Starting restoration from $S3_PATH"

# Check if S3 path exists
if aws s3 ls "$S3_PATH" > /dev/null 2>&1; then
    # Sync data from S3 to user volume, excluding cache directories
    aws s3 sync "$S3_PATH" /home/sagemaker-user --exclude ".cache/*" --exclude "lost+found/*"
    echo "Restoration completed successfully"
else
    echo "Warning: No backup found at $S3_PATH"
    echo "Skipping restoration for this space"
fi
"""
    return script


def create_lifecycle_config(
    sagemaker_client,
    app_type: str,
    s3_bucket: str,
    s3_prefix: str
) -> str:
    """
    Create a Studio lifecycle configuration for restoration
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        app_type: App type (JupyterLab or CodeEditor)
        s3_bucket: S3 bucket name
        s3_prefix: S3 prefix
        
    Returns:
        Lifecycle configuration ARN
    """
    try:
        lcc_name = f"restore-{app_type.lower()}-{int(time.time())}"
        script_content = generate_restore_lifecycle_script(s3_bucket, s3_prefix)
        
        # Encode script in base64
        script_encoded = base64.b64encode(script_content.encode('utf-8')).decode('utf-8')
        
        logger.info(f"Creating lifecycle configuration: {lcc_name}")
        
        response = sagemaker_client.create_studio_lifecycle_config(
            StudioLifecycleConfigName=lcc_name,
            StudioLifecycleConfigContent=script_encoded,
            StudioLifecycleConfigAppType=app_type
        )
        
        lcc_arn = response['StudioLifecycleConfigArn']
        logger.info(f"Created lifecycle configuration: {lcc_arn}")
        
        return lcc_arn
        
    except Exception as e:
        logger.error(f"Failed to create lifecycle configuration for {app_type}: {str(e)}")
        raise


def attach_lifecycle_config_to_domain(
    sagemaker_client,
    domain_id: str,
    jupyterlab_lcc_arn: str,
    codeeditor_lcc_arn: str
) -> None:
    """
    Attach lifecycle configurations to domain default user settings
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        jupyterlab_lcc_arn: JupyterLab lifecycle config ARN
        codeeditor_lcc_arn: CodeEditor lifecycle config ARN
    """
    try:
        logger.info(f"Attaching lifecycle configurations to domain {domain_id}")
        
        # Get current domain settings
        domain_response = sagemaker_client.describe_domain(DomainId=domain_id)
        default_user_settings = domain_response.get('DefaultUserSettings', {})
        
        # Update JupyterLab settings
        jupyter_settings = default_user_settings.get('JupyterLabAppSettings', {})
        jupyter_lcc_arns = jupyter_settings.get('LifecycleConfigArns', [])
        if jupyterlab_lcc_arn not in jupyter_lcc_arns:
            jupyter_lcc_arns.append(jupyterlab_lcc_arn)
        jupyter_settings['LifecycleConfigArns'] = jupyter_lcc_arns
        default_user_settings['JupyterLabAppSettings'] = jupyter_settings
        
        # Update CodeEditor settings
        codeeditor_settings = default_user_settings.get('CodeEditorAppSettings', {})
        codeeditor_lcc_arns = codeeditor_settings.get('LifecycleConfigArns', [])
        if codeeditor_lcc_arn not in codeeditor_lcc_arns:
            codeeditor_lcc_arns.append(codeeditor_lcc_arn)
        codeeditor_settings['LifecycleConfigArns'] = codeeditor_lcc_arns
        default_user_settings['CodeEditorAppSettings'] = codeeditor_settings
        
        # Update domain
        sagemaker_client.update_domain(
            DomainId=domain_id,
            DefaultUserSettings=default_user_settings
        )
        
        logger.info("Successfully attached lifecycle configurations to domain")
        
    except Exception as e:
        logger.error(f"Failed to attach lifecycle configurations: {str(e)}")
        raise


def validate_s3_backup_location(s3_client, s3_bucket: str, s3_prefix: str) -> bool:
    """
    Validate that the S3 backup location exists and is accessible
    
    Args:
        s3_client: Boto3 S3 client
        s3_bucket: S3 bucket name
        s3_prefix: S3 prefix
        
    Returns:
        True if location is accessible, False otherwise
    """
    try:
        logger.info(f"Validating S3 backup location: s3://{s3_bucket}/{s3_prefix}")
        
        # Try to list objects in the bucket with the prefix
        response = s3_client.list_objects_v2(
            Bucket=s3_bucket,
            Prefix=s3_prefix,
            MaxKeys=1
        )
        
        # Check if bucket is accessible (even if empty)
        if 'Contents' in response or 'KeyCount' in response:
            logger.info("S3 backup location is accessible")
            return True
        else:
            logger.warning(f"S3 location exists but appears empty: s3://{s3_bucket}/{s3_prefix}")
            return True
            
    except s3_client.exceptions.NoSuchBucket:
        logger.error(f"S3 bucket does not exist: {s3_bucket}")
        return False
    except Exception as e:
        logger.error(f"Failed to access S3 location: {str(e)}")
        return False


def wait_for_app_ready(
    sagemaker_client,
    domain_id: str,
    user_profile_name: Optional[str],
    space_name: Optional[str],
    app_type: str,
    app_name: str,
    max_wait_seconds: int = 600
) -> bool:
    """
    Wait for an app to reach InService status
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        user_profile_name: User profile name (for user profile apps)
        space_name: Space name (for space apps)
        app_type: App type
        app_name: App name
        max_wait_seconds: Maximum time to wait in seconds
        
    Returns:
        True if app is ready, False if timeout or failed
    """
    start_time = time.time()
    
    while time.time() - start_time < max_wait_seconds:
        try:
            kwargs = {
                'DomainId': domain_id,
                'AppType': app_type,
                'AppName': app_name
            }
            
            if user_profile_name:
                kwargs['UserProfileName'] = user_profile_name
            if space_name:
                kwargs['SpaceName'] = space_name
            
            response = sagemaker_client.describe_app(**kwargs)
            status = response['Status']
            
            if status == 'InService':
                return True
            elif status in ['Failed', 'Deleted']:
                logger.error(f"App {app_name} entered {status} state")
                return False
            
            logger.debug(f"App {app_name} status: {status}, waiting...")
            time.sleep(15)
            
        except Exception as e:
            logger.warning(f"Error checking app status: {str(e)}")
            time.sleep(15)
    
    logger.error(f"Timeout waiting for app {app_name} to be ready")
    return False


def start_space_app(
    sagemaker_client,
    domain_id: str,
    space_name: str,
    owner_user_profile: str,
    app_type: str = 'JupyterLab'
) -> Tuple[bool, Optional[str]]:
    """
    Start an app for a space to trigger restoration
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        space_name: Space name
        owner_user_profile: Owner user profile name
        app_type: App type (default: JupyterLab)
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    try:
        app_name = 'default'
        identifier = f"{space_name}/{app_type}/{app_name}"
        
        logger.info(f"Starting app for space: {identifier}")
        
        # Create the app
        sagemaker_client.create_app(
            DomainId=domain_id,
            SpaceName=space_name,
            AppType=app_type,
            AppName=app_name
        )
        
        logger.info(f"Initiated creation of app: {identifier}")
        
        # Wait for app to be ready
        if not wait_for_app_ready(
            sagemaker_client, domain_id, None, space_name, app_type, app_name
        ):
            error_msg = f"App failed to start or timed out: {identifier}"
            logger.error(error_msg)
            return False, error_msg
        
        logger.info(f"App started successfully: {identifier}")
        return True, None
        
    except sagemaker_client.exceptions.ResourceInUse:
        # App already exists, which is fine
        logger.info(f"App already exists for space {space_name}, skipping creation")
        return True, None
    except Exception as e:
        error_msg = f"Failed to start app for space {space_name}: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def start_all_spaces(
    sagemaker_client,
    domain_id: str,
    spaces_data: Dict[str, Any]
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Start apps for all spaces to trigger restoration
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        spaces_data: Spaces configuration data
        
    Returns:
        Tuple of (successful_count, failed_spaces)
    """
    spaces = spaces_data.get('Spaces', [])
    
    if not spaces:
        logger.warning("No spaces found in configuration")
        return 0, []
    
    logger.info(f"Starting apps for {len(spaces)} spaces...")
    
    successful_count = 0
    failed_spaces = []
    
    for space in spaces:
        space_name = space['SpaceName']
        owner_user_profile = space.get('OwnerUserProfileName', 'unknown')
        
        # Try JupyterLab first
        success, error = start_space_app(
            sagemaker_client,
            domain_id,
            space_name,
            owner_user_profile,
            app_type='JupyterLab'
        )
        
        if success:
            successful_count += 1
        else:
            failed_spaces.append({
                'space_name': space_name,
                'owner_user_profile': owner_user_profile,
                'app_type': 'JupyterLab',
                'error': error
            })
    
    return successful_count, failed_spaces


def restore_domain_data(
    domain_id: str,
    s3_bucket: str,
    s3_prefix: str,
    config_dir: str
) -> None:
    """
    Main restoration function to sync data from S3 back to user volumes
    
    Args:
        domain_id: SageMaker domain ID
        s3_bucket: S3 bucket name for backup
        s3_prefix: S3 prefix for backup
        config_dir: Directory containing configuration files
    """
    # Initialize AWS clients
    sagemaker_client = get_sagemaker_client()
    s3_client = get_s3_client()
    
    # Create output directory
    output_path = Path(config_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)
    logger.info("Starting domain restoration process")
    logger.info("=" * 60)
    logger.info(f"Domain ID: {domain_id}")
    logger.info(f"S3 Bucket: {s3_bucket}")
    logger.info(f"S3 Prefix: {s3_prefix}")
    logger.info("=" * 60)
    
    # Validate S3 backup location
    logger.info("Validating S3 backup location...")
    if not validate_s3_backup_location(s3_client, s3_bucket, s3_prefix):
        raise RuntimeError(
            f"S3 backup location is not accessible: s3://{s3_bucket}/{s3_prefix}. "
            "Please verify the bucket exists and you have permissions."
        )
    
    # Create lifecycle configurations
    logger.info("Creating lifecycle configurations...")
    jupyterlab_lcc_arn = create_lifecycle_config(
        sagemaker_client, 'JupyterLab', s3_bucket, s3_prefix
    )
    codeeditor_lcc_arn = create_lifecycle_config(
        sagemaker_client, 'CodeEditor', s3_bucket, s3_prefix
    )
    
    # Attach lifecycle configurations to domain
    attach_lifecycle_config_to_domain(
        sagemaker_client, domain_id, jupyterlab_lcc_arn, codeeditor_lcc_arn
    )
    
    # Load space configuration
    logger.info("Loading space configuration...")
    spaces_file = output_path / "spaces.json"
    if not spaces_file.exists():
        raise FileNotFoundError(f"Spaces configuration not found: {spaces_file}")
    
    spaces_data = load_json(str(spaces_file))
    
    # Start all spaces
    successful_count, failed_spaces = start_all_spaces(
        sagemaker_client, domain_id, spaces_data
    )
    
    # Save restoration status
    restoration_status = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'domain_id': domain_id,
        's3_bucket': s3_bucket,
        's3_prefix': s3_prefix,
        'jupyterlab_lcc_arn': jupyterlab_lcc_arn,
        'codeeditor_lcc_arn': codeeditor_lcc_arn,
        'total_spaces': len(spaces_data.get('Spaces', [])),
        'successful_spaces': successful_count,
        'failed_spaces': failed_spaces
    }
    
    status_file = output_path / "restoration_status.json"
    save_json(restoration_status, str(status_file))
    
    # Summary
    logger.info("=" * 60)
    logger.info("Restoration process completed")
    logger.info("=" * 60)
    logger.info(f"Total spaces: {len(spaces_data.get('Spaces', []))}")
    logger.info(f"Successfully restored: {successful_count}")
    logger.info(f"Failed: {len(failed_spaces)}")
    
    if failed_spaces:
        logger.warning("=" * 60)
        logger.warning("FAILED SPACE RESTORATIONS:")
        for failed_space in failed_spaces:
            logger.warning(f"  - {failed_space['space_name']} (owner: {failed_space['owner_user_profile']})")
            logger.warning(f"    Error: {failed_space['error']}")
        logger.warning("=" * 60)
        logger.warning(
            f"Restoration completed with {len(failed_spaces)} failure(s). "
            "Please check the logs and restoration_status.json for details."
        )
    
    logger.info(f"Restoration status saved to: {status_file}")
    logger.info("=" * 60)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Restore SageMaker Studio domain data from S3"
    )
    parser.add_argument(
        '--domain-id',
        required=True,
        help='SageMaker domain ID (e.g., d-xxxxxxxxxxxx)'
    )
    parser.add_argument(
        '--s3-bucket',
        required=True,
        help='S3 bucket name containing backup'
    )
    parser.add_argument(
        '--s3-prefix',
        default='',
        help='S3 prefix for backup (optional)'
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
        restore_domain_data(
            args.domain_id,
            args.s3_bucket,
            args.s3_prefix,
            args.config_dir
        )
        sys.exit(0)
    except Exception as e:
        logger.error(f"Restoration failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
