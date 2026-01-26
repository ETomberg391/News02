"""
News02 Functions Package

This package contains all the core functionality for the News02 application,
including web server, job scheduling, database management, and more.
"""

__version__ = "0.1.0"
__author__ = "News02 Team"

# Import key modules to make them accessible
from functions.config_manager import ConfigManager
from functions.database import NewsDatabase
from functions.exceptions import (
    ValidationError,
    AuthenticationError,
    RateLimitError,
    DatabaseError,
    LLMError,
    FeedError,
    DigestGenerationError,
    JobSchedulerError,
    ConnectionError,
    APIError,
)
from functions.llm_client import LLMClient
from functions.job_scheduler import JobScheduler
from functions.message_queue import MessageQueue
from functions.monitoring import Monitoring
from functions.feed_discovery import FeedDiscovery
from functions.news_digest_enhanced import NewsDigestEnhanced

__all__ = [
    "ConfigManager",
    "NewsDatabase",
    "ValidationError",
    "AuthenticationError",
    "RateLimitError",
    "DatabaseError",
    "LLMError",
    "FeedError",
    "DigestGenerationError",
    "JobSchedulerError",
    "ConnectionError",
    "APIError",
    "LLMClient",
    "JobScheduler",
    "MessageQueue",
    "Monitoring",
    "FeedDiscovery",
    "NewsDigestEnhanced",
]
