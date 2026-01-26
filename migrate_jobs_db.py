#!/usr/bin/env python3
"""
Migration script to add missing columns to jobs database
"""
import sqlite3
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """Add missing columns to jobs database"""
    db_path = 'data/jobs.db'
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get current columns for scheduled_jobs
    cursor.execute("PRAGMA table_info(scheduled_jobs)")
    scheduled_jobs_columns = [row[1] for row in cursor.fetchall()]
    logger.info(f"scheduled_jobs columns: {scheduled_jobs_columns}")
    
    # Add priority column if missing
    if 'priority' not in scheduled_jobs_columns:
        cursor.execute("ALTER TABLE scheduled_jobs ADD COLUMN priority INTEGER DEFAULT 2")
        logger.info("✅ Added priority column to scheduled_jobs table")
    else:
        logger.info("ℹ️  priority column already exists")
    
    # Add max_retries column if missing
    if 'max_retries' not in scheduled_jobs_columns:
        cursor.execute("ALTER TABLE scheduled_jobs ADD COLUMN max_retries INTEGER DEFAULT 3")
        logger.info("✅ Added max_retries column to scheduled_jobs table")
    else:
        logger.info("ℹ️  max_retries column already exists")
    
    # Add depends_on column if missing
    if 'depends_on' not in scheduled_jobs_columns:
        cursor.execute("ALTER TABLE scheduled_jobs ADD COLUMN depends_on TEXT DEFAULT '[]'")
        logger.info("✅ Added depends_on column to scheduled_jobs table")
    else:
        logger.info("ℹ️  depends_on column already exists")
    
    # Get current columns for job_executions
    cursor.execute("PRAGMA table_info(job_executions)")
    job_executions_columns = [row[1] for row in cursor.fetchall()]
    logger.info(f"job_executions columns: {job_executions_columns}")
    
    # Add worker_id column if missing
    if 'worker_id' not in job_executions_columns:
        cursor.execute("ALTER TABLE job_executions ADD COLUMN worker_id TEXT")
        logger.info("✅ Added worker_id column to job_executions table")
    else:
        logger.info("ℹ️  worker_id column already exists")
    
    # Add retry_count column if missing
    if 'retry_count' not in job_executions_columns:
        cursor.execute("ALTER TABLE job_executions ADD COLUMN retry_count INTEGER DEFAULT 0")
        logger.info("✅ Added retry_count column to job_executions table")
    else:
        logger.info("ℹ️  retry_count column already exists")
    
    conn.commit()
    conn.close()
    
    logger.info("✅ Migration completed successfully!")

if __name__ == '__main__':
    migrate_database()
