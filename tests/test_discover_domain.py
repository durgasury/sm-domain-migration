"""Unit tests for discover_domain script"""

import pytest
from scripts.discover_domain import (
    validate_domain_id,
    generate_backup_lifecycle_script
)


class TestDomainValidation:
    """Test domain ID validation"""
    
    def test_valid_domain_id(self):
        """Test validation accepts valid domain IDs"""
        assert validate_domain_id("d-abc123xyz") is True
        assert validate_domain_id("d-1234567890ab") is True
    
    def test_invalid_domain_id_format(self):
        """Test validation rejects invalid domain IDs"""
        with pytest.raises(ValueError, match="Invalid domain ID format"):
            validate_domain_id("invalid-id")
        
        with pytest.raises(ValueError, match="Invalid domain ID format"):
            validate_domain_id("d-")
        
        with pytest.raises(ValueError, match="Invalid domain ID format"):
            validate_domain_id("abc123")
