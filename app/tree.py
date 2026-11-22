"""가계도 보기. family-chart(D3 기반) 형식으로 데이터를 넘긴다.

family-chart 제약과 대응:
- 성별이 M/F 중 하나여야 한다 → 모르면 배우자/공동부모의 반대 성별, 그것도 없으면 M으로 두고
  gender_unknown 표시를 붙여 카드 색을 따로 칠한다.
- 부모는 최대 2명 → 친생 > 입양 > 의붓 순으로 2명만 보낸다. 나머지 부모 관계는 상세 화면에서 보인다.
"""
from collections import defaultdict

from flask import Blueprint, g, jsonify, render_template, request, url_for
from sqlalchemy import select

from .auth import login_required
from .kinship import kinships_from
from .models import Person, Relation, db
from .people import get_person_or_404, group_id

bp = Blueprint("tree", __name__, url_prefix="/tree")

PARENT_PRIORITY = {"biological": 0, "adoptive": 1, "step": 2}


def build_tree_data(gid: int, kins: dict | None = None) -> list[dict]:
    """kins: {person_id: Kin} — 있으면 카드에 나 기준 호칭을 붙인다."""
    kins = kins or {}
    persons = db.session.scalars(select(Person).where(Person.family_group_id == gid)).all()
    rels = db.session.scalars(select(Relation).where(Relation.family_group_id == gid)).all()

    candidates = defaultdict(list)  # child_id -> [(priority, rel_id, parent_id)]
    spouses = defaultdict(set)
    for r in rels:
        if r.type == "parent_child":
            candidates[r.person_b_id].append((PARENT_PRIORITY[r.kind], r.id, r.person_a_id))
        else:
            spouses[r.person_a_id].add(r.person_b_id)
            spouses[r.person_b_id].add(r.person_a_id)

    parents = {child: [pid for _, _, pid in sorted(c)[:2]] for child, c in candidates.items()}
    children = defaultdict(list)
    for child, pids in parents.items():
        for pid in pids:
            children[pid].append(child)

    known = {p.id: p.gender for p in persons}

    def chart_gender(p: Person) -> str:
        if p.gender:
            return "M" if p.gender == "male" else "F"
        # 배우자나 같은 자녀의 다른 부모 중 성별을 아는 사람의 반대
        partners = set(spouses[p.id])
        for child in children[p.id]:
            partners.update(x for x in parents[child] if x != p.id)
        for other in partners:
            if known.get(other) == "male":
                return "F"
            if known.get(other) == "female":
                return "M"
        return "M"

    birth_key = {p.id: p.birth_date or "99999999" for p in persons}
    result = []
    for p in persons:
        result.append(
            {
                "id": str(p.id),
                "data": {
                    "gender": chart_gender(p),
                    "gender_unknown": p.gender is None,
                    "name": p.name,
                    "birth": p.birth_date[:4] if p.birth_date else "",
                    "deceased": p.is_deceased,
                    "title": kins[p.id].title if p.id in kins and kins[p.id].tokens else "",
                },
                "rels": {
                    "parents": [str(x) for x in parents.get(p.id, [])],
                    "spouses": [str(x) for x in sorted(spouses[p.id])],
                    "children": [str(x) for x in sorted(children[p.id], key=birth_key.get)],
                },
            }
        )
    return result


@bp.get("")
@login_required
def view():
    main_id = request.args.get("main", type=int)
    main = get_person_or_404(main_id) if main_id else g.user.person
    return render_template(
        "tree.html",
        main=main,
        data_url=url_for("tree.data"),
        person_url=url_for("people.detail", pid=0)[:-1],
    )


@bp.get("/data")
@login_required
def data():
    return jsonify(build_tree_data(group_id(), kinships_from(g.user.person)))
