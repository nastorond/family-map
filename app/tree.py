"""가계도 보기. 배치는 app/layout.py가 계산하고, static/tree.js가 d3로 그린다."""
from flask import Blueprint, abort, g, jsonify, render_template, request, url_for

from .auth import login_required
from .kinship import kinships_from
from .layout import ViewUnavailable, available_views, build_layout
from .people import get_person_or_404, group_id

bp = Blueprint("tree", __name__, url_prefix="/tree")


@bp.get("")
@login_required
def view():
    main_id = request.args.get("main", type=int)
    main = get_person_or_404(main_id) if main_id else g.user.person
    views = available_views(group_id(), g.user.person)
    view = request.args.get("view", "all")
    if view not in dict(views):
        view = "all"
    return render_template(
        "tree.html",
        main=main,
        views=views,
        view=view,
        data_url=url_for("tree.data"),
        person_url=url_for("people.detail", pid=0)[:-1],
    )


@bp.get("/data")
@login_required
def data():
    me = g.user.person
    view = request.args.get("view", "all")
    if view not in ("all", "paternal", "maternal", "inlaw"):
        abort(400)
    try:
        return jsonify(build_layout(group_id(), me.id, kinships_from(me), view))
    except ViewUnavailable:
        abort(404)
