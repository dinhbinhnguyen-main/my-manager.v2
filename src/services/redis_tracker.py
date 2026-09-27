"""Redis Tracker service for cross-terminal live monitoring of automation jobs."""

import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

REDIS_CHANNEL = "my_manager:events"


class RedisTracker:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self._client = None
        self._connected = False
        self._init_connection()

    def _init_connection(self):
        try:
            import redis
            self._client = redis.Redis(host=self.host, port=self.port, db=self.db, decode_responses=True, socket_timeout=2.0)
            self._client.ping()
            self._connected = True
            logger.info("Connected to Redis server for job tracking.")
        except Exception as e:
            self._connected = False
            logger.warning(f"Redis connection unavailable ({e}). Live tracking will be limited to SQLite fallback.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def publish_event(self, event_type: str, data: Dict[str, Any]):
        """Publishes an event payload to Redis Pub/Sub channel."""
        if not self._connected or not self._client:
            return
        try:
            payload = json.dumps({"event": event_type, **data})
            self._client.publish(REDIS_CHANNEL, payload)
        except Exception as e:
            logger.warning(f"Failed to publish event to Redis: {e}")

    def update_job_state(
        self,
        job_id: int,
        account_uid: str,
        status: str,
        current_step: int = 0,
        total_steps: int = 1,
        current_action: str = "",
        container_id: str = "",
        message: str = "",
    ):
        """Updates job status hash in Redis and broadcasts event."""
        key = f"my_manager:job:{job_id}"
        state = {
            "job_id": str(job_id),
            "account_uid": account_uid,
            "status": status,
            "current_step": str(current_step),
            "total_steps": str(total_steps),
            "current_action": current_action,
            "container_id": container_id,
            "message": message,
        }

        if self._connected and self._client:
            try:
                self._client.hset(key, mapping=state)
                # Set TTL 24 hours
                self._client.expire(key, 86400)
            except Exception as e:
                logger.warning(f"Failed to set Redis hash for job {job_id}: {e}")

        # Broadcast event
        self.publish_event("job_update", state)

    def get_all_active_jobs(self) -> List[Dict[str, str]]:
        """Scans Redis for active job states."""
        if not self._connected or not self._client:
            return []
        try:
            keys = self._client.keys("my_manager:job:*")
            results = []
            for k in keys:
                data = self._client.hgetall(k)
                if data:
                    results.append(data)
            return results
        except Exception as e:
            logger.warning(f"Failed to fetch active jobs from Redis: {e}")
            return []

    def subscribe_events(self):
        """Returns a Redis Pub/Sub pubsub listener object."""
        if not self._connected or not self._client:
            return None
        try:
            pubsub = self._client.pubsub()
            pubsub.subscribe(REDIS_CHANNEL)
            return pubsub
        except Exception as e:
            logger.warning(f"Failed to subscribe to Redis channel: {e}")
            return None
