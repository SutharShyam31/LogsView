from datetime import timedelta
from flask import Flask
from config import Settings
from logsview.routes.pages import pages_bp
from logsview.routes.api import api_bp
from logsview.routes.admin import admin_bp


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = Settings.secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    return app


app = create_app()


if __name__ == "__main__":
    lan_bind = Settings.host not in ("127.0.0.1", "localhost")
    if lan_bind:
        from waitress import serve
        print(f"[logsview] serving via waitress on http://{Settings.host}:{Settings.port}")
        print("[logsview] WARNING: LAN-reachable. Debug mode is OFF. Ensure users have accounts.")
        serve(app, host=Settings.host, port=Settings.port, threads=8)
    else:
        app.run(host=Settings.host, port=Settings.port, debug=True)
