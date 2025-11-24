"""Unit tests for utility functions"""

import pytest
import json
import tempfile
from pathlib import Path
from scripts.utils.json_operations import save_json, load_json, validate_json_schema
from scripts.utils.config_schemas import DOMAIN_CONFIG_SCHEMA


class TestJSONOperations:
    """Test JSON file operations"""
    
    def test_save_and_load_json(self):
        """Test saving and loading JSON data"""
        test_data = {"key": "value", "number": 42}
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.json"
            
            # Save data
            save_json(test_data, str(filepath))
            
            # Load data
            loaded_data = load_json(str(filepath))
            
            assert loaded_data == test_data
    
    def test_load_nonexistent_file(self):
        """Test loading from non-existent file raises error"""
        with pytest.raises(FileNotFoundError):
            load_json("/nonexistent/path/file.json")
    
    def test_validate_schema_success(self):
        """Test schema validation with valid data"""
        data = {
            "DomainId": "d-test123",
            "DomainName": "test-domain",
            "DomainArn": "arn:aws:sagemaker:us-east-1:123456789012:domain/d-test123",
            "HomeEfsFileSystemId": "fs-test123",
            "SubnetIds": ["subnet-123"],
            "VpcId": "vpc-123",
            "AuthMode": "SSO",
            "DefaultUserSettings": {}
        }
        
        assert validate_json_schema(data, DOMAIN_CONFIG_SCHEMA) is True
    
    def test_validate_schema_missing_fields(self):
        """Test schema validation with missing required fields"""
        data = {
            "DomainId": "d-test123",
            "DomainName": "test-domain"
        }
        
        with pytest.raises(ValueError, match="Missing required fields"):
            validate_json_schema(data, DOMAIN_CONFIG_SCHEMA)


class TestConfigSchemas:
    """Test configuration schema definitions"""
    
    def test_domain_config_schema_has_required_fields(self):
        """Test domain config schema defines required fields"""
        assert "required" in DOMAIN_CONFIG_SCHEMA
        assert "DomainId" in DOMAIN_CONFIG_SCHEMA["required"]
        assert "DomainName" in DOMAIN_CONFIG_SCHEMA["required"]
