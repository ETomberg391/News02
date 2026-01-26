"""
Input validation utilities for News02 API endpoints
"""

import re
from typing import Dict, Any, Optional, List
from functions.exceptions import ValidationError


def validate_string_field(value: Any, field_name: str, min_length: int = 1, max_length: int = 255) -> str:
    """Validate a string field
    
    Args:
        value: Value to validate
        field_name: Name of the field (for error messages)
        min_length: Minimum allowed length
        max_length: Maximum allowed length
        
    Returns:
        Validated string value
        
    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")
    
    if not value.strip():
        raise ValidationError(f"{field_name} cannot be empty")
    
    if len(value.strip()) < min_length:
        raise ValidationError(f"{field_name} must be at least {min_length} characters")
    
    if len(value.strip()) > max_length:
        raise ValidationError(f"{field_name} must be at most {max_length} characters")
    
    return value.strip()


def validate_url(url: Any, field_name: str = "URL") -> str:
    """Validate a URL
    
    Args:
        url: URL to validate
        field_name: Name of the field (for error messages)
        
    Returns:
        Validated URL string
        
    Raises:
        ValidationError: If validation fails
    """
    url_str = validate_string_field(url, field_name, min_length=3)
    
    # Basic URL validation
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    if not url_pattern.match(url_str):
        raise ValidationError(f"{field_name} must be a valid URL (http:// or https://)")
    
    return url_str


def validate_time(time_str: Any, field_name: str = "time") -> str:
    """Validate a time string in HH:MM format
    
    Args:
        time_str: Time string to validate
        field_name: Name of the field (for error messages)
        
    Returns:
        Validated time string
        
    Raises:
        ValidationError: If validation fails
    """
    time_str = validate_string_field(time_str, field_name)
    
    # Validate HH:MM format
    time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
    
    if not time_pattern.match(time_str):
        raise ValidationError(f"{field_name} must be in HH:MM format (24-hour)")
    
    return time_str


def validate_recurrence(recurrence: Any, field_name: str = "recurrence") -> str:
    """Validate recurrence pattern
    
    Args:
        recurrence: Recurrence value to validate
        field_name: Name of the field (for error messages)
        
    Returns:
        Validated recurrence string
        
    Raises:
        ValidationError: If validation fails
    """
    recurrence = validate_string_field(recurrence, field_name)
    
    valid_recurrences = ['once', 'daily', 'weekdays', 'weekends']
    
    if recurrence not in valid_recurrences:
        raise ValidationError(
            f"{field_name} must be one of: {', '.join(valid_recurrences)}"
        )
    
    return recurrence


def validate_model_config_name(config_name: Any, field_name: str = "model_config") -> str:
    """Validate model configuration name
    
    Args:
        config_name: Model config name to validate
        field_name: Name of the field (for error messages)
        
    Returns:
        Validated model config name
        
    Raises:
        ValidationError: If validation fails
    """
    config_name = validate_string_field(config_name, field_name)
    
    # Model names should be alphanumeric with underscores and hyphens
    if not re.match(r'^[a-zA-Z0-9_-]+$', config_name):
        raise ValidationError(
            f"{field_name} must contain only letters, numbers, underscores, and hyphens"
        )
    
    return config_name


def validate_integer(value: Any, field_name: str, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    """Validate an integer value
    
    Args:
        value: Value to validate
        field_name: Name of the field (for error messages)
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        
    Returns:
        Validated integer value
        
    Raises:
        ValidationError: If validation fails
    """
    try:
        int_value = int(value)
    except (ValueError, TypeError):
        raise ValidationError(f"{field_name} must be an integer")
    
    if min_value is not None and int_value < min_value:
        raise ValidationError(f"{field_name} must be at least {min_value}")
    
    if max_value is not None and int_value > max_value:
        raise ValidationError(f"{field_name} must be at most {max_value}")
    
    return int_value


def validate_float(value: Any, field_name: str, min_value: Optional[float] = None, max_value: Optional[float] = None) -> float:
    """Validate a float value
    
    Args:
        value: Value to validate
        field_name: Name of the field (for error messages)
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        
    Returns:
        Validated float value
        
    Raises:
        ValidationError: If validation fails
    """
    try:
        float_value = float(value)
    except (ValueError, TypeError):
        raise ValidationError(f"{field_name} must be a number")
    
    if min_value is not None and float_value < min_value:
        raise ValidationError(f"{field_name} must be at least {min_value}")
    
    if max_value is not None and float_value > max_value:
        raise ValidationError(f"{field_name} must be at most {max_value}")
    
    return float_value


def validate_boolean(value: Any, field_name: str) -> bool:
    """Validate a boolean value
    
    Args:
        value: Value to validate
        field_name: Name of the field (for error messages)
        
    Returns:
        Validated boolean value
        
    Raises:
        ValidationError: If validation fails
    """
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        if value.lower() in ('true', '1', 'yes', 'on'):
            return True
        elif value.lower() in ('false', '0', 'no', 'off'):
            return False
    
    if isinstance(value, int):
        if value == 1:
            return True
        elif value == 0:
            return False
    
    raise ValidationError(f"{field_name} must be a boolean value")


def validate_list(value: Any, field_name: str, item_type: type = str) -> List[Any]:
    """Validate a list value
    
    Args:
        value: Value to validate
        field_name: Name of the field (for error messages)
        item_type: Expected type of list items
        
    Returns:
        Validated list
        
    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list")
    
    if not value:
        raise ValidationError(f"{field_name} cannot be empty")
    
    validated_items = []
    for i, item in enumerate(value):
        try:
            if item_type == str:
                validated_items.append(validate_string_field(item, f"{field_name}[{i}]"))
            elif item_type == int:
                validated_items.append(validate_integer(item, f"{field_name}[{i}]"))
            elif item_type == float:
                validated_items.append(validate_float(item, f"{field_name}[{i}]"))
            elif item_type == bool:
                validated_items.append(validate_boolean(item, f"{field_name}[{i}]"))
            else:
                validated_items.append(item)
        except ValidationError as e:
            raise ValidationError(f"Invalid item at index {i}: {str(e)}")
    
    return validated_items


def validate_digest_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate digest generation request
    
    Args:
        data: Request data to validate
        
    Returns:
        Validated request data
        
    Raises:
        ValidationError: If validation fails
    """
    validated = {}
    
    # Validate profile (required)
    if 'profile' not in data:
        raise ValidationError("Missing required field: profile")
    validated['profile'] = validate_string_field(data['profile'], 'profile')
    
    # Validate tts_voice (optional)
    if 'tts_voice' in data and data['tts_voice']:
        validated['tts_voice'] = validate_string_field(data['tts_voice'], 'tts_voice')
    
    return validated


def validate_job_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate job creation request
    
    Args:
        data: Request data to validate
        
    Returns:
        Validated request data
        
    Raises:
        ValidationError: If validation fails
    """
    validated = {}
    
    # Validate name (required)
    if 'name' not in data:
        raise ValidationError("Missing required field: name")
    validated['name'] = validate_string_field(data['name'], 'name')
    
    # Validate time (required)
    if 'time' not in data:
        raise ValidationError("Missing required field: time")
    validated['time'] = validate_time(data['time'])
    
    # Validate profile (required)
    if 'profile' not in data:
        raise ValidationError("Missing required field: profile")
    validated['profile'] = validate_string_field(data['profile'], 'profile')
    
    # Validate recurrence (required)
    if 'recurrence' not in data:
        raise ValidationError("Missing required field: recurrence")
    validated['recurrence'] = validate_recurrence(data['recurrence'])
    
    # Validate articles_per_feed (optional, default: 1)
    if 'articles_per_feed' in data:
        validated['articles_per_feed'] = validate_integer(
            data['articles_per_feed'], 'articles_per_feed', min_value=1, max_value=10
        )
    else:
        validated['articles_per_feed'] = 1
    
    # Validate summary_model (optional, default: 'default_model')
    if 'summary_model' in data:
        validated['summary_model'] = validate_model_config_name(data['summary_model'], 'summary_model')
    else:
        validated['summary_model'] = 'default_model'
    
    # Validate broadcast_model (optional, default: 'broadcast_model')
    if 'broadcast_model' in data:
        validated['broadcast_model'] = validate_model_config_name(data['broadcast_model'], 'broadcast_model')
    else:
        validated['broadcast_model'] = 'broadcast_model'
    
    # Validate tts_voice (optional)
    if 'tts_voice' in data and data['tts_voice']:
        validated['tts_voice'] = validate_string_field(data['tts_voice'], 'tts_voice')
    
    # Validate enabled (optional, default: True)
    if 'enabled' in data:
        validated['enabled'] = validate_boolean(data['enabled'], 'enabled')
    else:
        validated['enabled'] = True
    
    return validated


def validate_feed_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate feed save request
    
    Args:
        data: Request data to validate
        
    Returns:
        Validated request data
        
    Raises:
        ValidationError: If validation fails
    """
    validated = {}
    
    # Validate feeds (required)
    if 'feeds' not in data:
        raise ValidationError("Missing required field: feeds")
    
    feeds = validate_list(data['feeds'], 'feeds', str)
    
    # Validate each feed URL
    validated_feeds = []
    for i, feed in enumerate(feeds):
        try:
            validated_feeds.append(validate_url(feed, f'feeds[{i}]'))
        except ValidationError as e:
            raise ValidationError(f"Invalid feed at index {i}: {str(e)}")
    
    validated['feeds'] = validated_feeds
    
    return validated


def validate_profile_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate RSS profile request
    
    Args:
        data: Request data to validate
        
    Returns:
        Validated request data
        
    Raises:
        ValidationError: If validation fails
    """
    validated = {}
    
    # Validate name (required)
    if 'name' not in data:
        raise ValidationError("Missing required field: name")
    validated['name'] = validate_string_field(data['name'], 'name')
    
    # Validate feeds (required)
    if 'feeds' not in data:
        raise ValidationError("Missing required field: feeds")
    
    feeds = validate_list(data['feeds'], 'feeds', str)
    
    # Validate each feed URL
    validated_feeds = []
    for i, feed in enumerate(feeds):
        try:
            validated_feeds.append(validate_url(feed, f'feeds[{i}]'))
        except ValidationError as e:
            raise ValidationError(f"Invalid feed at index {i}: {str(e)}")
    
    validated['feeds'] = validated_feeds
    
    # Validate description (optional)
    if 'description' in data and data['description']:
        validated['description'] = validate_string_field(data['description'], 'description', max_length=500)
    
    return validated


def validate_model_config_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate model configuration request
    
    Args:
        data: Request data to validate
        
    Returns:
        Validated request data
        
    Raises:
        ValidationError: If validation fails
    """
    validated = {}
    
    # Validate name (required)
    if 'name' not in data:
        raise ValidationError("Missing required field: name")
    validated['name'] = validate_model_config_name(data['name'], 'name')
    
    # Validate config (required)
    if 'config' not in data:
        raise ValidationError("Missing required field: config")
    
    config = data['config']
    
    # Validate model (required)
    if 'model' not in config:
        raise ValidationError("Missing required field: config.model")
    validated['model'] = validate_string_field(config['model'], 'config.model')
    
    # Validate api_endpoint (required)
    if 'api_endpoint' not in config:
        raise ValidationError("Missing required field: config.api_endpoint")
    validated['api_endpoint'] = validate_url(config['api_endpoint'], 'config.api_endpoint')
    
    # Validate api_key (optional)
    if 'api_key' in config and config['api_key']:
        validated['api_key'] = validate_string_field(config['api_key'], 'config.api_key')
    
    # Validate temperature (optional, default: 0.7)
    if 'temperature' in config:
        validated['temperature'] = validate_float(
            config['temperature'], 'config.temperature', min_value=0.0, max_value=2.0
        )
    else:
        validated['temperature'] = 0.7
    
    # Validate max_tokens (optional, default: 4096)
    if 'max_tokens' in config:
        validated['max_tokens'] = validate_integer(
            config['max_tokens'], 'config.max_tokens', min_value=1, max_value=8192
        )
    else:
        validated['max_tokens'] = 4096
    
    # Validate top_p (optional)
    if 'top_p' in config and config['top_p'] is not None:
        validated['top_p'] = validate_float(
            config['top_p'], 'config.top_p', min_value=0.0, max_value=1.0
        )
    
    return validated
