#!/usr/bin/env python3
"""
Backup Script for SageMaker Domain Migration

This script creates lifecycle configurations to sync user data to S3,
attaches them to the domain, and restarts all active apps to trigger the backup.

Usage:
    python backup_domain_data.py --domain-id <domain-id> --s3-bucket <bucket> [--s3-prefix <prefix>] [--config-dir <path>]
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
    setup_logging,
    get_logger,
    save_json,
    load_json
)

logger = get_logger(__name__)


def generate_backup_lifecycle_script(s3_bucket: str, s3_prefix: str, backup_efs: bool = True) -> str:
    """
    Generate lifecycle configuration script for backing up data to S3
    
    Args:
        s3_bucket: S3 bucket name
        s3_prefix: S3 prefix (optional)
        backup_efs: Whether to backup EFS data (default: True)
        
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
export SM_BCK_SPACE_NAME=$(cat /opt/ml/metadata/resource-metadata.json | jq -r '.SpaceName')
export SM_BCK_DOMAIN_ID=$(cat /opt/ml/metadata/resource-metadata.json | jq -r '.DomainId')

# Get user profile name from space ownership
export SM_BCK_USER_PROFILE_NAME=$(aws sagemaker describe-space --domain-id=$SM_BCK_DOMAIN_ID --space-name=$SM_BCK_SPACE_NAME | jq -r '.OwnershipSettings.OwnerUserProfileName')

# Construct S3 path
S3_BUCKET="{s3_bucket}"
S3_PREFIX="{s3_prefix}"

# Build full S3 path with user profile and space
if [ -n "$S3_PREFIX" ] && [ "$S3_PREFIX" != "" ]; then
    S3_PATH="s3://${{S3_BUCKET}}/${{S3_PREFIX}}/${{SM_BCK_USER_PROFILE_NAME}}/${{SM_BCK_SPACE_NAME}}"
else
    S3_PATH="s3://${{S3_BUCKET}}/${{SM_BCK_USER_PROFILE_NAME}}/${{SM_BCK_SPACE_NAME}}"
fi

echo "Starting backup to $S3_PATH"
echo "Domain ID: $SM_BCK_DOMAIN_ID"
echo "Space Name: $SM_BCK_SPACE_NAME"
echo "User Profile: $SM_BCK_USER_PROFILE_NAME"
echo "Backup EFS: {'Yes' if backup_efs else 'No'}"

# Sync user data to S3, excluding cache directories and optionally EFS
nohup aws s3 sync /home/sagemaker-user "$S3_PATH" {exclude_params} > sync.log 2>&1 &

echo "Backup completed successfully"
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
    Create a Studio lifecycle configuration for backup
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        app_type: App type (JupyterLab or CodeEditor)
        s3_bucket: S3 bucket name
        s3_prefix: S3 prefix
        backup_efs: Whether to backup EFS data
        
    Returns:
        Lifecycle configuration ARN
    """
    try:
        lcc_name = f"backup-{app_type.lower()}-{int(time.time())}"
        script_content = generate_backup_lifecycle_script(s3_bucket, s3_prefix, backup_efs)
        
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


def list_active_apps(sagemaker_client, domain_id: str) -> List[Dict[str, Any]]:
    """
    List all JupyterLab and CodeEditor apps in the domain, excluding failed ones
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        
    Returns:
        List of app dictionaries with details (excluding failed apps)
    """
    try:
        logger.info(f"Listing apps for domain {domain_id}")
        apps = []
        app_status_counts = {}
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
                # Filter for JupyterLab and CodeEditor apps
                if app['AppType'] in ['JupyterLab', 'CodeEditor']:
                    status = app['Status']
                    app_status_counts[status] = app_status_counts.get(status, 0) + 1
                    
                    # Skip failed apps but include all others (InService, Pending, etc.)
                    if status != 'Failed':
                        apps.append({
                            'DomainId': app['DomainId'],
                            'UserProfileName': app.get('UserProfileName'),
                            'SpaceName': app.get('SpaceName'),
                            'AppType': app['AppType'],
                            'AppName': app['AppName'],
                            'Status': status
                        })
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        # Log status summary
        total_apps = sum(app_status_counts.values())
        logger.info(f"Found {total_apps} JupyterLab/CodeEditor apps:")
        for status, count in sorted(app_status_counts.items()):
            logger.info(f"  - {status}: {count}")
        
        # Specifically log failed apps count
        failed_count = app_status_counts.get('Failed', 0)
        if failed_count > 0:
            logger.warning(f"Skipping {failed_count} Failed apps")
        
        logger.info(f"Will process {len(apps)} apps (excluding failed)")
        return apps
        
    except Exception as e:
        logger.error(f"Failed to list apps: {str(e)}")
        raise


def wait_for_app_deleted(
    sagemaker_client,
    domain_id: str,
    user_profile_name: Optional[str],
    space_name: Optional[str],
    app_type: str,
    app_name: str,
    max_wait_seconds: int = 600
) -> bool:
    """
    Wait for an app to be deleted
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        user_profile_name: User profile name (for user profile apps)
        space_name: Space name (for space apps)
        app_type: App type
        app_name: App name
        max_wait_seconds: Maximum time to wait in seconds
        
    Returns:
        True if app is deleted, False if timeout
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
            
            if status == 'Deleted':
                return True
            
            logger.debug(f"App {app_name} status: {status}, waiting...")
            time.sleep(10)
            
        except sagemaker_client.exceptions.ResourceNotFound:
            # App is deleted
            return True
        except Exception as e:
            logger.warning(f"Error checking app status: {str(e)}")
            time.sleep(10)
    
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


def delete_app(
    sagemaker_client,
    app_info: Dict[str, Any]
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Delete an app and capture its ResourceSpec
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        app_info: App information dictionary
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str], resource_spec: Dict)
    """
    domain_id = app_info['DomainId']
    user_profile_name = app_info.get('UserProfileName')
    space_name = app_info.get('SpaceName')
    app_type = app_info['AppType']
    app_name = app_info['AppName']
    
    try:
        # Build identifier for logging
        if space_name:
            identifier = f"{space_name}/{app_type}/{app_name}"
        else:
            identifier = f"{user_profile_name}/{app_type}/{app_name}"
        
        logger.info(f"Deleting app: {identifier}")
        
        # Get app details before deletion to capture ResourceSpec
        describe_kwargs = {
            'DomainId': domain_id,
            'AppType': app_type,
            'AppName': app_name
        }
        
        if user_profile_name:
            describe_kwargs['UserProfileName'] = user_profile_name
        if space_name:
            describe_kwargs['SpaceName'] = space_name
        
        app_details = sagemaker_client.describe_app(**describe_kwargs)
        resource_spec = app_details.get('ResourceSpec', {})
        logger.info(f"Captured ResourceSpec for app: {identifier}")
        
        # Delete the app
        delete_kwargs = {
            'DomainId': domain_id,
            'AppType': app_type,
            'AppName': app_name
        }
        
        if user_profile_name:
            delete_kwargs['UserProfileName'] = user_profile_name
        if space_name:
            delete_kwargs['SpaceName'] = space_name
        
        sagemaker_client.delete_app(**delete_kwargs)
        logger.info(f"Initiated deletion of app: {identifier}")
        
        return True, None, resource_spec
        
    except Exception as e:
        error_msg = f"Failed to delete app: {str(e)}"
        logger.error(error_msg)
        return False, error_msg, {}


def create_app(
    sagemaker_client,
    app_info: Dict[str, Any],
    resource_spec: Dict[str, Any],
    jupyterlab_lcc_arn: str,
    codeeditor_lcc_arn: str
) -> Tuple[bool, Optional[str]]:
    """
    Create an app with the specified ResourceSpec
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        app_info: App information dictionary
        resource_spec: ResourceSpec to use for the app
        jupyterlab_lcc_arn: JupyterLab lifecycle config ARN
        codeeditor_lcc_arn: CodeEditor lifecycle config ARN
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    domain_id = app_info['DomainId']
    user_profile_name = app_info.get('UserProfileName')
    space_name = app_info.get('SpaceName')
    app_type = app_info['AppType']
    app_name = app_info['AppName']
    
    try:
        # Build identifier for logging
        if space_name:
            identifier = f"{space_name}/{app_type}/{app_name}"
        else:
            identifier = f"{user_profile_name}/{app_type}/{app_name}"
        
        logger.info(f"Creating app: {identifier}")
        
        # Recreate the app with the same ResourceSpec
        create_kwargs = {
            'DomainId': domain_id,
            'AppType': app_type,
            'AppName': app_name
        }
        
        if user_profile_name:
            create_kwargs['UserProfileName'] = user_profile_name
        if space_name:
            create_kwargs['SpaceName'] = space_name
        
        # Add ResourceSpec if it was present in the original app
        if resource_spec:
            # Append the appropriate lifecycle config ARN based on app type
            lcc_arn = jupyterlab_lcc_arn if app_type == 'JupyterLab' else codeeditor_lcc_arn
            resource_spec['LifecycleConfigArn'] = lcc_arn
            
            create_kwargs['ResourceSpec'] = resource_spec
            logger.info(f"Using ResourceSpec with LCC: {resource_spec}")
        
        sagemaker_client.create_app(**create_kwargs)
        logger.info(f"Initiated creation of app: {identifier}")
        
        return True, None
        
    except Exception as e:
        error_msg = f"Failed to create app: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def restart_apps_parallel(
    sagemaker_client,
    active_apps: List[Dict[str, Any]],
    jupyterlab_lcc_arn: str,
    codeeditor_lcc_arn: str
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Restart all apps in parallel by deleting all, then creating all
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        active_apps: List of app information dictionaries
        jupyterlab_lcc_arn: JupyterLab lifecycle config ARN
        codeeditor_lcc_arn: CodeEditor lifecycle config ARN
        
    Returns:
        Tuple of (successful_count, failed_apps)
    """
    failed_apps = []
    app_resource_specs = {}
    
    # Phase 1: Delete all apps and capture ResourceSpecs
    logger.info(f"Phase 1: Deleting {len(active_apps)} apps...")
    for app_info in active_apps:
        success, error, resource_spec = delete_app(sagemaker_client, app_info)
        
        if success:
            # Store ResourceSpec for later recreation
            app_key = (
                app_info.get('UserProfileName'),
                app_info.get('SpaceName'),
                app_info['AppType'],
                app_info['AppName']
            )
            app_resource_specs[app_key] = resource_spec
        else:
            failed_apps.append({
                'user_profile_name': app_info.get('UserProfileName'),
                'space_name': app_info.get('SpaceName'),
                'app_type': app_info['AppType'],
                'app_name': app_info['AppName'],
                'error': error,
                'phase': 'deletion'
            })
    
    # Wait for all deletions to complete
    logger.info("Waiting for all app deletions to complete...")
    for app_info in active_apps:
        # Skip apps that failed to delete
        app_key = (
            app_info.get('UserProfileName'),
            app_info.get('SpaceName'),
            app_info['AppType'],
            app_info['AppName']
        )
        if app_key not in app_resource_specs:
            continue
        
        if not wait_for_app_deleted(
            sagemaker_client,
            app_info['DomainId'],
            app_info.get('UserProfileName'),
            app_info.get('SpaceName'),
            app_info['AppType'],
            app_info['AppName']
        ):
            failed_apps.append({
                'user_profile_name': app_info.get('UserProfileName'),
                'space_name': app_info.get('SpaceName'),
                'app_type': app_info['AppType'],
                'app_name': app_info['AppName'],
                'error': 'Timeout waiting for app deletion',
                'phase': 'deletion_wait'
            })
            # Remove from resource specs so we don't try to recreate
            del app_resource_specs[app_key]
    
    logger.info(f"Phase 1 complete. {len(app_resource_specs)} apps ready for recreation")
    
    # Phase 2: Create all apps with 2-3 second delay between calls
    logger.info(f"Phase 2: Creating {len(app_resource_specs)} apps...")
    for i, (app_key, resource_spec) in enumerate(app_resource_specs.items()):
        user_profile_name, space_name, app_type, app_name = app_key
        
        # Find the original app_info
        app_info = next(
            (app for app in active_apps
             if app.get('UserProfileName') == user_profile_name
             and app.get('SpaceName') == space_name
             and app['AppType'] == app_type
             and app['AppName'] == app_name),
            None
        )
        
        if not app_info:
            continue
        
        success, error = create_app(
            sagemaker_client,
            app_info,
            resource_spec,
            jupyterlab_lcc_arn,
            codeeditor_lcc_arn
        )
        
        if not success:
            failed_apps.append({
                'user_profile_name': user_profile_name,
                'space_name': space_name,
                'app_type': app_type,
                'app_name': app_name,
                'error': error,
                'phase': 'creation'
            })
        
        # Add delay between API calls to avoid throttling (except for last app)
        if i < len(app_resource_specs) - 1:
            time.sleep(2)
    
    # Phase 3: Wait for all apps to be ready
    logger.info("Phase 3: Waiting for all apps to be ready...")
    successful_count = 0
    
    for app_key in app_resource_specs.keys():
        user_profile_name, space_name, app_type, app_name = app_key
        
        # Skip apps that failed to create
        if any(f['user_profile_name'] == user_profile_name
               and f['space_name'] == space_name
               and f['app_type'] == app_type
               and f['app_name'] == app_name
               and f['phase'] == 'creation'
               for f in failed_apps):
            continue
        
        # Find the original app_info
        app_info = next(
            (app for app in active_apps
             if app.get('UserProfileName') == user_profile_name
             and app.get('SpaceName') == space_name
             and app['AppType'] == app_type
             and app['AppName'] == app_name),
            None
        )
        
        if not app_info:
            continue
        
        if wait_for_app_ready(
            sagemaker_client,
            app_info['DomainId'],
            user_profile_name,
            space_name,
            app_type,
            app_name
        ):
            successful_count += 1
        else:
            failed_apps.append({
                'user_profile_name': user_profile_name,
                'space_name': space_name,
                'app_type': app_type,
                'app_name': app_name,
                'error': 'App failed to start or timed out',
                'phase': 'ready_wait'
            })
    
    logger.info(f"Phase 3 complete. {successful_count} apps ready")
    
    return successful_count, failed_apps


def backup_domain_data(
    domain_id: str,
    s3_bucket: str,
    s3_prefix: str,
    config_dir: str,
    backup_efs: bool = True
) -> None:
    """
    Main backup function to sync user data to S3
    
    Args:
        domain_id: SageMaker domain ID
        s3_bucket: S3 bucket name for backup
        s3_prefix: S3 prefix for backup
        config_dir: Directory containing configuration files
        backup_efs: Whether to backup EFS data (default: True)
    """
    # Initialize AWS client
    sagemaker_client = get_sagemaker_client()
    
    # Create output directory
    output_path = Path(config_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)
    logger.info("Starting domain backup process")
    logger.info("=" * 60)
    logger.info(f"Domain ID: {domain_id}")
    logger.info(f"S3 Bucket: {s3_bucket}")
    logger.info(f"S3 Prefix: {s3_prefix}")
    logger.info("=" * 60)
    
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
    
    # List active apps
    active_apps = list_active_apps(sagemaker_client, domain_id)
    
    if not active_apps:
        logger.warning("No active JupyterLab or CodeEditor apps found")
        logger.info("Backup lifecycle configurations have been attached to the domain")
        logger.info("Apps will sync data to S3 when they are next started")
    else:
        # Restart all active apps in parallel
        logger.info(f"Restarting {len(active_apps)} active apps in parallel...")
        
        successful_count, failed_apps = restart_apps_parallel(
            sagemaker_client,
            active_apps,
            jupyterlab_lcc_arn,
            codeeditor_lcc_arn
        )
        
        # Save backup status
        backup_status = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'domain_id': domain_id,
            's3_bucket': s3_bucket,
            's3_prefix': s3_prefix,
            'jupyterlab_lcc_arn': jupyterlab_lcc_arn,
            'codeeditor_lcc_arn': codeeditor_lcc_arn,
            'total_apps': len(active_apps),
            'successful_apps': successful_count,
            'failed_apps': failed_apps
        }
        
        status_file = output_path / "backup_status.json"
        save_json(backup_status, str(status_file))
        
        # Summary
        logger.info("=" * 60)
        logger.info("Backup process completed")
        logger.info("=" * 60)
        logger.info(f"Total apps: {len(active_apps)}")
        logger.info(f"Successfully restarted: {successful_count}")
        logger.info(f"Failed: {len(failed_apps)}")
        
        if failed_apps:
            logger.error("=" * 60)
            logger.error("FAILED APPS:")
            for failed_app in failed_apps:
                location = failed_app.get('space_name') or failed_app.get('user_profile_name')
                logger.error(f"  - {location}/{failed_app['app_type']}/{failed_app['app_name']}")
                logger.error(f"    Error: {failed_app['error']}")
            logger.error("=" * 60)
            
            # Fail the backup process if any apps failed
            raise RuntimeError(
                f"Backup process failed: {len(failed_apps)} app(s) failed to restart. "
                "Please check the logs and backup_status.json for details."
            )
        
        logger.info(f"Backup status saved to: {status_file}")
        logger.info("=" * 60)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Backup SageMaker Studio domain data to S3"
    )
    parser.add_argument(
        '--domain-id',
        required=True,
        help='SageMaker domain ID (e.g., d-xxxxxxxxxxxx)'
    )
    parser.add_argument(
        '--s3-bucket',
        required=True,
        help='S3 bucket name for backup'
    )
    parser.add_argument(
        '--s3-prefix',
        default='',
        help='S3 prefix for backup (optional)'
    )
    parser.add_argument(
        '--config-dir',
        default='./migration_data',
        help='Directory for configuration files (default: ./migration_data)'
    )
    parser.add_argument(
        '--backup-efs',
        action='store_true',
        default=True,
        help='Backup EFS data (default: True)'
    )
    parser.add_argument(
        '--no-backup-efs',
        action='store_false',
        dest='backup_efs',
        help='Skip EFS data backup'
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
        backup_domain_data(
            args.domain_id,
            args.s3_bucket,
            args.s3_prefix,
            args.config_dir,
            args.backup_efs
        )
        sys.exit(0)
    except Exception as e:
        logger.error(f"Backup failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
