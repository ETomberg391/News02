#!/usr/bin/env python3
"""
Message Queue Implementation for News02
Provides async message queuing for distributed processing
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import pickle
import hashlib

logger = logging.getLogger(__name__)


class QueueType(Enum):
    """Types of message queues"""
    DIGEST_GENERATION = "digest_generation"
    FEED_PROCESSING = "feed_processing"
    ARTICLE_SUMMARIZATION = "article_summarization"
    BROADCAST_GENERATION = "broadcast_generation"
    TTS_GENERATION = "tts_generation"


class QueueStatus(Enum):
    """Status of queue messages"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class QueueMessage:
    """Message structure for the queue"""
    message_id: str
    queue_type: QueueType
    payload: Dict[str, Any]
    status: QueueStatus
    created_at: datetime
    processed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary"""
        data = asdict(self)
        data['queue_type'] = self.queue_type.value
        data['status'] = self.status.value
        data['created_at'] = self.created_at.isoformat()
        if self.processed_at:
            data['processed_at'] = self.processed_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueueMessage':
        """Create message from dictionary"""
        return cls(
            message_id=data['message_id'],
            queue_type=QueueType(data['queue_type']),
            payload=data['payload'],
            status=QueueStatus(data['status']),
            created_at=datetime.fromisoformat(data['created_at']),
            processed_at=datetime.fromisoformat(data['processed_at']) if data.get('processed_at') else None,
            retry_count=data.get('retry_count', 0),
            max_retries=data.get('max_retries', 3),
            error_message=data.get('error_message')
        )


class MessageQueue:
    """In-memory message queue with persistence support"""
    
    def __init__(self, max_size: int = 1000, persistence_path: Optional[str] = None) -> None:
        """Initialize message queue
        
        Args:
            max_size: Maximum number of messages in queue
            persistence_path: Path to persist queue data (optional)
        """
        self.max_size = max_size
        self.persistence_path = persistence_path
        self.queues: Dict[QueueType, List[QueueMessage]] = {
            queue_type: [] for queue_type in QueueType
        }
        self.processors: Dict[QueueType, List[Callable]] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._worker_tasks: Dict[QueueType, asyncio.Task] = {}
        
        # Load persisted data if available
        self._load_persisted_data()
    
    def _load_persisted_data(self) -> None:
        """Load persisted queue data from disk"""
        if not self.persistence_path:
            return
        
        try:
            import os
            if os.path.exists(self.persistence_path):
                with open(self.persistence_path, 'rb') as f:
                    data = pickle.load(f)
                    for queue_type, messages in data.items():
                        self.queues[queue_type] = messages
                logger.info(f"Loaded {sum(len(m) for m in self.queues.values())} messages from persistence")
        except Exception as e:
            logger.warning(f"Failed to load persisted queue data: {e}")
    
    def _save_persisted_data(self) -> None:
        """Save queue data to disk"""
        if not self.persistence_path:
            return
        
        try:
            with open(self.persistence_path, 'wb') as f:
                pickle.dump(self.queues, f)
        except Exception as e:
            logger.warning(f"Failed to save persisted queue data: {e}")
    
    async def enqueue(self, queue_type: QueueType, payload: Dict[str, Any], max_retries: int = 3) -> str:
        """Add a message to the queue
        
        Args:
            queue_type: Type of queue
            payload: Message payload
            max_retries: Maximum retry attempts
            
        Returns:
            Message ID
        """
        async with self._lock:
            # Generate message ID
            message_id = hashlib.md5(
                f"{queue_type.value}_{time.time()}_{json.dumps(payload, sort_keys=True)}".encode()
            ).hexdigest()
            
            message = QueueMessage(
                message_id=message_id,
                queue_type=queue_type,
                payload=payload,
                status=QueueStatus.PENDING,
                created_at=datetime.now(),
                max_retries=max_retries
            )
            
            # Check queue size limit
            if len(self.queues[queue_type]) >= self.max_size:
                # Remove oldest message
                self.queues[queue_type].pop(0)
                logger.warning(f"Queue {queue_type.value} reached max size, removed oldest message")
            
            self.queues[queue_type].append(message)
            self._save_persisted_data()
            
            logger.info(f"Enqueued message {message_id} to {queue_type.value}")
            return message_id
    
    async def dequeue(self, queue_type: QueueType) -> Optional[QueueMessage]:
        """Get next message from queue
        
        Args:
            queue_type: Type of queue
            
        Returns:
            Next message or None if queue is empty
        """
        async with self._lock:
            if not self.queues[queue_type]:
                return None
            
            # Find first pending message
            for i, message in enumerate(self.queues[queue_type]):
                if message.status == QueueStatus.PENDING:
                    message.status = QueueStatus.PROCESSING
                    self._save_persisted_data()
                    return message
            
            return None
    
    async def mark_completed(self, message_id: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark message as completed
        
        Args:
            message_id: ID of message to mark
            result: Optional result data
        """
        async with self._lock:
            for queue_type, messages in self.queues.items():
                for message in messages:
                    if message.message_id == message_id:
                        message.status = QueueStatus.COMPLETED
                        message.processed_at = datetime.now()
                        if result:
                            message.payload['result'] = result
                        self._save_persisted_data()
                        logger.info(f"Marked message {message_id} as completed")
                        return
    
    async def mark_failed(self, message_id: str, error: str) -> None:
        """Mark message as failed
        
        Args:
            message_id: ID of message to mark
            error: Error message
        """
        async with self._lock:
            for queue_type, messages in self.queues.items():
                for message in messages:
                    if message.message_id == message_id:
                        message.error_message = error
                        message.retry_count += 1
                        
                        if message.retry_count >= message.max_retries:
                            message.status = QueueStatus.FAILED
                            logger.error(f"Message {message_id} failed after {message.retry_count} retries: {error}")
                        else:
                            message.status = QueueStatus.RETRYING
                            logger.warning(f"Message {message_id} retrying (attempt {message.retry_count}/{message.max_retries}): {error}")
                        
                        self._save_persisted_data()
                        return
    
    async def get_queue_status(self, queue_type: QueueType) -> Dict[str, int]:
        """Get queue statistics
        
        Args:
            queue_type: Type of queue
            
        Returns:
            Dictionary with queue statistics
        """
        async with self._lock:
            messages = self.queues[queue_type]
            return {
                'total': len(messages),
                'pending': len([m for m in messages if m.status == QueueStatus.PENDING]),
                'processing': len([m for m in messages if m.status == QueueStatus.PROCESSING]),
                'completed': len([m for m in messages if m.status == QueueStatus.COMPLETED]),
                'failed': len([m for m in messages if m.status == QueueStatus.FAILED]),
                'retrying': len([m for m in messages if m.status == QueueStatus.RETRYING]),
            }
    
    async def register_processor(self, queue_type: QueueType, processor: Callable) -> None:
        """Register a processor function for a queue type
        
        Args:
            queue_type: Type of queue
            processor: Async function that processes messages
        """
        if queue_type not in self.processors:
            self.processors[queue_type] = []
        self.processors[queue_type].append(processor)
        logger.info(f"Registered processor for {queue_type.value}")
    
    async def start_workers(self) -> None:
        """Start worker tasks for all registered processors"""
        if self._running:
            logger.warning("Workers already running")
            return
        
        self._running = True
        logger.info("Starting message queue workers...")
        
        for queue_type, processors in self.processors.items():
            for processor in processors:
                task = asyncio.create_task(self._worker_loop(queue_type, processor))
                self._worker_tasks[queue_type] = task
                logger.info(f"Started worker for {queue_type.value}")
    
    async def stop_workers(self) -> None:
        """Stop all worker tasks"""
        self._running = False
        logger.info("Stopping message queue workers...")
        
        for task in self._worker_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._worker_tasks.clear()
        logger.info("All workers stopped")
    
    async def _worker_loop(self, queue_type: QueueType, processor: Callable) -> None:
        """Worker loop that processes messages from queue
        
        Args:
            queue_type: Type of queue
            processor: Function to process messages
        """
        logger.info(f"Worker started for {queue_type.value}")
        
        while self._running:
            try:
                # Get next message
                message = await self.dequeue(queue_type)
                
                if message is None:
                    # No messages, wait a bit
                    await asyncio.sleep(1)
                    continue
                
                # Process message
                try:
                    result = await processor(message.payload)
                    await self.mark_completed(message.message_id, result)
                except Exception as e:
                    error_msg = str(e)
                    await self.mark_failed(message.message_id, error_msg)
                
                # Small delay to prevent overwhelming the system
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                logger.info(f"Worker for {queue_type.value} cancelled")
                break
            except Exception as e:
                logger.error(f"Error in worker loop for {queue_type.value}: {e}")
                await asyncio.sleep(5)  # Wait before retrying
    
    async def clear_queue(self, queue_type: QueueType) -> None:
        """Clear all messages from a queue
        
        Args:
            queue_type: Type of queue to clear
        """
        async with self._lock:
            self.queues[queue_type].clear()
            self._save_persisted_data()
            logger.info(f"Cleared queue {queue_type.value}")
    
    async def get_messages(self, queue_type: QueueType, status: Optional[QueueStatus] = None) -> List[QueueMessage]:
        """Get messages from queue with optional status filter
        
        Args:
            queue_type: Type of queue
            status: Optional status filter
            
        Returns:
            List of messages
        """
        async with self._lock:
            messages = self.queues[queue_type]
            if status:
                return [m for m in messages if m.status == status]
            return messages.copy()


# Global message queue instance
message_queue = MessageQueue(
    max_size=1000,
    persistence_path='data/message_queue.pkl'
)


# Example processor functions
async def process_digest_generation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process digest generation message"""
    logger.info(f"Processing digest generation: {payload}")
    # Simulate processing
    await asyncio.sleep(1)
    return {'status': 'success', 'digest_id': 'generated_123'}


async def process_feed_processing(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process feed processing message"""
    logger.info(f"Processing feed: {payload}")
    # Simulate processing
    await asyncio.sleep(0.5)
    return {'status': 'success', 'articles_found': 5}


async def process_article_summarization(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process article summarization message"""
    logger.info(f"Processing article summarization: {payload}")
    # Simulate processing
    await asyncio.sleep(2)
    return {'status': 'success', 'summary': 'Generated summary'}


async def process_broadcast_generation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process broadcast generation message"""
    logger.info(f"Processing broadcast generation: {payload}")
    # Simulate processing
    await asyncio.sleep(3)
    return {'status': 'success', 'broadcast': 'Generated broadcast'}


async def process_tts_generation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process TTS generation message"""
    logger.info(f"Processing TTS generation: {payload}")
    # Simulate processing
    await asyncio.sleep(5)
    return {'status': 'success', 'audio_path': 'generated_audio.mp3'}


# Register processors
async def register_all_processors() -> None:
    """Register all message processors"""
    await message_queue.register_processor(QueueType.DIGEST_GENERATION, process_digest_generation)
    await message_queue.register_processor(QueueType.FEED_PROCESSING, process_feed_processing)
    await message_queue.register_processor(QueueType.ARTICLE_SUMMARIZATION, process_article_summarization)
    await message_queue.register_processor(QueueType.BROADCAST_GENERATION, process_broadcast_generation)
    await message_queue.register_processor(QueueType.TTS_GENERATION, process_tts_generation)
    logger.info("All message processors registered")


# Example usage
async def example_usage() -> None:
    """Example of using the message queue"""
    # Register processors
    await register_all_processors()
    
    # Start workers
    await message_queue.start_workers()
    
    # Enqueue some messages
    await message_queue.enqueue(
        QueueType.DIGEST_GENERATION,
        {'profile': 'tech', 'articles': 10}
    )
    
    await message_queue.enqueue(
        QueueType.FEED_PROCESSING,
        {'feed_url': 'https://example.com/feed.xml'}
    )
    
    # Wait for processing
    await asyncio.sleep(10)
    
    # Check status
    status = await message_queue.get_queue_status(QueueType.DIGEST_GENERATION)
    print(f"Queue status: {status}")
    
    # Stop workers
    await message_queue.stop_workers()


if __name__ == "__main__":
    asyncio.run(example_usage())
