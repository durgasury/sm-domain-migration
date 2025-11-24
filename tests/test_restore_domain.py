"""Unit tests for restore_domain_data script"""

import pytest
from scripts.restore_domain_data import generate_restore_lifecycle_script


class TestLifecycleScriptGeneration:
    """Test lifecycle script generation"""
    
    def test_generate_restore_script_with_prefix(self):
        """Test restore script generation with S3 prefix"""
        script = generate_restore_lifecycle_script("my-bucket", "my-prefix")
        
        assert "my-bucket" in script
        assert "my-prefix" in script
        assert "aws s3 sync" in script
        assert "/home/sagemaker-user" in script
        assert "SAGEMAKER_USER_PROFILE_NAME" in script
        assert "SAGEMAKER_SPACE_NAME" in script
    
    def test_generate_restore_script_without_prefix(self):
        """Test restore script generation without S3 prefix"""
        script = generate_restore_lifecycle_script("my-bucket", "")
        
        assert "my-bucket" in script
        assert "aws s3 sync" in script
        assert "/home/sagemaker-user" in script
    
    def test_restore_script_excludes_cache(self):
        """Test restore script excludes cache directories"""
        script = generate_restore_lifecycle_script("my-bucket", "prefix")
        
        assert "--exclude" in script
        assert ".cache" in script
    
    def test_restore_script_checks_s3_path_exists(self):
        """Test restore script checks if S3 path exists before syncing"""
        script = generate_restore_lifecycle_script("my-bucket", "prefix")
        
        assert "aws s3 ls" in script
        assert "if" in script
    
    def test_restore_script_syncs_from_s3_to_local(self):
        """Test restore script syncs from S3 to local directory"""
        script = generate_restore_lifecycle_script("my-bucket", "prefix")
        
        # Verify the sync direction is FROM S3 TO local
        # The pattern should be: aws s3 sync "$S3_PATH" /home/sagemaker-user
        assert 'aws s3 sync "$S3_PATH" /home/sagemaker-user' in script
