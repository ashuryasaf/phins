"""
PHINS Scalability & Caching Module
Optimized for millions of concurrent users
Lightweight, dependency-free caching and performance monitoring
"""

from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from collections import OrderedDict
import threading
import time
from config import PHINSConfig, CacheStrategy


class SimpleCache:
    """Lightweight in-memory cache with TTL support"""
    
    def __init__(self, max_size: int = 10000):
        self.cache: OrderedDict = OrderedDict()
        self.ttl_map: Dict[str, float] = {}
        self.max_size = max_size
        self.lock = threading.RLock()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache, returns None if expired"""
        with self.lock:
            if key not in self.cache:
                self.stats["misses"] += 1
                return default
            
            # Check if expired
            if key in self.ttl_map:
                if time.time() > self.ttl_map[key]:
                    del self.cache[key]
                    del self.ttl_map[key]
                    self.stats["misses"] += 1
                    return default
            
            # Move to end (LRU)
            self.cache.move_to_end(key)
            self.stats["hits"] += 1
            return self.cache[key]
    
    def set(self, key: str, value: Any, ttl_seconds: int = 3600):
        """Store value in cache with optional TTL"""
        with self.lock:
            # Remove oldest if at capacity
            if len(self.cache) >= self.max_size and key not in self.cache:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                self.ttl_map.pop(oldest_key, None)
                self.stats["evictions"] += 1
            
            self.cache[key] = value
            if ttl_seconds > 0:
                self.ttl_map[key] = time.time() + ttl_seconds
    
    def delete(self, key: str):
        """Delete key from cache"""
        with self.lock:
            self.cache.pop(key, None)
            self.ttl_map.pop(key, None)
    
    def clear(self):
        """Clear entire cache"""
        with self.lock:
            self.cache.clear()
            self.ttl_map.clear()
            self.stats = {"hits": 0, "misses": 0, "evictions": 0}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self.lock:
            total = self.stats["hits"] + self.stats["misses"]
            hit_rate = (self.stats["hits"] / total * 100) if total > 0 else 0
            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "evictions": self.stats["evictions"],
                "hit_rate": round(hit_rate, 2),
            }


class QueryOptimizer:
    """Optimize database queries for high-volume scenarios"""
    
    def __init__(self):
        self.query_stats: Dict[str, Dict] = {}
        self.slow_query_threshold_ms = 1000
        self.lock = threading.RLock()
    
    def paginate(self, items: List[Any], page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Paginate results efficiently"""
        total = len(items)
        max_page = (total + page_size - 1) // page_size
        
        if page < 1:
            page = 1
        elif page > max_page and max_page > 0:
            page = max_page
        
        start = (page - 1) * page_size
        end = start + page_size
        
        return {
            "items": items[start:end],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max_page,
            "has_next": page < max_page,
            "has_previous": page > 1,
        }
    
    def batch_process(self, items: List[Any], batch_size: int, 
                     processor: Callable) -> List[Any]:
        """Process items in batches to reduce memory pressure"""
        results = []
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            results.extend(processor(batch))
        return results
    
    def record_query(self, query_name: str, duration_ms: float):
        """Record query performance"""
        with self.lock:
            if query_name not in self.query_stats:
                self.query_stats[query_name] = {
                    "count": 0,
                    "total_ms": 0,
                    "avg_ms": 0,
                    "max_ms": 0,
                    "min_ms": float('inf'),
                    "slow_count": 0,
                }
            
            stats = self.query_stats[query_name]
            stats["count"] += 1
            stats["total_ms"] += duration_ms
            stats["avg_ms"] = stats["total_ms"] / stats["count"]
            stats["max_ms"] = max(stats["max_ms"], duration_ms)
            stats["min_ms"] = min(stats["min_ms"], duration_ms)
            
            if duration_ms > self.slow_query_threshold_ms:
                stats["slow_count"] += 1
    
    def get_query_stats(self) -> Dict[str, Dict]:
        """Get query performance statistics"""
        with self.lock:
            return dict(self.query_stats)
    
    def get_slow_queries(self) -> List[tuple]:
        """Get queries exceeding threshold"""
        with self.lock:
            slow = []
            for query, stats in self.query_stats.items():
                if stats["slow_count"] > 0:
                    slow.append((query, stats))
            return sorted(slow, key=lambda x: x[1]["avg_ms"], reverse=True)


class PerformanceMonitor:
    """Monitor system performance metrics"""
    
    def __init__(self):
        self.metrics: Dict[str, List[float]] = {}
        self.start_time = datetime.now()
        self.lock = threading.RLock()
    
    def record_metric(self, metric_name: str, value: float):
        """Record a performance metric"""
        with self.lock:
            if metric_name not in self.metrics:
                self.metrics[metric_name] = []
            self.metrics[metric_name].append(value)
    
    def get_metric_summary(self, metric_name: str) -> Dict[str, float]:
        """Get statistics for a metric"""
        with self.lock:
            if metric_name not in self.metrics:
                return {}
            
            values = self.metrics[metric_name]
            if not values:
                return {}
            
            return {
                "count": len(values),
                "average": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "total": sum(values),
            }
    
    def get_uptime(self) -> Dict[str, Any]:
        """Get system uptime"""
        uptime = datetime.now() - self.start_time
        return {
            "start_time": self.start_time.isoformat(),
            "uptime_seconds": uptime.total_seconds(),
            "uptime_readable": str(uptime).split(".")[0],
        }
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get overall system health"""
        return {
            "status": "healthy",
            "uptime": self.get_uptime(),
            "timestamp": datetime.now().isoformat(),
        }


class RateLimiter:
    """Simple rate limiting for API and user actions"""
    
    def __init__(self, requests_per_hour: int = 1000):
        self.requests_per_hour = requests_per_hour
        self.user_requests: Dict[str, List[float]] = {}
        self.lock = threading.RLock()
    
    def is_allowed(self, user_id: str) -> bool:
        """Check if user is within rate limit"""
        with self.lock:
            now = time.time()
            hour_ago = now - 3600
            
            if user_id not in self.user_requests:
                self.user_requests[user_id] = []
            
            # Remove old requests
            self.user_requests[user_id] = [
                req_time for req_time in self.user_requests[user_id]
                if req_time > hour_ago
            ]
            
            # Check limit
            if len(self.user_requests[user_id]) >= self.requests_per_hour:
                return False
            
            # Record new request
            self.user_requests[user_id].append(now)
            return True
    
    def get_remaining(self, user_id: str) -> int:
        """Get remaining requests for user"""
        with self.lock:
            now = time.time()
            hour_ago = now - 3600
            
            if user_id not in self.user_requests:
                return self.requests_per_hour
            
            recent = [
                req_time for req_time in self.user_requests[user_id]
                if req_time > hour_ago
            ]
            return max(0, self.requests_per_hour - len(recent))


class ConnectionPool:
    """Lightweight connection pool simulator"""
    
    def __init__(self, pool_size: int = 20):
        self.pool_size = pool_size
        self.available = pool_size
        self.lock = threading.RLock()
    
    def acquire(self) -> bool:
        """Try to acquire a connection"""
        with self.lock:
            if self.available > 0:
                self.available -= 1
                return True
            return False
    
    def release(self):
        """Release a connection back to pool"""
        with self.lock:
            if self.available < self.pool_size:
                self.available += 1
    
    def get_stats(self) -> Dict[str, int]:
        """Get pool statistics"""
        with self.lock:
            return {
                "total": self.pool_size,
                "available": self.available,
                "in_use": self.pool_size - self.available,
            }


# Global instances
_cache: Optional[SimpleCache] = None
_query_optimizer: Optional[QueryOptimizer] = None
_performance_monitor: Optional[PerformanceMonitor] = None
_rate_limiter: Optional[RateLimiter] = None
_connection_pool: Optional[ConnectionPool] = None


def get_cache() -> SimpleCache:
    """Get global cache instance"""
    global _cache
    if _cache is None:
        _cache = SimpleCache(max_size=PHINSConfig.CACHE_MAX_SIZE)
    return _cache


def get_query_optimizer() -> QueryOptimizer:
    """Get global query optimizer"""
    global _query_optimizer
    if _query_optimizer is None:
        _query_optimizer = QueryOptimizer()
    return _query_optimizer


def get_performance_monitor() -> PerformanceMonitor:
    """Get global performance monitor"""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(requests_per_hour=PHINSConfig.API_RATE_LIMIT)
    return _rate_limiter


def get_connection_pool() -> ConnectionPool:
    """Get global connection pool"""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = ConnectionPool(pool_size=PHINSConfig.DATABASE_POOL_SIZE)
    return _connection_pool


# Export main components
__all__ = [
    'SimpleCache',
    'QueryOptimizer',
    'PerformanceMonitor',
    'RateLimiter',
    'ConnectionPool',
    'get_cache',
    'get_query_optimizer',
    'get_performance_monitor',
    'get_rate_limiter',
    'get_connection_pool',
]
