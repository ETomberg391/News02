# News02 API Documentation

## Overview

News02 provides a comprehensive REST API for managing news digest generation, feed management, job scheduling, and system monitoring. The API is divided into several categories:

- **Digest Management**: Generate and manage news digests
- **Feed Management**: Manage RSS feeds and profiles
- **Job Scheduling**: Schedule and manage automated digest generation
- **System Monitoring**: Health checks and metrics
- **Remote Digest API**: External access to generated digests

## Base URL

```
http://localhost:5000/api
```

## Authentication

Most endpoints require API key authentication. Include the API key in the request headers:

```
X-API-Key: your-api-key-here
```

For endpoints that don't require authentication, see the specific endpoint documentation.

## Rate Limiting

API requests are rate-limited to prevent abuse:
- **Standard requests**: 100 requests per hour per API key
- **Remote Digest API**: Configurable rate limit (default: 100 per hour)

## Response Format

All API responses follow this format:

```json
{
  "success": true,
  "data": {},
  "message": "Optional message"
}
```

For errors:

```json
{
  "success": false,
  "error": "Error message"
}
```

## Endpoints

### Digest Management

#### Generate Digest

**Endpoint**: `POST /api/generate_digest`

**Description**: Start generating a news digest in the background

**Authentication**: Required

**Request Body**:
```json
{
  "profile": "tech",
  "tts_voice": "en-US-GuyNeural",
  "model": "default_model"
}
```

**Parameters**:
- `profile` (string, required): RSS profile name to use
- `tts_voice` (string, optional): TTS voice for audio generation
- `model` (string, optional): Model configuration name

**Response**:
```json
{
  "success": true,
  "message": "Generation started"
}
```

**Error Responses**:
- `400`: Invalid request data
- `409`: Generation already in progress

---

#### Get Generation Status

**Endpoint**: `GET /api/generation_status`

**Description**: Get current digest generation status

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "running": true,
  "progress": 50,
  "stage": "Processing articles",
  "error": null,
  "result_file": null
}
```

**Fields**:
- `running` (boolean): Whether generation is in progress
- `progress` (number): Progress percentage (0-100)
- `stage` (string): Current stage of generation
- `error` (string|null): Error message if failed
- `result_file` (object|null): Result file paths if completed

---

#### Download Generated Files

**Endpoint**: `GET /api/download/<file_type>/<filename>`

**Description**: Download generated digest or audio file

**Authentication**: Required

**Parameters**:
- `file_type`: `digest` or `audio`
- `filename`: Name of the file to download

**Response**: Binary file download

**Example**:
```
GET /api/download/digest/digest_2024-01-15_10-30-00.md
GET /api/download/audio/digest_2024-01-15_10-30-00.mp3
```

---

### Feed Management

#### Get All Feeds

**Endpoint**: `GET /api/feeds`

**Description**: Get all configured RSS feeds

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "feeds": [
    "https://example.com/feed1.xml",
    "https://example.com/feed2.xml"
  ]
}
```

---

#### Save Feeds

**Endpoint**: `POST /api/save_feeds`

**Description**: Save RSS feeds configuration

**Authentication**: Required

**Request Body**:
```json
{
  "feeds": [
    "https://example.com/feed1.xml",
    "https://example.com/feed2.xml"
  ]
}
```

**Response**:
```json
{
  "success": true,
  "message": "Saved 2 feeds"
}
```

---

#### Test Feed

**Endpoint**: `POST /api/test_feed`

**Description**: Test a single RSS feed

**Authentication**: Required

**Request Body**:
```json
{
  "url": "https://example.com/feed.xml"
}
```

**Response**:
```json
{
  "success": true,
  "articles": 15,
  "title": "Example Feed",
  "last_updated": "2024-01-15T10:30:00"
}
```

---

#### Get RSS Profiles

**Endpoint**: `GET /api/rss_profiles`

**Description**: Get all RSS profiles

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "profiles": {
    "tech": {
      "description": "Technology news",
      "feeds": [
        "https://techcrunch.com/feed/",
        "https://arstechnica.com/feed/"
      ],
      "created_at": "2024-01-15T10:30:00",
      "feed_count": 2
    }
  }
}
```

---

#### Save RSS Profile

**Endpoint**: `POST /api/rss_profiles`

**Description**: Save or update an RSS profile

**Authentication**: Required

**Request Body**:
```json
{
  "name": "tech",
  "description": "Technology news",
  "feeds": [
    "https://techcrunch.com/feed/",
    "https://arstechnica.com/feed/"
  ]
}
```

**Response**:
```json
{
  "success": true,
  "message": "Profile \"tech\" saved successfully",
  "profile": {
    "description": "Technology news",
    "feeds": [
      "https://techcrunch.com/feed/",
      "https://arstechnica.com/feed/"
    ],
    "created_at": "2024-01-15T10:30:00",
    "feed_count": 2
  }
}
```

---

#### Delete RSS Profile

**Endpoint**: `DELETE /api/rss_profiles/<profile_name>`

**Description**: Delete an RSS profile

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "message": "Profile \"tech\" deleted successfully"
}
```

---

#### Load RSS Profile

**Endpoint**: `POST /api/rss_profiles/<profile_name>/load`

**Description**: Load feeds from a profile into the current feed list

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "message": "Loaded 2 feeds from profile \"tech\"",
  "feeds": [
    "https://techcrunch.com/feed/",
    "https://arstechnica.com/feed/"
  ],
  "profile": {
    "description": "Technology news",
    "feeds": [
      "https://techcrunch.com/feed/",
      "https://arstechnica.com/feed/"
    ],
    "created_at": "2024-01-15T10:30:00",
    "feed_count": 2
  }
}
```

---

### Job Scheduling

#### Get All Scheduled Jobs

**Endpoint**: `GET /api/scheduled_jobs`

**Description**: Get all scheduled jobs

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "jobs": [
    {
      "id": "abc123",
      "name": "Morning Tech Digest",
      "time": "08:00",
      "profile": "tech",
      "articles_per_feed": 1,
      "summary_model": "default_model",
      "broadcast_model": "broadcast_model",
      "tts_voice": "en-US-GuyNeural",
      "recurrence": "weekdays",
      "enabled": true,
      "created_at": "2024-01-15T10:30:00",
      "last_run": "2024-01-15T08:00:00",
      "next_run": "2024-01-16T08:00:00",
      "run_count": 5,
      "success_count": 5,
      "last_error": null,
      "last_output": null
    }
  ]
}
```

---

#### Create Scheduled Job

**Endpoint**: `POST /api/scheduled_jobs`

**Description**: Create a new scheduled job

**Authentication**: Required

**Request Body**:
```json
{
  "name": "Morning Tech Digest",
  "time": "08:00",
  "profile": "tech",
  "recurrence": "weekdays",
  "articles_per_feed": 1,
  "summary_model": "default_model",
  "broadcast_model": "broadcast_model",
  "tts_voice": "en-US-GuyNeural",
  "enabled": true
}
```

**Parameters**:
- `name` (string, required): Job name
- `time` (string, required): Execution time in HH:MM format
- `profile` (string, required): RSS profile name
- `recurrence` (string, required): `once`, `daily`, `weekdays`, or `weekends`
- `articles_per_feed` (number, optional): Articles per feed (default: 1)
- `summary_model` (string, optional): Summary model config (default: "default_model")
- `broadcast_model` (string, optional): Broadcast model config (default: "broadcast_model")
- `tts_voice` (string, optional): TTS voice (default: from .env)
- `enabled` (boolean, optional): Whether job is enabled (default: true)

**Response**:
```json
{
  "success": true,
  "message": "Job \"Morning Tech Digest\" created successfully",
  "job_id": "abc123"
}
```

---

#### Get Scheduled Job

**Endpoint**: `GET /api/scheduled_jobs/<job_id>`

**Description**: Get a specific scheduled job

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "job": {
    "id": "abc123",
    "name": "Morning Tech Digest",
    "time": "08:00",
    "profile": "tech",
    "recurrence": "weekdays",
    "enabled": true,
    "created_at": "2024-01-15T10:30:00",
    "last_run": "2024-01-15T08:00:00",
    "next_run": "2024-01-16T08:00:00",
    "run_count": 5,
    "success_count": 5,
    "last_error": null,
    "last_output": null
  }
}
```

---

#### Delete Scheduled Job

**Endpoint**: `DELETE /api/scheduled_jobs/<job_id>`

**Description**: Delete a scheduled job

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "message": "Job deleted successfully"
}
```

---

#### Enable Scheduled Job

**Endpoint**: `POST /api/scheduled_jobs/<job_id>/enable`

**Description**: Enable a scheduled job

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "message": "Job enabled successfully"
}
```

---

#### Disable Scheduled Job

**Endpoint**: `POST /api/scheduled_jobs/<job_id>/disable`

**Description**: Disable a scheduled job

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "message": "Job disabled successfully"
}
```

---

#### Run Scheduled Job

**Endpoint**: `POST /api/scheduled_jobs/<job_id>/run`

**Description**: Run a job immediately

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "message": "Job queued for immediate execution"
}
```

---

#### Get Job Status

**Endpoint**: `GET /api/job_status`

**Description**: Get current job execution status

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "status": {
    "running": true,
    "current_job": "Morning Tech Digest",
    "progress": 50,
    "stage": "Processing articles",
    "error": null
  },
  "queue": [
    {
      "id": "abc123",
      "name": "Morning Tech Digest",
      "profile": "tech"
    }
  ]
}
```

---

#### Run Overdue Jobs

**Endpoint**: `POST /api/run_jobs_now`

**Description**: Run all overdue jobs using the simple job executor

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "message": "Job execution started. Check console for progress."
}
```

---

### Model Configuration

#### Get All Model Configurations

**Endpoint**: `GET /api/model_configs`

**Description**: Get all model configurations

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "configs": {
    "default_model": {
      "api_endpoint": "http://127.0.0.1:8000/v1",
      "api_key": "sk-12345",
      "model": "gpt-3.5-turbo",
      "temperature": 0.7,
      "max_tokens": 4096,
      "top_p": 0.95
    }
  }
}
```

---

#### Get Model Configuration

**Endpoint**: `GET /api/model_configs/<model_name>`

**Description**: Get a specific model configuration

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "config": {
    "model": "gpt-3.5-turbo",
    "api_endpoint": "http://127.0.0.1:8000/v1",
    "api_key": "sk-12345",
    "temperature": 0.7,
    "max_tokens": 4096,
    "top_p": 0.95
  }
}
```

---

#### Create Model Configuration

**Endpoint**: `POST /api/model_configs`

**Description**: Create a new model configuration

**Authentication**: Required

**Request Body**:
```json
{
  "name": "custom_model",
  "api_endpoint": "http://127.0.0.1:8000/v1",
  "api_key": "sk-12345",
  "model": "gpt-3.5-turbo",
  "temperature": 0.7,
  "max_tokens": 4096,
  "top_p": 0.95
}
```

**Response**:
```json
{
  "success": true,
  "message": "Model configuration \"custom_model\" created successfully"
}
```

---

#### Update Model Configuration

**Endpoint**: `PUT /api/model_configs/<model_name>`

**Description**: Update an existing model configuration

**Authentication**: Required

**Request Body**:
```json
{
  "name": "custom_model",
  "api_endpoint": "http://127.0.0.1:8000/v1",
  "api_key": "sk-12345",
  "model": "gpt-3.5-turbo",
  "temperature": 0.7,
  "max_tokens": 4096,
  "top_p": 0.95
}
```

**Response**:
```json
{
  "success": true,
  "message": "Model configuration \"custom_model\" updated successfully"
}
```

---

#### Delete Model Configuration

**Endpoint**: `DELETE /api/model_configs/<model_name>`

**Description**: Delete a model configuration

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "message": "Model configuration \"custom_model\" deleted successfully"
}
```

---

### System Settings

#### Save Settings

**Endpoint**: `POST /api/save_settings`

**Description**: Save environment settings

**Authentication**: Required

**Request Body**:
```json
{
  "env_LLM_PROVIDER": "openai_compatible",
  "env_OPENAI_API_BASE": "http://127.0.0.1:8000/v1",
  "env_OPENAI_API_KEY": "sk-12345",
  "env_SUMMARY_MODEL_CONFIG": "default_model",
  "env_BROADCAST_MODEL_CONFIG": "broadcast_model",
  "env_TTS_VOICE": "en-US-GuyNeural",
  "env_DATABASE_ENABLED": "true",
  "env_MAX_ARTICLES_PER_FEED": "1"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Settings saved successfully"
}
```

---

### Database Management

#### Cleanup Database

**Endpoint**: `POST /api/cleanup_database`

**Description**: Clean up old articles from database

**Authentication**: Required

**Request Body**:
```json
{
  "days": 7
}
```

**Parameters**:
- `days` (number, optional): Number of days to keep (default: 7)

**Response**:
```json
{
  "success": true,
  "message": "Cleaned up 15 articles and 30 summaries older than 7 days"
}
```

---

#### Reset Processed Flag

**Endpoint**: `POST /api/reset_processed`

**Description**: Reset processed flag for all articles to allow reprocessing

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "message": "Reset processed flag for 100 articles. They can now be reprocessed."
}
```

---

#### Wipe Database

**Endpoint**: `POST /api/wipe_database`

**Description**: Nuclear option: Completely wipe the database clean

**Authentication**: Required

**Request Body**:
```json
{
  "confirmation": "WIPE DATABASE"
}
```

**Response**:
```json
{
  "success": true,
  "message": "🔥 NUCLEAR OPTION COMPLETE! Database completely wiped clean. Removed 100 articles, 200 summaries, and 50 broadcasts. Fresh start achieved."
}
```

---

### Feed Discovery

#### Get Feed Categories

**Endpoint**: `GET /api/feed_discovery/categories`

**Description**: Get all available feed categories

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "categories": {
    "technology": "Technology",
    "news": "News",
    "sports": "Sports"
  },
  "stats": {
    "total_feeds": 1500,
    "categories": 15
  }
}
```

---

#### Get Feeds by Category

**Endpoint**: `GET /api/feed_discovery/feeds/<category_key>`

**Description**: Get feeds for a specific category

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "feeds": [
    {
      "title": "TechCrunch",
      "url": "https://techcrunch.com/feed/",
      "category": "technology"
    }
  ],
  "count": 50
}
```

---

#### Search Feeds

**Endpoint**: `GET /api/feed_discovery/search`

**Description**: Search feeds with pagination

**Authentication**: Required

**Query Parameters**:
- `q` (string): Search query
- `category` (string, optional): Filter by category
- `page` (number, optional): Page number (default: 1)
- `per_page` (number, optional): Items per page (default: 30)

**Response**:
```json
{
  "success": true,
  "feeds": [
    {
      "title": "TechCrunch",
      "url": "https://techcrunch.com/feed/",
      "category": "technology"
    }
  ],
  "query": "tech",
  "pagination": {
    "page": 1,
    "per_page": 30,
    "total_feeds": 150,
    "total_pages": 5,
    "has_next": true,
    "has_prev": false
  }
}
```

---

#### Get Popular Feeds

**Endpoint**: `GET /api/feed_discovery/popular`

**Description**: Get popular/recommended feeds with pagination

**Authentication**: Required

**Query Parameters**:
- `page` (number, optional): Page number (default: 1)
- `per_page` (number, optional): Items per page (default: 30)

**Response**:
```json
{
  "success": true,
  "feeds": [
    {
      "title": "TechCrunch",
      "url": "https://techcrunch.com/feed/",
      "category": "technology"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 30,
    "total_feeds": 150,
    "total_pages": 5,
    "has_next": true,
    "has_prev": false
  }
}
```

---

#### Get English Feeds

**Endpoint**: `GET /api/feed_discovery/english`

**Description**: Get English-language feeds with pagination

**Authentication**: Required

**Query Parameters**:
- `page` (number, optional): Page number (default: 1)
- `per_page` (number, optional): Items per page (default: 30)

**Response**:
```json
{
  "success": true,
  "feeds": [
    {
      "title": "TechCrunch",
      "url": "https://techcrunch.com/feed/",
      "category": "technology"
    }
  ],
  "categories": {
    "technology": "Technology",
    "news": "News"
  },
  "pagination": {
    "page": 1,
    "per_page": 30,
    "total_feeds": 150,
    "total_pages": 5,
    "has_next": true,
    "has_prev": false
  }
}
```

---

#### Get English Categories

**Endpoint**: `GET /api/feed_discovery/english_categories`

**Description**: Get English-language categories only

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "categories": {
    "technology": "Technology",
    "news": "News"
  },
  "count": 2
}
```

---

### Remote Digest API

#### Get Remote Digest Settings

**Endpoint**: `GET /api/remote_digest_settings`

**Description**: Get current remote digest API settings

**Authentication**: Required

**Response**:
```json
{
  "success": true,
  "settings": {
    "enabled": true,
    "has_api_key": true,
    "max_per_request": 10,
    "rate_limit": 100
  }
}
```

---

#### Save Remote Digest Settings

**Endpoint**: `POST /api/remote_digest_settings`

**Description**: Save remote digest API settings

**Authentication**: Required

**Request Body**:
```json
{
  "enabled": true,
  "generate_new_key": false,
  "max_per_request": 10,
  "rate_limit": 100
}
```

**Response**:
```json
{
  "success": true,
  "message": "Remote Digest API settings saved",
  "settings": {
    "enabled": true,
    "has_api_key": true,
    "max_per_request": 10,
    "rate_limit": 100
  }
}
```

---

### Public Remote Digest API (No Authentication Required)

These endpoints require an API key in the request header.

#### Authenticate

**Endpoint**: `POST /api/remote/auth`

**Description**: Authenticate and get server info

**Authentication**: API Key Required

**Headers**:
```
X-API-Key: your-api-key
```

**Response**:
```json
{
  "authenticated": true,
  "server_info": {
    "name": "News02 Digest Server",
    "version": "1.0",
    "total_digests": 150
  }
}
```

---

#### Get Server Stats

**Endpoint**: `GET /api/remote/stats`

**Description**: Get server statistics

**Authentication**: API Key Required

**Headers**:
```
X-API-Key: your-api-key
```

**Response**:
```json
{
  "total_text_digests": 150,
  "total_audio_digests": 120,
  "total_profiles": 5,
  "total_articles_processed": 1500,
  "last_processed": "2024-01-15T10:30:00"
}
```

---

#### Get Available Digests

**Endpoint**: `GET /api/remote/digests`

**Description**: Get list of available digests, optionally filtered by profile

**Authentication**: API Key Required

**Headers**:
```
X-API-Key: your-api-key
```

**Query Parameters**:
- `limit` (number, optional): Limit number of results
- `order` (string, optional): `newest` or `oldest` (default: newest)
- `profile` (string, optional): Filter by profile name

**Response**:
```json
{
  "digests": [
    {
      "id": "digest_2024-01-15_10-30-00",
      "profile": "tech",
      "created_at": "2024-01-15T10:30:00",
      "article_count": 10,
      "has_audio": true
    }
  ],
  "total_available": 150,
  "profile_filter": "tech"
}
```

---

#### Get Available Profiles

**Endpoint**: `GET /api/remote/profiles`

**Description**: Get list of available RSS profiles

**Authentication**: API Key Required

**Headers**:
```
X-API-Key: your-api-key
```

**Response**:
```json
{
  "profiles": [
    {
      "name": "tech",
      "description": "Technology news",
      "feed_count": 2,
      "digest_count": 50
    }
  ],
  "stats": {
    "tech": {
      "digest_count": 50,
      "last_processed": "2024-01-15T10:30:00"
    }
  },
  "total_profiles": 1
}
```

---

#### Get Profile Digests

**Endpoint**: `GET /api/remote/profiles/<profile_name>/digests`

**Description**: Get digests for a specific profile

**Authentication**: API Key Required

**Headers**:
```
X-API-Key: your-api-key
```

**Query Parameters**:
- `limit` (number, optional): Limit number of results
- `order` (string, optional): `newest` or `oldest` (default: newest)

**Response**:
```json
{
  "profile": "tech",
  "digests": [
    {
      "id": "digest_2024-01-15_10-30-00",
      "profile": "tech",
      "created_at": "2024-01-15T10:30:00",
      "article_count": 10,
      "has_audio": true
    }
  ],
  "total_available": 50
}
```

---

#### Get Digest Text

**Endpoint**: `GET /api/remote/digest/<digest_id>/text`

**Description**: Get digest text content

**Authentication**: API Key Required

**Headers**:
```
X-API-Key: your-api-key
```

**Response**:
```json
{
  "digest_id": "digest_2024-01-15_10-30-00",
  "text": "# News Digest - 01/15/2024\n\nNews Digest - 2024-01-15 10:30:00\n\nGenerated by: News02 Enhanced\nRSS Profile: tech\nLLM Provider: openai_compatible\nArticles Processed: 10\nModels Used:\n- Summary: default_model\n- Broadcast: broadcast_model\n\n---\n\n[Broadcast content here...]"
}
```

---

#### Download Digest Audio

**Endpoint**: `GET /api/remote/digest/<digest_id>/audio`

**Description**: Download digest audio file

**Authentication**: API Key Required

**Headers**:
```
X-API-Key: your-api-key
```

**Response**: Binary audio file (MP3)

---

### System Health

#### Health Check

**Endpoint**: `GET /api/health`

**Description**: Health check endpoint for monitoring and load balancers

**Authentication**: Not Required

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00",
  "checks": {
    "database": {
      "status": "healthy",
      "message": "Database connection successful"
    },
    "llm_provider": {
      "status": "healthy",
      "message": "LLM provider connection successful"
    },
    "disk_space": {
      "status": "healthy",
      "message": "Disk space OK: 45.2% used",
      "details": {
        "total_gb": 100.0,
        "used_gb": 45.2,
        "free_gb": 54.8,
        "percent": 45.2
      }
    },
    "memory": {
      "status": "healthy",
      "message": "Memory OK: 65.3% used",
      "details": {
        "total_gb": 16.0,
        "available_gb": 5.5,
        "percent": 65.3
      }
    },
    "job_scheduler": {
      "status": "healthy",
      "message": "Job scheduler is running"
    },
    "output_directory": {
      "status": "healthy",
      "message": "Output directory is writable"
    },
    "configuration": {
      "status": "healthy",
      "message": "All configuration files present"
    },
    "python_environment": {
      "status": "healthy",
      "message": "Python 3.11.0 running",
      "details": {
        "version": "3.11.0",
        "executable": "/usr/local/bin/python"
      }
    }
  },
  "summary": {
    "total_checks": 8,
    "healthy": 8,
    "warning": 0,
    "critical": 0
  }
}
```

**HTTP Status Codes**:
- `200`: Healthy or degraded
- `503`: Critical

---

#### Test Connection

**Endpoint**: `POST /api/test_connection`

**Description**: Test LLM and database connections

**Authentication**: Required

**Request Body**:
```json
{
  "type": "llm"
}
```

**Parameters**:
- `type` (string, required): `llm` or `database`

**Response**:
```json
{
  "success": true
}
```

---

### Analytics

#### Get Analytics

**Endpoint**: `GET /api/analytics`

**Description**: Get analytics data for dashboard

**Authentication**: Required

**Response**:
```json
{
  "feed_analytics": [
    {
      "source_feed": "https://techcrunch.com/feed/",
      "article_count": 150,
      "last_article": "2024-01-15T10:30:00",
      "active_days": 30
    }
  ],
  "daily_counts": [
    {
      "date": "2024-01-08",
      "count": 15
    }
  ],
  "model_stats": [
    {
      "model": "default_model",
      "count": 150
    }
  ],
  "articles_today": 15,
  "broadcast_count": 120
}
```

---

## Error Codes

| Code | Description |
|------|-------------|
| `400` | Bad Request - Invalid input data |
| `401` | Unauthorized - Missing or invalid API key |
| `403` | Forbidden - Insufficient permissions |
| `404` | Not Found - Resource not found |
| `409` | Conflict - Resource already exists or operation in progress |
| `429` | Too Many Requests - Rate limit exceeded |
| `500` | Internal Server Error - Unexpected server error |
| `503` | Service Unavailable - Service temporarily unavailable |

## WebSocket Events (Optional)

For real-time updates, you can use WebSocket events:

### Events

- `digest_progress`: Real-time progress updates during digest generation
- `job_status`: Job execution status updates
- `system_alert`: System alerts and notifications

### Example WebSocket Connection

```javascript
const ws = new WebSocket('ws://localhost:5000/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Event:', data.event, 'Data:', data.data);
};
```

## Python Client Example

```python
import requests
import json

class News02Client:
    def __init__(self, base_url="http://localhost:5000/api", api_key=None):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {}
        if api_key:
            self.headers['X-API-Key'] = api_key
    
    def generate_digest(self, profile, tts_voice=None, model=None):
        """Generate a news digest"""
        data = {'profile': profile}
        if tts_voice:
            data['tts_voice'] = tts_voice
        if model:
            data['model'] = model
        
        response = requests.post(
            f"{self.base_url}/generate_digest",
            headers=self.headers,
            json=data
        )
        return response.json()
    
    def get_generation_status(self):
        """Get current generation status"""
        response = requests.get(
            f"{self.base_url}/generation_status",
            headers=self.headers
        )
        return response.json()
    
    def get_scheduled_jobs(self):
        """Get all scheduled jobs"""
        response = requests.get(
            f"{self.base_url}/scheduled_jobs",
            headers=self.headers
        )
        return response.json()
    
    def create_scheduled_job(self, name, time, profile, recurrence, **kwargs):
        """Create a scheduled job"""
        data = {
            'name': name,
            'time': time,
            'profile': profile,
            'recurrence': recurrence
        }
        data.update(kwargs)
        
        response = requests.post(
            f"{self.base_url}/scheduled_jobs",
            headers=self.headers,
            json=data
        )
        return response.json()
    
    def get_health(self):
        """Get system health status"""
        response = requests.get(f"{self.base_url}/health")
        return response.json()

# Example usage
client = News02Client(api_key="your-api-key")

# Generate a digest
result = client.generate_digest(profile="tech")
print(result)

# Check status
status = client.get_generation_status()
print(status)

# Create a scheduled job
job = client.create_scheduled_job(
    name="Morning Tech Digest",
    time="08:00",
    profile="tech",
    recurrence="weekdays"
)
print(job)

# Check health
health = client.get_health()
print(health)
```

## JavaScript/Node.js Client Example

```javascript
const axios = require('axios');

class News02Client {
  constructor(baseUrl = 'http://localhost:5000/api', apiKey = null) {
    this.baseUrl = baseUrl;
    this.apiKey = apiKey;
    this.headers = {};
    if (apiKey) {
      this.headers['X-API-Key'] = apiKey;
    }
  }

  async generateDigest(profile, ttsVoice = null, model = null) {
    const data = { profile };
    if (ttsVoice) data.tts_voice = ttsVoice;
    if (model) data.model = model;

    const response = await axios.post(
      `${this.baseUrl}/generate_digest`,
      data,
      { headers: this.headers }
    );
    return response.data;
  }

  async getGenerationStatus() {
    const response = await axios.get(
      `${this.baseUrl}/generation_status`,
      { headers: this.headers }
    );
    return response.data;
  }

  async getScheduledJobs() {
    const response = await axios.get(
      `${this.baseUrl}/scheduled_jobs`,
      { headers: this.headers }
    );
    return response.data;
  }

  async createScheduledJob(name, time, profile, recurrence, options = {}) {
    const data = { name, time, profile, recurrence, ...options };

    const response = await axios.post(
      `${this.baseUrl}/scheduled_jobs`,
      data,
      { headers: this.headers }
    );
    return response.data;
  }

  async getHealth() {
    const response = await axios.get(`${this.baseUrl}/health`);
    return response.data;
  }
}

// Example usage
const client = new News02Client('http://localhost:5000/api', 'your-api-key');

// Generate a digest
client.generateDigest('tech')
  .then(result => console.log(result))
  .catch(error => console.error(error));

// Check status
client.getGenerationStatus()
  .then(status => console.log(status))
  .catch(error => console.error(error));

// Create a scheduled job
client.createScheduledJob(
  'Morning Tech Digest',
  '08:00',
  'tech',
  'weekdays'
)
  .then(job => console.log(job))
  .catch(error => console.error(error));

// Check health
client.getHealth()
  .then(health => console.log(health))
  .catch(error => console.error(error));
```

## cURL Examples

### Generate Digest

```bash
curl -X POST http://localhost:5000/api/generate_digest \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"profile": "tech", "tts_voice": "en-US-GuyNeural"}'
```

### Get Generation Status

```bash
curl -X GET http://localhost:5000/api/generation_status \
  -H "X-API-Key: your-api-key"
```

### Create Scheduled Job

```bash
curl -X POST http://localhost:5000/api/scheduled_jobs \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Morning Tech Digest",
    "time": "08:00",
    "profile": "tech",
    "recurrence": "weekdays",
    "articles_per_feed": 1,
    "summary_model": "default_model",
    "broadcast_model": "broadcast_model",
    "tts_voice": "en-US-GuyNeural",
    "enabled": true
  }'
```

### Get Health

```bash
curl -X GET http://localhost:5000/api/health
```

### Test LLM Connection

```bash
curl -X POST http://localhost:5000/api/test_connection \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"type": "llm"}'
```

### Get Analytics

```bash
curl -X GET http://localhost:5000/api/analytics \
  -H "X-API-Key: your-api-key"
```

### Get Remote Digests (Public API)

```bash
curl -X GET "http://localhost:5000/api/remote/digests?limit=10&order=newest" \
  -H "X-API-Key: your-api-key"
```

### Download Digest Audio

```bash
curl -X GET http://localhost:5000/api/remote/digest/digest_2024-01-15_10-30-00/audio \
  -H "X-API-Key: your-api-key" \
  -o digest_audio.mp3
```

## Best Practices

1. **Rate Limiting**: Respect rate limits and implement exponential backoff
2. **Error Handling**: Always check the `success` field in responses
3. **Polling**: For long-running operations, poll the status endpoint
4. **API Key Security**: Never expose API keys in client-side code
5. **Connection Testing**: Test connections before making requests
6. **Validation**: Validate input data before sending requests
7. **Logging**: Implement proper logging for debugging
8. **Timeouts**: Set appropriate timeouts for API requests

## Troubleshooting

### Common Issues

1. **401 Unauthorized**: Check API key is correct and included in headers
2. **429 Too Many Requests**: Wait before retrying or reduce request frequency
3. **500 Internal Server Error**: Check server logs for details
4. **Generation Fails**: Check LLM provider connection and configuration
5. **Job Not Executing**: Verify job is enabled and scheduler is running

### Debug Mode

Enable debug logging by setting:
```bash
export LOG_LEVEL=DEBUG
```

### Health Check

Always check system health before making requests:
```bash
curl http://localhost:5000/api/health
```

## Version History

- **v1.0.0**: Initial API release
- **v1.1.0**: Added remote digest API
- **v1.2.0**: Added feed discovery endpoints
- **v1.3.0**: Added health check endpoint
- **v1.4.0**: Added model configuration endpoints
- **v1.5.0**: Added analytics endpoints

## Support

For API support or questions:
- Check the [README.md](../README.md) for general usage
- Review the [documents/](../documents/) directory for additional documentation
- Check server logs for detailed error messages
- Ensure all services (database, LLM provider) are running

## License

News02 API is part of the News02 project and is licensed under the MIT License.
