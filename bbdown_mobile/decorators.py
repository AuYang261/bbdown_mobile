import functools
from flask import session, redirect, url_for, request

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return {"error": "unauthorized"}, 401
            return redirect(url_for("api.login_page"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return {"error": "unauthorized"}, 401
            return redirect(url_for("api.login_page"))
        if not session.get("is_admin"):
            return {"error": "forbidden"}, 403
        return f(*args, **kwargs)
    return decorated
