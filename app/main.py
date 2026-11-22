from flask import Blueprint, g, redirect, url_for

from .auth import login_required

bp = Blueprint("main", __name__)


@bp.get("/")
@login_required
def home():
    # 가계도 보기를 붙이기 전까지는 내 상세 화면이 홈이다.
    return redirect(url_for("people.detail", pid=g.user.person_id))
