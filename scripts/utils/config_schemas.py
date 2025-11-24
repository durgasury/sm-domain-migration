"""Configuration file schema definitions"""

from typing import Dict, Any


DOMAIN_CONFIG_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "DomainId",
        "DomainName",
        "DomainArn",
        "HomeEfsFileSystemId",
        "SubnetIds",
        "VpcId",
        "AuthMode",
        "DefaultUserSettings"
    ],
    "properties": {
        "DomainId": {"type": "string"},
        "DomainName": {"type": "string"},
        "DomainArn": {"type": "string"},
        "HomeEfsFileSystemId": {"type": "string"},
        "SubnetIds": {"type": "array", "items": {"type": "string"}},
        "VpcId": {"type": "string"},
        "SecurityGroupIds": {"type": "array", "items": {"type": "string"}},
        "AuthMode": {"type": "string"},
        "DefaultUserSettings": {"type": "object"},
        "DomainSettings": {"type": "object"},
        "AppNetworkAccessType": {"type": "string"}
    }
}


USER_PROFILE_CONFIG_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["UserProfiles"],
    "properties": {
        "UserProfiles": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "UserProfileName",
                    "UserProfileArn",
                    "DomainId"
                ],
                "properties": {
                    "UserProfileName": {"type": "string"},
                    "UserProfileArn": {"type": "string"},
                    "DomainId": {"type": "string"},
                    "UserSettings": {"type": "object"}
                }
            }
        }
    }
}


SPACE_CONFIG_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["Spaces"],
    "properties": {
        "Spaces": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "SpaceName",
                    "SpaceArn",
                    "DomainId",
                    "OwnerUserProfileName"
                ],
                "properties": {
                    "SpaceName": {"type": "string"},
                    "SpaceArn": {"type": "string"},
                    "DomainId": {"type": "string"},
                    "OwnerUserProfileName": {"type": "string"},
                    "SpaceSharingSettings": {"type": "object"},
                    "SpaceSettings": {"type": "object"}
                }
            }
        }
    }
}


RESOURCE_MAPPING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["domain", "user_profiles", "spaces"],
    "properties": {
        "domain": {
            "type": "object",
            "required": ["old", "new"],
            "properties": {
                "old": {"type": "string"},
                "new": {"type": "string"}
            }
        },
        "user_profiles": {
            "type": "object",
            "additionalProperties": {"type": "string"}
        },
        "spaces": {
            "type": "object",
            "additionalProperties": {"type": "string"}
        }
    }
}


STATUS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["timestamp", "domain_id"],
    "properties": {
        "timestamp": {"type": "string"},
        "domain_id": {"type": "string"},
        "s3_bucket": {"type": "string"},
        "s3_prefix": {"type": "string"},
        "total_apps": {"type": "integer"},
        "successful_apps": {"type": "integer"},
        "failed_apps": {"type": "array"}
    }
}
