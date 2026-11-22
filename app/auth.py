import math
from datetime import timedelta
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from .models import GENDERS, User, db, utcnow
from .validation import parse_birth_date, validate_pin

bp = Blueprint("auth", __name__)

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 30


@bp.before_app_request
def load_current_user():
    g.user = None
    uid = session.get("uid")
    if uid is None:
        return
    user = db.session.get(User, uid)
    if user is None or user.status != "approved":
        session.clear()
        return
    g.user = user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user.role != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def hash_pin(pin: str) -> str:
    return generate_password_hash(pin)


def find_user(name: str, birth_date: str) -> User | None:
    return db.session.scalar(
        select(User).where(User.name == name, User.birth_date == birth_date)
    )


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("main.home"))
    if request.method == "GET":
        return render_template("auth/signup.html", form={})

    form = request.form
    name = form.get("name", "").strip()
    gender = form.get("gender", "")
    pin = form.get("pin", "")
    errors = []

    if not name:
        errors.append("이름을 입력해 주세요.")
    if gender not in GENDERS:
        errors.append("성별을 선택해 주세요.")
    try:
        birth_date = parse_birth_date(form.get("birth_date", ""))
    except ValueError as e:
        birth_date = None
        errors.append(str(e))
    if pin_error := validate_pin(pin):
        errors.append(pin_error)
    elif pin != form.get("pin_confirm", ""):
        errors.append("PIN 확인이 일치하지 않아요.")
    if not errors and find_user(name, birth_date):
        errors.append("같은 이름과 생년월일로 가입한 계정이 이미 있어요. 관리자에게 문의해 주세요.")

    if errors:
        for msg in errors:
            flash(msg, "error")
        return render_template("auth/signup.html", form=form), 400

    db.session.add(
        User(name=name, birth_date=birth_date, gender=gender, pin_hash=hash_pin(pin))
    )
    db.session.commit()
    return render_template("auth/pending.html", name=name)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("main.home"))
    if request.method == "GET":
        return render_template("auth/login.html", form={})

    form = request.form
    name = form.get("name", "").strip()
    pin = form.get("pin", "")
    generic_error = "이름, 생년월일, PIN을 다시 확인해 주세요."

    try:
        birth_date = parse_birth_date(form.get("birth_date", ""))
    except ValueError:
        birth_date = None
    user = find_user(name, birth_date) if name and birth_date else None

    if user is None:
        flash(generic_error, "error")
        return render_template("auth/login.html", form=form), 401

    now = utcnow()
    if user.is_locked(now):
        minutes = math.ceil((user.locked_until - now).total_seconds() / 60)
        flash(f"PIN을 {MAX_FAILED_ATTEMPTS}번 틀려서 잠겼어요. {minutes}분 뒤에 다시 시도하거나 관리자에게 문의해 주세요.", "error")
        return render_template("auth/login.html", form=form), 423

    if not check_password_hash(user.pin_hash, pin):
        user.failed_attempts += 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.failed_attempts = 0
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            flash(f"PIN을 {MAX_FAILED_ATTEMPTS}번 틀려서 {LOCK_MINUTES}분 동안 잠겼어요.", "error")
            status = 423
        else:
            left = MAX_FAILED_ATTEMPTS - user.failed_attempts
            flash(f"{generic_error} (남은 시도 {left}번)", "error")
            status = 401
        db.session.commit()
        return render_template("auth/login.html", form=form), status

    user.failed_attempts = 0
    user.locked_until = None
    if user.status != "approved":
        db.session.commit()
        return render_template("auth/pending.html", name=user.name)

    user.last_login_at = now
    db.session.commit()
    session.clear()
    session["uid"] = user.id
    session.permanent = True
    return redirect(url_for("main.home"))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
