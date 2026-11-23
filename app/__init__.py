import os
import sqlite3
from datetime import timedelta

from flask import Flask, flash, make_response, redirect, request
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
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

    # 운영(Docker)에서는 DATABASE_PATH=/data/... 를 쓰므로 instance 폴더를 만들지 않는다.
    # (컨테이너가 /app에 쓰기 권한이 없는 uid로 돌 수 있음)
    db_path = os.environ.get("DATABASE_PATH")
    if not db_path:
        os.makedirs(app.instance_path, exist_ok=True)
        db_path = os.path.join(app.instance_path, "family.db")
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

    @app.errorhandler(CSRFError)
    def csrf_failed(e):
        """세션 쿠키가 없거나 오래된 페이지에서 제출한 경우. 영어 400 화면 대신
        같은 페이지를 다시 열어(새 토큰) 안내한다."""
        app.logger.warning("CSRF 실패: %s %s (%s)", request.method, request.path, e.description)
        flash("페이지가 오래됐거나 접속 정보가 없어서 처리하지 못했어요. 다시 시도해 주세요.", "error")
        if request.headers.get("HX-Request") == "true":
            resp = make_response("", 200)
            resp.headers["HX-Refresh"] = "true"
            return resp
        # 같은 사이트에서 온 경우만 그 페이지로, 아니면 같은 주소(GET)로
        target = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else request.path
        return redirect(target)

    from . import admin, auth, cli, guide, main, people, tree

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(guide.bp)
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
