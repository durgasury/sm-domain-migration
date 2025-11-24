"""Unit tests for backup_domain_data script"""

import pytest
from scripts.backup_domain_data import generate_backup_lifecycle_script


class TestLifecycleScriptGeneration:
    """Test lifecycle script generation"""
    
    def test_generate_backup_script_with_prefix(self):
        """Test backup script generation with S3 prefix"""
        script = generate_backup_lifecycle_script("my-bucket", "my-prefix")
        
        assert "my-bucket" in script
        assert "my-prefix" in script
        assert "aws s3 sync" in script
        assert "/home/sagemaker-user" in script
        assert "SAGEMAKER_USER_PROFILE_NAME" in script
        assert "SAGEMAKER_SPACE_NAME" in script
    
    def test_generate_backup_script_without_prefix(self):
        """Test backup script generation without S3 prefix"""
        script = generate_backup_lifecycle_script("my-bucket", "")
        
        assert "my-bucket" in script
        assert "aws s3 sync" in script
        assert "/home/sagemaker-user" in script
    
    def test_backup_script_excludes_cache(self):
        """Test backup script excludes cache directories"""
        script = generate_backup_lifecycle_script("my-bucket", "prefix")
        
        assert "--exclude" in script
        assert ".cache" in script
