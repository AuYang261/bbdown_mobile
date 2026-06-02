import os
import sys
import logging
from flask import Flask

from auth import RateLimiter, hash_password
from users import UserStore
from tasks import TaskQueue

def create_app(instance_path: str | None = None) -> Flask:
    app = Flask(__name__)
    if instance_path:
        app.instance_path = instance_path

    # --- Config ---
    for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "APP_SESSION_SECRET", "SECRET_TOKEN"):
        if not os.environ.get(key):
            print(f"ERROR: Environment variable {key} must be set.", file=sys.stderr)
            sys.exit(1)

    app.secret_key = os.environ["APP_SESSION_SECRET"]
    app.config["ADMIN_USERNAME"] = os.environ["ADMIN_USERNAME"]
    app.config["ADMIN_PASSWORD"] = os.environ["ADMIN_PASSWORD"]
    app.config["SECRET_TOKEN"] = os.environ["SECRET_TOKEN"]

    # Hash admin password so we never keep it in plaintext
    salt, h = hash_password(os.environ["ADMIN_PASSWORD"])
    app.config["_admin_salt"] = salt
    app.config["_admin_hash"] = h

    # --- Logging ---
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    # Dedicated download audit log (file only, separate from request logs)
    audit_path = os.path.join(
        os.environ.get("DOWNLOAD_LOG_DIR", os.path.join(os.path.dirname(__file__), "downloads")),
        "download.log",
    )
    os.makedirs(os.path.dirname(audit_path), exist_ok=True)
    _audit_handler = logging.FileHandler(audit_path, encoding="utf-8")
    _audit_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    _audit_logger = logging.getLogger("bbdown.audit")
    _audit_logger.addHandler(_audit_handler)
    _audit_logger.setLevel(logging.INFO)
    _audit_logger.propagate = False  # don't spill into stdout

    # --- Support sub-path reverse proxy (e.g. /bbdown) ---
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)

    # --- Shared state ---
    users_path = os.path.join(app.instance_path, "users.json")
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["user_store"] = UserStore(users_path)
    app.config["task_queue"] = TaskQueue()
    app.config["rate_limiter"] = RateLimiter()
    app.config["bilibili_logged_in"] = set()  # set of usernames with valid BBDown.data
    app.config["downloads_dir"] = os.path.join(os.path.dirname(__file__), "downloads")
    os.makedirs(app.config["downloads_dir"], exist_ok=True)

    # --- Register blueprints ---
    from api_routes import api_bp
    app.register_blueprint(api_bp)

    from worker_routes import worker_bp
    app.register_blueprint(worker_bp)

    # --- Cleanup scheduler (daemon thread) ---
    _start_cleanup_thread(app)

    return app

def _start_cleanup_thread(app: Flask):
    import threading
    import time as _time
    from pathlib import Path

    def cleanup():
        while True:
            _time.sleep(600)  # every 10 minutes
            tq = app.config["task_queue"]
            dl_dir = Path(app.config["downloads_dir"])
            now = _time.time()
            with tq._lock:
                for tid, task in list(tq._tasks.items()):
                    if task["status"] == "completed" and task.get("file_path"):
                        fp = Path(task["file_path"])
                        age_hours = (now - task.get("completed_at", now)) / 3600
                        if age_hours >= 1 and fp.exists():
                            fp.unlink()
                            task["file_path"] = ""
                            logging.getLogger("bbdown").info(f"清理文件 {tid} {fp.name}")

    t = threading.Thread(target=cleanup, daemon=True)
    t.start()

def main():
    app = create_app()
    # Register blueprints here once they exist - for now just start
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="127.0.0.1", port=port, debug=False)

if __name__ == "__main__":
    main()
