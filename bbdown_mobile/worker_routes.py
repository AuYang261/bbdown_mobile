"""Worker-facing API routes — long-poll, progress updates, file upload.

The worker (downloader) talks to this blueprint at /api/worker/*.
It authenticates via Authorization: Bearer <SECRET_TOKEN>.
"""

import logging
import os
import threading
import time as _time
import uuid as _uuid

from flask import Blueprint, request, current_app, jsonify
from werkzeug.utils import secure_filename

logger = logging.getLogger("bbdown")
audit = logging.getLogger("bbdown.audit")
worker_bp = Blueprint("worker", __name__, url_prefix="/api/worker")

# ---- shared event for waking up long-poll requests ----
_poll_event = threading.Event()


# ------------------------------------------------------------------
# auth guard — every worker endpoint requires the secret token
# ------------------------------------------------------------------
@worker_bp.before_request
def _check_auth():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"error": "forbidden"}, 403
    if auth[7:] != current_app.config["SECRET_TOKEN"]:
        return {"error": "forbidden"}, 403
    return None  # allow request to proceed


# ------------------------------------------------------------------
# public helper called by api_routes when a new task is submitted
# ------------------------------------------------------------------
def notify_worker():
    """Wake up any outstanding long-poll request."""
    _poll_event.set()


# ------------------------------------------------------------------
# long-poll endpoint — worker blocks here waiting for new tasks
# ------------------------------------------------------------------
@worker_bp.route("/poll")
def worker_poll():
    """Worker polls for the next task.

    Query params:
        logged_in_users= (optional)  comma-separated usernames with valid BBDown.data
    Returns:
        A task dict immediately if one is available, otherwise blocks for up
        to 60 s.  If no task arrives, returns {"type":"wait","retry_after":5}.
    """
    # 1. update bilibili login status per-user from worker's report
    users_str = request.args.get("logged_in_users", "")
    logged_in = set(u.strip() for u in users_str.split(",") if u.strip())
    tq = current_app.config["task_queue"]
    if current_app.config["bilibili_logged_in"] != logged_in:
        current_app.config["bilibili_logged_in"] = logged_in
        tq.sse_publish_global("status:bilibili_update", {"users": list(logged_in)})

    tq = current_app.config["task_queue"]  # re-fetch in case another thread mutated

    # 2. clear event BEFORE checking — prevents race where notify_worker()
    #    fires between pop_pending() and clear(), which would drop the wakeup
    _poll_event.clear()
    task = tq.pop_pending()
    if task:
        return jsonify(task)

    # 3. wait for new work (with timeout)
    _poll_event.wait(timeout=60)

    # 4. try again after wakeup
    task = tq.pop_pending()
    if task:
        return jsonify(task)

    return {"type": "wait", "retry_after": 5}


# ------------------------------------------------------------------
# progress updates
# ------------------------------------------------------------------
@worker_bp.route("/progress/<task_id>", methods=["POST"])
def worker_progress(task_id):
    data = request.get_json() or {}
    tq = current_app.config["task_queue"]

    tq.update(task_id,
              title=data.get("title"),
              progress=data.get("progress"),
              speed=data.get("speed"),
              status="downloading")

    payload = {"task_id": task_id}
    for k in ("title", "progress", "speed"):
        if k in data:
            payload[k] = data[k]

    tq.sse_publish_task(task_id, "download:progress", payload)
    tq.sse_publish_global("download:progress", payload)
    return {"ok": True}


# ------------------------------------------------------------------
# qrcode for bilibili login
# ------------------------------------------------------------------
@worker_bp.route("/qrcode/<task_id>", methods=["POST"])
def worker_qrcode(task_id):
    data = request.get_json() or {}
    tq = current_app.config["task_queue"]
    tq.update(task_id, qrcode=data.get("qrcode"))
    payload = {"task_id": task_id, "qrcode": data.get("qrcode")}
    if data.get("image"):
        payload["image"] = data["image"]
    tq.sse_publish_task(task_id, "login:qrcode", payload)
    tq.sse_publish_global("login:qrcode", payload)
    return {"ok": True}


# ------------------------------------------------------------------
# login success
# ------------------------------------------------------------------
@worker_bp.route("/login-success/<task_id>", methods=["POST"])
def worker_login_success(task_id):
    tq = current_app.config["task_queue"]
    task = tq.get(task_id)
    username = task.get("username") if task else None
    if username:
        current_app.config["bilibili_logged_in"].add(username)
    tq.update(task_id, status="completed")
    tq.sse_publish_task(task_id, "login:success", {"task_id": task_id})
    tq.sse_publish_global("login:success", {"task_id": task_id})
    tq.sse_publish_global("status:bilibili_update",
                          {"users": list(current_app.config["bilibili_logged_in"])})
    logger.info("B站登录成功 task_id=%s user=%s", task_id, username)
    return {"ok": True}


# ------------------------------------------------------------------
# download complete — receives the file via multipart upload
# ------------------------------------------------------------------
@worker_bp.route("/complete/<task_id>", methods=["POST"])
def worker_complete(task_id):
    if "file" not in request.files:
        return {"error": "no file uploaded"}, 400

    f = request.files["file"]
    downloads_dir = current_app.config["downloads_dir"]

    prefix = _uuid.uuid4().hex[:12]
    orig_name = secure_filename(f.filename or "download")
    filename = f"{prefix}_{orig_name}"
    filepath = os.path.join(downloads_dir, filename)
    f.save(filepath)

    tq = current_app.config["task_queue"]
    tq.update(task_id, status="completed", file_path=filepath,
              completed_at=_time.time())

    tq.sse_publish_task(task_id, "download:complete",
                        {"task_id": task_id, "file_path": filepath,
                         "filename": filename})
    tq.sse_publish_global("download:complete", {"task_id": task_id})
    logger.info("下载完成 task_id=%s file=%s", task_id, filename)

    task = tq.get(task_id)
    user = task.get("username", "?") if task else "?"
    url = task.get("url", "?") if task else "?"
    audit.info(f"FINISH | user={user} | task={task_id} | mode={task.get('mode', '?') if task else '?'} | url={url} | file={filename}")

    return {"ok": True, "file_path": filepath, "filename": filename}


# ------------------------------------------------------------------
# task failed
# ------------------------------------------------------------------
@worker_bp.route("/fail/<task_id>", methods=["POST"])
def worker_fail(task_id):
    data = request.get_json() or {}
    error = data.get("error", "unknown error")
    tq = current_app.config["task_queue"]
    tq.update(task_id, status="failed", error=error)

    # Publish the right event based on task type
    task = tq.get(task_id)
    fail_event = "login:fail" if (task and task.get("type") == "login") else "download:fail"
    tq.sse_publish_task(task_id, fail_event,
                        {"task_id": task_id, "error": error})
    tq.sse_publish_global(fail_event,
                          {"task_id": task_id, "error": error})
    logger.info("任务失败 task_id=%s error=%s", task_id, error)

    user = task.get("username", "?") if task else "?"
    url = task.get("url", "?") if task else "?"
    audit.info(f"FAIL   | user={user} | task={task_id} | url={url} | error={error}")

    return {"ok": True}
