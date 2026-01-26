import openai
import requests
import logging
import hashlib
import json
import pickle
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable, TypeVar
from pathlib import Path
from functions.config_manager import ModelConfig
from functions.exceptions import LLMError, RateLimitError, ConnectionError

logger = logging.getLogger(__name__)


class LLMSessionCache:
    """Cache for LLM session responses"""
    
    def __init__(self, cache_dir: str = 'data/llm_cache', max_size_mb: int = 100) -> None:
        """Initialize LLM session cache
        
        Args:
            cache_dir: Directory to store cache files
            max_size_mb: Maximum cache size in MB
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._cleanup_old_cache()
    
    def _cleanup_old_cache(self) -> None:
        """Clean up old cache files if cache is too large"""
        try:
            cache_files = list(self.cache_dir.glob('*.cache'))
            if not cache_files:
                return
            
            # Sort by modification time (oldest first)
            cache_files.sort(key=lambda x: x.stat().st_mtime)
            
            current_size = sum(f.stat().st_size for f in cache_files)
            
            # Remove oldest files until under limit
            while current_size > self.max_size_bytes and cache_files:
                oldest = cache_files.pop(0)
                current_size -= oldest.stat().st_size
                oldest.unlink()
                logger.debug(f"Removed old cache file: {oldest.name}")
                
        except Exception as e:
            logger.warning(f"Cache cleanup failed: {e}")
    
    def _get_cache_key(self, messages: List[Dict[str, Any]], model_config: ModelConfig) -> str:
        """Generate cache key from messages and model config
        
        Args:
            messages: List of message dictionaries
            model_config: Model configuration
            
        Returns:
            Cache key string
        """
        # Create a deterministic key based on messages and model config
        key_data = {
            'messages': messages,
            'model': model_config.model,
            'temperature': model_config.temperature,
            'max_tokens': model_config.max_tokens,
            'top_p': model_config.top_p
        }
        
        # Convert to JSON string and hash
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, messages: List[Dict[str, Any]], model_config: ModelConfig) -> Optional[str]:
        """Get cached response if available
        
        Args:
            messages: List of message dictionaries
            model_config: Model configuration
            
        Returns:
            Cached response or None if not found
        """
        try:
            cache_key = self._get_cache_key(messages, model_config)
            cache_file = self.cache_dir / f"{cache_key}.cache"
            
            if cache_file.exists():
                # Check if cache is still valid (24 hours)
                cache_age = time.time() - cache_file.stat().st_mtime
                if cache_age < 24 * 3600:  # 24 hours
                    with open(cache_file, 'rb') as f:
                        cached_data = pickle.load(f)
                    logger.debug(f"Cache hit: {cache_key[:8]}...")
                    return cached_data['response']
                else:
                    # Cache expired
                    cache_file.unlink()
                    logger.debug(f"Cache expired: {cache_key[:8]}...")
        except Exception as e:
            logger.warning(f"Cache read failed: {e}")
        
        return None
    
    def set(self, messages: List[Dict[str, Any]], model_config: ModelConfig, response: str) -> None:
        """Cache a response
        
        Args:
            messages: List of message dictionaries
            model_config: Model configuration
            response: Response to cache
        """
        try:
            cache_key = self._get_cache_key(messages, model_config)
            cache_file = self.cache_dir / f"{cache_key}.cache"
            
            cached_data = {
                'response': response,
                'timestamp': time.time(),
                'model': model_config.model,
                'temperature': model_config.temperature
            }
            
            with open(cache_file, 'wb') as f:
                pickle.dump(cached_data, f)
            
            logger.debug(f"Cached response: {cache_key[:8]}...")
            
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")
    
    def clear(self) -> None:
        """Clear all cached responses"""
        try:
            cache_files = list(self.cache_dir.glob('*.cache'))
            for cache_file in cache_files:
                cache_file.unlink()
            logger.info(f"Cleared {len(cache_files)} cached responses")
        except Exception as e:
            logger.warning(f"Cache clear failed: {e}")


# Global cache instance
llm_cache = LLMSessionCache()

# Type variable for generic functions
T = TypeVar('T')


def cache_llm_response(max_age_hours: int = 24) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to cache LLM responses
    
    Args:
        max_age_hours: Maximum age of cache in hours
        
    Returns:
        Decorated function with caching
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(messages: List[Dict[str, Any]], model_config: ModelConfig) -> T:
            # Try to get from cache first
            cached_response = llm_cache.get(messages, model_config)
            if cached_response:
                return cached_response
            
            # Call the actual function
            response = func(messages, model_config)
            
            # Cache the response
            llm_cache.set(messages, model_config, response)
            
            return response
        return wrapper
    return decorator

class LLMClient(ABC):
    """Abstract base class for LLM clients"""
    
    @abstractmethod
    def chat_completion(self, messages: List[Dict[str, Any]], model_config: ModelConfig) -> str:
        """Execute a chat completion request
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            model_config: Configuration for the model to use
            
        Returns:
            The generated text response
        """
        pass

class OllamaClient(LLMClient):
    """Ollama LLM client implementation"""
    
    def chat_completion(self, messages: List[Dict[str, Any]], model_config: ModelConfig) -> str:
        """Execute chat completion using Ollama
        
        Args:
            messages: List of message dictionaries
            model_config: Model configuration
            
        Returns:
            Generated text response
            
        Raises:
            Exception: If Ollama API call fails
        """
        try:
            import ollama
            
            # Configure Ollama client if endpoint is not default
            if model_config.api_endpoint != "http://localhost:11434":
                client = ollama.Client(host=model_config.api_endpoint)
            else:
                client = ollama
            
            response = client.chat(
                model=model_config.model,
                messages=messages,
                options={
                    'temperature': model_config.temperature,
                    'num_predict': model_config.max_tokens
                }
            )
            return response['message']['content']
            
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            raise LLMError(f"Ollama API error: {str(e)}") from e

class OpenAICompatibleClient(LLMClient):
    """OpenAI-compatible LLM client implementation"""
    
    def chat_completion(self, messages: List[Dict[str, Any]], model_config: ModelConfig) -> str:
        """Execute chat completion using OpenAI-compatible API
        
        Args:
            messages: List of message dictionaries
            model_config: Model configuration
            
        Returns:
            Generated text response
            
        Raises:
            Exception: If API call fails
        """
        try:
            client = openai.OpenAI(
                base_url=model_config.api_endpoint,
                api_key=model_config.api_key
            )
            
            kwargs = {
                'model': model_config.model,
                'messages': messages,
                'temperature': model_config.temperature,
                'max_tokens': model_config.max_tokens
            }
            
            if model_config.top_p is not None:
                kwargs['top_p'] = model_config.top_p
            
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"OpenAI Compatible API error: {e}")
            raise LLMError(f"OpenAI Compatible API error: {str(e)}") from e

class GeminiClient(LLMClient):
    """Gemini LLM client with intelligent rate limiting"""
    
    def __init__(self) -> None:
        """Initialize Gemini client with rate limiting state"""
        self.last_request_time: float = 0
        self.request_count: int = 0
        self.reset_time: float = 0
        
    def chat_completion(self, messages: List[Dict[str, Any]], model_config: ModelConfig) -> str:
        """Execute chat completion using Gemini with rate limiting
        
        Args:
            messages: List of message dictionaries
            model_config: Model configuration
            
        Returns:
            Generated text response
            
        Raises:
            Exception: If API call fails or rate limit exceeded
        """
        import time
        
        # Implement rate limiting for Gemini free tier (10 requests per minute)
        current_time = time.time()
        
        # Reset counter every minute
        if current_time - self.reset_time >= 60:
            self.request_count = 0
            self.reset_time = current_time
            logger.info("🔄 Gemini rate limit counter reset")
        
        # If we're approaching the limit, add delay
        if self.request_count >= 8:  # Be conservative, start slowing at 8/10
            wait_time = 60 - (current_time - self.reset_time) + 5  # Wait until reset + buffer
            if wait_time > 0:
                logger.warning(f"🐌 Approaching Gemini rate limit. Waiting {wait_time:.1f}s to avoid 429 errors...")
                time.sleep(wait_time)
                # Reset after waiting
                self.request_count = 0
                self.reset_time = time.time()
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Use OpenAI-compatible endpoint for Gemini
                client = openai.OpenAI(
                    base_url=model_config.api_endpoint,
                    api_key=model_config.api_key
                )
                
                kwargs = {
                    'model': model_config.model,
                    'messages': messages,
                    'temperature': model_config.temperature,
                    'max_tokens': model_config.max_tokens
                }
                
                if model_config.top_p is not None:
                    kwargs['top_p'] = model_config.top_p
                
                response = client.chat.completions.create(**kwargs)
                self.request_count += 1
                self.last_request_time = time.time()
                
                logger.debug(f"✅ Gemini request successful ({self.request_count}/10 this minute)")
                return response.choices[0].message.content
                
            except Exception as e:
                error_str = str(e)
                
                # Check for rate limit error (429)
                if "429" in error_str or "rate limit" in error_str.lower() or "quota" in error_str.lower():
                    # Extract retry delay from error if available
                    retry_delay = 30  # Default to 30 seconds
                    
                    if "retryDelay" in error_str:
                        import re
                        delay_match = re.search(r'retryDelay.*?(\d+)s', error_str)
                        if delay_match:
                            retry_delay = int(delay_match.group(1)) + 5  # Add 5s buffer
                    
                    if attempt < max_retries - 1:
                        logger.warning(f"🚫 Gemini rate limit hit (429). Waiting {retry_delay}s before retry {attempt + 1}/{max_retries}")
                        logger.info("💡 Tip: Consider reducing MAX_ARTICLES_PER_FEED to avoid rate limits")
                        time.sleep(retry_delay)
                        
                        # Reset rate limiting counters after delay
                        self.request_count = 0
                        self.reset_time = time.time()
                        continue
                    else:
                        logger.error(f"❌ Gemini rate limit exceeded after {max_retries} attempts")
                        raise RateLimitError(f"Gemini rate limit exceeded. Try again in a few minutes or reduce MAX_ARTICLES_PER_FEED setting.")
                
                # For other errors, log and retry with shorter delay
                elif attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(f"🔄 Gemini API error (attempt {attempt + 1}/{max_retries}): {e}")
                    logger.info(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"❌ Gemini API error after {max_retries} attempts: {e}")
                    raise LLMError(f"Gemini API error after {max_retries} attempts: {str(e)}") from e
        
        raise LLMError("Max retries exceeded")

class LLMFactory:
    """Factory for creating LLM client instances"""
    
    _gemini_client: Optional[GeminiClient] = None  # Singleton to maintain rate limiting state
    
    @staticmethod
    def create_client(provider: str) -> LLMClient:
        """Create an LLM client for the specified provider
        
        Args:
            provider: Name of the LLM provider ('ollama', 'openai_compatible', or 'gemini')
            
        Returns:
            LLMClient instance for the specified provider
            
        Raises:
            ValueError: If provider is not supported
        """
        if provider == 'ollama':
            return OllamaClient()
        elif provider == 'openai_compatible':
            return OpenAICompatibleClient()
        elif provider == 'gemini':
            # Use singleton pattern to maintain rate limiting state across requests
            if LLMFactory._gemini_client is None:
                LLMFactory._gemini_client = GeminiClient()
                logger.info("🎯 Initialized Gemini client with intelligent rate limiting")
            return LLMFactory._gemini_client
        else:
            raise LLMError(f"Unsupported LLM provider: {provider}")

def retry_with_backoff(max_retries: int = 3, backoff_factor: int = 2) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for retry logic with exponential backoff
    
    Args:
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for exponential backoff
        
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> Optional[T]:
            import time
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Failed after {max_retries} attempts: {e}")
                        raise LLMError(f"Failed after {max_retries} attempts: {str(e)}") from e
                    wait_time = backoff_factor ** attempt
                    logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
            return None
        return wrapper
    return decorator