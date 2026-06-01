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

logger = logging.getLogger("bbdown")
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
        cookie_available= (optional)  "true" / "false" — updates bilibili_logged_in
    Returns:
        A task dict immediately if one is available, otherwise blocks for up
        to 60 s.  If no task arrives, returns {"type":"wait","retry_after":5}.
    """
    # 1. update bilibili cookie status from worker's report
    cookie_val = request.args.get("cookie_available", "").strip().lower()
    if cookie_val in ("true", "false"):
        wanted = cookie_val == "true"
        if current_app.config["bilibili_logged_in"] != wanted:
            current_app.config["bilibili_logged_in"] = wanted
            tq = current_app.config["task_queue"]
            tq.sse_publish_global("status:bilibili_update", {"logged_in": wanted})

    tq = current_app.config["task_queue"]

    # 2. try to pop immediately
    task = tq.pop_pending()
    if task:
        return jsonify(task)

    # 3. if the worker was just reporting cookie status, return immediately
    if cookie_val in ("true", "false"):
        return {"type": "wait", "retry_after": 5}

    # 4. wait for new work (with timeout)
    _poll_event.clear()
    _poll_event.wait(timeout=60)

    # 5. try again after wakeup
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
    tq.sse_publish_task(task_id, "login:qrcode",
                        {"task_id": task_id, "qrcode": data.get("qrcode")})
    return {"ok": True}


# ------------------------------------------------------------------
# login success
# ------------------------------------------------------------------
@worker_bp.route("/login-success/<task_id>", methods=["POST"])
def worker_login_success(task_id):
    current_app.config["bilibili_logged_in"] = True
    tq = current_app.config["task_queue"]
    tq.update(task_id, status="completed")
    tq.sse_publish_task(task_id, "login:success", {"task_id": task_id})
    tq.sse_publish_global("status:bilibili_update", {"logged_in": True})
    logger.info("B站登录成功 task_id=%s", task_id)
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
    orig_name = f.filename or "download"
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

    tq.sse_publish_task(task_id, "download:fail",
                        {"task_id": task_id, "error": error})
    tq.sse_publish_global("download:fail",
                          {"task_id": task_id, "error": error})
    logger.info("任务失败 task_id=%s error=%s", task_id, error)
    return {"ok": True}
