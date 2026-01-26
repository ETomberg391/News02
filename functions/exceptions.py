"""
Custom exceptions for News02 application
"""

class News02Error(Exception):
    """Base exception for News02 application"""
    pass


class ConfigurationError(News02Error):
    """Configuration-related errors"""
    pass


class DatabaseError(News02Error):
    """Database-related errors"""
    pass


class LLMError(News02Error):
    """LLM-related errors"""
    pass


class FeedError(News02Error):
    """RSS feed-related errors"""
    pass


class DigestGenerationError(News02Error):
    """Digest generation errors"""
    pass


class JobSchedulerError(News02Error):
    """Job scheduler errors"""
    pass


class APIError(News02Error):
    """API-related errors"""
    pass


class RateLimitError(LLMError):
    """Rate limit exceeded errors"""
    pass


class AuthenticationError(APIError):
    """Authentication-related errors"""
    pass


class ValidationError(News02Error):
    """Input validation errors"""
    pass


class ConnectionError(News02Error):
    """Connection-related errors"""
    pass
