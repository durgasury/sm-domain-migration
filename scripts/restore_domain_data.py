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


def generate_restore_lifecycle_script(s3_bucket: str, s3_prefix: str, backup_efs: bool = True) -> str:
    """
    Generate lifecycle configuration script for restoring data from S3
    
    Args:
        s3_bucket: S3 bucket name
        s3_prefix: S3 prefix (optional)
        backup_efs: Whether EFS data was backed up (default: True)
        
    Returns:
        Bash script content as string
    """
    # Build exclude parameters based on backup_efs flag
    exclude_params = '--exclude ".cache/*" --exclude "lost+found/*"'
    if not backup_efs:
        exclude_params += ' --exclude "user-default-efs/*"'
    
    script = f"""#!/bin/bash
set -e

# Get space name and domain ID from metadata file
export SM_RST_SPACE_NAME=$(cat /opt/ml/metadata/resource-metadata.json | jq -r '.SpaceName')
export SM_RST_DOMAIN_ID=$(cat /opt/ml/metadata/resource-metadata.json | jq -r '.DomainId')

# Get user profile name from space ownership
export SM_RST_USER_PROFILE_NAME=$(aws sagemaker describe-space --domain-id=$SM_RST_DOMAIN_ID --space-name=$SM_RST_SPACE_NAME | jq -r '.OwnershipSettings.OwnerUserProfileName')

# Construct S3 path
S3_BUCKET="{s3_bucket}"
S3_PREFIX="{s3_prefix}"

# Build full S3 path with user profile and space
if [ -n "$S3_PREFIX" ] && [ "$S3_PREFIX" != "" ]; then
    S3_PATH="s3://${{S3_BUCKET}}/${{S3_PREFIX}}/${{SM_RST_USER_PROFILE_NAME}}/${{SM_RST_SPACE_NAME}}"
else
    S3_PATH="s3://${{S3_BUCKET}}/${{SM_RST_USER_PROFILE_NAME}}/${{SM_RST_SPACE_NAME}}"
fi

echo "Starting restoration from $S3_PATH"
echo "Domain ID: $SM_RST_DOMAIN_ID"
echo "Space Name: $SM_RST_SPACE_NAME"
echo "User Profile: $SM_RST_USER_PROFILE_NAME"
echo "Restore EFS: {'Yes' if backup_efs else 'No'}"

# Check if S3 path exists
if aws s3 ls "$S3_PATH" > /dev/null 2>&1; then
    # Sync data from S3 to user volume, excluding cache directories and optionally EFS
    nohup aws s3 sync "$S3_PATH" /home/sagemaker-user {exclude_params} > sync.log 2>&1 &
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
    s3_prefix: str,
    backup_efs: bool = True
) -> str:
    """
    Create a Studio lifecycle configuration for restoration
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        app_type: App type (JupyterLab or CodeEditor)
        s3_bucket: S3 bucket name
        s3_prefix: S3 prefix
        backup_efs: Whether EFS data was backed up
        
    Returns:
        Lifecycle configuration ARN
    """
    try:
        lcc_name = f"restore-{app_type.lower()}-{int(time.time())}"
        script_content = generate_restore_lifecycle_script(s3_bucket, s3_prefix, backup_efs)
        
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
    lcc_arn: str,
    default_resource_spec: Optional[Dict[str, Any]] = None,
    app_type: str = 'JupyterLab'
) -> Tuple[bool, Optional[str]]:
    """
    Start an app for a space to trigger restoration
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        space_name: Space name
        owner_user_profile: Owner user profile name
        lcc_arn: Lifecycle configuration ARN to attach
        default_resource_spec: Default ResourceSpec from original domain (optional)
        app_type: App type (default: JupyterLab)
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    try:
        app_name = 'default'
        identifier = f"{space_name}/{app_type}/{app_name}"
        
        logger.info(f"Starting app for space: {identifier}")
        
        # Check if app already exists
        try:
            existing_app = sagemaker_client.describe_app(
                DomainId=domain_id,
                SpaceName=space_name,
                AppType=app_type,
                AppName=app_name
            )
            
            if existing_app['Status'] in ['InService', 'Pending']:
                logger.info(f"App already exists for space {space_name}, skipping creation")
                return True, None
            
            # Get existing ResourceSpec if available
            resource_spec = existing_app.get('ResourceSpec', {})
        except sagemaker_client.exceptions.ResourceNotFound:
            # App doesn't exist, use provided default ResourceSpec or create a minimal one
            if default_resource_spec:
                resource_spec = default_resource_spec.copy()
                logger.info(f"Using ResourceSpec from original domain: {resource_spec}")
            else:
                # Fallback to minimal ResourceSpec
                resource_spec = {
                    'InstanceType': 'ml.t3.medium'
                }
                logger.warning(f"No ResourceSpec found, using fallback: ml.t3.medium")
        
        # Add lifecycle config ARN to ResourceSpec
        resource_spec['LifecycleConfigArn'] = lcc_arn
        
        # Create the app with ResourceSpec
        create_kwargs = {
            'DomainId': domain_id,
            'SpaceName': space_name,
            'AppType': app_type,
            'AppName': app_name,
            'ResourceSpec': resource_spec
        }
        
        sagemaker_client.create_app(**create_kwargs)
        logger.info(f"Initiated creation of app: {identifier} with LCC: {lcc_arn}")
        
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


def create_space_app(
    sagemaker_client,
    domain_id: str,
    space_name: str,
    lcc_arn: str,
    resource_spec: Optional[Dict[str, Any]] = None,
    app_type: str = 'JupyterLab'
) -> Tuple[bool, Optional[str]]:
    """
    Create an app for a space (without waiting)
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        space_name: Space name
        lcc_arn: Lifecycle configuration ARN to attach
        resource_spec: ResourceSpec from original domain (optional)
        app_type: App type (default: JupyterLab)
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    try:
        app_name = 'default'
        identifier = f"{space_name}/{app_type}/{app_name}"
        
        logger.info(f"Creating app for space: {identifier}")
        
        # Check if app already exists
        try:
            existing_app = sagemaker_client.describe_app(
                DomainId=domain_id,
                SpaceName=space_name,
                AppType=app_type,
                AppName=app_name
            )
            
            if existing_app['Status'] in ['InService', 'Pending']:
                logger.info(f"App already exists for space {space_name}, skipping creation")
                return True, None
        except sagemaker_client.exceptions.ResourceNotFound:
            # App doesn't exist, proceed with creation
            pass
        
        # Use provided ResourceSpec or create a minimal one
        if resource_spec:
            final_resource_spec = resource_spec.copy()
            logger.info(f"Using ResourceSpec from original domain: {final_resource_spec}")
        else:
            # Fallback to minimal ResourceSpec
            final_resource_spec = {
                'InstanceType': 'ml.t3.medium'
            }
            logger.warning(f"No ResourceSpec found, using fallback: ml.t3.medium")
        
        # Add lifecycle config ARN to ResourceSpec
        final_resource_spec['LifecycleConfigArn'] = lcc_arn
        
        # Create the app with ResourceSpec
        create_kwargs = {
            'DomainId': domain_id,
            'SpaceName': space_name,
            'AppType': app_type,
            'AppName': app_name,
            'ResourceSpec': final_resource_spec
        }
        
        sagemaker_client.create_app(**create_kwargs)
        logger.info(f"Initiated creation of app: {identifier} with LCC: {lcc_arn}")
        
        return True, None
        
    except sagemaker_client.exceptions.ResourceInUse:
        # App already exists, which is fine
        logger.info(f"App already exists for space {space_name}, skipping creation")
        return True, None
    except Exception as e:
        error_msg = f"Failed to create app for space {space_name}: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def start_all_spaces(
    sagemaker_client,
    domain_id: str,
    spaces_data: Dict[str, Any],
    apps_data: Dict[str, Any],
    jupyterlab_lcc_arn: str,
    codeeditor_lcc_arn: str
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Start apps for all spaces to trigger restoration (in parallel)
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        spaces_data: Spaces configuration data
        apps_data: Apps configuration data with ResourceSpecs
        jupyterlab_lcc_arn: JupyterLab lifecycle config ARN
        codeeditor_lcc_arn: CodeEditor lifecycle config ARN
        
    Returns:
        Tuple of (successful_count, failed_spaces)
    """
    spaces = spaces_data.get('Spaces', [])
    apps = apps_data.get('Apps', [])
    
    if not spaces:
        logger.warning("No spaces found in configuration")
        return 0, []
    
    # Build a lookup map for app ResourceSpecs by space name and app type
    # Skip failed apps from the original domain
    app_resource_specs = {}
    app_status_counts = {}
    
    for app in apps:
        if app.get('SpaceName'):
            status = app.get('Status', 'Unknown')
            app_status_counts[status] = app_status_counts.get(status, 0) + 1
            
            # Only use ResourceSpecs from non-failed apps
            if status != 'Failed':
                key = (app['SpaceName'], app['AppType'])
                app_resource_specs[key] = app.get('ResourceSpec', {})
    
    # Log status summary if we have status information
    if app_status_counts:
        total_apps = sum(app_status_counts.values())
        logger.info(f"Found {total_apps} apps from original domain:")
        for status, count in sorted(app_status_counts.items()):
            logger.info(f"  - {status}: {count}")
        
        failed_count = app_status_counts.get('Failed', 0)
        if failed_count > 0:
            logger.warning(f"Skipping ResourceSpecs from {failed_count} Failed apps")
    
    logger.info(f"Starting apps for {len(spaces)} spaces in parallel...")
    logger.info(f"Using ResourceSpecs from {len(app_resource_specs)} non-failed apps")
    
    failed_spaces = []
    created_apps = []
    
    # Phase 1: Create all apps with delay between calls
    logger.info(f"Phase 1: Creating apps for {len(spaces)} spaces...")
    for i, space in enumerate(spaces):
        space_name = space['SpaceName']
        
        # Get owner user profile name from OwnershipSettings
        if 'OwnershipSettings' in space and 'OwnerUserProfileName' in space['OwnershipSettings']:
            owner_user_profile = space['OwnershipSettings']['OwnerUserProfileName']
        else:
            owner_user_profile = space.get('OwnerUserProfileName', 'unknown')
        
        # Get ResourceSpec for this space's JupyterLab app if available
        resource_spec = app_resource_specs.get((space_name, 'JupyterLab'))
        
        # Create JupyterLab app
        success, error = create_space_app(
            sagemaker_client,
            domain_id,
            space_name,
            jupyterlab_lcc_arn,
            resource_spec=resource_spec,
            app_type='JupyterLab'
        )
        
        if success:
            created_apps.append({
                'space_name': space_name,
                'owner_user_profile': owner_user_profile,
                'app_type': 'JupyterLab'
            })
        else:
            failed_spaces.append({
                'space_name': space_name,
                'owner_user_profile': owner_user_profile,
                'app_type': 'JupyterLab',
                'error': error,
                'phase': 'creation'
            })
        
        # Add delay between API calls to avoid throttling (except for last app)
        if i < len(spaces) - 1:
            time.sleep(2)
    
    logger.info(f"Phase 1 complete. {len(created_apps)} apps created")
    
    # Phase 2: Wait for all apps to be ready
    logger.info(f"Phase 2: Waiting for {len(created_apps)} apps to be ready...")
    successful_count = 0
    
    for app_info in created_apps:
        space_name = app_info['space_name']
        app_type = app_info['app_type']
        app_name = 'default'
        
        if wait_for_app_ready(
            sagemaker_client,
            domain_id,
            None,
            space_name,
            app_type,
            app_name
        ):
            successful_count += 1
            logger.info(f"App ready: {space_name}/{app_type}/{app_name}")
        else:
            failed_spaces.append({
                'space_name': space_name,
                'owner_user_profile': app_info['owner_user_profile'],
                'app_type': app_type,
                'error': 'App failed to start or timed out',
                'phase': 'ready_wait'
            })
    
    logger.info(f"Phase 2 complete. {successful_count} apps ready")
    
    return successful_count, failed_spaces


def restore_domain_data(
    domain_id: str,
    s3_bucket: str,
    s3_prefix: str,
    config_dir: str,
    backup_efs: bool = True
) -> None:
    """
    Main restoration function to sync data from S3 back to user volumes
    
    Args:
        domain_id: SageMaker domain ID
        s3_bucket: S3 bucket name for backup
        s3_prefix: S3 prefix for backup
        config_dir: Directory containing configuration files
        backup_efs: Whether EFS data was backed up (default: True)
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
        sagemaker_client, 'JupyterLab', s3_bucket, s3_prefix, backup_efs
    )
    codeeditor_lcc_arn = create_lifecycle_config(
        sagemaker_client, 'CodeEditor', s3_bucket, s3_prefix, backup_efs
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
    
    # Load apps configuration (optional - may not exist if no apps were running during discovery)
    apps_file = output_path / "apps.json"
    if apps_file.exists():
        logger.info("Loading apps configuration...")
        apps_data = load_json(str(apps_file))
    else:
        logger.warning("Apps configuration not found - will use default ResourceSpecs")
        apps_data = {"Apps": []}
    
    # Start all spaces
    successful_count, failed_spaces = start_all_spaces(
        sagemaker_client, domain_id, spaces_data, apps_data, jupyterlab_lcc_arn, codeeditor_lcc_arn
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
        '--backup-efs',
        action='store_true',
        default=True,
        help='EFS data was backed up (default: True)'
    )
    parser.add_argument(
        '--no-backup-efs',
        action='store_false',
        dest='backup_efs',
        help='EFS data was not backed up'
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
            args.config_dir,
            args.backup_efs
        )
        sys.exit(0)
    except Exception as e:
        logger.error(f"Restoration failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
