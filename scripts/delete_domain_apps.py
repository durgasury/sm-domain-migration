#!/usr/bin/env python3
"""
Delete Apps Script for SageMaker Domain

This script deletes all JupyterLab and CodeEditor apps in a SageMaker domain
to save costs when apps are not actively being used.

Usage:
    python delete_domain_apps.py --domain-id <domain-id> [--dry-run] [--config-dir <path>]
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from utils import (
    get_sagemaker_client,
    setup_logging,
    get_logger,
    save_json
)

logger = get_logger(__name__)


def list_all_apps(sagemaker_client, domain_id: str) -> List[Dict[str, Any]]:
    """
    List all JupyterLab and CodeEditor apps in the domain
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: SageMaker domain ID
        
    Returns:
        List of app dictionaries with details
    """
    try:
        logger.info(f"Listing all JupyterLab and CodeEditor apps for domain {domain_id}")
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
                # Filter for JupyterLab and CodeEditor apps (all statuses except Deleted)
                if app['AppType'] in ['JupyterLab', 'CodeEditor'] and app['Status'] != 'Deleted':
                    apps.append({
                        'DomainId': app['DomainId'],
                        'UserProfileName': app.get('UserProfileName'),
                        'SpaceName': app.get('SpaceName'),
                        'AppType': app['AppType'],
                        'AppName': app['AppName'],
                        'Status': app['Status']
                    })
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Found {len(apps)} JupyterLab/CodeEditor apps")
        return apps
        
    except Exception as e:
        logger.error(f"Failed to list apps: {str(e)}")
        raise


def delete_app(
    sagemaker_client,
    app_info: Dict[str, Any],
    dry_run: bool = False
) -> tuple[bool, Optional[str]]:
    """
    Delete a single app
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        app_info: App information dictionary
        dry_run: If True, only log what would be deleted without actually deleting
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    domain_id = app_info['DomainId']
    user_profile_name = app_info.get('UserProfileName')
    space_name = app_info.get('SpaceName')
    app_type = app_info['AppType']
    app_name = app_info['AppName']
    status = app_info['Status']
    
    try:
        # Build identifier for logging
        if space_name:
            identifier = f"{space_name}/{app_type}/{app_name}"
        else:
            identifier = f"{user_profile_name}/{app_type}/{app_name}"
        
        if dry_run:
            logger.info(f"[DRY RUN] Would delete app: {identifier} (Status: {status})")
            return True, None
        
        logger.info(f"Deleting app: {identifier} (Status: {status})")
        
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
        logger.info(f"Successfully initiated deletion of app: {identifier}")
        return True, None
        
    except Exception as e:
        error_msg = f"Failed to delete app: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def delete_domain_apps(
    domain_id: str,
    dry_run: bool,
    config_dir: str
) -> None:
    """
    Main function to delete all JupyterLab and CodeEditor apps in a domain
    
    Args:
        domain_id: SageMaker domain ID
        dry_run: If True, only log what would be deleted without actually deleting
        config_dir: Directory for output files
    """
    # Initialize AWS client
    sagemaker_client = get_sagemaker_client()
    
    # Create output directory
    output_path = Path(config_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)
    if dry_run:
        logger.info("DRY RUN MODE - No apps will be deleted")
    else:
        logger.info("Starting app deletion process")
    logger.info("=" * 60)
    logger.info(f"Domain ID: {domain_id}")
    logger.info("=" * 60)
    
    # List all apps
    all_apps = list_all_apps(sagemaker_client, domain_id)
    
    if not all_apps:
        logger.info("No JupyterLab or CodeEditor apps found in the domain")
        return
    
    # Display summary
    logger.info(f"Found {len(all_apps)} apps to delete:")
    for app_info in all_apps:
        location = app_info.get('SpaceName') or app_info.get('UserProfileName')
        logger.info(f"  - {location}/{app_info['AppType']}/{app_info['AppName']} (Status: {app_info['Status']})")
    
    if dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN COMPLETE - No apps were deleted")
        logger.info("Run without --dry-run to actually delete the apps")
        logger.info("=" * 60)
        return
    
    # Confirm deletion
    logger.warning("=" * 60)
    logger.warning("WARNING: This will delete all listed apps!")
    logger.warning("Apps will need to be restarted manually by users")
    logger.warning("=" * 60)
    
    # Delete all apps
    logger.info(f"Deleting {len(all_apps)} apps...")
    
    failed_apps = []
    successful_count = 0
    
    for app_info in all_apps:
        success, error = delete_app(sagemaker_client, app_info, dry_run=False)
        
        if success:
            successful_count += 1
        else:
            failed_apps.append({
                'user_profile_name': app_info.get('UserProfileName'),
                'space_name': app_info.get('SpaceName'),
                'app_type': app_info['AppType'],
                'app_name': app_info['AppName'],
                'status': app_info['Status'],
                'error': error
            })
    
    # Save deletion status
    deletion_status = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'domain_id': domain_id,
        'total_apps': len(all_apps),
        'successful_deletions': successful_count,
        'failed_deletions': failed_apps
    }
    
    status_file = output_path / "deletion_status.json"
    save_json(deletion_status, str(status_file))
    
    # Summary
    logger.info("=" * 60)
    logger.info("App deletion process completed")
    logger.info("=" * 60)
    logger.info(f"Total apps: {len(all_apps)}")
    logger.info(f"Successfully deleted: {successful_count}")
    logger.info(f"Failed: {len(failed_apps)}")
    
    if failed_apps:
        logger.error("=" * 60)
        logger.error("FAILED DELETIONS:")
        for failed_app in failed_apps:
            location = failed_app.get('space_name') or failed_app.get('user_profile_name')
            logger.error(f"  - {location}/{failed_app['app_type']}/{failed_app['app_name']}")
            logger.error(f"    Status: {failed_app['status']}")
            logger.error(f"    Error: {failed_app['error']}")
        logger.error("=" * 60)
        
        raise RuntimeError(
            f"Deletion process failed: {len(failed_apps)} app(s) failed to delete. "
            "Please check the logs and deletion_status.json for details."
        )
    
    logger.info(f"Deletion status saved to: {status_file}")
    logger.info("=" * 60)
    logger.info("NOTE: Apps are being deleted asynchronously.")
    logger.info("It may take several minutes for all apps to be fully deleted.")
    logger.info("=" * 60)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Delete all JupyterLab and CodeEditor apps in a SageMaker domain"
    )
    parser.add_argument(
        '--domain-id',
        required=True,
        help='SageMaker domain ID (e.g., d-xxxxxxxxxxxx)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    parser.add_argument(
        '--config-dir',
        default='./migration_data',
        help='Directory for output files (default: ./migration_data)'
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
        delete_domain_apps(
            args.domain_id,
            args.dry_run,
            args.config_dir
        )
        sys.exit(0)
    except Exception as e:
        logger.error(f"Deletion failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
