import os
import sqlite3
from datetime import timedelta

from flask import Flask
from flask_wtf import CSRFProtect
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix

from .models import GENDERS, PARENT_KINDS, SPOUSE_STATUSES, FamilyGroup, db
from .validation import format_birth_date

csrf = CSRFProtect()

DEFAULT_GROUP_NAME = "우리 집안"


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    if isinstance(dbapi_conn, sqlite3.Connection):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    db_path = os.environ.get("DATABASE_PATH") or os.path.join(app.instance_path, "family.db")
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # 터널 뒤에서는 https라 기본값은 Secure. 로컬 http 개발 때만 COOKIE_SECURE=0.
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
        WTF_CSRF_TIME_LIMIT=None,
    )
    if test_config:
        app.config.update(test_config)

    if not app.config["SECRET_KEY"]:
        if app.debug or app.testing:
            app.config["SECRET_KEY"] = "dev-only-not-secret"
        else:
            raise RuntimeError("SECRET_KEY 환경변수를 설정해야 합니다.")

    # cloudflared가 붙여주는 X-Forwarded-* 헤더를 신뢰한다 (프록시 1단).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)

    from . import admin, auth, cli, main, people, tree

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(people.bp)
    app.register_blueprint(tree.bp)
    app.register_blueprint(admin.bp)
    cli.register(app)

    app.jinja_env.filters["birth"] = format_birth_date
    app.jinja_env.globals.update(
        GENDERS=GENDERS, PARENT_KINDS=PARENT_KINDS, SPOUSE_STATUSES=SPOUSE_STATUSES
    )

    with app.app_context():
        db.create_all()
        if db.session.scalar(select(FamilyGroup).limit(1)) is None:
            db.session.add(FamilyGroup(name=DEFAULT_GROUP_NAME))
            db.session.commit()

    return app
