import sqlite3
import json
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Generator
from pathlib import Path
import yaml
import asyncio
import os
import uuid
from contextlib import contextmanager
from functions.exceptions import JobSchedulerError, ValidationError, DatabaseError
import threading
from enum import Enum

logger = logging.getLogger(__name__)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available. Using SQLite-based locking only.")


class JobPriority(Enum):
    """Job priority levels for queue management"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


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


class JobScheduler:
    """Job scheduler for automated digest generation"""
    
    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize job scheduler
         
        Args:
            db_path: Path to jobs database file
        """
        # Use environment variable or default
        self.db_path: str = db_path or os.getenv('JOBS_DATABASE_PATH', 'data/jobs.db')
        self.running: bool = False
        self.current_job: Optional[Dict[str, Any]] = None
        self.job_queue: List[Dict[str, Any]] = []
        self.execution_status: Dict[str, Any] = {
            'running': False,
            'current_job': None,
            'progress': 0,
            'stage': 'idle',
            'error': None
        }
        self.scheduler_thread: Optional[threading.Thread] = None
        self.execution_lock = threading.Lock()  # Lock to prevent concurrent job execution
        self.queue_lock = threading.Lock()  # Lock for job queue operations
        self.worker_id = str(uuid.uuid4())  # Unique ID for this scheduler instance
        self.connection_pool = ConnectionPool(self.db_path, max_connections=10)
        
        # Initialize Redis for distributed locking
        self.redis_client: Optional[redis.Redis] = None
        self.redis_available: bool = False
        self._init_redis()
        
        # Retry configuration
        self.max_retries = 3
        self.backoff_factor = 2
        
        # Priority queue configuration
        self.priority_queues = {
            JobPriority.CRITICAL: [],
            JobPriority.HIGH: [],
            JobPriority.NORMAL: [],
            JobPriority.LOW: []
        }
        
        self.init_database()
    
    def _init_redis(self) -> None:
        """Initialize Redis client for distributed locking"""
        if not REDIS_AVAILABLE:
            logger.warning("Redis not installed. Using SQLite-based locking only.")
            return
        
        try:
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', '6379'))
            redis_db = int(os.getenv('REDIS_DB', '0'))
            redis_password = os.getenv('REDIS_PASSWORD', None)
            
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                max_connections=10
            )
            
            # Test connection
            self.redis_client.ping()
            self.redis_available = True
            logger.info(f"Redis client initialized: {redis_host}:{redis_port}/{redis_db}")
            
        except Exception as e:
            logger.warning(f"Failed to initialize Redis: {e}. Using SQLite-based locking only.")
            self.redis_available = False
        
    def init_database(self) -> None:
        """Initialize the jobs database
         
        Creates tables for scheduled jobs and job executions with appropriate indexes.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                time TEXT NOT NULL,
                profile TEXT NOT NULL,
                articles_per_feed INTEGER DEFAULT 1,
                summary_model TEXT DEFAULT 'default_model',
                broadcast_model TEXT DEFAULT 'broadcast_model',
                tts_voice TEXT DEFAULT NULL,
                recurrence TEXT DEFAULT 'once',
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_run TIMESTAMP,
                next_run TIMESTAMP,
                run_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                last_error TEXT,
                last_output TEXT,
                priority INTEGER DEFAULT 2,
                max_retries INTEGER DEFAULT 3,
                depends_on TEXT DEFAULT '[]'
            );
            
            CREATE TABLE IF NOT EXISTS job_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                status TEXT DEFAULT 'running',
                error_message TEXT,
                output_file TEXT,
                audio_file TEXT,
                article_count INTEGER,
                worker_id TEXT,
                retry_count INTEGER DEFAULT 0,
                FOREIGN KEY (job_id) REFERENCES scheduled_jobs (id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_jobs_next_run ON scheduled_jobs(next_run);
            CREATE INDEX IF NOT EXISTS idx_jobs_enabled ON scheduled_jobs(enabled);
            CREATE INDEX IF NOT EXISTS idx_jobs_priority ON scheduled_jobs(priority);
            CREATE INDEX IF NOT EXISTS idx_executions_status ON job_executions(status);
        """)
        
        # Migration: Add tts_voice column if it doesn't exist
        cursor.execute("PRAGMA table_info(scheduled_jobs)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'tts_voice' not in columns:
            cursor.execute("ALTER TABLE scheduled_jobs ADD COLUMN tts_voice TEXT DEFAULT NULL")
            logger.info("Added tts_voice column to scheduled_jobs table")
        
        # Migration: Add worker_id column if it doesn't exist
        cursor.execute("PRAGMA table_info(job_executions)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'worker_id' not in columns:
            cursor.execute("ALTER TABLE job_executions ADD COLUMN worker_id TEXT")
            logger.info("Added worker_id column to job_executions table")
        
        # Migration: Add priority column if it doesn't exist
        cursor.execute("PRAGMA table_info(scheduled_jobs)")
        scheduled_jobs_columns = [row[1] for row in cursor.fetchall()]
        if 'priority' not in scheduled_jobs_columns:
            cursor.execute("ALTER TABLE scheduled_jobs ADD COLUMN priority INTEGER DEFAULT 2")
            logger.info("Added priority column to scheduled_jobs table")
        
        # Migration: Add max_retries column if it doesn't exist
        if 'max_retries' not in scheduled_jobs_columns:
            cursor.execute("ALTER TABLE scheduled_jobs ADD COLUMN max_retries INTEGER DEFAULT 3")
            logger.info("Added max_retries column to scheduled_jobs table")
        
        # Migration: Add depends_on column if it doesn't exist
        if 'depends_on' not in scheduled_jobs_columns:
            cursor.execute("ALTER TABLE scheduled_jobs ADD COLUMN depends_on TEXT DEFAULT '[]'")
            logger.info("Added depends_on column to scheduled_jobs table")
        
        # Migration: Add retry_count column to job_executions if it doesn't exist
        cursor.execute("PRAGMA table_info(job_executions)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'retry_count' not in columns:
            cursor.execute("ALTER TABLE job_executions ADD COLUMN retry_count INTEGER DEFAULT 0")
            logger.info("Added retry_count column to job_executions table")
        
        conn.commit()
        conn.close()
        logger.info(f"Job scheduler database initialized: {self.db_path}")
    
    def acquire_distributed_lock(self, job_id: str, timeout: int = 300) -> bool:
        """Acquire distributed lock for job execution
        
        Args:
            job_id: ID of the job to lock
            timeout: Lock timeout in seconds (default: 5 minutes)
            
        Returns:
            True if lock was acquired, False otherwise
        """
        if not self.redis_available:
            # Fall back to local lock
            return self.execution_lock.acquire(blocking=False)
        
        try:
            lock_key = f"job_lock:{job_id}"
            # Use SET with NX (only set if not exists) and EX (expire)
            result = self.redis_client.set(
                lock_key,
                self.worker_id,
                nx=True,
                ex=timeout
            )
            return result is True
        except Exception as e:
            logger.error(f"Error acquiring distributed lock for job {job_id}: {e}")
            return False
    
    def release_distributed_lock(self, job_id: str) -> None:
        """Release distributed lock for job execution
        
        Args:
            job_id: ID of the job to unlock
        """
        if not self.redis_available:
            # Release local lock
            try:
                self.execution_lock.release()
            except RuntimeError:
                # Lock was not acquired or already released
                pass
            return
        
        try:
            lock_key = f"job_lock:{job_id}"
            # Only delete if we own the lock
            current_value = self.redis_client.get(lock_key)
            if current_value and current_value.decode('utf-8') == self.worker_id:
                self.redis_client.delete(lock_key)
        except Exception as e:
            logger.error(f"Error releasing distributed lock for job {job_id}: {e}")
    
    def is_job_locked(self, job_id: str) -> bool:
        """Check if a job is currently locked
        
        Args:
            job_id: ID of the job to check
            
        Returns:
            True if job is locked, False otherwise
        """
        if not self.redis_available:
            # Check local lock status
            return self.execution_status['running'] and self.current_job and self.current_job.get('id') == job_id
        
        try:
            lock_key = f"job_lock:{job_id}"
            return self.redis_client.exists(lock_key) == 1
        except Exception as e:
            logger.error(f"Error checking lock status for job {job_id}: {e}")
            return False
    
    def get_locked_jobs(self) -> List[str]:
        """Get list of currently locked job IDs
        
        Returns:
            List of job IDs that are currently locked
        """
        if not self.redis_available:
            # Return current job if running
            if self.execution_status['running'] and self.current_job:
                return [self.current_job.get('id', '')]
            return []
        
        try:
            # Get all keys matching job_lock pattern
            lock_keys = self.redis_client.keys("job_lock:*")
            return [key.decode('utf-8').replace('job_lock:', '') for key in lock_keys]
        except Exception as e:
            logger.error(f"Error getting locked jobs: {e}")
            return []
    
    def create_job(self, job_data: Dict[str, Any]) -> str:
        """Create a new scheduled job
          
        Args:
            job_data: Dictionary containing job configuration
                Required keys: 'name', 'time', 'profile', 'recurrence'
                Optional keys: 'articles_per_feed', 'summary_model', 'broadcast_model', 'tts_voice', 'enabled', 'priority', 'depends_on', 'max_retries'
              
        Returns:
            Job ID of the created job
              
        Raises:
            ValidationError: If required fields are missing
            JobSchedulerError: If job creation fails
        """
        # Validate required fields
        required_fields = ['name', 'time', 'profile', 'recurrence']
        for field in required_fields:
            if field not in job_data or not job_data[field]:
                raise ValidationError(f"Missing required field: {field}")
        
        import uuid
        job_id = str(uuid.uuid4())
        
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # Calculate next run time
                next_run = self._calculate_next_run(job_data['time'], job_data['recurrence'])
                
                # Get priority (default to NORMAL)
                priority = job_data.get('priority', 'NORMAL')
                if isinstance(priority, str):
                    try:
                        priority = JobPriority[priority.upper()]
                    except KeyError:
                        priority = JobPriority.NORMAL
                elif isinstance(priority, int):
                    priority = JobPriority(priority)
                
                # Get max retries (default to class default)
                max_retries = job_data.get('max_retries', self.max_retries)
                
                # Get dependencies
                depends_on = job_data.get('depends_on', [])
                if isinstance(depends_on, str):
                    depends_on = [depends_on]
                
                cursor.execute("""
                    INSERT INTO scheduled_jobs
                    (id, name, time, profile, articles_per_feed, summary_model,
                     broadcast_model, tts_voice, recurrence, enabled, next_run, priority, max_retries, depends_on)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job_id, job_data['name'], job_data['time'], job_data['profile'],
                    job_data['articles_per_feed'], job_data['summary_model'],
                    job_data['broadcast_model'], job_data.get('tts_voice'),
                    job_data['recurrence'], job_data['enabled'], next_run,
                    priority.value, max_retries, json.dumps(depends_on)
                ))
                
                conn.commit()
                logger.info(f"Created job: {job_id} - {job_data['name']} with priority {priority.name}")
                return job_id
                
            except Exception as e:
                logger.error(f"Error creating job: {e}")
                conn.rollback()
                raise JobSchedulerError(f"Failed to create job: {str(e)}") from e
    
    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get all scheduled jobs
         
        Returns:
            List of job dictionaries sorted by next run time
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM scheduled_jobs
                ORDER BY next_run ASC
            """)
            
            columns = [description[0] for description in cursor.description]
            jobs = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            return jobs
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific job by ID
         
        Args:
            job_id: ID of the job to retrieve
             
        Returns:
            Job dictionary if found, None otherwise
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            
            if row:
                columns = [description[0] for description in cursor.description]
                job = dict(zip(columns, row))
            else:
                job = None
                
            return job
    
    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """Update a job
         
        Args:
            job_id: ID of the job to update
            updates: Dictionary of fields to update
             
        Returns:
            True if update was successful, False otherwise
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # Build update query dynamically
                set_clauses = []
                values = []
                
                for key, value in updates.items():
                    if key in ['name', 'time', 'profile', 'articles_per_feed', 'summary_model',
                              'broadcast_model', 'tts_voice', 'recurrence', 'enabled', 'next_run', 'last_run',
                              'run_count', 'success_count', 'last_error', 'last_output']:
                        set_clauses.append(f"{key} = ?")
                        values.append(value)
                
                if not set_clauses:
                    return False
                    
                values.append(job_id)
                
                cursor.execute(f"""
                    UPDATE scheduled_jobs
                    SET {', '.join(set_clauses)}
                    WHERE id = ?
                """, values)
                
                conn.commit()
                return cursor.rowcount > 0
                
            except Exception as e:
                logger.error(f"Error updating job {job_id}: {e}")
                conn.rollback()
                raise JobSchedulerError(f"Failed to update job {job_id}: {str(e)}") from e
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job
         
        Args:
            job_id: ID of the job to delete
             
        Returns:
            True if deletion was successful, False otherwise
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # Delete executions first (foreign key constraint)
                cursor.execute("DELETE FROM job_executions WHERE job_id = ?", (job_id,))
                executions_deleted = cursor.rowcount
                
                # Delete the job
                cursor.execute("DELETE FROM scheduled_jobs WHERE id = ?", (job_id,))
                job_deleted = cursor.rowcount
                
                conn.commit()
                
                if job_deleted > 0:
                    logger.info(f"Deleted job: {job_id} (and {executions_deleted} executions)")
                    return True
                else:
                    logger.warning(f"Job not found: {job_id}")
                    return False
                
            except Exception as e:
                logger.error(f"Error deleting job {job_id}: {e}")
                conn.rollback()
                raise JobSchedulerError(f"Failed to delete job {job_id}: {str(e)}") from e
    
    def toggle_job(self, job_id: str, enabled: bool) -> bool:
        """Enable or disable a job
        
        Args:
            job_id: ID of the job to toggle
            enabled: True to enable, False to disable
            
        Returns:
            True if toggle was successful, False otherwise
        """
        updates: Dict[str, Any] = {'enabled': enabled}
        
        if enabled:
            # Recalculate next run when enabling
            job = self.get_job(job_id)
            if job:
                next_run = self._calculate_next_run(job['time'], job['recurrence'])
                updates['next_run'] = next_run
        else:
            updates['next_run'] = None
            
        return self.update_job(job_id, updates)
    
    def run_job_immediately(self, job_id: str) -> bool:
        """Add job to execution queue for immediate run
          
        Args:
            job_id: ID of the job to run immediately
              
        Returns:
            True if job was added to queue, False otherwise
        """
        job = self.get_job(job_id)
        if not job:
            return False
            
        # Use lock to prevent race conditions when adding to queue
        with self.queue_lock:
            # Add to queue if not already running
            if not any(q['id'] == job_id for q in self.job_queue):
                self.job_queue.append(job)
                logger.info(f"Added job {job_id} to immediate execution queue")
                return True
        
        return False

    def schedule_job_with_retry(self, job_data: Dict[str, Any], priority: JobPriority = JobPriority.NORMAL) -> str:
        """Schedule job with retry logic
         
        Args:
            job_data: Dictionary containing job configuration
            priority: Job priority level
         
        Returns:
            Job ID of the created job
        """
        job_id = job_data.get('job_id', str(uuid.uuid4()))
        job_data['job_id'] = job_id
        job_data['retry_count'] = 0
        job_data['max_retries'] = job_data.get('max_retries', self.max_retries)
        job_data['priority'] = priority.value
        
        # Store job metadata in Redis for retry tracking
        if self.redis_available:
            try:
                meta_key = f"job_meta:{job_id}"
                self.redis_client.setex(
                    meta_key,
                    86400,  # 24 hours
                    json.dumps(job_data)
                )
            except Exception as e:
                logger.error(f"Error storing job metadata: {e}")
        
        # Add to priority queue
        self.enqueue_job(job_data, priority)
        
        return job_id

    def handle_job_failure(self, job_id: str, error: str) -> None:
        """Handle job failure with retry logic
         
        Args:
            job_id: ID of the failed job
            error: Error message
        """
        if not self.redis_available:
            logger.warning("Redis not available, cannot track retry logic")
            return
        
        meta_key = f"job_meta:{job_id}"
        meta_data = self.redis_client.get(meta_key)
        
        if not meta_data:
            return
        
        try:
            job_data = json.loads(meta_data)
            retry_count = job_data.get('retry_count', 0)
            max_retries = job_data.get('max_retries', self.max_retries)
            
            if retry_count < max_retries:
                # Schedule retry with exponential backoff
                delay = self.backoff_factor ** retry_count
                job_data['retry_count'] = retry_count + 1
                job_data['last_error'] = error
                
                # Store updated metadata
                self.redis_client.setex(meta_key, 86400, json.dumps(job_data))
                
                # Schedule retry
                retry_key = f"retry:{job_id}"
                self.redis_client.setex(retry_key, delay, json.dumps(job_data))
                
                logger.info(f"Scheduled retry for job {job_id} in {delay}s (attempt {retry_count + 1}/{max_retries})")
            else:
                # Max retries reached, mark as failed
                job_data['status'] = 'failed'
                job_data['final_error'] = error
                self.redis_client.setex(meta_key, 86400, json.dumps(job_data))
                
                logger.error(f"Job {job_id} failed after {max_retries} retries")
                
        except Exception as e:
            logger.error(f"Error handling job failure: {e}")

    def enqueue_job(self, job_data: Dict[str, Any], priority: JobPriority = JobPriority.NORMAL) -> None:
        """Add job to priority queue
         
        Args:
            job_data: Job configuration
            priority: Job priority level
        """
        with self.queue_lock:
            # Add to appropriate priority queue
            self.priority_queues[priority].append(job_data)
            logger.info(f"Added job {job_data.get('job_id', 'unknown')} to {priority.name} priority queue")

    def dequeue_job(self, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """Get job from priority queue with priority
         
        Args:
            timeout: Timeout in seconds
         
        Returns:
            Job dictionary or None
        """
        # Try high priority first
        for priority in [JobPriority.CRITICAL, JobPriority.HIGH, JobPriority.NORMAL, JobPriority.LOW]:
            with self.queue_lock:
                if self.priority_queues[priority]:
                    return self.priority_queues[priority].pop(0)
        
        # Fallback to normal queue
        with self.queue_lock:
            if self.job_queue:
                return self.job_queue.pop(0)
        
        return None

    def add_job_dependency(self, job_id: str, depends_on: List[str]) -> None:
        """Add job dependencies
         
        Args:
            job_id: ID of the job
            depends_on: List of job IDs this job depends on
        """
        if not self.redis_available:
            logger.warning("Redis not available, cannot track job dependencies")
            return
        
        try:
            dep_key = f"job_deps:{job_id}"
            self.redis_client.set(dep_key, json.dumps(depends_on))
            logger.info(f"Added dependencies for job {job_id}: {depends_on}")
        except Exception as e:
            logger.error(f"Error adding job dependencies: {e}")

    def can_execute_job(self, job_id: str) -> bool:
        """Check if job can execute (all dependencies met)
         
        Args:
            job_id: ID of the job to check
         
        Returns:
            True if job can execute, False otherwise
        """
        if not self.redis_available:
            return True
        
        try:
            dep_key = f"job_deps:{job_id}"
            deps_data = self.redis_client.get(dep_key)
            
            if not deps_data:
                return True
            
            dependencies = json.loads(deps_data)
            for dep_id in dependencies:
                dep_status = self.redis_client.get(f"job_status:{dep_id}")
                if dep_status != b'completed':
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking job dependencies: {e}")
            return True

    def get_job_dependencies(self, job_id: str) -> List[str]:
        """Get job dependencies
         
        Args:
            job_id: ID of the job
         
        Returns:
            List of job IDs this job depends on
        """
        if not self.redis_available:
            return []
        
        try:
            dep_key = f"job_deps:{job_id}"
            deps_data = self.redis_client.get(dep_key)
            
            if not deps_data:
                return []
            
            return json.loads(deps_data)
            
        except Exception as e:
            logger.error(f"Error getting job dependencies: {e}")
            return []

    def get_job_retry_info(self, job_id: str) -> Dict[str, Any]:
        """Get retry information for a job
         
        Args:
            job_id: ID of the job
         
        Returns:
            Dictionary with retry information
        """
        if not self.redis_available:
            return {
                'retry_count': 0,
                'max_retries': self.max_retries,
                'last_error': None,
                'status': 'unknown'
            }
        
        try:
            meta_key = f"job_meta:{job_id}"
            meta_data = self.redis_client.get(meta_key)
            
            if not meta_data:
                return {
                    'retry_count': 0,
                    'max_retries': self.max_retries,
                    'last_error': None,
                    'status': 'unknown'
                }
            
            job_data = json.loads(meta_data)
            return {
                'retry_count': job_data.get('retry_count', 0),
                'max_retries': job_data.get('max_retries', self.max_retries),
                'last_error': job_data.get('last_error'),
                'status': job_data.get('status', 'pending')
            }
            
        except Exception as e:
            logger.error(f"Error getting retry info: {e}")
            return {
                'retry_count': 0,
                'max_retries': self.max_retries,
                'last_error': None,
                'status': 'unknown'
            }

    def update_job_status(self, job_id: str, status: str) -> None:
        """Update job status in Redis
         
        Args:
            job_id: ID of the job
            status: New status
        """
        if not self.redis_available:
            return
        
        try:
            status_key = f"job_status:{job_id}"
            self.redis_client.setex(status_key, 86400, status)
        except Exception as e:
            logger.error(f"Error updating job status: {e}")
    
    def start_scheduler(self) -> None:
        """Start the job scheduler
        
        Starts a background thread that checks for due jobs every 10 seconds.
        """
        if self.running:
            return
            
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        logger.info("Job scheduler started")
    
    def stop_scheduler(self) -> None:
        """Stop the job scheduler
         
        Sets the running flag to False to stop the scheduler loop.
        """
        self.running = False
        self.connection_pool.close_all()
        logger.info("Job scheduler stopped")
    
    def _scheduler_loop(self) -> None:
        """Main scheduler loop
        
        Runs in a background thread, checking for due jobs every 10 seconds.
        Processes immediate queue first, then checks scheduled jobs.
        """
        logger.info("Scheduler loop started")
        while self.running:
            try:
                # Process immediate queue first
                if self.job_queue and not self.execution_status['running']:
                    job = self.job_queue.pop(0)
                    logger.info(f"Executing immediate job: {job['name']}")
                    self._execute_job(job)
                
                # Check for scheduled jobs
                if not self.execution_status['running']:
                    due_jobs = self._get_due_jobs()
                    if due_jobs:
                        logger.info(f"Found {len(due_jobs)} due jobs, executing: {due_jobs[0]['name']}")
                        self._execute_job(due_jobs[0])
                    else:
                        # Log current time and next job times for debugging
                        now = datetime.now()
                        all_jobs = self.get_jobs()
                        enabled_jobs = [j for j in all_jobs if j['enabled'] and j['next_run']]
                        if enabled_jobs:
                            logger.debug(f"Current time: {now.isoformat()}")
                            for job in enabled_jobs[:3]:  # Log next 3 jobs
                                logger.debug(f"Job '{job['name']}' next run: {job['next_run']}")
                
                time.sleep(10)  # Check every 10 seconds instead of 30
                
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(30)  # Wait on error
    
    def _get_due_jobs(self) -> List[Dict[str, Any]]:
        """Get jobs that are due to run
         
        Returns:
            List of job dictionaries that are due to run
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now()
            now_iso = now.isoformat()
            
            # Use IMMEDIATE transaction to prevent race conditions
            cursor.execute("BEGIN IMMEDIATE")
            
            cursor.execute("""
                SELECT * FROM scheduled_jobs
                WHERE enabled = TRUE
                AND next_run IS NOT NULL
                AND next_run <= ?
                ORDER BY next_run ASC
            """, (now_iso,))
            
            columns = [description[0] for description in cursor.description]
            jobs = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # Debug logging
            if jobs:
                logger.info(f"Found {len(jobs)} due jobs at {now_iso}")
                for job in jobs:
                    logger.info(f"Due job: {job['name']} (scheduled: {job['next_run']})")
            else:
                # Check all enabled jobs for debugging
                cursor.execute("""
                    SELECT name, next_run FROM scheduled_jobs
                    WHERE enabled = TRUE AND next_run IS NOT NULL
                    ORDER BY next_run ASC
                """)
                all_enabled = cursor.fetchall()
                if all_enabled:
                    logger.debug(f"No due jobs found. Current time: {now_iso}")
                    for name, next_run in all_enabled[:3]:
                        logger.debug(f"Upcoming job: {name} at {next_run}")
            
            conn.commit()
            return jobs
    
    def _execute_job(self, job: Dict[str, Any]) -> None:
        """Execute a job
         
        Args:
            job: Job dictionary to execute
        """
        job_id = job['id']
        
        # Acquire distributed lock to prevent concurrent job execution across workers
        lock_acquired = self.acquire_distributed_lock(job_id, timeout=600)  # 10 minute timeout
        
        if not lock_acquired:
            logger.warning(f"Job {job_id} cannot start - lock not acquired (job may be running on another worker)")
            return
        
        try:
            # Check if a job is already running locally
            if self.execution_status['running']:
                logger.warning(f"Job {job_id} cannot start - another job is already running locally")
                return
            
            self.execution_status.update({
                'running': True,
                'current_job': job['name'],
                'progress': 0,
                'stage': 'Starting',
                'error': None
            })
            
            logger.info(f"Starting job execution: {job['name']} ({job_id})")
            
            # Record execution start
            execution_id = self._start_job_execution(job_id)
            
            # Load the RSS profile
            self.execution_status.update({'progress': 10, 'stage': 'Loading RSS profile'})
            profile_feeds = self._load_profile_feeds(job['profile'])
            
            if not profile_feeds:
                raise Exception(f"Profile '{job['profile']}' not found or has no feeds")
            
            # Set environment variables for this job
            self._set_job_environment(job)
            
            # Import digest generation functions
            from functions.news_digest_enhanced import (
                fetch_articles, extract_and_summarize_articles,
                generate_broadcast_with_llm, save_digest, text_to_speech
            )
            
            # Fetch articles
            self.execution_status.update({'progress': 25, 'stage': 'Fetching articles'})
            articles = fetch_articles(profile_feeds)
            
            if not articles:
                raise Exception("No new articles found")
            
            # Process articles
            self.execution_status.update({
                'progress': 50,
                'stage': f'Processing {len(articles)} articles'
            })
            summaries = extract_and_summarize_articles(articles)
            
            if not summaries:
                raise Exception("No articles successfully processed")
            
            # Generate broadcast
            self.execution_status.update({
                'progress': 75,
                'stage': f'Generating broadcast from {len(summaries)} articles'
            })
            broadcast = generate_broadcast_with_llm(summaries)
            
            # Save files with profile name
            self.execution_status.update({'progress': 90, 'stage': 'Saving files'})
            digest_path = save_digest(broadcast, summaries=summaries, job_name=job['profile'])
            
            # Generate audio
            self.execution_status.update({'progress': 95, 'stage': 'Generating audio'})
            mp3_path = digest_path.replace('.md', '.mp3')
            
            # Run TTS in async context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(text_to_speech(broadcast, output_path=mp3_path))
            loop.close()
            
            # Store broadcast in database
            try:
                from functions.database import NewsDatabase
                from functions.config_manager import config_manager
                
                db_config = config_manager.get_database_config()
                if db_config['enabled']:
                    database = NewsDatabase(db_config['path'])
                    broadcast_model = job.get('broadcast_model', 'broadcast_model')
                    database.store_broadcast(broadcast, broadcast_model, len(summaries),
                                           digest_path, mp3_path)
                    logger.info("Stored broadcast in database")
            except Exception as e:
                logger.warning(f"Failed to store broadcast in database: {e}")
                # Don't raise here - broadcast was generated successfully, just DB storage failed
            
            # Complete execution
            self._complete_job_execution(execution_id, 'completed',
                                       digest_path, mp3_path, len(summaries))
            
            # Update job status
            self._update_job_after_execution(job, True)
            
            self.execution_status.update({
                'progress': 100,
                'stage': 'Complete',
                'running': False
            })
            
            logger.info(f"Job completed successfully: {job['name']}")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Job execution failed: {job['name']} - {error_msg}")
            
            if 'execution_id' in locals():
                self._complete_job_execution(execution_id, 'failed', error=error_msg)
            
            self._update_job_after_execution(job, False, error_msg)
            
            self.execution_status.update({
                'running': False,
                'stage': 'Error',
                'error': error_msg
            })
            
            # Re-raise as JobSchedulerError for proper error handling
            raise JobSchedulerError(f"Job execution failed: {error_msg}") from e
        finally:
            # Always release the distributed lock
            self.release_distributed_lock(job_id)
    
    def _load_profile_feeds(self, profile_name: str) -> List[str]:
        """Load feeds from a profile
        
        Args:
            profile_name: Name of the profile to load
            
        Returns:
            List of feed URLs from the profile
        """
        try:
            # Get project root directory
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            profiles_file = Path(project_root) / 'settings' / 'feeds' / 'profiles.yaml'
            if not profiles_file.exists():
                return []
                
            with open(profiles_file, 'r') as f:
                profiles = yaml.safe_load(f) or {}
                
            if profile_name in profiles:
                return profiles[profile_name].get('feeds', [])
            return []
            
        except Exception as e:
            logger.error(f"Error loading profile {profile_name}: {e}")
            return []
    
    def _set_job_environment(self, job: Dict[str, Any]) -> None:
        """Set environment variables for job execution
        
        Args:
            job: Job dictionary containing configuration
        """
        os.environ['MAX_ARTICLES_PER_FEED'] = str(job['articles_per_feed'])
        os.environ['SUMMARY_MODEL_CONFIG'] = job['summary_model']
        os.environ['BROADCAST_MODEL_CONFIG'] = job['broadcast_model']
        
        # Set TTS voice if specified, otherwise use default from .env
        if job.get('tts_voice'):
            os.environ['TTS_VOICE'] = job['tts_voice']
        # If no job-specific voice, keep the existing TTS_VOICE from .env
    
    def _start_job_execution(self, job_id: str) -> int:
        """Record the start of job execution
         
        Args:
            job_id: ID of the job being executed
             
        Returns:
            Execution ID
             
        Raises:
            JobSchedulerError: If database operation fails
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Use IMMEDIATE transaction to prevent race conditions
            cursor.execute("BEGIN IMMEDIATE")
            
            # Check if job is already being executed by another worker
            cursor.execute("""
                SELECT COUNT(*) FROM job_executions
                WHERE job_id = ? AND status = 'running'
            """, (job_id,))
            
            if cursor.fetchone()[0] > 0:
                raise JobSchedulerError(f"Job {job_id} is already being executed by another worker")
            
            cursor.execute("""
                INSERT INTO job_executions (job_id, status, worker_id)
                VALUES (?, 'running', ?)
            """, (job_id, self.worker_id))
            
            try:
                execution_id = cursor.lastrowid
                conn.commit()
            except Exception as e:
                logger.error(f"Error starting job execution: {e}")
                raise JobSchedulerError(f"Failed to start job execution: {str(e)}") from e
        
        return execution_id
    
    def _complete_job_execution(self, execution_id: int, status: str,
                               output_file: Optional[str] = None, audio_file: Optional[str] = None,
                               article_count: Optional[int] = None, error: Optional[str] = None) -> None:
        """Record job execution completion
         
        Args:
            execution_id: ID of the execution to complete
            status: Completion status ('completed' or 'failed')
            output_file: Path to output file
            audio_file: Path to audio file
            article_count: Number of articles processed
            error: Error message if failed
        """
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Use IMMEDIATE transaction to prevent race conditions
            cursor.execute("BEGIN IMMEDIATE")
            
            cursor.execute("""
                UPDATE job_executions
                SET completed_at = CURRENT_TIMESTAMP,
                    status = ?,
                    error_message = ?,
                    output_file = ?,
                    audio_file = ?,
                    article_count = ?
                WHERE id = ?
            """, (status, error, output_file, audio_file, article_count, execution_id))
            
            try:
                conn.commit()
            except Exception as e:
                logger.error(f"Error committing job execution update: {e}")
                raise JobSchedulerError(f"Failed to commit job execution update: {str(e)}") from e
    
    def _update_job_after_execution(self, job: Dict[str, Any], success: bool,
                                  error: Optional[str] = None) -> None:
        """Update job after execution
        
        Args:
            job: Job dictionary
            success: Whether execution was successful
            error: Error message if failed
        """
        updates: Dict[str, Any] = {
            'last_run': datetime.now().isoformat(),
            'run_count': (job.get('run_count', 0) or 0) + 1
        }
        
        if success:
            updates['success_count'] = (job.get('success_count', 0) or 0) + 1
            updates['last_error'] = None
        else:
            updates['last_error'] = error
        
        # Calculate next run for recurring jobs
        if job['recurrence'] != 'once':
            updates['next_run'] = self._calculate_next_run(job['time'], job['recurrence'])
        else:
            updates['enabled'] = False
            updates['next_run'] = None
        
        self.update_job(job['id'], updates)
    
    def _calculate_next_run(self, time_str: str, recurrence: str) -> Optional[str]:
        """Calculate the next run time for a job
        
        Args:
            time_str: Time string in HH:MM format
            recurrence: Recurrence pattern ('once', 'daily', 'weekdays', 'weekends')
            
        Returns:
            ISO format timestamp of next run, or None if not applicable
        """
        try:
            now = datetime.now()
            target_time = datetime.strptime(time_str, '%H:%M').time()
            
            # Start with today
            next_run = datetime.combine(now.date(), target_time)
            
            # If time has already passed today, move to tomorrow
            if next_run <= now:
                next_run += timedelta(days=1)
            
            # Handle recurrence
            if recurrence == 'daily':
                # Already set correctly above
                pass
            elif recurrence == 'weekdays':
                # Monday=0, Sunday=6
                while next_run.weekday() >= 5:  # Saturday=5, Sunday=6
                    next_run += timedelta(days=1)
            elif recurrence == 'weekends':
                while next_run.weekday() < 5:  # Monday-Friday
                    next_run += timedelta(days=1)
            elif recurrence == 'once':
                # For one-time jobs, only run if in the future
                if next_run <= now:
                    return None
            
            return next_run.isoformat()
            
        except Exception as e:
            logger.error(f"Error calculating next run: {e}")
            raise JobSchedulerError(f"Failed to calculate next run: {str(e)}") from e
    
    def get_execution_status(self) -> Dict[str, Any]:
        """Get current execution status
        
        Returns:
            Dictionary containing execution status and queue information
        """
        return {
            'status': self.execution_status,
            'queue': [{'id': job['id'], 'name': job['name'], 'profile': job['profile']}
                     for job in self.job_queue]
        }

# Global scheduler instance
job_scheduler = JobScheduler()