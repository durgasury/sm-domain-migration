#!/usr/bin/env python3
"""
Retagging Script for SageMaker Domain Migration

This script updates tags on SageMaker resources to reference the new domain,
user profiles, and spaces after migration.

Usage:
    python retag_resources.py --old-domain-id <old_id> --new-domain-id <new_id> [--config-dir <path>]
"""

import argparse
import sys
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


def load_resource_mapping(config_dir: str) -> Dict[str, Any]:
    """
    Load resource mapping from JSON file
    
    Args:
        config_dir: Directory containing configuration files
        
    Returns:
        Resource mapping dictionary
        
    Raises:
        FileNotFoundError: If mapping file is missing
    """
    config_path = Path(config_dir)
    mapping_file = config_path / "recreation_mapping.json"
    
    if not mapping_file.exists():
        raise FileNotFoundError(f"Resource mapping not found: {mapping_file}")
    
    logger.info(f"Loading resource mapping from {mapping_file}")
    mapping = load_json(str(mapping_file))
    
    logger.info(f"Loaded mapping: {len(mapping.get('user_profiles', {}))} user profiles, "
                f"{len(mapping.get('spaces', {}))} spaces")
    
    return mapping


def list_training_jobs_by_domain(sagemaker_client, domain_id: str) -> List[str]:
    """
    List all training jobs tagged with the specified domain ID
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID to filter by
        
    Returns:
        List of training job ARNs
    """
    training_job_arns = []
    next_token = None
    
    logger.info(f"Listing training jobs for domain {domain_id}")
    
    try:
        while True:
            list_params = {'MaxResults': 100}
            if next_token:
                list_params['NextToken'] = next_token
            
            response = sagemaker_client.list_training_jobs(**list_params)
            
            for job_summary in response.get('TrainingJobSummaries', []):
                job_name = job_summary['TrainingJobName']
                
                # Get job details to check tags
                job_details = sagemaker_client.describe_training_job(TrainingJobName=job_name)
                job_arn = job_details['TrainingJobArn']
                
                # Check if job has domain tag
                tags = sagemaker_client.list_tags(ResourceArn=job_arn).get('Tags', [])
                for tag in tags:
                    if tag.get('Key') == 'sagemaker:domain-id' and tag.get('Value') == domain_id:
                        training_job_arns.append(job_arn)
                        break
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Found {len(training_job_arns)} training jobs")
        return training_job_arns
        
    except Exception as e:
        logger.error(f"Failed to list training jobs: {str(e)}")
        raise


def list_processing_jobs_by_domain(sagemaker_client, domain_id: str) -> List[str]:
    """
    List all processing jobs tagged with the specified domain ID
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID to filter by
        
    Returns:
        List of processing job ARNs
    """
    processing_job_arns = []
    next_token = None
    
    logger.info(f"Listing processing jobs for domain {domain_id}")
    
    try:
        while True:
            list_params = {'MaxResults': 100}
            if next_token:
                list_params['NextToken'] = next_token
            
            response = sagemaker_client.list_processing_jobs(**list_params)
            
            for job_summary in response.get('ProcessingJobSummaries', []):
                job_name = job_summary['ProcessingJobName']
                
                # Get job details to check tags
                job_details = sagemaker_client.describe_processing_job(ProcessingJobName=job_name)
                job_arn = job_details['ProcessingJobArn']
                
                # Check if job has domain tag
                tags = sagemaker_client.list_tags(ResourceArn=job_arn).get('Tags', [])
                for tag in tags:
                    if tag.get('Key') == 'sagemaker:domain-id' and tag.get('Value') == domain_id:
                        processing_job_arns.append(job_arn)
                        break
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Found {len(processing_job_arns)} processing jobs")
        return processing_job_arns
        
    except Exception as e:
        logger.error(f"Failed to list processing jobs: {str(e)}")
        raise


def list_transform_jobs_by_domain(sagemaker_client, domain_id: str) -> List[str]:
    """
    List all transform jobs tagged with the specified domain ID
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID to filter by
        
    Returns:
        List of transform job ARNs
    """
    transform_job_arns = []
    next_token = None
    
    logger.info(f"Listing transform jobs for domain {domain_id}")
    
    try:
        while True:
            list_params = {'MaxResults': 100}
            if next_token:
                list_params['NextToken'] = next_token
            
            response = sagemaker_client.list_transform_jobs(**list_params)
            
            for job_summary in response.get('TransformJobSummaries', []):
                job_name = job_summary['TransformJobName']
                
                # Get job details to check tags
                job_details = sagemaker_client.describe_transform_job(TransformJobName=job_name)
                job_arn = job_details['TransformJobArn']
                
                # Check if job has domain tag
                tags = sagemaker_client.list_tags(ResourceArn=job_arn).get('Tags', [])
                for tag in tags:
                    if tag.get('Key') == 'sagemaker:domain-id' and tag.get('Value') == domain_id:
                        transform_job_arns.append(job_arn)
                        break
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Found {len(transform_job_arns)} transform jobs")
        return transform_job_arns
        
    except Exception as e:
        logger.error(f"Failed to list transform jobs: {str(e)}")
        raise


def list_pipelines_by_domain(sagemaker_client, domain_id: str) -> List[str]:
    """
    List all pipelines tagged with the specified domain ID
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID to filter by
        
    Returns:
        List of pipeline ARNs
    """
    pipeline_arns = []
    next_token = None
    
    logger.info(f"Listing pipelines for domain {domain_id}")
    
    try:
        while True:
            list_params = {'MaxResults': 100}
            if next_token:
                list_params['NextToken'] = next_token
            
            response = sagemaker_client.list_pipelines(**list_params)
            
            for pipeline_summary in response.get('PipelineSummaries', []):
                pipeline_name = pipeline_summary['PipelineName']
                
                # Get pipeline details
                pipeline_details = sagemaker_client.describe_pipeline(PipelineName=pipeline_name)
                pipeline_arn = pipeline_details['PipelineArn']
                
                # Check if pipeline has domain tag
                tags = sagemaker_client.list_tags(ResourceArn=pipeline_arn).get('Tags', [])
                for tag in tags:
                    if tag.get('Key') == 'sagemaker:domain-id' and tag.get('Value') == domain_id:
                        pipeline_arns.append(pipeline_arn)
                        break
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Found {len(pipeline_arns)} pipelines")
        return pipeline_arns
        
    except Exception as e:
        logger.error(f"Failed to list pipelines: {str(e)}")
        raise


def list_endpoints_by_domain(sagemaker_client, domain_id: str) -> List[str]:
    """
    List all endpoints tagged with the specified domain ID
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID to filter by
        
    Returns:
        List of endpoint ARNs
    """
    endpoint_arns = []
    next_token = None
    
    logger.info(f"Listing endpoints for domain {domain_id}")
    
    try:
        while True:
            list_params = {'MaxResults': 100}
            if next_token:
                list_params['NextToken'] = next_token
            
            response = sagemaker_client.list_endpoints(**list_params)
            
            for endpoint_summary in response.get('Endpoints', []):
                endpoint_name = endpoint_summary['EndpointName']
                
                # Get endpoint details
                endpoint_details = sagemaker_client.describe_endpoint(EndpointName=endpoint_name)
                endpoint_arn = endpoint_details['EndpointArn']
                
                # Check if endpoint has domain tag
                tags = sagemaker_client.list_tags(ResourceArn=endpoint_arn).get('Tags', [])
                for tag in tags:
                    if tag.get('Key') == 'sagemaker:domain-id' and tag.get('Value') == domain_id:
                        endpoint_arns.append(endpoint_arn)
                        break
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"Found {len(endpoint_arns)} endpoints")
        return endpoint_arns
        
    except Exception as e:
        logger.error(f"Failed to list endpoints: {str(e)}")
        raise


def list_tagged_resources(sagemaker_client, domain_id: str) -> Dict[str, List[str]]:
    """
    List all SageMaker resources tagged with the specified domain ID
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        domain_id: Domain ID to filter by
        
    Returns:
        Dictionary with resource types as keys and lists of ARNs as values
    """
    logger.info(f"Discovering all resources tagged with domain {domain_id}")
    
    resources = {
        'training_jobs': list_training_jobs_by_domain(sagemaker_client, domain_id),
        'processing_jobs': list_processing_jobs_by_domain(sagemaker_client, domain_id),
        'transform_jobs': list_transform_jobs_by_domain(sagemaker_client, domain_id),
        'pipelines': list_pipelines_by_domain(sagemaker_client, domain_id),
        'endpoints': list_endpoints_by_domain(sagemaker_client, domain_id)
    }
    
    total_resources = sum(len(arns) for arns in resources.values())
    logger.info(f"Total resources found: {total_resources}")
    
    return resources


def get_resource_tags(sagemaker_client, resource_arn: str) -> List[Dict[str, str]]:
    """
    Retrieve current tags for a resource
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        resource_arn: Resource ARN
        
    Returns:
        List of tag dictionaries
    """
    try:
        response = sagemaker_client.list_tags(ResourceArn=resource_arn)
        return response.get('Tags', [])
    except Exception as e:
        logger.error(f"Failed to get tags for {resource_arn}: {str(e)}")
        raise


def map_arn(old_arn: str, mapping: Dict[str, Any]) -> str:
    """
    Translate old ARN to new ARN using the mapping
    
    Args:
        old_arn: Original ARN
        mapping: Resource mapping dictionary
        
    Returns:
        New ARN if found in mapping, otherwise original ARN
    """
    # Check user profile mapping
    if old_arn in mapping.get('user_profiles', {}):
        return mapping['user_profiles'][old_arn]
    
    # Check space mapping
    if old_arn in mapping.get('spaces', {}):
        return mapping['spaces'][old_arn]
    
    # No mapping found, return original
    return old_arn


def update_resource_tags(
    sagemaker_client,
    resource_arn: str,
    old_domain_id: str,
    new_domain_id: str,
    mapping: Dict[str, Any]
) -> Tuple[bool, Optional[str]]:
    """
    Update tags on a resource with new domain, user profile, and space ARNs
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        resource_arn: Resource ARN to update
        old_domain_id: Original domain ID
        new_domain_id: New domain ID
        mapping: Resource mapping dictionary
        
    Returns:
        Tuple of (success, error_message)
    """
    try:
        # Get current tags
        current_tags = get_resource_tags(sagemaker_client, resource_arn)
        
        # Build new tags list
        tags_to_delete = []
        tags_to_add = []
        
        for tag in current_tags:
            key = tag['Key']
            value = tag['Value']
            
            # Check if tag needs updating
            if key == 'sagemaker:domain-id' and value == old_domain_id:
                # Update domain ID tag
                tags_to_delete.append(key)
                tags_to_add.append({'Key': key, 'Value': new_domain_id})
                logger.debug(f"Updating domain ID tag: {old_domain_id} -> {new_domain_id}")
            
            elif key == 'sagemaker:user-profile-arn':
                # Map user profile ARN
                new_arn = map_arn(value, mapping)
                if new_arn != value:
                    tags_to_delete.append(key)
                    tags_to_add.append({'Key': key, 'Value': new_arn})
                    logger.debug(f"Updating user profile ARN: {value} -> {new_arn}")
            
            elif key == 'sagemaker:space-arn':
                # Map space ARN
                new_arn = map_arn(value, mapping)
                if new_arn != value:
                    tags_to_delete.append(key)
                    tags_to_add.append({'Key': key, 'Value': new_arn})
                    logger.debug(f"Updating space ARN: {value} -> {new_arn}")
        
        # Apply tag updates if needed
        if tags_to_delete:
            logger.debug(f"Deleting {len(tags_to_delete)} tags from {resource_arn}")
            sagemaker_client.delete_tags(
                ResourceArn=resource_arn,
                TagKeys=tags_to_delete
            )
        
        if tags_to_add:
            logger.debug(f"Adding {len(tags_to_add)} tags to {resource_arn}")
            sagemaker_client.add_tags(
                ResourceArn=resource_arn,
                Tags=tags_to_add
            )
        
        if tags_to_delete or tags_to_add:
            logger.info(f"Successfully updated tags for {resource_arn}")
        else:
            logger.debug(f"No tag updates needed for {resource_arn}")
        
        return True, None
        
    except Exception as e:
        error_msg = f"Failed to update tags: {str(e)}"
        logger.error(f"{error_msg} for {resource_arn}")
        return False, error_msg


def retag_all_resources(
    sagemaker_client,
    resources: Dict[str, List[str]],
    old_domain_id: str,
    new_domain_id: str,
    mapping: Dict[str, Any]
) -> Tuple[int, List[Dict[str, str]]]:
    """
    Update tags on all discovered resources
    
    Args:
        sagemaker_client: Boto3 SageMaker client
        resources: Dictionary of resource types and ARNs
        old_domain_id: Original domain ID
        new_domain_id: New domain ID
        mapping: Resource mapping dictionary
        
    Returns:
        Tuple of (successful_count, failed_resources)
    """
    successful_count = 0
    failed_resources = []
    
    # Process all resource types
    for resource_type, arns in resources.items():
        logger.info(f"Updating tags for {len(arns)} {resource_type}")
        
        for arn in arns:
            success, error = update_resource_tags(
                sagemaker_client,
                arn,
                old_domain_id,
                new_domain_id,
                mapping
            )
            
            if success:
                successful_count += 1
            else:
                failed_resources.append({
                    'resource_type': resource_type,
                    'resource_arn': arn,
                    'error': error
                })
    
    return successful_count, failed_resources


def retag_resources(config_dir: str, old_domain_id: str, new_domain_id: str) -> None:
    """
    Main retagging function to update all resource tags
    
    Args:
        config_dir: Directory containing configuration files
        old_domain_id: Original domain ID
        new_domain_id: New domain ID
    """
    # Initialize AWS client
    sagemaker_client = get_sagemaker_client()
    
    # Create output directory
    output_path = Path(config_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)
    logger.info("Starting resource retagging process")
    logger.info("=" * 60)
    logger.info(f"Old domain ID: {old_domain_id}")
    logger.info(f"New domain ID: {new_domain_id}")
    logger.info("=" * 60)
    
    # Load resource mapping
    logger.info("Step 1: Loading resource mapping...")
    mapping = load_resource_mapping(config_dir)
    
    # Validate domain IDs match mapping
    if mapping['domain']['old'] != old_domain_id:
        logger.warning(f"Old domain ID mismatch: provided {old_domain_id}, "
                      f"mapping has {mapping['domain']['old']}")
    if mapping['domain']['new'] != new_domain_id:
        logger.warning(f"New domain ID mismatch: provided {new_domain_id}, "
                      f"mapping has {mapping['domain']['new']}")
    
    # Discover tagged resources
    logger.info("Step 2: Discovering tagged resources...")
    resources = list_tagged_resources(sagemaker_client, old_domain_id)
    
    total_resources = sum(len(arns) for arns in resources.values())
    if total_resources == 0:
        logger.info("No resources found with old domain tags. Retagging complete.")
        return
    
    # Update tags on all resources
    logger.info("Step 3: Updating resource tags...")
    successful_count, failed_resources = retag_all_resources(
        sagemaker_client,
        resources,
        old_domain_id,
        new_domain_id,
        mapping
    )
    
    # Save retagging status
    logger.info("Step 4: Saving retagging status...")
    status = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'old_domain_id': old_domain_id,
        'new_domain_id': new_domain_id,
        'total_resources': total_resources,
        'successful_resources': successful_count,
        'failed_resources': failed_resources,
        'resources_by_type': {
            resource_type: len(arns)
            for resource_type, arns in resources.items()
        }
    }
    
    status_file = output_path / "retagging_status.json"
    save_json(status, str(status_file))
    
    # Summary
    logger.info("=" * 60)
    logger.info("Retagging process completed")
    logger.info("=" * 60)
    logger.info(f"Total resources processed: {total_resources}")
    logger.info(f"Successfully updated: {successful_count}")
    logger.info(f"Failed: {len(failed_resources)}")
    
    if failed_resources:
        logger.warning("=" * 60)
        logger.warning("FAILED RESOURCES:")
        for failed in failed_resources:
            logger.warning(f"  - {failed['resource_type']}: {failed['resource_arn']}")
            logger.warning(f"    Error: {failed['error']}")
    
    logger.info("=" * 60)
    logger.info(f"Retagging status saved to: {status_file}")
    logger.info("=" * 60)
    
    # Raise error if there were failures
    if failed_resources:
        raise RuntimeError(
            f"Retagging completed with {len(failed_resources)} failure(s). "
            "Please check the logs for details."
        )


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Update SageMaker resource tags after domain migration"
    )
    parser.add_argument(
        '--config-dir',
        default='./migration_data',
        help='Directory containing configuration files (default: ./migration_data)'
    )
    parser.add_argument(
        '--old-domain-id',
        required=True,
        help='Original domain ID'
    )
    parser.add_argument(
        '--new-domain-id',
        required=True,
        help='New domain ID'
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
        retag_resources(args.config_dir, args.old_domain_id, args.new_domain_id)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Retagging failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
