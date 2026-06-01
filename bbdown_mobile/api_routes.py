import logging
import json as _json
import os
from flask import Blueprint, render_template, request, session, jsonify, send_file, current_app, Response
from decorators import login_required, admin_required
from auth import hash_password, verify_password

logger = logging.getLogger("bbdown")
api_bp = Blueprint("api", __name__)

# --- Page routes ---

@api_bp.route("/login")
def login_page():
    return render_template("login.html")

@api_bp.route("/")
@login_required
def index():
    return render_template("index.html", username=session["user"], is_admin=session.get("is_admin", False))

# --- Auth API ---

@api_bp.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return {"error": "用户名和密码不能为空"}, 400

    ip = request.remote_addr or "unknown"
    rl = current_app.config["rate_limiter"]
    if rl.is_blocked(ip):
        logger.warning(f"IP {ip} 登录锁定中")
        return {"error": "登录尝试次数过多，请15分钟后再试"}, 429

    app = current_app
    admin_user = app.config["ADMIN_USERNAME"]

    # Check admin
    if username == admin_user:
        stored_salt = app.config.get("_admin_salt")
        stored_hash = app.config.get("_admin_hash")
        if verify_password(password, stored_salt, stored_hash):
            session["user"] = username
            session["is_admin"] = True
            rl.reset(ip)
            logger.info(f"{username} 登录成功 (admin)")
            return {"ok": True, "is_admin": True}
        else:
            rl.record_failure(ip)
            logger.warning(f"管理员登录失败 IP={ip}")
            return {"error": "用户名或密码错误"}, 401

    # Check regular user
    user_store = app.config["user_store"]
    if user_store.verify(username, password):
        session["user"] = username
        session["is_admin"] = False
        rl.reset(ip)
        logger.info(f"{username} 登录成功")
        return {"ok": True, "is_admin": False}

    rl.record_failure(ip)
    logger.warning(f"{username} 登录失败 IP={ip}")
    return {"error": "用户名或密码错误"}, 401

@api_bp.route("/api/logout", methods=["POST"])
def api_logout():
    user = session.pop("user", None)
    session.pop("is_admin", None)
    if user:
        logger.info(f"{user} 登出")
    return {"ok": True}

# --- Download API ---

@api_bp.route("/api/download", methods=["POST"])
@login_required
def api_download():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    mode = data.get("mode", "video")
    if not url:
        return {"error": "请粘贴B站链接"}, 400
    if mode not in ("audio", "video"):
        mode = "video"

    tq = current_app.config["task_queue"]
    tid = tq.add_download(url=url, mode=mode, username=session["user"])

    response = {"task_id": tid, "bilibili_available": current_app.config["bilibili_logged_in"]}
    if not current_app.config["bilibili_logged_in"]:
        response["warning"] = "尚未登录B站，高清晰度/大会员视频可能无法下载"
    return response

@api_bp.route("/api/login-bilibili", methods=["POST"])
@login_required
def api_login_bilibili():
    tq = current_app.config["task_queue"]
    tid = tq.add_login()
    tq.update(tid, username=session["user"])
    logger.info(f"{session['user']} 提交B站登录")
    return {"task_id": tid}

@api_bp.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks():
    tq = current_app.config["task_queue"]
    return jsonify(tq.list_all())

@api_bp.route("/api/status", methods=["GET"])
@login_required
def api_status():
    return {"bilibili_logged_in": current_app.config["bilibili_logged_in"]}

@api_bp.route("/api/events")
@login_required
def api_events():
    """SSE endpoint — streams task progress and global events to the client."""
    tq = current_app.config["task_queue"]

    def generate():
        sub = tq.sse_subscribe_global()
        try:
            while True:
                msg = sub.wait(timeout=15)
                if msg:
                    yield f"event: {msg['event']}\ndata: {_json.dumps(msg['data'])}\n\n"
                else:
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            sub.close()

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@api_bp.route("/api/file/<task_id>")
@login_required
def api_file(task_id):
    tq = current_app.config["task_queue"]
    task = tq.get(task_id)
    if not task or task["status"] != "completed" or not task.get("file_path"):
        return {"error": "文件不存在或尚未完成"}, 404
    fpath = task["file_path"]
    if not os.path.exists(fpath):
        return {"error": "文件已被清理"}, 404
    logger.info(f"{session['user']} 下载文件 {task_id} {os.path.basename(fpath)}")
    return send_file(fpath, as_attachment=True, download_name=os.path.basename(fpath))

# --- User management API ---

@api_bp.route("/api/users", methods=["GET"])
@login_required
@admin_required
def api_users_list():
    store = current_app.config["user_store"]
    return jsonify(store.list_users())

@api_bp.route("/api/users/add", methods=["POST"])
@login_required
@admin_required
def api_users_add():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return {"error": "用户名和密码不能为空"}, 400
    store = current_app.config["user_store"]
    try:
        store.add_user(username, password)
        logger.info(f"管理员 {session['user']} 添加用户 {username}")
        return {"ok": True}
    except ValueError as e:
        return {"error": str(e)}, 409

@api_bp.route("/api/users/remove", methods=["POST"])
@login_required
@admin_required
def api_users_remove():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    if not username:
        return {"error": "用户名不能为空"}, 400
    if username == current_app.config["ADMIN_USERNAME"]:
        return {"error": "不能删除管理员"}, 400
    store = current_app.config["user_store"]
    store.remove_user(username)
    logger.info(f"管理员 {session['user']} 删除用户 {username}")
    return {"ok": True}

@api_bp.route("/api/users/change-password", methods=["POST"])
@login_required
def api_users_change_password():
    data = request.get_json() or {}
    target = data.get("username", "").strip()
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")

    if not target or not old_pw or not new_pw:
        return {"error": "用户名、旧密码、新密码均不能为空"}, 400

    app = current_app
    is_admin = session.get("is_admin", False)

    if not is_admin and target != session["user"]:
        return {"error": "只能修改自己的密码"}, 403

    if target == app.config["ADMIN_USERNAME"]:
        return {"error": "管理员密码请通过环境变量修改"}, 400

    store = app.config["user_store"]
    if is_admin:
        salt, h = hash_password(new_pw)
        if target not in store.list_users():
            return {"error": "用户不存在"}, 404
        store._users[target] = {"salt": salt, "hash": h}
        store._save()
        logger.info(f"管理员 {session['user']} 重置 {target} 的密码")
        return {"ok": True}
    else:
        if store.change_password(target, old_pw, new_pw):
            logger.info(f"{target} 修改密码")
            return {"ok": True}
        return {"error": "旧密码不正确"}, 401
