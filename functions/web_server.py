#!/usr/bin/env python3
"""
News02 Web Interface
Modern dashboard for managing news digest generation
"""

import os
import json
import yaml
import asyncio
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename
import threading
import time
from pathlib import Path
from functions.exceptions import (
    ValidationError, DatabaseError, LLMError, FeedError,
    DigestGenerationError, JobSchedulerError, APIError,
    AuthenticationError, RateLimitError, ConnectionError
)
from functions.validation import (
    validate_digest_request, validate_job_request, validate_feed_request,
    validate_profile_request, validate_model_config_request
)

logger = logging.getLogger(__name__)

# Ensure data directory exists
DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

# Import our modules
from functions.config_manager import config_manager
from functions.database import NewsDatabase
from functions.news_digest_enhanced import (
    load_feeds, fetch_articles, extract_and_summarize_articles,
    generate_broadcast_with_llm, save_digest, text_to_speech
)
from functions.news_cli import test_llm_connection, test_database
from functions.feed_discovery import feed_discovery
from functions.job_scheduler import job_scheduler
from functions.remote_digest_api import remote_api, require_api_key

# Error handling decorator
def handle_api_errors(f):
    """Decorator to handle errors in API endpoints and return consistent error responses"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValidationError as e:
            logger.warning(f"Validation error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 400
        except AuthenticationError as e:
            logger.warning(f"Authentication error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 401
        except RateLimitError as e:
            logger.warning(f"Rate limit error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 429
        except DatabaseError as e:
            logger.error(f"Database error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': 'Database operation failed'}), 500
        except LLMError as e:
            logger.error(f"LLM error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': 'LLM operation failed'}), 500
        except FeedError as e:
            logger.error(f"Feed error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': 'RSS feed operation failed'}), 500
        except DigestGenerationError as e:
            logger.error(f"Digest generation error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': 'Digest generation failed'}), 500
        except JobSchedulerError as e:
            logger.error(f"Job scheduler error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': 'Job scheduler operation failed'}), 500
        except ConnectionError as e:
            logger.error(f"Connection error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': 'Connection failed'}), 500
        except APIError as e:
            logger.error(f"API error in {f.__name__}: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
        except Exception as e:
            logger.error(f"Unexpected error in {f.__name__}: {str(e)}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    return decorated_function


# Helper function to get project root path
def get_project_root():
    """Get the project root directory path"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_output_dir():
    """Get the output directory path"""
    return Path(get_project_root()) / 'output'

# Create Flask app with correct template and static paths relative to project root
project_root = get_project_root()
template_dir = os.path.join(project_root, 'templates')
static_dir = os.path.join(project_root, 'static')

app = Flask(__name__,
           template_folder=template_dir,
           static_folder=static_dir)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'news02-secret-key-change-me')

# Template filters
@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    """Convert timestamp to readable date"""
    return datetime.fromtimestamp(timestamp).strftime('%B %d, %Y')

@app.template_filter('timestamp_to_time')
def timestamp_to_time(timestamp):
    """Convert timestamp to readable time"""
    return datetime.fromtimestamp(timestamp).strftime('%I:%M %p')

@app.template_filter('filesizeformat')
def filesizeformat(num_bytes):
    """Format file size in human readable format"""
    if num_bytes == 0:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"

# Global variables for background tasks
generation_status = {
    'running': False,
    'progress': 0,
    'stage': 'idle',
    'error': None,
    'result_file': None
}

def get_database():
    """Get database instance if enabled"""
    db_config = config_manager.get_database_config()
    if not db_config['enabled']:
        return None
    
    db_path = db_config['path']
    # Ensure directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    return NewsDatabase(db_path)

def extract_sources_from_content(content):
    """Extract source information from digest content"""
    sources = []
    lines = content.split('\n')
    
    # First, try to find the "Article Sources" section we now embed
    in_sources_section = False
    current_article = None
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Look for our embedded "Article Sources" section
        if line == "## Article Sources":
            in_sources_section = True
            continue
            
        if in_sources_section:
            # Pattern: "1. **Title**"
            if line and line[0].isdigit() and '**' in line:
                if current_article:
                    sources.append(current_article)
                
                # Extract title between ** markers
                import re
                title_match = re.search(r'\*\*(.*?)\*\*', line)
                if title_match:
                    title = title_match.group(1)
                    current_article = {
                        'title': title,
                        'url': None,
                        'source': None
                    }
            
            # Pattern: "   - URL: ..."
            elif current_article and line.startswith('- URL:'):
                url = line.replace('- URL:', '').strip()
                current_article['url'] = url
            
            # Pattern: "   - Source: ..."
            elif current_article and line.startswith('- Source:'):
                source = line.replace('- Source:', '').strip()
                current_article['source'] = source
    
    # Add the last article if we were in sources section
    if current_article and in_sources_section:
        sources.append(current_article)
    
    # If we found sources from the embedded section, return them
    if sources:
        return sources
    
    # Fallback: Parse older digest format or broadcast content
    current_article = None
    article_count = 0
    current_source = None
    
    for line in lines:
        line = line.strip()
        
        # Pattern 1: "From source:" headers
        if line.startswith('From ') and line.endswith(':'):
            current_source = line.replace('From ', '').replace(':', '').strip()
            continue
            
        # Pattern 2: Article bullets "- Title: Summary"
        elif line.startswith('- ') and ':' in line:
            if current_article:
                sources.append(current_article)
                
            title_part = line[2:].split(':', 1)[0].strip()
            article_count += 1
            
            current_article = {
                'title': title_part,
                'url': None,
                'source': current_source if current_source else f'Article {article_count}'
            }
            
        # Pattern 3: Headers like "### Title" or "## Title"
        elif line.startswith('###') or line.startswith('##'):
            if current_article:
                sources.append(current_article)
            
            title = line.replace('###', '').replace('##', '').strip()
            article_count += 1
            
            current_article = {
                'title': title,
                'url': None,
                'source': f'Article {article_count}'
            }
        
        # Look for URLs in the content
        elif current_article and ('http' in line or 'Source:' in line):
            import re
            url_match = re.search(r'https?://[^\s]+', line)
            if url_match:
                current_article['url'] = url_match.group()
                
                # Extract domain as source if not already set
                if not current_article['source'] or current_article['source'].startswith('Article '):
                    try:
                        from urllib.parse import urlparse
                        domain = urlparse(current_article['url']).netloc
                        current_article['source'] = domain.replace('www.', '')
                    except:
                        pass
    
    # Add the last article if exists
    if current_article:
        sources.append(current_article)
    
    # If we found actual articles, return them
    if sources and article_count > 0:
        return sources
    
    # If we have some sources from content parsing, return them
    if sources and len(sources) > 0:
        return sources
    
    # Only use database fallback if we found no sources at all from content
    try:
        db = get_database()
        if db:
            import sqlite3
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            
            # Get only very recent processed articles (last 10 minutes) to avoid mixing old digests
            cursor.execute("""
                SELECT title, link, source_feed
                FROM articles
                WHERE processed = TRUE
                AND fetched_at > datetime('now', '-10 minutes')
                ORDER BY fetched_at DESC
                LIMIT 20
            """)
            
            db_articles = cursor.fetchall()
            conn.close()
            
            for title, link, source_feed in db_articles:
                from urllib.parse import urlparse
                domain = urlparse(source_feed).netloc.replace('www.', '')
                sources.append({
                    'title': title,
                    'url': link,
                    'source': domain
                })
                
            if sources:
                return sources
    except:
        pass
    
    # Final fallback: RSS feeds
    try:
        feed_urls = load_feeds()
        for url in feed_urls:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace('www.', '')
            sources.append({
                'title': f'Feed: {domain}',
                'url': url,
                'source': domain
            })
    except:
        pass
    
    return sources

@app.route('/')
def dashboard():
    """Main dashboard"""
    db = get_database()
    
    # Get recent articles and analytics
    recent_articles = []
    feed_analytics = []
    recent_broadcasts = []
    
    if db:
        try:
            recent_articles = db.get_recent_articles_for_dashboard(5)
            feed_analytics = db.get_feed_analytics()[:5]
            
            # Get recent broadcasts from database first
            import sqlite3
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM broadcasts
                ORDER BY created_at DESC
                LIMIT 5
            """)
            columns = [description[0] for description in cursor.description]
            recent_broadcasts = [dict(zip(columns, row)) for row in cursor.fetchall()]
            conn.close()
        except Exception as e:
            flash(f"Database error: {e}", 'error')
    
    # If no broadcasts in database, get from output folder
    if not recent_broadcasts:
        from pathlib import Path
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = Path(project_root) / 'output'
        if output_dir.exists():
            # Get all mp3 files and create broadcast entries
            # Support both old format (digest_*.mp3) and new profile format (Profile_*.mp3)
            mp3_files = list(output_dir.glob('digest_*.mp3')) + list(output_dir.glob('*_20*.mp3'))
            mp3_files = sorted(mp3_files, key=lambda x: x.stat().st_mtime, reverse=True)
            recent_broadcasts = []
            processed_files = set()  # Track processed files to avoid duplicates
            
            for mp3_file in mp3_files[:10]:  # Get more files initially to filter duplicates
                # Skip if we've already processed this file
                if mp3_file.name in processed_files:
                    continue
                
                processed_files.add(mp3_file.name)
                
                # Get corresponding markdown file
                md_file = mp3_file.with_suffix('.md')
                if md_file.exists():
                    recent_broadcasts.append({
                        'created_at': datetime.fromtimestamp(mp3_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                        'audio_path': str(mp3_file),
                        'file_path': str(md_file),
                        'model_used': 'File-based',
                        'article_count': 'N/A'  # Could parse from file if needed
                    })
                    
                    # Stop once we have 5 unique broadcasts
                    if len(recent_broadcasts) >= 5:
                        break
    
    return render_template('dashboard.html',
                         recent_articles=recent_articles,
                         feed_analytics=feed_analytics,
                         recent_broadcasts=recent_broadcasts,
                         generation_status=generation_status)

@app.route('/settings')
def settings():
    """Settings page"""
    # Load current settings
    env_vars = {
        'LLM_PROVIDER': os.getenv('LLM_PROVIDER', 'ollama'),
        'OLLAMA_BASE_URL': os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434'),
        'OPENAI_API_BASE': os.getenv('OPENAI_API_BASE', ''),
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY', ''),
        'GEMINI_API_KEY': os.getenv('GEMINI_API_KEY', ''),
        'SUMMARY_MODEL_CONFIG': os.getenv('SUMMARY_MODEL_CONFIG', 'default_model'),
        'BROADCAST_MODEL_CONFIG': os.getenv('BROADCAST_MODEL_CONFIG', 'broadcast_model'),
        'TTS_VOICE': os.getenv('TTS_VOICE', 'en-US-GuyNeural'),
        'DATABASE_ENABLED': os.getenv('DATABASE_ENABLED', 'true'),
        'MAX_ARTICLES_PER_FEED': os.getenv('MAX_ARTICLES_PER_FEED', '1')
    }
    
    # Load model configurations
    model_configs = {}
    try:
        model_configs = config_manager.models_config
    except Exception as e:
        flash(f"Error loading model configs: {e}", 'error')
    
    return render_template('settings.html',
                         env_vars=env_vars,
                         model_configs=model_configs)

# Model Configuration Management
@app.route('/api/model_configs', methods=['GET'])
@handle_api_errors
def api_get_model_configs():
    """Get all model configurations"""
    return jsonify({
        'success': True,
        'configs': config_manager.models_config
    })

@app.route('/api/model_configs/<model_name>', methods=['GET'])
@handle_api_errors
def api_get_model_config(model_name):
    """Get a specific model configuration"""
    if model_name not in config_manager.models_config:
        raise ValidationError(f'Model "{model_name}" not found')
    
    config = config_manager.models_config[model_name]
    return jsonify({
        'success': True,
        'config': {
            'model': config.model,
            'api_endpoint': config.api_endpoint,
            'api_key': config.api_key,
            'temperature': config.temperature,
            'max_tokens': config.max_tokens,
            'top_p': config.top_p
        }
    })

@app.route('/api/model_configs', methods=['POST'])
@handle_api_errors
def api_create_model_config():
    """Create a new model configuration"""
    data = request.get_json()
    
    # Validate request data
    validated_data = validate_model_config_request(data)
    
    name = validated_data['name']
    config = validated_data
    
    if name in config_manager.models_config:
        raise ValidationError(f'Model "{name}" already exists')
    
    # Add to YAML file
    config_path = os.getenv('AI_MODELS_CONFIG', 'settings/llm_settings/ai_models.yml')
    
    # Load existing configs
    try:
        with open(config_path, 'r') as f:
            configs = yaml.safe_load(f) or {}
    except FileNotFoundError:
        configs = {}
    
    # Add new config
    configs[name] = {
        'api_endpoint': config['api_endpoint'],
        'api_key': config.get('api_key', ''),
        'model': config['model'],
        'temperature': config.get('temperature', 0.7),
        'max_tokens': config.get('max_tokens', 4096)
    }
    
    if config.get('top_p'):
        configs[name]['top_p'] = config['top_p']
    
    # Save to file
    with open(config_path, 'w') as f:
        yaml.dump(configs, f, default_flow_style=False, sort_keys=True)
    
    # Reload config manager
    config_manager.models_config = config_manager.load_model_configs()
    
    return jsonify({
        'success': True,
        'message': f'Model configuration "{name}" created successfully'
    })

@app.route('/api/model_configs/<model_name>', methods=['PUT'])
@handle_api_errors
def api_update_model_config(model_name):
    """Update an existing model configuration"""
    data = request.get_json()
    
    # Validate request data
    validated_data = validate_model_config_request(data)
    
    new_name = validated_data['name']
    config = validated_data
    
    if model_name not in config_manager.models_config:
        raise ValidationError(f'Model "{model_name}" not found')
    
    # Check if new name conflicts with existing model (unless it's the same model)
    if new_name != model_name and new_name in config_manager.models_config:
        raise ValidationError(f'Model "{new_name}" already exists')
    
    # Update YAML file
    config_path = os.getenv('AI_MODELS_CONFIG', 'settings/llm_settings/ai_models.yml')
    
    # Load existing configs
    with open(config_path, 'r') as f:
        configs = yaml.safe_load(f) or {}
    
    # Remove old config if name changed
    if new_name != model_name:
        del configs[model_name]
    
    # Update/add config
    configs[new_name] = {
        'api_endpoint': config['api_endpoint'],
        'api_key': config.get('api_key', ''),
        'model': config['model'],
        'temperature': config.get('temperature', 0.7),
        'max_tokens': config.get('max_tokens', 4096)
    }
    
    if config.get('top_p'):
        configs[new_name]['top_p'] = config['top_p']
    
    # Save to file
    with open(config_path, 'w') as f:
        yaml.dump(configs, f, default_flow_style=False, sort_keys=True)
    
    # Reload config manager
    config_manager.models_config = config_manager.load_model_configs()
    
    return jsonify({
        'success': True,
        'message': f'Model configuration "{new_name}" updated successfully'
    })

@app.route('/api/model_configs/<model_name>', methods=['DELETE'])
@handle_api_errors
def api_delete_model_config(model_name):
    """Delete a model configuration"""
    if model_name not in config_manager.models_config:
        raise ValidationError(f'Model "{model_name}" not found')
    
    # Update YAML file
    config_path = os.getenv('AI_MODELS_CONFIG', 'settings/llm_settings/ai_models.yml')
    
    # Load existing configs
    with open(config_path, 'r') as f:
        configs = yaml.safe_load(f) or {}
    
    # Delete config
    del configs[model_name]
    
    # Save to file
    with open(config_path, 'w') as f:
        yaml.dump(configs, f, default_flow_style=False, sort_keys=True)
    
    # Reload config manager
    config_manager.models_config = config_manager.load_model_configs()
    
    return jsonify({
        'success': True,
        'message': f'Model configuration "{model_name}" deleted successfully'
    })

@app.route('/feeds')
def feeds():
    """RSS feeds management"""
    try:
        feed_urls = load_feeds()
        db = get_database()
        
        # Get feed statistics if database is available
        feed_stats = {}
        if db:
            analytics = db.get_feed_analytics()
            for stat in analytics:
                feed_stats[stat['source_feed']] = stat
                
    except Exception as e:
        flash(f"Error loading feeds: {e}", 'error')
        feed_urls = []
        feed_stats = {}
    
    return render_template('feeds.html', 
                         feed_urls=feed_urls, 
                         feed_stats=feed_stats)

@app.route('/history')
def history():
    """Generated content history"""
    db = get_database()
    articles = []
    broadcasts = []
    existing_broadcast_files = set()  # Track files already represented in DB
    
    if db:
        try:
            # Get recent articles with summaries
            import sqlite3
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT a.*, s.summary_text, s.model_used, s.created_at as summary_date
                FROM articles a
                LEFT JOIN summaries s ON a.id = s.article_id
                WHERE a.processed = TRUE
                ORDER BY a.fetched_at DESC
                LIMIT 50
            """)
            columns = [description[0] for description in cursor.description]
            articles = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # Get broadcasts
            cursor.execute("""
                SELECT * FROM broadcasts
                ORDER BY created_at DESC
                LIMIT 20
            """)
            columns = [description[0] for description in cursor.description]
            broadcasts = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # Track which files are already represented in the database
            for broadcast in broadcasts:
                if broadcast.get('file_path'):
                    from pathlib import Path
                    file_path = Path(broadcast['file_path'])
                    # Add both the full name and stem (without extension) for better matching
                    existing_broadcast_files.add(file_path.name)
                    existing_broadcast_files.add(file_path.stem)
                    # Also add any timestamp-based variations
                    if 'digest_' in file_path.name:
                        existing_broadcast_files.add(file_path.name)
            
            conn.close()
        except Exception as e:
            flash(f"Database error: {e}", 'error')
    
    # Add file-based broadcasts only if they're not already in the database
    from pathlib import Path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = Path(project_root) / 'output'
    if output_dir.exists():
        # Get all markdown and audio files
        md_files = list(output_dir.glob('digest_*.md')) + list(output_dir.glob('*_20*.md'))
        file_broadcasts = []
        processed_files = set()  # Track files we've already processed to avoid duplicates
        
        for md_file in sorted(md_files, key=lambda x: x.stat().st_mtime, reverse=True):
            # Skip if this file is already represented in database broadcasts
            # Check both the full filename and stem for better matching
            if (md_file.name in existing_broadcast_files or
                md_file.stem in existing_broadcast_files):
                continue
            
            # Skip if we've already processed this file (prevent duplicates within file-based)
            if md_file.name in processed_files:
                continue
            
            processed_files.add(md_file.name)
                
            mp3_file = md_file.with_suffix('.mp3')
            
            # Extract article count from file if possible
            article_count = 'N/A'
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Look for article count in metadata
                for line in content.split('\n')[:10]:
                    if 'Articles Processed:' in line:
                        article_count = line.split(':')[1].strip()
                        break
            except:
                pass
            
            file_broadcasts.append({
                'id': f'file_{md_file.stem}',
                'broadcast_text': f'File-based broadcast: {md_file.name}',
                'model_used': 'File-based',
                'article_count': article_count,
                'created_at': datetime.fromtimestamp(md_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'file_path': str(md_file),
                'audio_path': str(mp3_file) if mp3_file.exists() else None
            })
        
        # Add file-based broadcasts to the list (limit total to 20)
        broadcasts.extend(file_broadcasts[:max(0, 20 - len(broadcasts))])
        
        # Sort all broadcasts by creation time
        broadcasts.sort(key=lambda x: x['created_at'], reverse=True)
    
    return render_template('history.html',
                         articles=articles,
                         broadcasts=broadcasts)

@app.route('/broadcast/<broadcast_id>')
def view_broadcast(broadcast_id):
    """View full broadcast content"""
    db = get_database()
    broadcast = None
    
    # First try to get from database
    if db and not broadcast_id.startswith('file_'):
        try:
            import sqlite3
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM broadcasts WHERE id = ?
            """, (broadcast_id,))
            
            row = cursor.fetchone()
            if row:
                columns = [description[0] for description in cursor.description]
                broadcast = dict(zip(columns, row))
            
            conn.close()
        except Exception as e:
            flash(f"Database error: {e}", 'error')
    
    # If not found in database or file-based, try to load from file
    if not broadcast:
        from pathlib import Path
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = Path(project_root) / 'output'
        
        # Extract filename from file-based broadcast_id
        if broadcast_id.startswith('file_'):
            filename = broadcast_id[5:]  # Remove 'file_' prefix
        else:
            filename = broadcast_id
        
        # Try both .md extensions
        md_file = output_dir / f"{filename}.md"
        if not md_file.exists():
            # Try finding any matching file
            md_files = list(output_dir.glob('*.md'))
            for f in md_files:
                if filename in f.stem:
                    md_file = f
                    break
        
        if md_file.exists():
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                mp3_file = md_file.with_suffix('.mp3')
                
                # Extract metadata from content
                article_count = 'N/A'
                model_used = 'Unknown'
                for line in content.split('\n')[:15]:
                    if 'Articles Processed:' in line:
                        article_count = line.split(':')[1].strip()
                    elif 'LLM Provider:' in line:
                        model_used = line.split(':')[1].strip()
                
                broadcast = {
                    'id': broadcast_id,
                    'broadcast_text': content,
                    'model_used': model_used,
                    'article_count': article_count,
                    'created_at': datetime.fromtimestamp(md_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'file_path': str(md_file),
                    'audio_path': str(mp3_file) if mp3_file.exists() else None
                }
            except Exception as e:
                flash(f"Error reading broadcast file: {e}", 'error')
                return redirect(url_for('history'))
    
    if not broadcast:
        flash('Broadcast not found', 'error')
        return redirect(url_for('history'))
    
    return render_template('broadcast_view.html', broadcast=broadcast)

@app.route('/share/broadcast/<broadcast_id>')
def share_broadcast(broadcast_id):
    """Generate a shareable link for a broadcast"""
    # For now, just redirect to the broadcast view
    # In the future, this could generate a public sharing link
    return redirect(url_for('view_broadcast', broadcast_id=broadcast_id))

@app.route('/lounge')
def lounge():
    """Lounge area for viewing and playing generated content"""
    # Get recent digest files with correct path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = Path(project_root) / 'output'
    digest_files = []
    seen_files = set()  # Track files we've already processed to avoid duplicates
    
    if output_dir.exists():
        # Get all markdown files (digests) and their corresponding audio files
        # Support both old format (digest_*.md) and new profile format (Profile_*.md)
        md_files = list(output_dir.glob('digest_*.md')) + list(output_dir.glob('*_20*.md'))
        
        # Remove duplicates that might occur from glob patterns
        unique_md_files = []
        for md_file in md_files:
            if md_file.name not in seen_files:
                seen_files.add(md_file.name)
                unique_md_files.append(md_file)
        
        for md_file in sorted(unique_md_files, key=lambda x: x.stat().st_mtime, reverse=True):
            mp3_file = md_file.with_suffix('.mp3')
            
            # Read the content
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Extract sources from content
                sources = extract_sources_from_content(content)
            
                digest_info = {
                    'filename': md_file.name,
                    'audio_filename': mp3_file.name if mp3_file.exists() else None,
                    'created': md_file.stat().st_mtime,
                    'size': md_file.stat().st_size,
                    'content': content,
                    'has_audio': mp3_file.exists(),
                    'sources': sources
                }
                digest_files.append(digest_info)
            except Exception as e:
                print(f"Error reading {md_file}: {e}")
    
    return render_template('lounge.html', digest_files=digest_files)

@app.route('/api/test_connection', methods=['POST'])
@handle_api_errors
def api_test_connection():
    """Test LLM and database connections"""
    data = request.get_json()
    
    # Validate connection type
    if 'type' not in data:
        raise ValidationError("Missing required field: type")
    
    connection_type = data['type']
    
    # Validate connection type is a string
    if not isinstance(connection_type, str):
        raise ValidationError("Type must be a string")
    
    # Validate connection type value
    valid_types = ['llm', 'database']
    if connection_type not in valid_types:
        raise ValidationError(f"Invalid connection type. Must be one of: {', '.join(valid_types)}")
    
    if connection_type == 'llm':
        success = test_web_llm_connection()
        return jsonify({'success': success})
    elif connection_type == 'database':
        success = test_database()
        return jsonify({'success': success})
    else:
        raise ValidationError("Invalid connection type")

@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check endpoint for monitoring and load balancers"""
    import psutil
    import os
    
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'checks': {}
    }
    
    # Check 1: Database connection
    try:
        db = get_database()
        if db:
            # Test database connection
            import sqlite3
            conn = sqlite3.connect(db.db_path, timeout=5)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            conn.close()
            health_status['checks']['database'] = {
                'status': 'healthy',
                'message': 'Database connection successful'
            }
        else:
            health_status['checks']['database'] = {
                'status': 'warning',
                'message': 'Database is disabled'
            }
    except Exception as e:
        health_status['checks']['database'] = {
            'status': 'critical',
            'message': f'Database connection failed: {str(e)}'
        }
        health_status['status'] = 'degraded'
    
    # Check 2: LLM provider connection
    try:
        llm_connected = test_web_llm_connection()
        health_status['checks']['llm_provider'] = {
            'status': 'healthy' if llm_connected else 'critical',
            'message': 'LLM provider connection successful' if llm_connected else 'LLM provider connection failed'
        }
        if not llm_connected:
            health_status['status'] = 'degraded'
    except Exception as e:
        health_status['checks']['llm_provider'] = {
            'status': 'critical',
            'message': f'LLM provider check failed: {str(e)}'
        }
        health_status['status'] = 'degraded'
    
    # Check 3: Disk space
    try:
        disk_usage = psutil.disk_usage('/')
        health_status['checks']['disk_space'] = {
            'status': 'healthy' if disk_usage.percent < 90 else 'warning',
            'message': f'{disk_usage.percent}% used',
            'details': {
                'total_gb': round(disk_usage.total / (1024**3), 2),
                'used_gb': round(disk_usage.used / (1024**3), 2),
                'free_gb': round(disk_usage.free / (1024**3), 2),
                'percent': disk_usage.percent
            }
        }
        if disk_usage.percent >= 95:
            health_status['status'] = 'degraded'
    except Exception as e:
        health_status['checks']['disk_space'] = {
            'status': 'warning',
            'message': f'Could not check disk space: {str(e)}'
        }
    
    # Check 4: Memory usage
    try:
        memory = psutil.virtual_memory()
        health_status['checks']['memory'] = {
            'status': 'healthy' if memory.percent < 90 else 'warning',
            'message': f'{memory.percent}% used',
            'details': {
                'total_gb': round(memory.total / (1024**3), 2),
                'available_gb': round(memory.available / (1024**3), 2),
                'percent': memory.percent
            }
        }
        if memory.percent >= 95:
            health_status['status'] = 'degraded'
    except Exception as e:
        health_status['checks']['memory'] = {
            'status': 'warning',
            'message': f'Could not check memory: {str(e)}'
        }
    
    # Check 5: Job scheduler status
    try:
        scheduler_running = job_scheduler.running
        health_status['checks']['job_scheduler'] = {
            'status': 'healthy' if scheduler_running else 'critical',
            'message': 'Job scheduler is running' if scheduler_running else 'Job scheduler is not running'
        }
        if not scheduler_running:
            health_status['status'] = 'degraded'
    except Exception as e:
        health_status['checks']['job_scheduler'] = {
            'status': 'critical',
            'message': f'Job scheduler check failed: {str(e)}'
        }
        health_status['status'] = 'degraded'
    
    # Check 6: Output directory
    try:
        output_dir = get_output_dir()
        if output_dir.exists():
            # Check write permissions
            test_file = output_dir / '.health_test'
            test_file.touch()
            test_file.unlink()
            health_status['checks']['output_directory'] = {
                'status': 'healthy',
                'message': 'Output directory is writable'
            }
        else:
            health_status['checks']['output_directory'] = {
                'status': 'critical',
                'message': 'Output directory does not exist'
            }
            health_status['status'] = 'degraded'
    except Exception as e:
        health_status['checks']['output_directory'] = {
            'status': 'critical',
            'message': f'Output directory check failed: {str(e)}'
        }
        health_status['status'] = 'degraded'
    
    # Check 7: Configuration files
    try:
        config_files = [
            'settings/llm_settings/ai_models.yml',
            'settings/feeds/feeds.yaml',
            'settings/feeds/profiles.yaml'
        ]
        missing_files = []
        for config_file in config_files:
            if not os.path.exists(config_file):
                missing_files.append(config_file)
        
        if missing_files:
            health_status['checks']['configuration'] = {
                'status': 'warning',
                'message': f'Missing configuration files: {", ".join(missing_files)}'
            }
        else:
            health_status['checks']['configuration'] = {
                'status': 'healthy',
                'message': 'All configuration files present'
            }
    except Exception as e:
        health_status['checks']['configuration'] = {
            'status': 'warning',
            'message': f'Configuration check failed: {str(e)}'
        }
    
    # Check 8: Python environment
    try:
        import sys
        health_status['checks']['python_environment'] = {
            'status': 'healthy',
            'message': f'Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} running',
            'details': {
                'version': f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
                'executable': sys.executable
            }
        }
    except Exception as e:
        health_status['checks']['python_environment'] = {
            'status': 'warning',
            'message': f'Could not check Python environment: {str(e)}'
        }
    
    # Determine overall status
    critical_checks = [check for check in health_status['checks'].values() if check['status'] == 'critical']
    warning_checks = [check for check in health_status['checks'].values() if check['status'] == 'warning']
    
    if critical_checks:
        health_status['status'] = 'critical'
    elif warning_checks:
        health_status['status'] = 'degraded'
    
    # Add summary
    health_status['summary'] = {
        'total_checks': len(health_status['checks']),
        'healthy': len([c for c in health_status['checks'].values() if c['status'] == 'healthy']),
        'warning': len(warning_checks),
        'critical': len(critical_checks)
    }
    
    # Return appropriate HTTP status code
    if health_status['status'] == 'critical':
        return jsonify(health_status), 503
    elif health_status['status'] == 'degraded':
        return jsonify(health_status), 200
    else:
        return jsonify(health_status), 200

def test_web_llm_connection():
    """Test LLM connection using current web settings"""
    try:
        # Reload environment variables from .env file
        from dotenv import load_dotenv
        load_dotenv('.env', override=True)
        
        # Get current provider setting
        provider = os.getenv('LLM_PROVIDER', 'ollama')
        print(f"Testing LLM connection...")
        print(f"Provider: {provider}")
        
        if provider == 'gemini':
            api_key = os.getenv('GEMINI_API_KEY')
            if not api_key:
                print("❌ No Gemini API key configured")
                return False
                
            # Get the configured model from settings
            summary_model = os.getenv('SUMMARY_MODEL_CONFIG', 'gemini_flash')
            
            # Map our config names to actual Gemini model names
            model_mapping = {
                'gemini_flash': 'gemini-1.5-flash',
                'gemini_pro': 'gemini-1.5-pro',
                'default_model': 'gemini-1.5-flash'
            }
            
            actual_model = model_mapping.get(summary_model, 'gemini-1.5-flash')
            
            print(f"Testing Google Gemini connection...")
            print(f"Using model: {actual_model} (from config: {summary_model})")
            
            # Test Gemini connection
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                
                # Test with the configured model
                model = genai.GenerativeModel(actual_model)
                response = model.generate_content("Hello")
                
                print("✅ Gemini connection successful")
                return True
                
            except Exception as e:
                print(f"❌ Gemini connection failed: {e}")
                print(f"   Attempted model: {actual_model}")
                print(f"   Try checking available models at https://ai.google.dev/models")
                return False
                
        elif provider == 'openai':
            api_key = os.getenv('OPENAI_API_KEY')
            api_base = os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1')
            
            if not api_key:
                print("❌ No OpenAI API key configured")
                return False
                
            print(f"Endpoint: {api_base}")
            print(f"Testing OpenAI-compatible connection...")
            
            # Test OpenAI connection
            try:
                import openai
                client = openai.OpenAI(
                    api_key=api_key,
                    base_url=api_base
                )
                
                # Test with a simple completion
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": "Hello"}],
                    max_tokens=10
                )
                
                print("✅ OpenAI connection successful")
                return True
                
            except Exception as e:
                print(f"❌ OpenAI connection failed: {e}")
                return False
                
        elif provider == 'ollama':
            base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
            model = os.getenv('SUMMARY_MODEL_CONFIG', 'mistral:latest')
            
            print(f"Model: {model}")
            print(f"Endpoint: {base_url}")
            
            # Test Ollama connection
            try:
                import ollama
                client = ollama.Client(host=base_url)
                
                # Test with a simple prompt
                response = client.generate(model=model, prompt="Hello", stream=False)
                
                print("✅ Ollama connection successful")
                return True
                
            except Exception as e:
                print(f"❌ Ollama connection failed: {e}")
                return False
        else:
            print(f"❌ Unknown provider: {provider}")
            return False
            
    except Exception as e:
        print(f"❌ Connection test error: {e}")
        return False

@app.route('/api/save_settings', methods=['POST'])
@handle_api_errors
def api_save_settings():
    """Save environment settings"""
    settings_data = request.json
    
    # Validate settings data
    if not settings_data or not isinstance(settings_data, dict):
        raise ValidationError("Settings data must be a valid JSON object")
    
    print(f"Received settings data: {settings_data}")
    
    # Validate each setting key
    for key, value in settings_data.items():
        if not isinstance(key, str):
            raise ValidationError(f"Invalid setting key: {key}")
        
        if not key.startswith('env_'):
            raise ValidationError(f"Invalid setting key format: {key}. Must start with 'env_'")
        
        # Validate value is a string
        if not isinstance(value, str):
            raise ValidationError(f"Setting value for {key} must be a string")
    
    # Update .env file
    env_lines = []
    env_file_path = '.env'
    updated_keys = set()
    
    # Add/update new settings first
    for key, value in settings_data.items():
        env_key = key[4:]  # Remove 'env_' prefix
        env_lines.append(f"{env_key}={value}")
        updated_keys.add(env_key)
        print(f"Setting {env_key} = {value}")
    
    # Read existing .env and preserve non-updated values
    if os.path.exists(env_file_path):
        with open(env_file_path, 'r') as f:
            existing_lines = f.readlines()
        
        # Keep comments and non-updated settings
        for line in existing_lines:
            line = line.strip()
            if line.startswith('#') or ('=' not in line and line):
                env_lines.append(line)
            elif '=' in line:
                key = line.split('=')[0]
                if key not in updated_keys:
                    env_lines.append(line)
    
    # Write updated .env file
    with open(env_file_path, 'w') as f:
        f.write('\n'.join(env_lines) + '\n')
    
    print(f"Updated .env file with {len(updated_keys)} settings")
    
    # Reload environment variables immediately
    from dotenv import load_dotenv
    load_dotenv('.env', override=True)
    
    # Verify the setting was applied
    max_articles = os.getenv('MAX_ARTICLES_PER_FEED')
    print(f"Settings saved and reloaded. MAX_ARTICLES_PER_FEED is now: {max_articles}")
    
    return jsonify({'success': True, 'message': 'Settings saved successfully'})

@app.route('/api/save_feeds', methods=['POST'])
@handle_api_errors
def api_save_feeds():
    """Save RSS feeds"""
    feeds_data = request.json
    
    # Validate request data
    validated_data = validate_feed_request(feeds_data)
    
    # Save to feeds.yaml
    feeds_config = {'feeds': validated_data['feeds']}
    with open('settings/feeds/feeds.yaml', 'w') as f:
        yaml.dump(feeds_config, f, default_flow_style=False)
    
    return jsonify({'success': True, 'message': f'Saved {len(validated_data["feeds"])} feeds'})

@app.route('/api/generate_digest', methods=['POST'])
@handle_api_errors
def api_generate_digest():
    """Start digest generation in background"""
    global generation_status
    
    if generation_status['running']:
        raise ValidationError("Generation already in progress")
    
    # Validate request data
    data = request.get_json()
    validated_data = validate_digest_request(data)
    
    # Start background task
    thread = threading.Thread(target=background_generate_digest)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': 'Generation started'})

@app.route('/api/generation_status')
@handle_api_errors
def api_generation_status():
    """Get current generation status"""
    return jsonify(generation_status)

def background_generate_digest():
    """Background task for digest generation"""
    global generation_status
    
    generation_status['running'] = True
    generation_status['progress'] = 0
    generation_status['stage'] = 'Initializing'
    generation_status['error'] = None
    generation_status['result_file'] = None
    
    try:
        # Stage 1: Load feeds
        generation_status['stage'] = 'Loading RSS feeds'
        generation_status['progress'] = 10
        feed_urls = load_feeds()
        print(f"Loaded {len(feed_urls)} RSS feeds")
        
        # Stage 2: Fetch articles
        generation_status['stage'] = 'Fetching articles'
        generation_status['progress'] = 25
        articles = fetch_articles(feed_urls)
        
        if not articles:
            generation_status['error'] = 'No new articles found. This could be due to: 1) All articles already processed (check database), 2) Network/feed issues, 3) All feeds failing to load'
            return
        
        print(f"Found {len(articles)} new articles to process")
        
        # Stage 3: Process articles
        generation_status['stage'] = f'Processing {len(articles)} articles'
        generation_status['progress'] = 50
        summaries = extract_and_summarize_articles(articles)
        
        if not summaries:
            # Count how many articles were attempted vs successful
            total_articles = len(articles)
            generation_status['error'] = f'No articles successfully processed (0 of {total_articles}). Common causes: 1) 403/404 errors from news sites, 2) Paywall-protected articles, 3) Network connectivity issues. Try different RSS feeds or check the logs for specific errors.'
            return
        
        successful_count = len(summaries)
        total_count = len(articles)
        print(f"🔍 ARTICLE PROCESSING SUMMARY:")
        print(f"   📥 Total articles found: {total_count}")
        print(f"   ✅ Successfully processed: {successful_count}")
        print(f"   ❌ Failed/skipped: {total_count - successful_count}")
        print(f"   📊 Success rate: {(successful_count/total_count)*100:.1f}%")
        
        # Stage 4: Generate broadcast
        generation_status['stage'] = f'Generating broadcast from {successful_count} articles'
        generation_status['progress'] = 75
        broadcast = generate_broadcast_with_llm(summaries)
        
        # Stage 5: Save files
        generation_status['stage'] = 'Saving files'
        generation_status['progress'] = 90
        digest_path = save_digest(broadcast, summaries=summaries)
        
        # Stage 6: Generate audio
        generation_status['stage'] = 'Generating audio'
        generation_status['progress'] = 95
        mp3_path = digest_path.replace('.md', '.mp3')
        
        # Run TTS in async context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(text_to_speech(broadcast, output_path=mp3_path))
        loop.close()
        
        # Complete
        generation_status['stage'] = 'Complete'
        generation_status['progress'] = 100
        generation_status['result_file'] = {
            'digest': digest_path,
            'audio': mp3_path
        }
        
        print(f"Generation completed successfully: {digest_path}")
        
    except Exception as e:
        generation_status['error'] = f"Generation failed: {str(e)}"
        generation_status['stage'] = 'Error'
        print(f"Generation error: {e}")
    finally:
        generation_status['running'] = False

@app.route('/api/download/<file_type>/<path:filename>')
@handle_api_errors
def api_download_file(file_type, filename):
    """Download generated files"""
    if file_type in ['digest', 'audio']:
        # Secure the filename to prevent directory traversal
        safe_filename = secure_filename(filename)
        
        # Use absolute path relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        file_path = os.path.join(project_root, 'output', safe_filename)
        
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            print(f"File not found: {file_path}")
            return jsonify({'error': f'File not found: {safe_filename}'}), 404
    return jsonify({'error': 'Invalid file type'}), 404

@app.route('/api/analytics')
@handle_api_errors
def api_analytics():
    """Get analytics data for dashboard"""
    db = get_database()
    if not db:
        raise ValidationError("Database not enabled")
    
    # Get various analytics
    feed_analytics = db.get_feed_analytics()
    
    # Get daily article counts for the last 7 days
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DATE(fetched_at) as date, COUNT(*) as count
        FROM articles
        WHERE fetched_at >= date('now', '-7 days')
        GROUP BY DATE(fetched_at)
        ORDER BY date
    """)
    daily_counts = [{'date': row[0], 'count': row[1]} for row in cursor.fetchall()]
    
    # Get model usage statistics
    cursor.execute("""
        SELECT model_used, COUNT(*) as count
        FROM summaries
        GROUP BY model_used
        ORDER BY count DESC
    """)
    model_stats = [{'model': row[0], 'count': row[1]} for row in cursor.fetchall()]
    
    # Get articles processed today (before closing connection)
    cursor.execute("""
        SELECT COUNT(*)
        FROM articles
        WHERE DATE(fetched_at) = DATE('now')
        AND processed = TRUE
    """)
    articles_today_count = cursor.fetchone()[0]
    
    conn.close()
    
    # Count actual broadcast files (mp3s) in output folder with deduplication
    broadcast_count = 0
    try:
        from pathlib import Path
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = Path(project_root) / 'output'
        if output_dir.exists():
            # Count both old format and new profile format audio files
            mp3_files = list(output_dir.glob('digest_*.mp3')) + list(output_dir.glob('*_20*.mp3'))
            # Remove duplicates by using a set of file names
            unique_mp3_files = set()
            for mp3_file in mp3_files:
                unique_mp3_files.add(mp3_file.name)
            broadcast_count = len(unique_mp3_files)
    except Exception as e:
        print(f"Error counting broadcast files: {e}")

    return jsonify({
        'feed_analytics': feed_analytics,
        'daily_counts': daily_counts,
        'model_stats': model_stats,
        'articles_today': articles_today_count,
        'broadcast_count': broadcast_count
    })

@app.route('/api/test_feed', methods=['POST'])
@handle_api_errors
def api_test_feed():
    """Test a single RSS feed"""
    data = request.json
    
    # Validate request data
    if not data or not isinstance(data, dict):
        raise ValidationError("Request data must be a valid JSON object")
    
    # Validate URL field
    if 'url' not in data:
        raise ValidationError("Missing required field: url")
    
    feed_url = data['url']
    
    # Validate URL is a string
    if not isinstance(feed_url, str):
        raise ValidationError("URL must be a string")
    
    # Validate URL format
    if not feed_url.startswith(('http://', 'https://')):
        raise ValidationError("URL must start with http:// or https://")
    
    # Test the feed
    import feedparser
    feed = feedparser.parse(feed_url)
    
    if feed.bozo and feed.bozo_exception:
        raise ValidationError(f"Feed parsing error: {feed.bozo_exception}")
    
    article_count = len(feed.entries)
    feed_title = getattr(feed.feed, 'title', 'Unknown Feed')
    
    return jsonify({
        'success': True,
        'articles': article_count,
        'title': feed_title,
        'last_updated': getattr(feed.feed, 'updated', None)
    })

@app.route('/api/cleanup_database', methods=['POST'])
@handle_api_errors
def api_cleanup_database():
    """Clean up old articles from database"""
    data = request.json
    days = data.get('days', 7)  # Default to 7 days
    
    db = get_database()
    if not db:
        raise ValidationError("Database not enabled")
    
    # Delete old articles
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    # Delete articles older than specified days
    cursor.execute("""
        DELETE FROM articles
        WHERE fetched_at < datetime('now', '-{} days')
    """.format(days))
    
    deleted_articles = cursor.rowcount
    
    # Delete orphaned summaries
    cursor.execute("""
        DELETE FROM summaries
        WHERE article_id NOT IN (SELECT id FROM articles)
    """)
    
    deleted_summaries = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'message': f'Cleaned up {deleted_articles} articles and {deleted_summaries} summaries older than {days} days'
    })

@app.route('/api/reset_processed', methods=['POST'])
@handle_api_errors
def api_reset_processed():
    """Reset processed flag for all articles to allow reprocessing"""
    db = get_database()
    if not db:
        raise ValidationError("Database not enabled")
    
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    # Reset processed flag
    cursor.execute("UPDATE articles SET processed = FALSE")
    updated_count = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'message': f'Reset processed flag for {updated_count} articles. They can now be reprocessed.'
    })

@app.route('/api/wipe_database', methods=['POST'])
@handle_api_errors
def api_wipe_database():
    """Nuclear option: Completely wipe the database clean"""
    data = request.json
    confirmation = data.get('confirmation', '')
    
    # Require specific confirmation text
    if confirmation != 'WIPE DATABASE':
        raise ValidationError('Invalid confirmation. Please type "WIPE DATABASE" exactly.')
    
    db = get_database()
    if not db:
        raise ValidationError("Database not enabled")
    
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    # Get counts before deletion
    cursor.execute("SELECT COUNT(*) FROM articles")
    article_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM summaries")
    summary_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM broadcasts")
    broadcast_count = cursor.fetchone()[0]
    
    # Nuclear option: Drop and recreate all tables
    cursor.execute("DROP TABLE IF EXISTS articles")
    cursor.execute("DROP TABLE IF EXISTS summaries")
    cursor.execute("DROP TABLE IF EXISTS broadcasts")
    
    # Recreate tables with correct schema (matching database.py)
    cursor.executescript("""
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT UNIQUE NOT NULL,
            published_date TEXT,
            source_feed TEXT NOT NULL,
            content TEXT,
            content_hash TEXT UNIQUE,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed BOOLEAN DEFAULT FALSE
        );
        
        CREATE TABLE summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            summary_text TEXT NOT NULL,
            model_used TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processing_time_ms INTEGER,
            FOREIGN KEY (article_id) REFERENCES articles (id)
        );
        
        CREATE TABLE broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broadcast_text TEXT NOT NULL,
            model_used TEXT NOT NULL,
            article_count INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            file_path TEXT,
            audio_path TEXT
        );
        
        CREATE TABLE feed_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            name TEXT,
            active BOOLEAN DEFAULT TRUE,
            last_fetched TIMESTAMP,
            fetch_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0
        );
        
        CREATE INDEX idx_articles_link ON articles(link);
        CREATE INDEX idx_articles_processed ON articles(processed);
        CREATE INDEX idx_summaries_article_id ON summaries(article_id);
        CREATE INDEX idx_feed_sources_url ON feed_sources(url);
    """)
    
    conn.commit()
    conn.close()
    
    print(f"🔥 NUCLEAR OPTION EXECUTED: Database completely wiped!")
    print(f"   Removed: {article_count} articles, {summary_count} summaries, {broadcast_count} broadcasts")
    
    return jsonify({
        'success': True,
        'message': f'🔥 NUCLEAR OPTION COMPLETE! Database completely wiped clean. Removed {article_count} articles, {summary_count} summaries, and {broadcast_count} broadcasts. Fresh start achieved.'
    })

@app.route('/api/feed_discovery/categories')
@handle_api_errors
def api_feed_discovery_categories():
    """Get all available feed categories"""
    categories = feed_discovery.get_all_categories()
    stats = feed_discovery.get_feed_stats()
    return jsonify({
        'success': True,
        'categories': categories,
        'stats': stats
    })

@app.route('/api/feed_discovery/feeds/<category_key>')
@handle_api_errors
def api_feed_discovery_feeds(category_key):
    """Get feeds for a specific category"""
    feeds = feed_discovery.get_feeds_by_category(category_key)
    return jsonify({
        'success': True,
        'feeds': feeds,
        'count': len(feeds)
    })

@app.route('/api/feed_discovery/search')
@handle_api_errors
def api_feed_discovery_search():
    """Search feeds with pagination"""
    query = request.args.get('q', '').strip()
    category_filter = request.args.get('category', None)
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 30))
    
    if not query:
        # Return popular feeds if no query
        all_feeds = feed_discovery.get_popular_feeds(999)
    else:
        all_feeds = feed_discovery.search_feeds(query, category_filter)
    
    total_feeds = len(all_feeds)
    
    # Calculate pagination
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    feeds = all_feeds[start_idx:end_idx]
    
    total_pages = (total_feeds + per_page - 1) // per_page
    
    return jsonify({
        'success': True,
        'feeds': feeds,
        'query': query,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_feeds': total_feeds,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
    })

@app.route('/api/feed_discovery/popular')
@handle_api_errors
def api_feed_discovery_popular():
    """Get popular/recommended feeds with pagination"""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 30))
    
    # Get all popular feeds first
    all_feeds = feed_discovery.get_popular_feeds(999)
    total_feeds = len(all_feeds)
    
    # Calculate pagination
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    feeds = all_feeds[start_idx:end_idx]
    
    total_pages = (total_feeds + per_page - 1) // per_page
    
    return jsonify({
        'success': True,
        'feeds': feeds,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_feeds': total_feeds,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
    })

@app.route('/api/feed_discovery/english')
@handle_api_errors
def api_feed_discovery_english():
    """Get English-language feeds with pagination"""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 30))
    
    # Get all English feeds first
    all_feeds = feed_discovery.get_english_feeds(999)  # Get all
    total_feeds = len(all_feeds)
    
    # Calculate pagination
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    feeds = all_feeds[start_idx:end_idx]
    
    total_pages = (total_feeds + per_page - 1) // per_page
    
    categories = feed_discovery.get_english_categories()
    return jsonify({
        'success': True,
        'feeds': feeds,
        'categories': categories,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_feeds': total_feeds,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
    })

@app.route('/api/feed_discovery/english_categories')
@handle_api_errors
def api_feed_discovery_english_categories():
    """Get English-language categories only"""
    categories = feed_discovery.get_english_categories()
    return jsonify({
        'success': True,
        'categories': categories,
        'count': len(categories)
    })

@app.route('/api/feed_discovery/health', methods=['POST'])
@handle_api_errors
def api_feed_discovery_health():
    """Check health of a single feed"""
    data = request.json
    
    # Validate request data
    if not data or not isinstance(data, dict):
        raise ValidationError("Request data must be a valid JSON object")
    
    # Validate URL field
    if 'url' not in data:
        raise ValidationError("Missing required field: url")
    
    feed_url = data['url']
    
    # Validate URL is a string
    if not isinstance(feed_url, str):
        raise ValidationError("URL must be a string")
    
    # Validate URL format
    if not feed_url.startswith(('http://', 'https://')):
        raise ValidationError("URL must start with http:// or https://")
    
    # Get timeout if provided
    timeout = data.get('timeout', 10)
    if not isinstance(timeout, int) or timeout < 1:
        raise ValidationError("Timeout must be a positive integer")
    
    # Check feed health
    health = feed_discovery.check_feed_health(feed_url, timeout)
    score = feed_discovery.calculate_feed_score(feed_url, timeout)
    
    return jsonify({
        'success': True,
        'url': feed_url,
        'health': health,
        'score': score
    })

@app.route('/api/feed_discovery/batch_health', methods=['POST'])
@handle_api_errors
def api_feed_discovery_batch_health():
    """Check health of multiple feeds"""
    data = request.json
    
    # Validate request data
    if not data or not isinstance(data, dict):
        raise ValidationError("Request data must be a valid JSON object")
    
    # Validate feeds field
    if 'feeds' not in data:
        raise ValidationError("Missing required field: feeds")
    
    feeds = data['feeds']
    
    # Validate feeds is a list
    if not isinstance(feeds, list):
        raise ValidationError("Feeds must be a list")
    
    # Validate each feed URL
    for feed_url in feeds:
        if not isinstance(feed_url, str):
            raise ValidationError("Each feed URL must be a string")
        if not feed_url.startswith(('http://', 'https://')):
            raise ValidationError(f"Invalid URL: {feed_url}")
    
    # Get timeout if provided
    timeout = data.get('timeout', 10)
    if not isinstance(timeout, int) or timeout < 1:
        raise ValidationError("Timeout must be a positive integer")
    
    # Check health of all feeds
    results = feed_discovery.batch_check_feeds(feeds, timeout)
    
    # Calculate summary statistics
    healthy_count = sum(1 for r in results if r['health']['status'] == 'healthy')
    unhealthy_count = len(results) - healthy_count
    avg_score = sum(r['score'] for r in results) / len(results) if results else 0
    
    return jsonify({
        'success': True,
        'results': results,
        'summary': {
            'total': len(results),
            'healthy': healthy_count,
            'unhealthy': unhealthy_count,
            'average_score': round(avg_score, 2)
        }
    })

@app.route('/api/feed_discovery/categories/<path:feed_url>')
@handle_api_errors
def api_feed_discovery_feed_categories(feed_url):
    """Get categories for a specific feed"""
    # Validate URL
    if not feed_url.startswith(('http://', 'https://')):
        raise ValidationError("URL must start with http:// or https://")
    
    categories = feed_discovery.get_feed_categories(feed_url)
    
    return jsonify({
        'success': True,
        'url': feed_url,
        'categories': categories,
        'count': len(categories)
    })

@app.route('/api/feed_discovery/custom', methods=['POST'])
@handle_api_errors
def api_feed_discovery_add_custom():
    """Add a custom feed"""
    data = request.json
    
    # Validate request data
    if not data or not isinstance(data, dict):
        raise ValidationError("Request data must be a valid JSON object")
    
    # Validate required fields
    if 'url' not in data:
        raise ValidationError("Missing required field: url")
    
    if 'title' not in data:
        raise ValidationError("Missing required field: title")
    
    feed_url = data['url']
    title = data['title']
    description = data.get('description', '')
    category = data.get('category', 'custom')
    
    # Validate URL
    if not isinstance(feed_url, str):
        raise ValidationError("URL must be a string")
    if not feed_url.startswith(('http://', 'https://')):
        raise ValidationError("URL must start with http:// or https://")
    
    # Validate title
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("Title must be a non-empty string")
    
    # Validate category
    if not isinstance(category, str) or not category.strip():
        raise ValidationError("Category must be a non-empty string")
    
    # Add custom feed
    success = feed_discovery.add_custom_feed(feed_url, title, description, category)
    
    if not success:
        return jsonify({
            'success': False,
            'error': 'Feed already exists or could not be added'
        }), 400
    
    return jsonify({
        'success': True,
        'message': f'Custom feed "{title}" added successfully',
        'url': feed_url,
        'category': category
    })

@app.route('/api/feed_discovery/custom', methods=['DELETE'])
@handle_api_errors
def api_feed_discovery_remove_custom():
    """Remove a custom feed"""
    data = request.json
    
    # Validate request data
    if not data or not isinstance(data, dict):
        raise ValidationError("Request data must be a valid JSON object")
    
    # Validate required fields
    if 'url' not in data:
        raise ValidationError("Missing required field: url")
    
    feed_url = data['url']
    category = data.get('category', 'custom')
    
    # Validate URL
    if not isinstance(feed_url, str):
        raise ValidationError("URL must be a string")
    if not feed_url.startswith(('http://', 'https://')):
        raise ValidationError("URL must start with http:// or https://")
    
    # Validate category
    if not isinstance(category, str) or not category.strip():
        raise ValidationError("Category must be a non-empty string")
    
    # Remove custom feed
    success = feed_discovery.remove_custom_feed(feed_url, category)
    
    if not success:
        return jsonify({
            'success': False,
            'error': 'Feed not found or could not be removed'
        }), 404
    
    return jsonify({
        'success': True,
        'message': 'Custom feed removed successfully',
        'url': feed_url
    })

@app.route('/api/feed_discovery/export', methods=['GET'])
@handle_api_errors
def api_feed_discovery_export():
    """Export feeds in specified format"""
    format = request.args.get('format', 'opml')
    category = request.args.get('category', None)
    
    # Validate format
    if format not in ['opml', 'json', 'csv']:
        raise ValidationError("Format must be one of: opml, json, csv")
    
    try:
        content = feed_discovery.export_feeds(format, category)
        
        # Set appropriate content type and headers
        if format == 'opml':
            content_type = 'application/xml'
            filename = f'news02_feeds_{category or "all"}.opml'
        elif format == 'json':
            content_type = 'application/json'
            filename = f'news02_feeds_{category or "all"}.json'
        else:  # csv
            content_type = 'text/csv'
            filename = f'news02_feeds_{category or "all"}.csv'
        
        return content, 200, {
            'Content-Type': content_type,
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        
    except Exception as e:
        raise APIError(f"Export failed: {str(e)}")

@app.route('/api/feed_discovery/import', methods=['POST'])
@handle_api_errors
def api_feed_discovery_import():
    """Import feeds from uploaded file"""
    # Check if file was uploaded
    if 'file' not in request.files:
        raise ValidationError("No file uploaded")
    
    file = request.files['file']
    
    if file.filename == '':
        raise ValidationError("No file selected")
    
    # Get format from filename or query parameter
    format = request.args.get('format', None)
    if not format:
        # Determine format from filename
        filename = file.filename.lower()
        if filename.endswith('.opml'):
            format = 'opml'
        elif filename.endswith('.json'):
            format = 'json'
        elif filename.endswith('.csv'):
            format = 'csv'
        else:
            raise ValidationError("Unsupported file format. Use .opml, .json, or .csv")
    
    # Validate format
    if format not in ['opml', 'json', 'csv']:
        raise ValidationError("Format must be one of: opml, json, csv")
    
    # Get category from query parameter
    category = request.args.get('category', 'imported')
    
    # Read file content
    try:
        content = file.read().decode('utf-8')
    except Exception as e:
        raise ValidationError(f"Could not read file: {str(e)}")
    
    # Import feeds
    try:
        result = feed_discovery.import_feeds(content, format, category)
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': f'Successfully imported {result["imported_count"]} feeds',
                'imported_count': result['imported_count'],
                'category': result['category']
            })
        else:
            return jsonify({
                'success': False,
                'error': result['error'],
                'imported_count': result['imported_count']
            }), 400
            
    except Exception as e:
        raise APIError(f"Import failed: {str(e)}")

# RSS Profile Management
@app.route('/api/rss_profiles', methods=['GET'])
@handle_api_errors
def api_get_rss_profiles():
    """Get all RSS profiles"""
    profiles_file = Path('settings/feeds/profiles.yaml')
    if profiles_file.exists():
        with open(profiles_file, 'r') as f:
            profiles = yaml.safe_load(f) or {}
    else:
        profiles = {}
    
    return jsonify({
        'success': True,
        'profiles': profiles
    })

@app.route('/api/rss_profiles', methods=['POST'])
@handle_api_errors
def api_save_rss_profile():
    """Save or update an RSS profile"""
    data = request.get_json()
    
    # Validate request data
    validated_data = validate_profile_request(data)
    
    # Ensure profiles directory exists
    profiles_dir = Path('settings/feeds')
    profiles_dir.mkdir(parents=True, exist_ok=True)
    
    profiles_file = profiles_dir / 'profiles.yaml'
    
    # Load existing profiles
    if profiles_file.exists():
        with open(profiles_file, 'r') as f:
            profiles = yaml.safe_load(f) or {}
    else:
        profiles = {}
    
    # Save the profile
    profiles[validated_data['name']] = {
        'description': validated_data.get('description', ''),
        'feeds': validated_data['feeds'],
        'created_at': datetime.now().isoformat(),
        'feed_count': len(validated_data['feeds'])
    }
    
    # Write back to file
    with open(profiles_file, 'w') as f:
        yaml.dump(profiles, f, default_flow_style=False, sort_keys=True)
    
    return jsonify({
        'success': True,
        'message': f'Profile "{validated_data["name"]}" saved successfully',
        'profile': profiles[validated_data['name']]
    })

@app.route('/api/rss_profiles/<profile_name>', methods=['DELETE'])
@handle_api_errors
def api_delete_rss_profile(profile_name):
    """Delete an RSS profile"""
    profiles_file = Path('settings/feeds/profiles.yaml')
    
    if not profiles_file.exists():
        return jsonify({'success': False, 'error': 'No profiles found'})
    
    with open(profiles_file, 'r') as f:
        profiles = yaml.safe_load(f) or {}
    
    if profile_name not in profiles:
        return jsonify({'success': False, 'error': f'Profile "{profile_name}" not found'})
    
    del profiles[profile_name]
    
    with open(profiles_file, 'w') as f:
        yaml.dump(profiles, f, default_flow_style=False, sort_keys=True)
    
    return jsonify({
        'success': True,
        'message': f'Profile "{profile_name}" deleted successfully'
    })

@app.route('/api/rss_profiles/<profile_name>/load', methods=['POST'])
@handle_api_errors
def api_load_rss_profile(profile_name):
    """Load feeds from a profile into the current feed list"""
    profiles_file = Path('settings/feeds/profiles.yaml')
    
    if not profiles_file.exists():
        return jsonify({'success': False, 'error': 'No profiles found'})
    
    with open(profiles_file, 'r') as f:
        profiles = yaml.safe_load(f) or {}
    
    if profile_name not in profiles:
        return jsonify({'success': False, 'error': f'Profile "{profile_name}" not found'})
    
    profile = profiles[profile_name]
    feeds = profile.get('feeds', [])
    
    # Load feeds into the current feeds.yaml
    feeds_file = Path('settings/feeds/feeds.yaml')
    
    # Create feeds directory if it doesn't exist
    feeds_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Save feeds to feeds.yaml
    feeds_config = {'feeds': feeds}
    with open(feeds_file, 'w') as f:
        yaml.dump(feeds_config, f, default_flow_style=False)
    
    return jsonify({
        'success': True,
        'message': f'Loaded {len(feeds)} feeds from profile "{profile_name}"',
        'feeds': feeds,
        'profile': profile
    })

# Jobs page and API routes
@app.route('/jobs')
def jobs():
    """Scheduled jobs management page"""
    return render_template('jobs.html')

@app.route('/api/scheduled_jobs', methods=['GET'])
@handle_api_errors
def api_get_scheduled_jobs():
    """Get all scheduled jobs"""
    jobs = job_scheduler.get_jobs()
    return jsonify({
        'success': True,
        'jobs': jobs
    })

@app.route('/api/scheduled_jobs', methods=['POST'])
@handle_api_errors
def api_create_scheduled_job():
    """Create a new scheduled job"""
    job_data = request.get_json()
    
    # Validate request data
    validated_data = validate_job_request(job_data)
    
    job_id = job_scheduler.create_job(validated_data)
    
    return jsonify({
        'success': True,
        'message': f'Job "{validated_data["name"]}" created successfully',
        'job_id': job_id
    })

@app.route('/api/scheduled_jobs/<job_id>', methods=['GET'])
@handle_api_errors
def api_get_scheduled_job(job_id):
    """Get a specific scheduled job"""
    job = job_scheduler.get_job(job_id)
    if job:
        return jsonify({
            'success': True,
            'job': job
        })
    else:
        return jsonify({'success': False, 'error': 'Job not found'})

@app.route('/api/scheduled_jobs/<job_id>', methods=['DELETE'])
@handle_api_errors
def api_delete_scheduled_job(job_id):
    """Delete a scheduled job"""
    success = job_scheduler.delete_job(job_id)
    if success:
        return jsonify({
            'success': True,
            'message': 'Job deleted successfully'
        })
    else:
        return jsonify({'success': False, 'error': 'Job not found'})

@app.route('/api/scheduled_jobs/<job_id>/enable', methods=['POST'])
@handle_api_errors
def api_enable_scheduled_job(job_id):
    """Enable a scheduled job"""
    success = job_scheduler.toggle_job(job_id, True)
    if success:
        return jsonify({
            'success': True,
            'message': 'Job enabled successfully'
        })
    else:
        return jsonify({'success': False, 'error': 'Job not found'})

@app.route('/api/scheduled_jobs/<job_id>/disable', methods=['POST'])
@handle_api_errors
def api_disable_scheduled_job(job_id):
    """Disable a scheduled job"""
    success = job_scheduler.toggle_job(job_id, False)
    if success:
        return jsonify({
            'success': True,
            'message': 'Job disabled successfully'
        })
    else:
        return jsonify({'success': False, 'error': 'Job not found'})

@app.route('/api/scheduled_jobs/<job_id>/run', methods=['POST'])
@handle_api_errors
def api_run_scheduled_job(job_id):
    """Run a job immediately"""
    success = job_scheduler.run_job_immediately(job_id)
    if success:
        return jsonify({
            'success': True,
            'message': 'Job queued for immediate execution'
        })
    else:
        return jsonify({'success': False, 'error': 'Job not found or already in queue'})

@app.route('/api/job_status')
@handle_api_errors
def api_job_status():
    """Get current job execution status"""
    status = job_scheduler.get_execution_status()
    return jsonify({
        'success': True,
        **status
    })

@app.route('/api/run_jobs_now', methods=['POST'])
@handle_api_errors
def api_run_jobs_now():
    """Run overdue jobs using the simple job executor"""
    import threading
    
    def run_jobs_in_background():
        """Run overdue jobs in background thread"""
        try:
            from functions.simple_job_executor import execute_overdue_jobs
            executed_count = execute_overdue_jobs()
            print(f"Background job execution completed: {executed_count} jobs executed")
        except Exception as e:
            print(f"Error executing jobs: {e}")
            import traceback
            traceback.print_exc()
    
    # Run in background thread
    thread = threading.Thread(target=run_jobs_in_background, daemon=True)
    thread.start()
    
    return jsonify({
        'success': True,
        'message': 'Job execution started. Check console for progress.'
    })

# Remote Digest API endpoints
@app.route('/api/remote_digest_settings', methods=['GET'])
@handle_api_errors
def api_get_remote_digest_settings():
    """Get current remote digest API settings"""
    return jsonify({
        'success': True,
        'settings': {
            'enabled': remote_api.api_enabled,
            'has_api_key': bool(remote_api.api_key),
            'max_per_request': remote_api.max_digests_per_request,
            'rate_limit': remote_api.rate_limit_per_hour
        }
    })

@app.route('/api/remote_digest_settings', methods=['POST'])
@handle_api_errors
def api_save_remote_digest_settings():
    """Save remote digest API settings"""
    data = request.get_json()
    
    enabled = data.get('enabled', False)
    generate_new_key = data.get('generate_new_key', False)
    max_per_request = data.get('max_per_request', 10)
    rate_limit = data.get('rate_limit', 100)
    
    # Generate new API key if requested
    api_key = None
    if generate_new_key or (enabled and not remote_api.api_key):
        api_key = remote_api.generate_api_key()
    
    # Save settings
    remote_api.save_config(
        enabled=enabled,
        api_key=api_key,
        max_per_request=max_per_request,
        rate_limit=rate_limit
    )
    
    response = {
        'success': True,
        'message': 'Remote Digest API settings saved',
        'settings': {
            'enabled': remote_api.api_enabled,
            'has_api_key': bool(remote_api.api_key),
            'max_per_request': remote_api.max_digests_per_request,
            'rate_limit': remote_api.rate_limit_per_hour
        }
    }
    
    if api_key:
        response['new_api_key'] = api_key
    
    return jsonify(response)

# Public Remote Digest API endpoints (require API key)
@app.route('/api/remote/auth', methods=['POST'])
@require_api_key
def api_remote_auth():
    """Authenticate and get server info"""
    try:
        stats = remote_api.get_server_stats()
        return jsonify({
            'authenticated': True,
            'server_info': {
                'name': 'News02 Digest Server',
                'version': '1.0',
                'total_digests': stats['total_text_digests']
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/remote/stats', methods=['GET'])
@require_api_key
def api_remote_stats():
    """Get server statistics"""
    try:
        stats = remote_api.get_server_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/remote/digests', methods=['GET'])
@require_api_key
def api_remote_digests():
    """Get list of available digests, optionally filtered by profile"""
    try:
        limit = request.args.get('limit', type=int)
        order = request.args.get('order', 'newest')
        profile = request.args.get('profile')  # New profile filter parameter
        
        if order not in ['newest', 'oldest']:
            order = 'newest'
        
        digests = remote_api.get_available_digests(limit=limit, order=order, profile_filter=profile)
        
        return jsonify({
            'digests': digests,
            'total_available': len(remote_api.get_available_digests(profile_filter=profile)),
            'profile_filter': profile
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/remote/profiles', methods=['GET'])
@require_api_key
def api_remote_profiles():
    """Get list of available RSS profiles"""
    try:
        profiles = remote_api.get_available_profiles()
        profile_stats = remote_api.get_profile_stats()
        
        return jsonify({
            'profiles': profiles,
            'stats': profile_stats,
            'total_profiles': len(profiles)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/remote/profiles/<profile_name>/digests', methods=['GET'])
@require_api_key
def api_remote_profile_digests(profile_name):
    """Get digests for a specific profile"""
    try:
        limit = request.args.get('limit', type=int)
        order = request.args.get('order', 'newest')
        
        if order not in ['newest', 'oldest']:
            order = 'newest'
        
        digests = remote_api.get_available_digests(limit=limit, order=order, profile_filter=profile_name)
        
        return jsonify({
            'profile': profile_name,
            'digests': digests,
            'total_available': len(remote_api.get_available_digests(profile_filter=profile_name))
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/remote/digest/<digest_id>/text', methods=['GET'])
@require_api_key
def api_remote_digest_text(digest_id):
    """Get digest text content"""
    try:
        content = remote_api.get_digest_content(digest_id, 'text')
        if content is None:
            return jsonify({'error': 'Digest not found'}), 404
        
        return jsonify({
            'digest_id': digest_id,
            'text': content
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/remote/digest/<digest_id>/audio', methods=['GET'])
@require_api_key
def api_remote_digest_audio(digest_id):
    """Download digest audio file"""
    try:
        audio_path = remote_api.get_digest_content(digest_id, 'audio')
        if audio_path is None:
            return jsonify({'error': 'Audio file not found'}), 404
        
        return send_file(audio_path, as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def start_background_job_checker():
    """Start background thread to check for overdue jobs every 5 minutes"""
    import threading
    import time
    
    def job_checker_loop():
        while True:
            try:
                time.sleep(300)  # 5 minutes = 300 seconds
                print("🔍 Checking for overdue jobs...")
                from functions.simple_job_executor import execute_overdue_jobs
                executed_count = execute_overdue_jobs()
                if executed_count > 0:
                    print(f"✅ Executed {executed_count} overdue jobs")
            except Exception as e:
                print(f"❌ Error in background job checker: {e}")
    
    # Start background thread
    checker_thread = threading.Thread(target=job_checker_loop, daemon=True)
    checker_thread.start()
    print("⏰ Background job checker started (5-minute intervals)")

if __name__ == '__main__':
    # Ensure output directory exists
    output_path = os.path.join(get_project_root(), 'output')
    os.makedirs(output_path, exist_ok=True)
    
    # Only start background services in the reloader child process (not the main process)
    # This prevents duplicate services when Flask debug mode creates 2 processes
    if os.getenv('WERKZEUG_RUN_MAIN') == 'true':
        # This is the reloader child process - start services here
        job_scheduler.start_scheduler()
        print("🚀 Job scheduler started in reloader process")
        
        start_background_job_checker()
    else:
        print("🔄 Main process detected - services will start in reloader process")
    
    # Run the Flask app (localhost only for web interface)
    try:
        print("🖥️  Web Interface starting on localhost:5000")
        print("📱 Dashboard: http://localhost:5000")
        print("🔒 Web interface restricted to localhost only")
        print("💡 For API access, run: python api_server.py")
        app.run(host='127.0.0.1', port=5000, debug=True)
    finally:
        # Stop the scheduler when the app shuts down
        if job_scheduler.running:
            job_scheduler.stop_scheduler()
            print("🛑 Job scheduler stopped")