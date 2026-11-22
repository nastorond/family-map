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

    return {
        "parents": sorted(parents, key=lambda x: (x[0].gender != "male", _birth_key(x[0]))),
        "spouses": sorted(spouses, key=lambda x: x[1].created_at),
        "children": sorted(children, key=lambda x: _birth_key(x[0])),
        "siblings": siblings_of(person, parents),
    }


def sibling_title(me: Person, sib: Person) -> str:
    """me가 sib을 부르는 말. 성별이나 나이 순서를 모르면 '형제자매'."""
    if not (me.gender and sib.gender and me.birth_date and sib.birth_date):
        return {"male": "남자 형제", "female": "여자 형제"}.get(sib.gender, "형제자매")
    if sib.birth_date == me.birth_date:
        return {"male": "남자 형제", "female": "여자 형제"}[sib.gender]
    if sib.birth_date < me.birth_date:
        if sib.gender == "male":
            return "형" if me.gender == "male" else "오빠"
        return "누나" if me.gender == "male" else "언니"
    return "남동생" if sib.gender == "male" else "여동생"


def siblings_of(person: Person, parents: list) -> list[tuple[Person, str, str | None]]:
    """부모가 같은 사람을 계산한다. (사람, 호칭, 비고)

    비고: 친부모가 한쪽만 같으면 '한쪽 부모만 같음', 친부모가 겹치지 않고
    입양/의붓 부모로만 이어지면 '입양·의붓으로 연결'.
    """
    parent_ids = [p.id for p, _ in parents]
    if not parent_ids:
        return []
    links = db.session.scalars(
        select(Relation).where(
            Relation.type == "parent_child",
            or_(Relation.person_a_id.in_(parent_ids), Relation.person_b_id == person.id),
        )
    ).all()
    my_bio = {r.person_a_id for r in links if r.person_b_id == person.id and r.kind == "biological"}
    sib_ids = {r.person_b_id for r in links if r.person_a_id in parent_ids} - {person.id}
    if not sib_ids:
        return []

    sib_bio = {sid: set() for sid in sib_ids}
    for r in db.session.scalars(
        select(Relation).where(
            Relation.type == "parent_child",
            Relation.kind == "biological",
            Relation.person_b_id.in_(sib_ids),
        )
    ):
        sib_bio[r.person_b_id].add(r.person_a_id)

    result = []
    for sib in db.session.scalars(select(Person).where(Person.id.in_(sib_ids))):
        shared = my_bio & sib_bio[sib.id]
        if not shared:
            note = "입양·의붓으로 연결"
        elif shared == my_bio == sib_bio[sib.id]:
            note = None
        else:
            note = "한쪽 부모만 같음"
        result.append((sib, sibling_title(person, sib), note))
    return sorted(result, key=lambda x: _birth_key(x[0]))


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


def find_candidates(target: Person, name: str, birth_date: str | None) -> list[tuple[Person, str]]:
    """같은 사람일 수 있는 기존 Person과 그 이유.

    - 이름과 생년월일이 같음
    - 이름이 같고 한쪽의 생년월일을 모름 (생년월일 모르는 고인이 중복되기 쉬워서)
    """
    rows = db.session.scalars(
        select(Person)
        .where(
            Person.family_group_id == target.family_group_id,
            Person.name == name,
            Person.id != target.id,
        )
        .order_by(Person.id)
    ).all()
    result = []
    for p in rows:
        if birth_date and p.birth_date == birth_date:
            result.append((p, "이름·생년월일 같음"))
        elif not birth_date or not p.birth_date:
            result.append((p, "이름 같음, 생년월일 확인 필요"))
    return result


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

    def render(form, status=200, candidates=None):
        return render_template(
            "people/add.html",
            target=target,
            rel=rel,
            label=REL_LABELS[rel],
            form=form,
            candidates=candidates or [],
        ), status

    if request.method == "GET":
        return render({})

    form = request.form
    kind, rel_status = read_relation_detail(rel, form)

    # 중복 후보 중 하나를 골라 기존 사람과 연결하는 경우
    if link_to := form.get("link_to"):
        other = get_person_or_404(int(link_to)) if link_to.isdigit() else abort(400)
        if reason := check_relation(rel, target, other.id, kind):
            flash(reason, "error")
            return render(form, 400)
        _create_relation(rel, target, other, kind, rel_status)
        db.session.commit()
        flash(f"{other.name}님을 {target.name}님의 {REL_LABELS[rel]}(으)로 연결했어요.")
        return redirect(url_for("people.detail", pid=target.id))

    values, errors = read_person_form(form)
    if not errors and (reason := check_relation(rel, target, None, kind)):
        errors.append(reason)
    if errors:
        for msg in errors:
            flash(msg, "error")
        return render(form, 400)

    # 같은 사람일 수 있는 후보가 있으면 저장 전에 한 번 보여준다. 병합은 하지 않는다.
    if not form.get("confirm_new"):
        if candidates := find_candidates(target, values["name"], values["birth_date"]):
            return render(form, 200, candidates)

    person = Person(family_group_id=target.family_group_id, created_by=g.user.id, **values)
    db.session.add(person)
    db.session.flush()
    _create_relation(rel, target, person, kind, rel_status)
    db.session.commit()
    flash(f"{person.name}님을 {target.name}님의 {REL_LABELS[rel]}(으)로 추가했어요.")
    return redirect(url_for("people.detail", pid=target.id))


@bp.route("/<int:pid>/add-sibling", methods=["GET", "POST"])
@login_required
def add_sibling(pid: int):
    """형제자매 추가. 형제 관계는 저장하지 않고, target의 부모 밑에 자녀로 넣는다.

    target의 부모가 등록돼 있지 않으면 부모 두 명(이름 모르면 '이름 모름')을 함께 만든다.
    """
    target = get_person_or_404(pid)
    parent_rels = relatives(target)["parents"]
    bio = [(p, r) for p, r in parent_rels if r.kind == "biological"]
    base = bio or parent_rels  # [(부모, target과의 관계)]

    def render(form, status=200, candidates=None):
        return render_template(
            "people/add_sibling.html",
            target=target,
            parents=[p for p, _ in base],
            form=form,
            candidates=candidates or [],
        ), status

    if request.method == "GET":
        return render({})

    form = request.form
    if base:
        share = form.get("share", "all")
        chosen = base if share == "all" else [(p, r) for p, r in base if str(p.id) == share]
        if not chosen:
            abort(400)
        links = [(p, r.kind) for p, r in chosen]
        new_parents = []
    else:
        links = []
        new_parents = [
            (form.get("father_name", "").strip() or "이름 모름", "male"),
            (form.get("mother_name", "").strip() or "이름 모름", "female"),
        ]

    def finish(sibling: Person, verb: str):
        made = []
        for name, gender in new_parents:
            parent = Person(
                family_group_id=target.family_group_id, name=name, gender=gender, created_by=g.user.id
            )
            db.session.add(parent)
            db.session.flush()
            _create_relation("child", parent, target, "biological", None)
            links.append((parent, "biological"))
            made.append(name)
        for parent, kind in links:
            _create_relation("child", parent, sibling, kind, None)
        db.session.commit()
        flash(f"{sibling.name}님을 {target.name}님의 형제자매로 {verb}.")
        if made:
            flash(f"부모가 등록돼 있지 않아서 부모({', '.join(made)})를 함께 만들었어요. 나중에 정보를 고칠 수 있어요.")
        return redirect(url_for("people.detail", pid=target.id))

    if link_to := form.get("link_to"):
        other = get_person_or_404(int(link_to)) if link_to.isdigit() else abort(400)
        reason = "자기 자신과는 연결할 수 없어요." if other.id == target.id else None
        for parent, kind in links:
            reason = reason or check_relation("child", parent, other.id, kind)
        if not reason and new_parents and _bio_parent_count(other.id) > 0:
            reason = "이 사람은 이미 부모가 등록돼 있어요. 부모 화면에서 자녀로 연결해 주세요."
        if reason:
            flash(reason, "error")
            return render(form, 400)
        return finish(other, "연결했어요")

    values, errors = read_person_form(form)
    if errors:
        for msg in errors:
            flash(msg, "error")
        return render(form, 400)
    if not form.get("confirm_new"):
        if candidates := find_candidates(target, values["name"], values["birth_date"]):
            return render(form, 200, candidates)

    sibling = Person(family_group_id=target.family_group_id, created_by=g.user.id, **values)
    db.session.add(sibling)
    db.session.flush()
    return finish(sibling, "추가했어요")


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
