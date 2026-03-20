"""
PHINS Notification Queue Service
Enterprise-grade async notification delivery with retry logic

Features:
- Priority-based queue processing
- Exponential backoff retry
- Dead letter queue for failed messages
- Scheduled delivery support
- Queue health monitoring
- Worker pool management
"""

from __future__ import annotations

import json
import threading
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from queue import PriorityQueue, Empty
from concurrent.futures import ThreadPoolExecutor, Future
import uuid

from services.notification_service import (
    NotificationService,
    NotificationRequest,
    NotificationResult,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
    NotificationConfig,
    generate_id,
)

logger = logging.getLogger('phins.notification_queue')


def _normalize_utc_datetime(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetimes used by the queue to timezone-aware UTC values."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ============================================================================
# QUEUE CONFIGURATION
# ============================================================================

class QueueConfig:
    """Configuration for notification queue"""
    
    # Worker settings
    WORKER_COUNT = int(NotificationConfig.QUEUE_WORKER_THREADS)
    WORKER_POLL_INTERVAL = 0.5  # seconds
    
    # Retry settings
    MAX_RETRIES = int(NotificationConfig.QUEUE_MAX_RETRIES)
    BASE_RETRY_DELAY = int(NotificationConfig.QUEUE_RETRY_DELAY_SECONDS)
    MAX_RETRY_DELAY = 3600  # 1 hour max
    RETRY_MULTIPLIER = 2.0  # Exponential backoff multiplier
    
    # Queue limits
    MAX_QUEUE_SIZE = 100000
    BATCH_SIZE = 100
    
    # Priority weights (lower = higher priority)
    PRIORITY_WEIGHTS = {
        NotificationPriority.CRITICAL: 0,
        NotificationPriority.HIGH: 1,
        NotificationPriority.NORMAL: 2,
        NotificationPriority.LOW: 3,
    }
    
    # Health check
    HEALTH_CHECK_INTERVAL = 30  # seconds
    STALE_MESSAGE_THRESHOLD = 3600  # 1 hour


# ============================================================================
# DATA CLASSES
# ============================================================================

class QueueItemStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    SCHEDULED = "scheduled"
    EXPIRED = "expired"


@dataclass
class QueueItem:
    """Notification queue item"""
    id: str
    notification_request: NotificationRequest
    priority: NotificationPriority = NotificationPriority.NORMAL
    status: QueueItemStatus = QueueItemStatus.PENDING
    
    # Scheduling
    scheduled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    # Retry tracking
    attempt_count: int = 0
    max_attempts: int = QueueConfig.MAX_RETRIES
    next_retry_at: Optional[datetime] = None
    
    # Results
    last_result: Optional[NotificationResult] = None
    error_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Correlation
    correlation_id: Optional[str] = None
    
    def __lt__(self, other: 'QueueItem') -> bool:
        """Comparison for priority queue ordering"""
        self_priority = QueueConfig.PRIORITY_WEIGHTS.get(self.priority, 2)
        other_priority = QueueConfig.PRIORITY_WEIGHTS.get(other.priority, 2)
        
        if self_priority != other_priority:
            return self_priority < other_priority
        
        # Same priority - order by created_at
        return self.created_at < other.created_at
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'priority': self.priority.value,
            'status': self.status.value,
            'channel': self.notification_request.channel.value,
            'recipient': self.notification_request.recipient[:3] + '***',  # Masked
            'scheduled_at': self.scheduled_at.isoformat() if self.scheduled_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'attempt_count': self.attempt_count,
            'max_attempts': self.max_attempts,
            'next_retry_at': self.next_retry_at.isoformat() if self.next_retry_at else None,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'correlation_id': self.correlation_id
        }


@dataclass
class QueueStats:
    """Queue statistics"""
    total_items: int = 0
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    dead_letter: int = 0
    scheduled: int = 0
    
    # Rate metrics
    processed_per_minute: float = 0.0
    success_rate: float = 1.0
    average_processing_time_ms: float = 0.0
    
    # Worker status
    active_workers: int = 0
    total_workers: int = 0
    
    # Queue health
    oldest_pending_item_age_seconds: float = 0.0
    is_healthy: bool = True
    health_issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_items': self.total_items,
            'pending': self.pending,
            'processing': self.processing,
            'completed': self.completed,
            'failed': self.failed,
            'dead_letter': self.dead_letter,
            'scheduled': self.scheduled,
            'processed_per_minute': round(self.processed_per_minute, 2),
            'success_rate': round(self.success_rate, 4),
            'average_processing_time_ms': round(self.average_processing_time_ms, 2),
            'active_workers': self.active_workers,
            'total_workers': self.total_workers,
            'oldest_pending_item_age_seconds': round(self.oldest_pending_item_age_seconds, 2),
            'is_healthy': self.is_healthy,
            'health_issues': self.health_issues
        }


# ============================================================================
# NOTIFICATION QUEUE SERVICE
# ============================================================================

class NotificationQueueService:
    """
    Enterprise notification queue with async processing.
    
    Features:
    - Priority-based processing (critical > high > normal > low)
    - Exponential backoff retry with jitter
    - Dead letter queue for permanent failures
    - Scheduled delivery
    - Worker pool management
    - Real-time health monitoring
    """
    
    def __init__(
        self,
        notification_service: NotificationService,
        worker_count: int = QueueConfig.WORKER_COUNT,
        auto_start: bool = False
    ):
        self._notification_service = notification_service
        self._worker_count = worker_count
        
        # Main queue (priority queue)
        self._queue: PriorityQueue[QueueItem] = PriorityQueue(
            maxsize=QueueConfig.MAX_QUEUE_SIZE
        )
        
        # Item storage for lookup
        self._items: Dict[str, QueueItem] = {}
        self._items_lock = threading.Lock()
        
        # Dead letter queue
        self._dead_letter: Dict[str, QueueItem] = {}
        
        # Scheduled items (sorted by schedule time)
        self._scheduled: Dict[str, QueueItem] = {}
        
        # Processing metrics
        self._metrics: Dict[str, Any] = {
            'processed_count': 0,
            'success_count': 0,
            'failure_count': 0,
            'processing_times': [],  # Last 1000
            'start_time': datetime.now(timezone.utc)
        }
        self._metrics_lock = threading.Lock()
        
        # Worker management
        self._executor: Optional[ThreadPoolExecutor] = None
        self._workers_active = False
        self._shutdown_event = threading.Event()
        self._worker_futures: List[Future] = []
        
        # Scheduler thread
        self._scheduler_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self._on_success_callbacks: List[Callable[[QueueItem, NotificationResult], None]] = []
        self._on_failure_callbacks: List[Callable[[QueueItem, str], None]] = []
        
        if auto_start:
            self.start()
    
    # ========== Public API ==========
    
    def enqueue(
        self,
        request: NotificationRequest,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        scheduled_at: Optional[datetime] = None,
        expires_at: Optional[datetime] = None,
        max_attempts: Optional[int] = None,
        correlation_id: Optional[str] = None
    ) -> str:
        """
        Add notification to queue.
        
        Args:
            request: NotificationRequest to send
            priority: Processing priority
            scheduled_at: When to send (None = immediately)
            expires_at: Don't send after this time
            max_attempts: Override default max retry attempts
            correlation_id: For tracking related items
        
        Returns:
            Queue item ID
        """
        item_id = generate_id('QUEUE')
        scheduled_at = _normalize_utc_datetime(scheduled_at or request.send_at)
        expires_at = _normalize_utc_datetime(expires_at or request.expires_at)
        
        item = QueueItem(
            id=item_id,
            notification_request=request,
            priority=priority,
            scheduled_at=scheduled_at,
            expires_at=expires_at,
            max_attempts=max_attempts or QueueConfig.MAX_RETRIES,
            correlation_id=correlation_id or request.correlation_id
        )
        
        with self._items_lock:
            self._items[item_id] = item
        
        now = datetime.now(timezone.utc)

        if expires_at and expires_at <= now:
            item.status = QueueItemStatus.EXPIRED
            item.completed_at = now
            logger.info(f"Notification {item_id} expired before queueing")
        elif scheduled_at and scheduled_at > now:
            # Scheduled for later
            item.status = QueueItemStatus.SCHEDULED
            with self._items_lock:
                self._scheduled[item_id] = item
            logger.info(f"Notification {item_id} scheduled for {scheduled_at}")
        else:
            # Add to queue immediately
            self._queue.put(item)
            logger.debug(f"Notification {item_id} added to queue with priority {priority}")
        
        return item_id
    
    def get_status(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a queue item"""
        with self._items_lock:
            item = self._items.get(item_id)
            if item:
                return item.to_dict()
            
            # Check dead letter
            item = self._dead_letter.get(item_id)
            if item:
                return item.to_dict()
        
        return None
    
    def cancel(self, item_id: str) -> bool:
        """Cancel a pending queue item"""
        with self._items_lock:
            item = self._items.get(item_id)
            if item and item.status in (QueueItemStatus.PENDING, QueueItemStatus.SCHEDULED):
                item.status = QueueItemStatus.EXPIRED
                # Remove from scheduled if applicable
                self._scheduled.pop(item_id, None)
                logger.info(f"Notification {item_id} cancelled")
                return True
        return False
    
    def retry(self, item_id: str) -> bool:
        """Manually retry a failed item"""
        with self._items_lock:
            item = self._dead_letter.get(item_id)
            if item:
                # Reset and re-queue
                item.status = QueueItemStatus.PENDING
                item.attempt_count = 0
                item.error_history.clear()
                item.next_retry_at = None
                
                self._dead_letter.pop(item_id, None)
                self._items[item_id] = item
                self._queue.put(item)
                
                logger.info(f"Notification {item_id} moved from dead letter queue and re-queued")
                return True
        return False
    
    def get_stats(self) -> QueueStats:
        """Get current queue statistics"""
        stats = QueueStats()
        
        with self._items_lock:
            stats.total_items = len(self._items)
            
            for item in self._items.values():
                if item.status == QueueItemStatus.PENDING:
                    stats.pending += 1
                elif item.status == QueueItemStatus.PROCESSING:
                    stats.processing += 1
                elif item.status == QueueItemStatus.COMPLETED:
                    stats.completed += 1
                elif item.status == QueueItemStatus.FAILED:
                    stats.failed += 1
                elif item.status == QueueItemStatus.SCHEDULED:
                    stats.scheduled += 1
            
            stats.dead_letter = len(self._dead_letter)
        
        # Calculate metrics
        with self._metrics_lock:
            elapsed = (datetime.now(timezone.utc) - self._metrics['start_time']).total_seconds() / 60
            if elapsed > 0:
                stats.processed_per_minute = self._metrics['processed_count'] / elapsed
            
            total_processed = self._metrics['success_count'] + self._metrics['failure_count']
            if total_processed > 0:
                stats.success_rate = self._metrics['success_count'] / total_processed
            
            if self._metrics['processing_times']:
                stats.average_processing_time_ms = sum(self._metrics['processing_times']) / len(self._metrics['processing_times'])
        
        # Worker status
        stats.total_workers = self._worker_count
        stats.active_workers = sum(1 for f in self._worker_futures if not f.done())
        
        # Health check
        stats.health_issues = []
        
        # Check for stale items
        with self._items_lock:
            pending_items = [i for i in self._items.values() if i.status == QueueItemStatus.PENDING]
            if pending_items:
                oldest = min(i.created_at for i in pending_items)
                stats.oldest_pending_item_age_seconds = (datetime.now(timezone.utc) - oldest).total_seconds()
                
                if stats.oldest_pending_item_age_seconds > QueueConfig.STALE_MESSAGE_THRESHOLD:
                    stats.health_issues.append(f"Stale messages detected (oldest: {stats.oldest_pending_item_age_seconds:.0f}s)")
        
        # Check worker health
        if self._workers_active and stats.active_workers == 0:
            stats.health_issues.append("No active workers")
        
        # Check success rate
        if stats.success_rate < 0.9:
            stats.health_issues.append(f"Low success rate: {stats.success_rate:.2%}")
        
        # Check dead letter queue size
        if stats.dead_letter > 100:
            stats.health_issues.append(f"High dead letter queue count: {stats.dead_letter}")
        
        stats.is_healthy = len(stats.health_issues) == 0
        
        return stats
    
    def get_dead_letter_items(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get items in dead letter queue"""
        with self._items_lock:
            items = list(self._dead_letter.values())[:limit]
            return [item.to_dict() for item in items]
    
    def purge_dead_letter(self, item_ids: Optional[List[str]] = None) -> int:
        """Remove items from dead letter queue"""
        with self._items_lock:
            if item_ids:
                count = sum(1 for id in item_ids if self._dead_letter.pop(id, None))
            else:
                count = len(self._dead_letter)
                self._dead_letter.clear()
        
        logger.info(f"Purged {count} items from dead letter queue")
        return count
    
    def start(self) -> None:
        """Start queue workers"""
        if self._workers_active:
            logger.warning("Queue workers already running")
            return
        
        self._shutdown_event.clear()
        self._workers_active = True
        
        # Start worker pool
        self._executor = ThreadPoolExecutor(
            max_workers=self._worker_count,
            thread_name_prefix='notif_worker'
        )
        
        self._worker_futures = [
            self._executor.submit(self._worker_loop, worker_id)
            for worker_id in range(self._worker_count)
        ]
        
        # Start scheduler thread
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name='notif_scheduler',
            daemon=True
        )
        self._scheduler_thread.start()
        
        logger.info(f"Started {self._worker_count} queue workers")
    
    def stop(self, wait: bool = True, timeout: float = 30.0) -> None:
        """Stop queue workers"""
        if not self._workers_active:
            return
        
        self._workers_active = False
        self._shutdown_event.set()
        
        if wait and self._executor:
            self._executor.shutdown(wait=True, cancel_futures=False)
        elif self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
        
        self._executor = None
        self._worker_futures = []
        
        logger.info("Queue workers stopped")
    
    def on_success(self, callback: Callable[[QueueItem, NotificationResult], None]) -> None:
        """Register callback for successful deliveries"""
        self._on_success_callbacks.append(callback)
    
    def on_failure(self, callback: Callable[[QueueItem, str], None]) -> None:
        """Register callback for permanent failures"""
        self._on_failure_callbacks.append(callback)
    
    # ========== Private Methods ==========
    
    def _worker_loop(self, worker_id: int) -> None:
        """Main worker loop"""
        logger.debug(f"Worker {worker_id} started")
        
        while not self._shutdown_event.is_set():
            try:
                # Get item from queue with timeout
                try:
                    item = self._queue.get(timeout=QueueConfig.WORKER_POLL_INTERVAL)
                except Empty:
                    continue
                
                # Skip if cancelled/expired
                if item.status not in (QueueItemStatus.PENDING,):
                    continue
                
                # Check expiry
                if item.expires_at and datetime.now(timezone.utc) > item.expires_at:
                    item.status = QueueItemStatus.EXPIRED
                    logger.debug(f"Item {item.id} expired")
                    continue
                
                # Check if this is a retry that's not ready yet
                if item.next_retry_at and datetime.now(timezone.utc) < item.next_retry_at:
                    # Put back in queue
                    self._queue.put(item)
                    time.sleep(0.1)  # Small delay to prevent busy loop
                    continue
                
                # Process item
                self._process_item(item, worker_id)
                
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {str(e)}")
                time.sleep(1)  # Brief pause on error
        
        logger.debug(f"Worker {worker_id} stopped")
    
    def _process_item(self, item: QueueItem, worker_id: int) -> None:
        """Process a single queue item"""
        start_time = datetime.now(timezone.utc)
        
        # Update status
        item.status = QueueItemStatus.PROCESSING
        item.started_at = start_time
        item.attempt_count += 1
        
        logger.debug(f"Worker {worker_id} processing {item.id} (attempt {item.attempt_count})")
        
        try:
            # Send notification
            result = self._notification_service.send(item.notification_request)
            
            # Record timing
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            with self._metrics_lock:
                self._metrics['processing_times'].append(processing_time)
                if len(self._metrics['processing_times']) > 1000:
                    self._metrics['processing_times'] = self._metrics['processing_times'][-1000:]
                self._metrics['processed_count'] += 1
            
            if result.success:
                self._handle_success(item, result)
            else:
                self._handle_failure(item, result.error_code, result.error_message)
            
        except Exception as e:
            logger.error(f"Error processing {item.id}: {str(e)}")
            self._handle_failure(item, "PROCESSING_ERROR", str(e))
    
    def _handle_success(self, item: QueueItem, result: NotificationResult) -> None:
        """Handle successful delivery"""
        item.status = QueueItemStatus.COMPLETED
        item.completed_at = datetime.now(timezone.utc)
        item.last_result = result
        
        with self._metrics_lock:
            self._metrics['success_count'] += 1
        
        logger.info(f"Notification {item.id} delivered successfully")
        
        # Trigger callbacks
        for callback in self._on_success_callbacks:
            try:
                callback(item, result)
            except Exception as e:
                logger.error(f"Success callback error: {str(e)}")
    
    def _handle_failure(
        self,
        item: QueueItem,
        error_code: Optional[str],
        error_message: Optional[str]
    ) -> None:
        """Handle delivery failure"""
        # Record error
        item.error_history.append({
            'attempt': item.attempt_count,
            'error_code': error_code,
            'error_message': error_message,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        with self._metrics_lock:
            self._metrics['failure_count'] += 1
        
        # Check if should retry
        if item.attempt_count < item.max_attempts:
            # Calculate retry delay with exponential backoff
            delay = min(
                QueueConfig.BASE_RETRY_DELAY * (QueueConfig.RETRY_MULTIPLIER ** (item.attempt_count - 1)),
                QueueConfig.MAX_RETRY_DELAY
            )
            
            # Add jitter (±20%)
            import random
            jitter = delay * random.uniform(-0.2, 0.2)
            delay = delay + jitter
            
            item.status = QueueItemStatus.PENDING
            item.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            
            # Re-queue
            self._queue.put(item)
            
            logger.warning(
                f"Notification {item.id} failed (attempt {item.attempt_count}), "
                f"retry in {delay:.1f}s: {error_message}"
            )
        else:
            # Move to dead letter queue
            item.status = QueueItemStatus.DEAD_LETTER
            item.completed_at = datetime.now(timezone.utc)
            
            with self._items_lock:
                self._dead_letter[item.id] = item
            
            logger.error(
                f"Notification {item.id} moved to dead letter queue after "
                f"{item.attempt_count} attempts: {error_message}"
            )
            
            # Trigger failure callbacks
            for callback in self._on_failure_callbacks:
                try:
                    callback(item, error_message or "Unknown error")
                except Exception as e:
                    logger.error(f"Failure callback error: {str(e)}")
    
    def _scheduler_loop(self) -> None:
        """Scheduler loop to process scheduled items"""
        logger.debug("Scheduler started")
        
        while not self._shutdown_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                
                # Check scheduled items
                with self._items_lock:
                    ready_items = [
                        (id, item) for id, item in self._scheduled.items()
                        if item.scheduled_at and item.scheduled_at <= now
                    ]
                    
                    for item_id, item in ready_items:
                        item.status = QueueItemStatus.PENDING
                        self._scheduled.pop(item_id, None)
                        self._queue.put(item)
                        logger.debug(f"Scheduled item {item_id} moved to queue")
                
            except Exception as e:
                logger.error(f"Scheduler error: {str(e)}")
            
            time.sleep(1)  # Check every second
        
        logger.debug("Scheduler stopped")
    
    def __enter__(self) -> 'NotificationQueueService':
        """Context manager entry"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit"""
        self.stop(wait=True)


# ============================================================================
# BATCH OPERATIONS
# ============================================================================

class BatchNotificationService:
    """
    Service for sending batch notifications efficiently.
    
    Use cases:
    - Marketing campaigns
    - System-wide announcements
    - Scheduled reports
    """
    
    def __init__(
        self,
        queue_service: NotificationQueueService,
        batch_size: int = QueueConfig.BATCH_SIZE
    ):
        self._queue_service = queue_service
        self._batch_size = batch_size
    
    def send_batch(
        self,
        requests: List[NotificationRequest],
        priority: NotificationPriority = NotificationPriority.LOW,
        stagger_seconds: float = 0.0
    ) -> Dict[str, Any]:
        """
        Queue a batch of notifications.
        
        Args:
            requests: List of NotificationRequests
            priority: Priority for all items
            stagger_seconds: Delay between scheduling each item
        
        Returns:
            Dict with batch_id and item_ids
        """
        batch_id = generate_id('BATCH')
        item_ids = []
        
        scheduled_at = datetime.now(timezone.utc)
        
        for i, request in enumerate(requests):
            if stagger_seconds > 0:
                scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=i * stagger_seconds)
            
            item_id = self._queue_service.enqueue(
                request=request,
                priority=priority,
                scheduled_at=scheduled_at if stagger_seconds > 0 else None,
                correlation_id=batch_id
            )
            item_ids.append(item_id)
        
        logger.info(f"Batch {batch_id}: queued {len(requests)} notifications")
        
        return {
            'batch_id': batch_id,
            'item_count': len(requests),
            'item_ids': item_ids
        }
    
    def get_batch_status(self, batch_id: str) -> Dict[str, Any]:
        """Get status of all items in a batch"""
        stats = self._queue_service.get_stats()
        
        # Get items with this correlation_id
        items = []
        with self._queue_service._items_lock:
            for item in self._queue_service._items.values():
                if item.correlation_id == batch_id:
                    items.append(item.to_dict())
        
        status_counts = {}
        for item in items:
            status = item['status']
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            'batch_id': batch_id,
            'total_items': len(items),
            'status_breakdown': status_counts,
            'items': items
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'QueueConfig',
    'QueueItemStatus',
    'QueueItem',
    'QueueStats',
    'NotificationQueueService',
    'BatchNotificationService',
]
