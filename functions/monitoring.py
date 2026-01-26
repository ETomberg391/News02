#!/usr/bin/env python3
"""
Comprehensive Monitoring System for News02
Provides metrics, logging, and health monitoring
"""

import logging
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, asdict
from collections import defaultdict
import threading
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Metric:
    """Represents a single metric"""
    name: str
    value: float
    timestamp: datetime
    tags: Dict[str, str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to dictionary"""
        return {
            'name': self.name,
            'value': self.value,
            'timestamp': self.timestamp.isoformat(),
            'tags': self.tags or {}
        }


@dataclass
class PerformanceMetric:
    """Performance metrics for operations"""
    operation: str
    duration_ms: float
    success: bool
    timestamp: datetime
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert performance metric to dictionary"""
        return {
            'operation': self.operation,
            'duration_ms': self.duration_ms,
            'success': self.success,
            'timestamp': self.timestamp.isoformat(),
            'error_message': self.error_message
        }


class MetricsCollector:
    """Collects and manages application metrics"""
    
    def __init__(self, max_metrics: int = 10000) -> None:
        """Initialize metrics collector
        
        Args:
            max_metrics: Maximum number of metrics to keep in memory
        """
        self.max_metrics = max_metrics
        self.metrics: List[Metric] = []
        self.performance_metrics: List[PerformanceMetric] = []
        self._lock = threading.Lock()
        self._start_time = time.time()
        
        # Counters for different metric types
        self.counters: Dict[str, int] = defaultdict(int)
        self.gauges: Dict[str, float] = {}
        
        logger.info("Metrics collector initialized")
    
    def record_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a metric
        
        Args:
            name: Metric name
            value: Metric value
            tags: Optional tags for filtering
        """
        with self._lock:
            metric = Metric(
                name=name,
                value=value,
                timestamp=datetime.now(),
                tags=tags or {}
            )
            self.metrics.append(metric)
            
            # Update counters and gauges
            if name.startswith('counter.'):
                counter_name = name.replace('counter.', '')
                self.counters[counter_name] += int(value)
            elif name.startswith('gauge.'):
                gauge_name = name.replace('gauge.', '')
                self.gauges[gauge_name] = value
            
            # Trim if exceeds max
            if len(self.metrics) > self.max_metrics:
                self.metrics = self.metrics[-self.max_metrics:]
    
    def record_performance(self, operation: str, duration_ms: float, success: bool, error_message: Optional[str] = None) -> None:
        """Record performance metric
        
        Args:
            operation: Operation name
            duration_ms: Duration in milliseconds
            success: Whether operation succeeded
            error_message: Optional error message
        """
        with self._lock:
            metric = PerformanceMetric(
                operation=operation,
                duration_ms=duration_ms,
                success=success,
                timestamp=datetime.now(),
                error_message=error_message
            )
            self.performance_metrics.append(metric)
            
            # Trim if exceeds max
            if len(self.performance_metrics) > self.max_metrics:
                self.performance_metrics = self.performance_metrics[-self.max_metrics:]
    
    def increment_counter(self, name: str, value: int = 1) -> None:
        """Increment a counter
        
        Args:
            name: Counter name
            value: Amount to increment
        """
        self.record_metric(f"counter.{name}", value)
    
    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge value
        
        Args:
            name: Gauge name
            value: Gauge value
        """
        self.record_metric(f"gauge.{name}", value)
    
    def get_metrics(self, name: Optional[str] = None, since: Optional[datetime] = None) -> List[Metric]:
        """Get metrics with optional filters
        
        Args:
            name: Filter by metric name
            since: Filter by timestamp
            
        Returns:
            List of matching metrics
        """
        with self._lock:
            metrics = self.metrics
            
            if name:
                metrics = [m for m in metrics if m.name == name]
            
            if since:
                metrics = [m for m in metrics if m.timestamp >= since]
            
            return metrics.copy()
    
    def get_performance_metrics(self, operation: Optional[str] = None, since: Optional[datetime] = None) -> List[PerformanceMetric]:
        """Get performance metrics with optional filters
        
        Args:
            operation: Filter by operation name
            since: Filter by timestamp
            
        Returns:
            List of matching performance metrics
        """
        with self._lock:
            metrics = self.performance_metrics
            
            if operation:
                metrics = [m for m in metrics if m.operation == operation]
            
            if since:
                metrics = [m for m in metrics if m.timestamp >= since]
            
            return metrics.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about collected metrics
        
        Returns:
            Dictionary with statistics
        """
        with self._lock:
            # Calculate performance statistics
            perf_stats = {}
            for metric in self.performance_metrics:
                if metric.operation not in perf_stats:
                    perf_stats[metric.operation] = {
                        'count': 0,
                        'total_duration': 0,
                        'success_count': 0,
                        'error_count': 0,
                        'errors': []
                    }
                
                stats = perf_stats[metric.operation]
                stats['count'] += 1
                stats['total_duration'] += metric.duration_ms
                if metric.success:
                    stats['success_count'] += 1
                else:
                    stats['error_count'] += 1
                    if metric.error_message:
                        stats['errors'].append(metric.error_message)
            
            # Calculate averages
            for op, stats in perf_stats.items():
                stats['avg_duration_ms'] = stats['total_duration'] / stats['count'] if stats['count'] > 0 else 0
                stats['success_rate'] = stats['success_count'] / stats['count'] if stats['count'] > 0 else 0
            
            return {
                'total_metrics': len(self.metrics),
                'total_performance_metrics': len(self.performance_metrics),
                'uptime_seconds': time.time() - self._start_time,
                'counters': dict(self.counters),
                'gauges': dict(self.gauges),
                'performance_stats': perf_stats
            }
    
    def export_metrics(self, filepath: str) -> None:
        """Export metrics to JSON file
        
        Args:
            filepath: Path to export file
        """
        with self._lock:
            data = {
                'metrics': [m.to_dict() for m in self.metrics],
                'performance_metrics': [m.to_dict() for m in self.performance_metrics],
                'stats': self.get_stats(),
                'exported_at': datetime.now().isoformat()
            }
            
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Exported {len(self.metrics)} metrics to {filepath}")


class PerformanceTimer:
    """Context manager for timing operations"""
    
    def __init__(self, operation: str, metrics_collector: MetricsCollector) -> None:
        """Initialize performance timer
        
        Args:
            operation: Operation name
            metrics_collector: Metrics collector instance
        """
        self.operation = operation
        self.metrics_collector = metrics_collector
        self.start_time: Optional[float] = None
    
    def __enter__(self) -> 'PerformanceTimer':
        """Start timing"""
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Stop timing and record metric"""
        if self.start_time is None:
            return False
        
        duration_ms = (time.time() - self.start_time) * 1000
        success = exc_type is None
        error_message = str(exc_val) if exc_val else None
        
        self.metrics_collector.record_performance(
            operation=self.operation,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message
        )
        
        return False  # Don't suppress exceptions


class HealthMonitor:
    """Monitors system health and provides health checks"""
    
    def __init__(self, metrics_collector: MetricsCollector) -> None:
        """Initialize health monitor
        
        Args:
            metrics_collector: Metrics collector instance
        """
        self.metrics_collector = metrics_collector
        self.health_checks: Dict[str, Callable] = {}
        self._start_time = time.time()
        
        logger.info("Health monitor initialized")
    
    def register_health_check(self, name: str, check_func: Callable) -> None:
        """Register a health check function
        
        Args:
            name: Name of the health check
            check_func: Function that returns (status, message)
        """
        self.health_checks[name] = check_func
        logger.info(f"Registered health check: {name}")
    
    async def run_health_checks(self) -> Dict[str, Any]:
        """Run all registered health checks
        
        Returns:
            Dictionary with health check results
        """
        results = {}
        
        for name, check_func in self.health_checks.items():
            try:
                if asyncio.iscoroutinefunction(check_func):
                    status, message = await check_func()
                else:
                    status, message = check_func()
                
                results[name] = {
                    'status': status,
                    'message': message,
                    'timestamp': datetime.now().isoformat()
                }
                
                # Record metric
                self.metrics_collector.record_metric(
                    f"health.{name}",
                    1 if status == 'healthy' else 0
                )
                
            except Exception as e:
                results[name] = {
                    'status': 'critical',
                    'message': f'Health check failed: {str(e)}',
                    'timestamp': datetime.now().isoformat()
                }
                logger.error(f"Health check {name} failed: {e}")
        
        # Determine overall health
        statuses = [r['status'] for r in results.values()]
        if 'critical' in statuses:
            overall_status = 'critical'
        elif 'degraded' in statuses:
            overall_status = 'degraded'
        else:
            overall_status = 'healthy'
        
        return {
            'overall_status': overall_status,
            'checks': results,
            'uptime_seconds': time.time() - self._start_time,
            'timestamp': datetime.now().isoformat()
        }


class AlertManager:
    """Manages alerts and notifications"""
    
    def __init__(self, metrics_collector: MetricsCollector) -> None:
        """Initialize alert manager
        
        Args:
            metrics_collector: Metrics collector instance
        """
        self.metrics_collector = metrics_collector
        self.alert_rules: List[Dict[str, Any]] = []
        self.alerts: List[Dict[str, Any]] = []
        self._alert_handlers: List[Callable] = []
        
        logger.info("Alert manager initialized")
    
    def add_alert_rule(self, rule: Dict[str, Any]) -> None:
        """Add an alert rule
        
        Args:
            rule: Alert rule configuration
        """
        self.alert_rules.append(rule)
        logger.info(f"Added alert rule: {rule.get('name', 'unnamed')}")
    
    def register_alert_handler(self, handler: Callable) -> None:
        """Register an alert handler function
        
        Args:
            handler: Function to handle alerts
        """
        self._alert_handlers.append(handler)
        logger.info("Registered alert handler")
    
    def check_alerts(self) -> List[Dict[str, Any]]:
        """Check all alert rules and trigger alerts if needed
        
        Returns:
            List of triggered alerts
        """
        triggered_alerts = []
        
        for rule in self.alert_rules:
            try:
                # Get metric value
                metric_name = rule.get('metric')
                metric_value = None
                
                if metric_name:
                    metrics = self.metrics_collector.get_metrics(name=metric_name, since=datetime.now() - timedelta(minutes=5))
                    if metrics:
                        metric_value = metrics[-1].value
                
                # Check condition
                condition = rule.get('condition')
                threshold = rule.get('threshold')
                
                should_alert = False
                if condition == 'greater_than' and metric_value is not None:
                    should_alert = metric_value > threshold
                elif condition == 'less_than' and metric_value is not None:
                    should_alert = metric_value < threshold
                elif condition == 'equal_to' and metric_value is not None:
                    should_alert = abs(metric_value - threshold) < 0.001
                
                if should_alert:
                    alert = {
                        'rule': rule.get('name', 'unnamed'),
                        'metric': metric_name,
                        'value': metric_value,
                        'threshold': threshold,
                        'condition': condition,
                        'timestamp': datetime.now().isoformat(),
                        'severity': rule.get('severity', 'warning')
                    }
                    
                    self.alerts.append(alert)
                    triggered_alerts.append(alert)
                    
                    # Call alert handlers
                    for handler in self._alert_handlers:
                        try:
                            handler(alert)
                        except Exception as e:
                            logger.error(f"Alert handler failed: {e}")
                    
                    logger.warning(f"Alert triggered: {alert['rule']}")
                    
            except Exception as e:
                logger.error(f"Error checking alert rule: {e}")
        
        return triggered_alerts
    
    def get_alerts(self, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get alerts with optional time filter
        
        Args:
            since: Filter alerts since timestamp
            
        Returns:
            List of alerts
        """
        if since:
            return [a for a in self.alerts if datetime.fromisoformat(a['timestamp']) >= since]
        return self.alerts.copy()


class Monitoring:
    """Main monitoring class that aggregates all monitoring components"""
    
    def __init__(self) -> None:
        """Initialize monitoring system with all components"""
        self.metrics_collector = MetricsCollector()
        self.health_monitor = HealthMonitor(self.metrics_collector)
        self.alert_manager = AlertManager(self.metrics_collector)
        logger.info("Monitoring system initialized")
    
    async def run_health_checks(self) -> Dict[str, Any]:
        """Run all registered health checks
        
        Returns:
            Dictionary with health check results
        """
        return await self.health_monitor.run_health_checks()
    
    def check_alerts(self) -> List[Dict[str, Any]]:
        """Check all alert rules and trigger alerts if needed
        
        Returns:
            List of triggered alerts
        """
        return self.alert_manager.check_alerts()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about collected metrics
        
        Returns:
            Dictionary with statistics
        """
        return self.metrics_collector.get_stats()
    
    def export_metrics(self, filepath: str) -> None:
        """Export metrics to JSON file
        
        Args:
            filepath: Path to export file
        """
        self.metrics_collector.export_metrics(filepath)


# Global monitoring instances
metrics_collector = MetricsCollector()
health_monitor = HealthMonitor(metrics_collector)
alert_manager = AlertManager(metrics_collector)


# Default health checks
async def check_database_health() -> tuple:
    """Check database health"""
    try:
        from functions.database import NewsDatabase
        from functions.config_manager import config_manager
        
        db_config = config_manager.get_database_config()
        if not db_config['enabled']:
            return 'degraded', 'Database is disabled'
        
        db = NewsDatabase(db_config['path'])
        # Test connection
        import sqlite3
        conn = sqlite3.connect(db.db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        
        return 'healthy', 'Database connection successful'
    except Exception as e:
        return 'critical', f'Database connection failed: {str(e)}'


async def check_llm_health() -> tuple:
    """Check LLM provider health"""
    try:
        from functions.llm_client import LLMFactory
        from functions.config_manager import config_manager
        
        llm_client = LLMFactory.create_client(config_manager.llm_provider)
        
        # Test with a simple prompt
        messages = [{"role": "user", "content": "Hello"}]
        model_config = config_manager.get_model_config('default_model')
        
        # This will test the connection
        llm_client.chat_completion(messages, model_config)
        
        return 'healthy', 'LLM provider connection successful'
    except Exception as e:
        return 'critical', f'LLM provider connection failed: {str(e)}'


async def check_disk_space() -> tuple:
    """Check disk space"""
    try:
        import psutil
        disk_usage = psutil.disk_usage('/')
        
        if disk_usage.percent > 95:
            return 'critical', f'Disk space critical: {disk_usage.percent}% used'
        elif disk_usage.percent > 90:
            return 'degraded', f'Disk space low: {disk_usage.percent}% used'
        else:
            return 'healthy', f'Disk space OK: {disk_usage.percent}% used'
    except Exception as e:
        return 'degraded', f'Could not check disk space: {str(e)}'


async def check_memory_usage() -> tuple:
    """Check memory usage"""
    try:
        import psutil
        memory = psutil.virtual_memory()
        
        if memory.percent > 95:
            return 'critical', f'Memory critical: {memory.percent}% used'
        elif memory.percent > 90:
            return 'degraded', f'Memory low: {memory.percent}% used'
        else:
            return 'healthy', f'Memory OK: {memory.percent}% used'
    except Exception as e:
        return 'degraded', f'Could not check memory: {str(e)}'


async def check_job_scheduler_health() -> tuple:
    """Check job scheduler health"""
    try:
        from functions.job_scheduler import job_scheduler
        
        if job_scheduler.running:
            return 'healthy', 'Job scheduler is running'
        else:
            return 'critical', 'Job scheduler is not running'
    except Exception as e:
        return 'critical', f'Job scheduler check failed: {str(e)}'


# Register default health checks
async def register_default_health_checks() -> None:
    """Register default health checks"""
    health_monitor.register_health_check('database', check_database_health)
    health_monitor.register_health_check('llm_provider', check_llm_health)
    health_monitor.register_health_check('disk_space', check_disk_space)
    health_monitor.register_health_check('memory', check_memory_usage)
    health_monitor.register_health_check('job_scheduler', check_job_scheduler_health)
    logger.info("Default health checks registered")


# Default alert rules
def register_default_alert_rules() -> None:
    """Register default alert rules"""
    alert_manager.add_alert_rule({
        'name': 'high_cpu_usage',
        'metric': 'gauge.cpu_percent',
        'condition': 'greater_than',
        'threshold': 90,
        'severity': 'warning'
    })
    
    alert_manager.add_alert_rule({
        'name': 'high_memory_usage',
        'metric': 'gauge.memory_percent',
        'condition': 'greater_than',
        'threshold': 90,
        'severity': 'warning'
    })
    
    alert_manager.add_alert_rule({
        'name': 'low_disk_space',
        'metric': 'gauge.disk_percent',
        'condition': 'greater_than',
        'threshold': 90,
        'severity': 'warning'
    })
    
    alert_manager.add_alert_rule({
        'name': 'high_error_rate',
        'metric': 'counter.errors',
        'condition': 'greater_than',
        'threshold': 10,
        'severity': 'critical'
    })
    
    logger.info("Default alert rules registered")


# Alert handler
def alert_handler(alert: Dict[str, Any]) -> None:
    """Handle alerts by logging them"""
    logger.warning(f"ALERT: {alert['rule']} - {alert['message']}")
    # In production, this could send emails, Slack messages, etc.


# Register alert handler
alert_manager.register_alert_handler(alert_handler)


# Performance monitoring decorator
def monitor_performance(operation_name: str):
    """Decorator to monitor performance of functions"""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            with PerformanceTimer(operation_name, metrics_collector):
                return func(*args, **kwargs)
        return wrapper
    return decorator


# Async performance monitoring decorator
def monitor_performance_async(operation_name: str):
    """Decorator to monitor performance of async functions"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            with PerformanceTimer(operation_name, metrics_collector):
                return await func(*args, **kwargs)
        return wrapper
    return decorator


# Example usage
async def example_monitoring() -> None:
    """Example of using the monitoring system"""
    # Register health checks
    await register_default_health_checks()
    
    # Register alert rules
    register_default_alert_rules()
    
    # Record some metrics
    metrics_collector.increment_counter('articles_processed', 10)
    metrics_collector.set_gauge('queue_size', 5)
    metrics_collector.record_metric('processing_time', 150.5, {'operation': 'summarize'})
    
    # Run health checks
    health_status = await health_monitor.run_health_checks()
    print(f"Health status: {json.dumps(health_status, indent=2)}")
    
    # Check alerts
    alerts = alert_manager.check_alerts()
    if alerts:
        print(f"Alerts triggered: {json.dumps(alerts, indent=2)}")
    
    # Get stats
    stats = metrics_collector.get_stats()
    print(f"Stats: {json.dumps(stats, indent=2)}")
    
    # Export metrics
    metrics_collector.export_metrics('data/metrics_export.json')


if __name__ == "__main__":
    asyncio.run(example_monitoring())
