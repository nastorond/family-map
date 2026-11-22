from flask import Blueprint, redirect, url_for

from .auth import login_required

bp = Blueprint("main", __name__)


@bp.get("/")
@login_required
def home():
    return redirect(url_for("tree.view"))
