"""가족 추가 안내 (팝업).

1단계: 분류 고르기 — 우리 가족 / 친가 / 외가 / 처가(시가)
2단계: 유형 고르기 — 예) 친가 → 큰아버지·작은아버지
3단계: 누구에게 붙일지 — 기준이 되는 사람이 여럿이면 고른다 (예: 사촌이면 어느 삼촌의 자녀인지)
마지막: 기존 추가 화면(people.add / people.add_sibling)으로 이동해 이름 등을 입력한다.

각 유형은 "나에서 기준 인물까지의 경로 + 마지막 동작"으로 정의한다.
  경로 단계: ("P", 성별) 부모, ("B", 성별) 형제자매, ("S", None) 배우자, ("C", 성별) 자녀
  마지막 동작: parent / spouse / sibling / child
"""
from dataclasses import dataclass, field

from flask import Blueprint, abort, g, render_template, request, url_for

from .auth import login_required
from .kinship import FamilyGraph, kinships_from

bp = Blueprint("guide", __name__, url_prefix="/people/guide")


@dataclass
class Item:
    key: str
    label: str
    path: list = field(default_factory=list)
    action: str = "child"
    gender: str | None = None  # 입력 폼에 미리 골라둘 성별


def catalog(me_gender: str | None) -> list[tuple[str, str, str, list[Item]]]:
    """(key, 이름, 설명, 유형들)"""
    female = me_gender == "female"
    inlaw_name = "시가" if female else ("처가" if me_gender == "male" else "배우자 쪽")
    return [
        ("mine", "우리 가족", "배우자, 자녀, 형제자매와 그 가족", [
            Item("spouse", "배우자", [], "spouse"),
            Item("child", "자녀 (아들·딸)", [], "child"),
            Item("sibling", "형제자매 (형·오빠·누나·언니·동생)", [], "sibling"),
            Item("grandchild", "손주", [("C", None)], "child"),
            Item("child_spouse", "사위·며느리", [("C", None)], "spouse"),
            Item("nephew", "조카", [("B", None)], "child"),
            Item("sibling_spouse", "형제자매의 배우자 (형수·매형·올케 등)", [("B", None)], "spouse"),
        ]),
        ("paternal", "친가", "아버지 쪽", [
            Item("father", "아버지", [], "parent", "male"),
            Item("p_grand", "할아버지·할머니", [("P", "male")], "parent"),
            Item("p_uncle", "큰아버지·작은아버지", [("P", "male")], "sibling", "male"),
            Item("p_aunt", "고모", [("P", "male")], "sibling", "female"),
            Item("p_uncle_spouse", "큰어머니·작은어머니·고모부", [("P", "male"), ("B", None)], "spouse"),
            Item("p_cousin", "사촌·고종사촌", [("P", "male"), ("B", None)], "child"),
            Item("p_ggrand", "증조할아버지·증조할머니", [("P", "male"), ("P", None)], "parent"),
            Item("p_granduncle", "큰할아버지·작은할아버지·고모할머니", [("P", "male"), ("P", None)], "sibling"),
        ]),
        ("maternal", "외가", "어머니 쪽", [
            Item("mother", "어머니", [], "parent", "female"),
            Item("m_grand", "외할아버지·외할머니", [("P", "female")], "parent"),
            Item("m_uncle", "외삼촌", [("P", "female")], "sibling", "male"),
            Item("m_aunt", "이모", [("P", "female")], "sibling", "female"),
            Item("m_uncle_spouse", "외숙모·이모부", [("P", "female"), ("B", None)], "spouse"),
            Item("m_cousin", "외사촌·이종사촌", [("P", "female"), ("B", None)], "child"),
            Item("m_ggrand", "외증조할아버지·외증조할머니", [("P", "female"), ("P", None)], "parent"),
            Item("m_granduncle", "외할아버지·외할머니의 형제자매", [("P", "female"), ("P", None)], "sibling"),
        ]),
        ("inlaw", inlaw_name, "배우자 쪽", [
            Item("spouse2", "배우자", [], "spouse"),
            Item("in_parents", "시아버지·시어머니" if female else "장인·장모", [("S", None)], "parent"),
            Item("in_sibling", "아주버님·시동생·시누이" if female else "처남·처형·처제", [("S", None)], "sibling"),
            Item("in_sibling_spouse", "배우자 형제자매의 배우자", [("S", None), ("B", None)], "spouse"),
            Item("in_nephew", "배우자 형제자매의 자녀 (조카)", [("S", None), ("B", None)], "child"),
        ]),
    ]


STEP_WORDS = {
    ("P", "male"): "아버지", ("P", "female"): "어머니", ("P", None): "부모",
    ("B", None): "형제자매", ("B", "male"): "형제", ("B", "female"): "자매",
    ("S", None): "배우자", ("C", None): "자녀", ("C", "male"): "아들", ("C", "female"): "딸",
}
ACTION_STEP = {"parent": "P", "sibling": "B", "spouse": "S", "child": "C"}


def _step(graph: FamilyGraph, ids: set[int], step: tuple[str, str | None]) -> set[int]:
    kind, gender = step
    out = set()
    for pid in ids:
        if kind == "P":
            nxt = graph.parents[pid]
        elif kind == "C":
            nxt = graph.children[pid]
        elif kind == "S":
            nxt = graph.spouses[pid]
        else:  # 형제자매 = 부모의 다른 자녀
            nxt = {c for p in graph.parents[pid] for c in graph.children[p]} - {pid}
        out |= {n for n in nxt if gender is None or graph.people[n].gender == gender}
    return out


def resolve(graph: FamilyGraph, me_id: int, item: Item) -> tuple[list[int], int | None]:
    """(기준 인물 후보, 막힌 단계 번호). 후보가 없으면 몇 번째 단계에서 막혔는지."""
    ids = {me_id}
    for i, step in enumerate(item.path):
        ids = _step(graph, ids, step)
        if not ids:
            return [], i
    return sorted(ids), None


def path_words(path) -> str:
    return "의 ".join(STEP_WORDS.get(s, "?") for s in path) or "나"


def prerequisite(items: list[Item], item: Item, blocked: int) -> list[Item]:
    """막힌 단계까지를 만들어 주는 유형 (예: 사촌이 막히면 '큰아버지·작은아버지', '고모')."""
    need = item.path[: blocked + 1]
    found = []
    for other in items:
        sig = other.path + [(ACTION_STEP[other.action], other.gender)]
        if len(sig) != len(need):
            continue
        if all(a[0] == b[0] and (b[1] is None or a[1] in (None, b[1])) for a, b in zip(sig, need)):
            found.append(other)
    return found


def add_url(item: Item, anchor_id: int) -> str:
    params = {"pid": anchor_id}
    if item.gender:
        params["gender"] = item.gender
    params["guide"] = item.key
    if item.action == "sibling":
        return url_for("people.add_sibling", **params)
    return url_for("people.add", rel=item.action, **params)


def find_item(key: str, me_gender):
    for cat_key, name, desc, items in catalog(me_gender):
        for it in items:
            if it.key == key:
                return cat_key, name, it
    return None


# --- 화면 (htmx 요청이면 팝업 조각, 아니면 전체 페이지) ---

def _render(partial: str, **ctx):
    ctx["partial"] = partial
    if request.headers.get("HX-Request"):
        return render_template(partial, **ctx)
    return render_template("guide/page.html", **ctx)


@bp.get("")
@login_required
def categories():
    cats = [(k, n, d) for k, n, d, _ in catalog(g.user.person.gender)]
    return _render("guide/_categories.html", cats=cats)


@bp.get("/<cat>")
@login_required
def items(cat: str):
    me = g.user.person
    found = [c for c in catalog(me.gender) if c[0] == cat]
    if not found:
        abort(404)
    cat_key, name, desc, its = found[0]
    graph = FamilyGraph(me.family_group_id)
    rows = []
    for it in its:
        anchors, blocked = resolve(graph, me.id, it)
        rows.append({
            "item": it,
            "anchors": anchors,
            "direct": add_url(it, anchors[0]) if len(anchors) == 1 else None,
            "need": path_words(it.path[: blocked + 1]) if blocked is not None else None,
            "blocked": blocked,
        })
    # 먼저 등록해야 하는 유형으로 가는 링크 (기준 인물이 하나면 바로 입력 화면)
    by_key = {r["item"].key: r for r in rows}
    for r in rows:
        r["prereq"] = []
        if r["blocked"] is None:
            continue
        for p in prerequisite(its, r["item"], r["blocked"]):
            pr = by_key[p.key]
            if pr["direct"]:
                r["prereq"].append((p.label, pr["direct"], False))
            elif pr["anchors"]:
                r["prereq"].append((p.label, url_for("guide.anchors", cat=cat_key, key=p.key), True))
    return _render("guide/_items.html", cat=cat_key, name=name, rows=rows)


@bp.get("/<cat>/<key>")
@login_required
def anchors(cat: str, key: str):
    me = g.user.person
    found = find_item(key, me.gender)
    if not found or found[0] != cat:
        abort(404)
    _, name, it = found
    graph = FamilyGraph(me.family_group_id)
    ids, blocked = resolve(graph, me.id, it)
    kins = kinships_from(me)
    people = [(graph.people[i], kins.get(i), add_url(it, i)) for i in ids]
    return _render(
        "guide/_anchors.html",
        cat=cat,
        name=name,
        item=it,
        people=people,
        need=path_words(it.path[: blocked + 1]) if blocked is not None else None,
        question=f"누구의 {_action_word(it.action)}인가요?",
    )


def _action_word(action: str) -> str:
    return {"parent": "부모", "sibling": "형제자매", "spouse": "배우자", "child": "자녀"}[action]
