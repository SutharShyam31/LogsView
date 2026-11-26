from flask import Blueprint, render_template, redirect, request, session
from config import load_servers
from logsview import user_store, activity
from logsview.auth import (
    login_required,
    is_login_blocked,
    record_failed_login,
    reset_login_attempts,
)

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
@login_required()
def dashboard():
    servers = load_servers()
    return render_template("dashboard.html", servers=servers, user=_user_ctx())


@pages_bp.get("/login")
def login_page():
    if session.get("username"):
        return redirect("/")
    first_setup = len(user_store.list_users()) == 0
    return render_template("login.html", first_setup=first_setup, error=None)


@pages_bp.post("/login")
def login_submit():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    users = user_store.list_users()
    first_setup = len(users) == 0

    if first_setup:
        try:
            user_store.add_user(username, password, "devops")
        except ValueError as exc:
            return render_template("login.html", first_setup=True, error=str(exc)), 400
        session.permanent = True
        session["username"] = username
        session["role"] = "devops"
        activity.record(username, "login", {"role": "devops", **activity.ip_detail()})
        return redirect("/")

    ip = request.remote_addr or "unknown"
    if is_login_blocked(ip):
        return (
            render_template(
                "login.html",
                first_setup=False,
                error="Too many failed attempts. Try again in a few minutes.",
            ),
            429,
        )

    if not user_store.verify_credentials(username, password):
        record_failed_login(ip)
        return (
            render_template(
                "login.html",
                first_setup=False,
                error="Invalid username or password.",
            ),
            401,
        )

    reset_login_attempts(ip)
    user = next((u for u in users if u["username"] == username), None)
    session.permanent = True
    session["username"] = username
    role = (user or {}).get("role", "developer")
    session["role"] = role
    activity.record(username, "login", {"role": role, **activity.ip_detail()})
    return redirect("/")


@pages_bp.get("/logout")
def logout():
    username = session.get("username", "")
    if username:
        activity.record(username, "logout", activity.ip_detail())
    session.clear()
    return redirect("/login")


@pages_bp.get("/admin")
@login_required(role="devops")
def admin_page():
    return render_template("admin.html", tab="servers", user=_user_ctx())


def _user_ctx() -> dict:
    return {
        "username": session.get("username", ""),
        "role": session.get("role", ""),
    }
