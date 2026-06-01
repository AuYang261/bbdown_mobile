"""Task queue with SSE pub/sub for real-time progress updates."""

import logging
import queue
import threading
import uuid

logger = logging.getLogger("bbdown")


class SSESubscription:
    """A subscription to SSE events for a specific task or global events.

    Created via TaskQueue.sse_subscribe_task() or sse_subscribe_global().
    Call wait() to block until an event arrives, then close() when done.
    """

    def __init__(self, tq: "TaskQueue", task_id: str | None):
        self._tq = tq
        self._task_id = task_id
        self._queue: queue.Queue = queue.Queue()
        self._closed = False
        with tq._listeners_lock:
            if task_id is None:
                tq._global_listeners.append(self._queue)
            else:
                tq._task_listeners.setdefault(task_id, []).append(self._queue)

    def wait(self, timeout: float = 30) -> dict | None:
        """Block until an event arrives or timeout expires.

        Returns {"event": ..., "data": ...} or None on timeout/close.
        """
        if self._closed:
            return None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        """Unregister this subscription and release resources."""
        if self._closed:
            return
        self._closed = True
        with self._tq._listeners_lock:
            if self._task_id is None:
                try:
                    self._tq._global_listeners.remove(self._queue)
                except ValueError:
                    pass
            else:
                listeners = self._tq._task_listeners.get(self._task_id)
                if listeners:
                    try:
                        listeners.remove(self._queue)
                    except ValueError:
                        pass


class TaskQueue:
    """Thread-safe task queue for downloads and logins with SSE pub/sub.

    Tasks are stored in _tasks dict keyed by 12-char hex ID.
    Pending tasks are tracked in _pending_order (FIFO).
    SSE events are pushed to global/per-task listeners.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._pending_order: list[str] = []
        self._lock = threading.Lock()
        self._listeners_lock = threading.Lock()
        self._global_listeners: list[queue.Queue] = []
        self._task_listeners: dict[str, list[queue.Queue]] = {}

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _generate_id(self) -> str:
        return uuid.uuid4().hex[:12]

    # ------------------------------------------------------------------
    # task creation
    # ------------------------------------------------------------------

    def add_download(self, url: str, mode: str, username: str) -> str:
        """Create a pending download task.  Returns the new task ID."""
        tid = self._generate_id()
        task: dict = {
            "id": tid,
            "type": "download",
            "url": url,
            "mode": mode,
            "username": username,
            "status": "pending",
        }
        with self._lock:
            self._tasks[tid] = task
            self._pending_order.append(tid)
        logger.info(
            "Download task created: id=%s url=%s mode=%s user=%s",
            tid, url, mode, username,
        )
        return tid

    def add_login(self) -> str:
        """Create a pending login task.  Returns the new task ID."""
        tid = self._generate_id()
        task: dict = {
            "id": tid,
            "type": "login",
            "status": "pending",
        }
        with self._lock:
            self._tasks[tid] = task
            self._pending_order.append(tid)
        logger.info("Login task created: id=%s", tid)
        return tid

    # ------------------------------------------------------------------
    # task access
    # ------------------------------------------------------------------

    def get(self, tid: str) -> dict | None:
        """Return the task dict for *tid*, or None."""
        with self._lock:
            return self._tasks.get(tid)

    def list_all(self) -> list[dict]:
        """Return a shallow copy of all tasks."""
        with self._lock:
            return list(self._tasks.values())

    def pop_pending(self) -> dict | None:
        """Remove and return the **oldest** pending task, or None."""
        with self._lock:
            if not self._pending_order:
                return None
            tid = self._pending_order.pop(0)
            return self._tasks.get(tid)

    def pending_count(self) -> int:
        """Return the number of tasks still in pending state."""
        with self._lock:
            return len(self._pending_order)

    def update(self, tid: str, **kwargs) -> None:
        """Merge *kwargs* into the task dict identified by *tid*."""
        with self._lock:
            task = self._tasks.get(tid)
            if task is not None:
                task.update(kwargs)

    # ------------------------------------------------------------------
    # SSE pub/sub
    # ------------------------------------------------------------------

    def sse_subscribe_global(self) -> SSESubscription:
        """Subscribe to all global SSE events."""
        return SSESubscription(self, None)

    def sse_subscribe_task(self, tid: str) -> SSESubscription:
        """Subscribe to SSE events for a specific task."""
        return SSESubscription(self, tid)

    def sse_publish_task(self, tid: str, event: str, data: dict) -> None:
        """Push an event to every subscriber of *tid*."""
        with self._listeners_lock:
            listeners = list(self._task_listeners.get(tid, []))
        message = {"event": event, "data": data}
        for q in listeners:
            try:
                q.put_nowait(message)
            except queue.Full:
                pass

    def sse_publish_global(self, event: str, data: dict) -> None:
        """Push an event to every global subscriber."""
        with self._listeners_lock:
            listeners = list(self._global_listeners)
        message = {"event": event, "data": data}
        for q in listeners:
            try:
                q.put_nowait(message)
            except queue.Full:
                pass
