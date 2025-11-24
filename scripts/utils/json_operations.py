"""JSON file operations utilities"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from .logging_config import get_logger

logger = get_logger(__name__)


def save_json(data: Any, filepath: str, indent: int = 2) -> None:
    """
    Save data to a JSON file
    
    Args:
        data: Data to save (must be JSON serializable)
        filepath: Path to the output file
        indent: JSON indentation level (default: 2)
        
    Raises:
        IOError: If file cannot be written
        TypeError: If data is not JSON serializable
    """
    try:
        # Create directory if it doesn't exist
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=indent, default=str)
        
        logger.info(f"Successfully saved data to {filepath}")
    except Exception as e:
        logger.error(f"Failed to save JSON to {filepath}: {str(e)}")
        raise


def load_json(filepath: str) -> Any:
    """
    Load data from a JSON file
    
    Args:
        filepath: Path to the input file
        
    Returns:
        Loaded data
        
    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file contains invalid JSON
    """
    try:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        logger.info(f"Successfully loaded data from {filepath}")
        return data
    except Exception as e:
        logger.error(f"Failed to load JSON from {filepath}: {str(e)}")
        raise


def validate_json_schema(data: Any, schema: Dict[str, Any]) -> bool:
    """
    Validate data against a JSON schema
    
    Args:
        data: Data to validate
        schema: JSON schema definition
        
    Returns:
        True if validation passes
        
    Raises:
        ValueError: If validation fails
    """
    # Basic validation - check required fields exist
    if 'required' in schema:
        if not isinstance(data, dict):
            raise ValueError("Data must be a dictionary for schema validation")
        
        missing_fields = [field for field in schema['required'] if field not in data]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
    
    logger.debug("Schema validation passed")
    return True
