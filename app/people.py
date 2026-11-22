from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import or_, select

from .auth import login_required
from .models import GENDERS, PARENT_KINDS, SPOUSE_STATUSES, Person, Relation, User, db
from .validation import parse_birth_date, parse_phone

bp = Blueprint("people", __name__, url_prefix="/people")


# --- 공통 ---

def group_id() -> int:
    return g.user.person.family_group_id


def get_person_or_404(pid: int) -> Person:
    person = db.session.get(Person, pid)
    if person is None or person.family_group_id != group_id():
        abort(404)
    return person


def can_edit(user: User, person: Person) -> bool:
    """관리자는 전부, 일반 사용자는 본인과 자기가 등록한 사람만."""
    return user.role == "admin" or person.id == user.person_id or person.created_by == user.id


def _birth_key(p: Person) -> str:
    return p.birth_date or "99999999"


def relatives(person: Person) -> dict:
    """저장된 관계(부모-자녀, 배우자)와 거기서 계산한 형제자매."""
    pid = person.id
    rels = db.session.scalars(
        select(Relation).where(or_(Relation.person_a_id == pid, Relation.person_b_id == pid))
    ).all()
    parents = [(r.person_a, r) for r in rels if r.type == "parent_child" and r.person_b_id == pid]
    children = [(r.person_b, r) for r in rels if r.type == "parent_child" and r.person_a_id == pid]
    spouses = [
        (r.person_b if r.person_a_id == pid else r.person_a, r) for r in rels if r.type == "spouse"
    ]

    parent_ids = [p.id for p, _ in parents]
    siblings = []
    if parent_ids:
        siblings = db.session.scalars(
            select(Person)
            .join(Relation, Relation.person_b_id == Person.id)
            .where(
                Relation.type == "parent_child",
                Relation.person_a_id.in_(parent_ids),
                Person.id != pid,
            )
            .distinct()
        ).all()

    return {
        "parents": sorted(parents, key=lambda x: (x[0].gender != "male", _birth_key(x[0]))),
        "spouses": sorted(spouses, key=lambda x: x[1].created_at),
        "children": sorted(children, key=lambda x: _birth_key(x[0])),
        "siblings": sorted(siblings, key=_birth_key),
    }


def read_person_form(form) -> tuple[dict, list[str]]:
    """사람 입력 폼을 검사한다. (값, 오류 목록)"""
    errors = []
    values = {
        "name": form.get("name", "").strip(),
        "gender": form.get("gender") or None,
        "is_deceased": form.get("is_deceased") == "1",
    }
    if not values["name"]:
        errors.append("이름을 입력해 주세요.")
    if values["gender"] not in (None, *GENDERS):
        errors.append("성별 값이 올바르지 않아요.")

    raw_birth = form.get("birth_date", "").strip()
    values["birth_date"] = None
    if raw_birth:
        try:
            values["birth_date"] = parse_birth_date(raw_birth)
        except ValueError as e:
            errors.append(str(e))

    try:
        values["phone"] = parse_phone(form.get("phone", ""))
    except ValueError as e:
        values["phone"] = None
        errors.append(str(e))
    return values, errors


# --- 관계 ---

REL_LABELS = {"parent": "부모", "spouse": "배우자", "child": "자녀"}


def read_relation_detail(rel: str, form) -> tuple[str | None, str | None]:
    """(kind, status). 값이 없으면 기본값(친생, 혼인 중)."""
    if rel == "spouse":
        status = form.get("status") or "married"
        if status not in SPOUSE_STATUSES:
            abort(400)
        return None, status
    kind = form.get("kind") or "biological"
    if kind not in PARENT_KINDS:
        abort(400)
    return kind, None


def _walk(start_id: int, up: bool) -> set[int]:
    """up=True면 조상, False면 자손 id 집합."""
    seen: set[int] = set()
    frontier = {start_id}
    src, dst = (Relation.person_b_id, Relation.person_a_id) if up else (Relation.person_a_id, Relation.person_b_id)
    while frontier:
        rows = db.session.execute(
            select(dst).where(Relation.type == "parent_child", src.in_(frontier))
        ).scalars().all()
        frontier = set(rows) - seen
        seen |= frontier
    return seen


def _bio_parent_count(child_id: int) -> int:
    return len(
        db.session.scalars(
            select(Relation.id).where(
                Relation.type == "parent_child",
                Relation.person_b_id == child_id,
                Relation.kind == "biological",
            )
        ).all()
    )


def relation_pair(rel: str, target_id: int, other_id: int) -> tuple[str, int, int]:
    """(type, person_a_id, person_b_id)"""
    if rel == "parent":
        return "parent_child", other_id, target_id
    if rel == "child":
        return "parent_child", target_id, other_id
    a, b = sorted((target_id, other_id))
    return "spouse", a, b


def check_relation(rel: str, target: Person, other_id: int | None, kind: str | None) -> str | None:
    """관계를 추가할 수 없으면 이유를 돌려준다. other_id가 None이면 새로 만드는 사람."""
    if kind == "biological":
        child_id = target.id if rel == "parent" else other_id
        if child_id is not None and _bio_parent_count(child_id) >= 2:
            return "친생 부모는 두 명까지만 등록할 수 있어요."
    if other_id is None:
        return None

    if other_id == target.id:
        return "자기 자신과는 연결할 수 없어요."
    rtype, a, b = relation_pair(rel, target.id, other_id)
    exists = db.session.scalar(
        select(Relation.id).where(Relation.type == rtype, Relation.person_a_id == a, Relation.person_b_id == b)
    )
    if exists:
        return "이미 연결된 관계예요."
    if rel == "parent" and other_id in _walk(target.id, up=False):
        return "자손을 부모로 등록할 수 없어요."
    if rel == "child" and other_id in _walk(target.id, up=True):
        return "조상을 자녀로 등록할 수 없어요."
    return None


# --- 화면 ---

@bp.get("/<int:pid>")
@login_required
def detail(pid: int):
    person = get_person_or_404(pid)
    return render_template(
        "people/detail.html",
        person=person,
        rel=relatives(person),
        is_me=person.id == g.user.person_id,
        can_edit=can_edit(g.user, person),
    )


@bp.route("/<int:pid>/add", methods=["GET", "POST"])
@login_required
def add(pid: int):
    """target의 부모/배우자/자녀를 새로 등록한다. 관계 추가는 승인된 사용자 누구나 할 수 있다."""
    target = get_person_or_404(pid)
    rel = request.values.get("rel")
    if rel not in REL_LABELS:
        abort(400)

    def render(form, status=200):
        return render_template(
            "people/add.html", target=target, rel=rel, label=REL_LABELS[rel], form=form
        ), status

    if request.method == "GET":
        return render({})

    form = request.form
    kind, rel_status = read_relation_detail(rel, form)
    values, errors = read_person_form(form)
    if not errors and (reason := check_relation(rel, target, None, kind)):
        errors.append(reason)
    if errors:
        for msg in errors:
            flash(msg, "error")
        return render(form, 400)

    person = Person(family_group_id=target.family_group_id, created_by=g.user.id, **values)
    db.session.add(person)
    db.session.flush()
    _create_relation(rel, target, person, kind, rel_status)
    db.session.commit()
    flash(f"{person.name}님을 {target.name}님의 {REL_LABELS[rel]}(으)로 추가했어요.")
    return redirect(url_for("people.detail", pid=target.id))


def _create_relation(rel: str, target: Person, other: Person, kind, status) -> None:
    rtype, a, b = relation_pair(rel, target.id, other.id)
    db.session.add(
        Relation(
            family_group_id=target.family_group_id,
            type=rtype,
            person_a_id=a,
            person_b_id=b,
            kind=kind,
            status=status,
            created_by=g.user.id,
        )
    )


@bp.route("/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def edit(pid: int):
    person = get_person_or_404(pid)
    if not can_edit(g.user, person):
        abort(403)

    if request.method == "GET":
        form = {
            "name": person.name,
            "gender": person.gender or "",
            "birth_date": person.birth_date or "",
            "phone": person.phone or "",
            "is_deceased": "1" if person.is_deceased else "",
        }
        return render_template("people/edit.html", person=person, form=form)

    values, errors = read_person_form(request.form)
    if errors:
        for msg in errors:
            flash(msg, "error")
        return render_template("people/edit.html", person=person, form=request.form), 400

    for key, value in values.items():
        setattr(person, key, value)
    db.session.commit()
    flash("저장했어요.")
    return redirect(url_for("people.detail", pid=person.id))
