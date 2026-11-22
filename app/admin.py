from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select

from .auth import admin_required
from .models import Person, User, db, utcnow

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _group_id() -> int:
    return g.user.person.family_group_id


def _pending_user_or_404(uid: int) -> User:
    user = db.session.get(User, uid)
    if user is None or user.status != "pending":
        abort(404)
    return user


@bp.get("/users")
@admin_required
def users():
    gid = _group_id()
    now = utcnow()
    pending = db.session.scalars(
        select(User).where(User.status == "pending").order_by(User.created_at)
    ).all()
    unlinked = db.session.scalars(
        select(Person)
        .where(Person.family_group_id == gid, ~Person.user.has())
        .order_by(Person.name, Person.birth_date)
    ).all()
    approved = db.session.scalars(
        select(User).where(User.status == "approved").order_by(User.name)
    ).all()

    # 이름과 생년월일이 같은 미연결 Person은 "같은 사람일 수 있음" 후보로 위에 올린다.
    options = {}
    for u in pending:
        same = [p for p in unlinked if p.name == u.name and p.birth_date == u.birth_date]
        others = [p for p in unlinked if p not in same]
        options[u.id] = (same, others)

    return render_template(
        "admin/users.html",
        pending=pending,
        options=options,
        approved=approved,
        now=now,
    )


@bp.post("/users/<int:uid>/approve")
@admin_required
def approve(uid: int):
    user = _pending_user_or_404(uid)
    target = request.form.get("target", "")

    if target == "new":
        person = Person(
            family_group_id=_group_id(),
            name=user.name,
            gender=user.gender,
            birth_date=user.birth_date,
            created_by=g.user.id,
        )
        db.session.add(person)
    else:
        person = db.session.get(Person, int(target)) if target.isdigit() else None
        if person is None or person.family_group_id != _group_id() or person.user is not None:
            flash("연결할 사람을 다시 골라 주세요.", "error")
            return redirect(url_for("admin.users"))

    user.person = person
    user.status = "approved"
    db.session.commit()
    flash(f"{user.name}님을 승인했어요.")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:uid>/reject")
@admin_required
def reject(uid: int):
    user = _pending_user_or_404(uid)
    name = user.name
    db.session.delete(user)
    db.session.commit()
    flash(f"{name}님의 가입 신청을 거절했어요.")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:uid>/unlock")
@admin_required
def unlock(uid: int):
    user = db.session.get(User, uid) or abort(404)
    user.failed_attempts = 0
    user.locked_until = None
    db.session.commit()
    flash(f"{user.name}님의 잠금을 풀었어요.")
    return redirect(url_for("admin.users"))
