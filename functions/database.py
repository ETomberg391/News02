import sqlite3
import hashlib
import logging
import os
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Generator
from contextlib import contextmanager
from functions.exceptions import DatabaseError, ValidationError

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Connection pool for SQLite database connections"""
    
    def __init__(self, db_path: str, max_connections: int = 10) -> None:
        """Initialize connection pool
        
        Args:
            db_path: Path to SQLite database
            max_connections: Maximum number of connections in the pool
        """
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool: List[sqlite3.Connection] = []
        self.lock = threading.Lock()
        self._initialize_pool()
    
    def _initialize_pool(self) -> None:
        """Initialize the connection pool with connections"""
        for _ in range(self.max_connections):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self.pool.append(conn)
    
    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a connection from the pool
        
        Yields:
            SQLite connection
        """
        with self.lock:
            if not self.pool:
                # Create a new connection if pool is empty
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                conn.row_factory = sqlite3.Row
            else:
                conn = self.pool.pop()
        
        try:
            yield conn
        finally:
            with self.lock:
                self.pool.append(conn)
    
    def close_all(self) -> None:
        """Close all connections in the pool"""
        with self.lock:
            for conn in self.pool:
                conn.close()
            self.pool.clear()

class NewsDatabase:
    """SQLite database manager for News02 application"""
    
    def __init__(self, db_path: str = 'news.db') -> None:
        """Initialize database connection
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path: str = db_path
        # Ensure directory exists before initializing database
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Created database directory: {db_dir}")
        self.connection_pool = ConnectionPool(self.db_path, max_connections=10)
        self.init_database()
        
    def init_database(self) -> None:
        """Initialize database with required tables
         
        Creates tables for articles, summaries, broadcasts, and feed sources
        with appropriate indexes for performance.
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create tables
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS articles (
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
                
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    summary_text TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processing_time_ms INTEGER,
                    FOREIGN KEY (article_id) REFERENCES articles (id)
                );
                
                CREATE TABLE IF NOT EXISTS broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broadcast_text TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    article_count INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_path TEXT,
                    audio_path TEXT
                );
                
                CREATE TABLE IF NOT EXISTS feed_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    name TEXT,
                    active BOOLEAN DEFAULT TRUE,
                    last_fetched TIMESTAMP,
                    fetch_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0
                );
                
                CREATE INDEX IF NOT EXISTS idx_articles_link ON articles(link);
                CREATE INDEX IF NOT EXISTS idx_articles_processed ON articles(processed);
                CREATE INDEX IF NOT EXISTS idx_summaries_article_id ON summaries(article_id);
                CREATE INDEX IF NOT EXISTS idx_feed_sources_url ON feed_sources(url);
            """)
            
            conn.commit()
            logger.info(f"Database initialized: {self.db_path}")
    
    def article_exists(self, link: str) -> bool:
        """Check if article already exists
         
        Args:
            link: URL of the article to check
             
        Returns:
            True if article exists, False otherwise
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM articles WHERE link = ?", (link,))
            exists = cursor.fetchone() is not None
            return exists
    
    def store_article(self, article_data: Dict[str, Any]) -> Optional[int]:
        """Store new article with deduplication
         
        Args:
            article_data: Dictionary containing article information
                Required keys: 'title', 'link', 'source_feed'
                Optional keys: 'published', 'content'
             
        Returns:
            Article ID if stored successfully, None if duplicate
             
        Raises:
            DatabaseError: If database operation fails
            ValidationError: If required fields are missing
        """
        # Validate required fields
        required_fields = ['title', 'link', 'source_feed']
        for field in required_fields:
            if field not in article_data or not article_data[field]:
                raise ValidationError(f"Missing required field: {field}")
        
        if self.article_exists(article_data['link']):
            logger.debug(f"Article already exists: {article_data['link']}")
            return None
        
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            content = article_data.get('content', '')
            content_hash = hashlib.md5(content.encode()).hexdigest() if content else None
            
            try:
                cursor.execute("""
                    INSERT INTO articles
                    (title, link, published_date, source_feed, content, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    article_data['title'],
                    article_data['link'],
                    article_data.get('published', ''),
                    article_data['source_feed'],
                    content,
                    content_hash
                ))
                
                article_id = cursor.lastrowid
                conn.commit()
                logger.debug(f"Stored article: {article_id}")
                return article_id
                
            except sqlite3.IntegrityError as e:
                logger.warning(f"Duplicate content detected: {e}")
                return None
            except sqlite3.Error as e:
                logger.error(f"Database error while storing article: {e}")
                raise DatabaseError(f"Failed to store article: {str(e)}") from e
    
    def get_recent_articles(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get articles from last N hours to avoid reprocessing
         
        Args:
            hours: Number of hours to look back
             
        Returns:
            List of article dictionaries
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM articles
                WHERE fetched_at > datetime('now', '-{} hours')
                AND processed = FALSE
            """.format(hours))
            
            columns = [description[0] for description in cursor.description]
            articles = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return articles
    
    def get_recent_articles_for_dashboard(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get most recent articles for dashboard display (processed or not)
         
        Args:
            limit: Maximum number of articles to return
             
        Returns:
            List of article dictionaries with selected fields
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, link, published_date, source_feed, fetched_at, processed
                FROM articles
                ORDER BY fetched_at DESC
                LIMIT ?
            """, (limit,))
            
            columns = [description[0] for description in cursor.description]
            articles = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return articles
    
    def store_summary(self, article_id: int, summary_text: str, model_used: str, processing_time: int) -> None:
        """Store AI-generated summary
         
        Args:
            article_id: ID of the article being summarized
            summary_text: Generated summary text
            model_used: Name of the model that generated the summary
            processing_time: Processing time in milliseconds
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO summaries
                    (article_id, summary_text, model_used, processing_time_ms)
                    VALUES (?, ?, ?, ?)
                """, (article_id, summary_text, model_used, processing_time))
                
                # Mark article as processed
                cursor.execute("""
                    UPDATE articles SET processed = TRUE WHERE id = ?
                """, (article_id,))
                
                conn.commit()
                logger.debug(f"Stored summary for article: {article_id}")
                
            except Exception as e:
                logger.error(f"Error storing summary: {e}")
                conn.rollback()
                raise DatabaseError(f"Failed to store summary: {str(e)}") from e
    
    def store_broadcast(self, broadcast_text: str, model_used: str, article_count: int,
                       file_path: str, audio_path: str) -> int:
        """Store generated broadcast
         
        Args:
            broadcast_text: Generated broadcast text
            model_used: Name of the model that generated the broadcast
            article_count: Number of articles included
            file_path: Path to the broadcast file
            audio_path: Path to the audio file
             
        Returns:
            Broadcast ID
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO broadcasts
                    (broadcast_text, model_used, article_count, file_path, audio_path)
                    VALUES (?, ?, ?, ?, ?)
                """, (broadcast_text, model_used, article_count, file_path, audio_path))
                
                broadcast_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Stored broadcast: {broadcast_id}")
                return broadcast_id
                
            except Exception as e:
                logger.error(f"Error storing broadcast: {e}")
                conn.rollback()
                raise DatabaseError(f"Failed to store broadcast: {str(e)}") from e
    
    def get_feed_analytics(self) -> List[Dict[str, Any]]:
        """Get performance analytics for RSS feeds
         
        Returns:
            List of analytics dictionaries with feed statistics
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    source_feed,
                    COUNT(*) as article_count,
                    MAX(fetched_at) as last_article,
                    COUNT(DISTINCT DATE(fetched_at)) as active_days
                FROM articles
                GROUP BY source_feed
                ORDER BY article_count DESC
            """)
            
            columns = [description[0] for description in cursor.description]
            analytics = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return analytics
    
    def update_feed_stats(self, feed_url: str, success: bool = True) -> None:
        """Update feed fetch statistics
         
        Args:
            feed_url: URL of the feed to update
            success: Whether the fetch was successful
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # Insert or update feed source
                cursor.execute("""
                    INSERT OR IGNORE INTO feed_sources (url, name)
                    VALUES (?, ?)
                """, (feed_url, feed_url.split('/')[-1]))
                
                if success:
                    cursor.execute("""
                        UPDATE feed_sources
                        SET last_fetched = CURRENT_TIMESTAMP,
                            fetch_count = fetch_count + 1
                        WHERE url = ?
                    """, (feed_url,))
                else:
                    cursor.execute("""
                        UPDATE feed_sources
                        SET error_count = error_count + 1
                        WHERE url = ?
                    """, (feed_url,))
                
                conn.commit()
                
            except Exception as e:
                logger.error(f"Error updating feed stats: {e}")
                raise DatabaseError(f"Failed to update feed stats: {str(e)}") from e
    
    def get_article_by_id(self, article_id: int) -> Optional[Dict[str, Any]]:
        """Get article by ID
         
        Args:
            article_id: ID of the article to retrieve
             
        Returns:
            Article dictionary if found, None otherwise
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
            
            row = cursor.fetchone()
            if row:
                columns = [description[0] for description in cursor.description]
                article = dict(zip(columns, row))
            else:
                article = None
                
            return article
    
    def cleanup_old_data(self, days: int = 30) -> None:
        """Clean up old data beyond specified days
         
        Args:
            days: Number of days to keep data
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    DELETE FROM summaries
                    WHERE article_id IN (
                        SELECT id FROM articles
                        WHERE fetched_at < datetime('now', '-{} days')
                    )
                """.format(days))
                
                cursor.execute("""
                    DELETE FROM articles
                    WHERE fetched_at < datetime('now', '-{} days')
                """.format(days))
                
                cursor.execute("""
                    DELETE FROM broadcasts
                    WHERE created_at < datetime('now', '-{} days')
                """.format(days))
                
                conn.commit()
                logger.info(f"Cleaned up data older than {days} days")
                
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
                conn.rollback()
                raise DatabaseError(f"Failed to cleanup old data: {str(e)}") from e