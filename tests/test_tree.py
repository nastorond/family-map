import time
from collections import defaultdict

import pytest

from app.layout import CARD_W, GAP_IN, LAYER_H, build_layout
from app.models import FamilyGroup, Person, Relation, User, db
from tests.conftest import login


def mk_person(name, gender=None, birth=None, group=1, deceased=False):
    p = Person(family_group_id=group, name=name, gender=gender, birth_date=birth, is_deceased=deceased)
    db.session.add(p)
    db.session.flush()
    return p


def parent(p, c, kind="biological"):
    db.session.add(Relation(family_group_id=1, type="parent_child", person_a_id=p.id, person_b_id=c.id, kind=kind))


def spouse(a, b, status="married"):
    a_id, b_id = sorted((a.id, b.id))
    db.session.add(Relation(family_group_id=1, type="spouse", person_a_id=a_id, person_b_id=b_id, status=status))


def assert_no_overlap(nodes):
    rows = defaultdict(list)
    for n in nodes:
        rows[n["y"]].append(n["x"])
    for xs in rows.values():
        xs.sort()
        for a, b in zip(xs, xs[1:]):
            assert b - a >= CARD_W + GAP_IN - 0.5, (a, b)


@pytest.fixture
def big_family(app, admin):
    """나, 부모, 조부모, 삼촌/고모와 사촌, 외가, 처가, 자녀, 의붓엄마."""
    with app.app_context():
        me = db.session.get(User, admin).person
        P = {"나": me}

        def m(name, gender=None, birth=None):
            P[name] = mk_person(name, gender, birth)
            return P[name]

        m("할아버지", "male", "19250101"); m("할머니", "female", "19270101")
        m("외할아버지", "male", "19300101"); m("외할머니", "female")
        m("아버지", "male", "19450101"); m("어머니", "female", "19470101"); m("새어머니", "female")
        m("큰아버지", "male", "19400101"); m("큰어머니", "female"); m("사촌", "male", "19650101")
        m("고모", "female", "19500101"); m("고종사촌", "female", "19750101")
        m("이모", "female", "19520101"); m("이종사촌", "male", "19800101")
        m("아내", "female", "19720101"); m("장인", "male"); m("장모", "female"); m("처제", "female")
        m("딸", "female", "20000101"); m("아들", "male", "20030101")
        m("남남", "male")  # 연결 안 됨

        spouse(P["할아버지"], P["할머니"]); spouse(P["외할아버지"], P["외할머니"])
        for c in ("아버지", "큰아버지", "고모"):
            parent(P["할아버지"], P[c]); parent(P["할머니"], P[c])
        for c in ("어머니", "이모"):
            parent(P["외할아버지"], P[c]); parent(P["외할머니"], P[c])
        spouse(P["아버지"], P["어머니"], "divorced"); spouse(P["아버지"], P["새어머니"])
        parent(P["아버지"], me); parent(P["어머니"], me); parent(P["새어머니"], me, "step")
        spouse(P["큰아버지"], P["큰어머니"]); parent(P["큰아버지"], P["사촌"]); parent(P["큰어머니"], P["사촌"])
        parent(P["고모"], P["고종사촌"]); parent(P["이모"], P["이종사촌"])
        spouse(me, P["아내"])
        for c in ("아내", "처제"):
            parent(P["장인"], P[c]); parent(P["장모"], P[c])
        for c in ("딸", "아들"):
            parent(me, P[c]); parent(P["아내"], P[c])
        db.session.commit()
        layout = build_layout(1, me.id)
        return layout, {p.id: n for n, p in P.items()}


def by_name(layout, names):
    return {names[int(n["id"])]: n for n in layout["nodes"]}


def test_everyone_is_drawn_including_collaterals(big_family):
    layout, names = big_family
    nodes = by_name(layout, names)
    assert set(nodes) == set(names.values())
    assert len(layout["nodes"]) == len(names)


def test_generations(big_family):
    layout, names = big_family
    n = by_name(layout, names)
    assert n["할아버지"]["y"] == n["외할아버지"]["y"] == 0
    for name in ("아버지", "어머니", "큰아버지", "고모", "이모", "장인", "장모"):
        assert n[name]["y"] == LAYER_H, name
    for name in ("나", "아내", "사촌", "고종사촌", "이종사촌", "처제"):
        assert n[name]["y"] == 2 * LAYER_H, name
    assert n["딸"]["y"] == n["아들"]["y"] == 3 * LAYER_H


def test_no_overlap_and_couples_adjacent(big_family):
    layout, names = big_family
    me_comp = [n for n in layout["nodes"] if names[int(n["id"])] != "남남"]
    assert_no_overlap(me_comp)
    n = by_name(layout, names)
    assert abs(abs(n["나"]["x"] - n["아내"]["x"]) - (CARD_W + GAP_IN)) < 0.5
    assert abs(abs(n["큰아버지"]["x"] - n["큰어머니"]["x"]) - (CARD_W + GAP_IN)) < 0.5
    # 재혼: 아버지가 두 배우자 사이 가운데
    xs = sorted([n["어머니"]["x"], n["아버지"]["x"], n["새어머니"]["x"]])
    assert xs[1] == n["아버지"]["x"]


def test_children_under_parents(big_family):
    layout, names = big_family
    n = by_name(layout, names)
    mid = (n["나"]["x"] + n["아내"]["x"]) / 2
    kids = (n["딸"]["x"] + n["아들"]["x"]) / 2
    assert abs(mid - kids) < CARD_W  # 자녀 묶음이 부모 밑 근처


def test_unconnected_drawn_separately(big_family):
    layout, names = big_family
    n = by_name(layout, names)
    others = [v["x"] for k, v in n.items() if k != "남남"]
    assert n["남남"]["x"] > max(others)


def test_edges(big_family):
    layout, _ = big_family
    types = defaultdict(int)
    for e in layout["edges"]:
        types[e["type"]] += 1
        assert e["d"].startswith("M")
    assert types["spouse"] == 6
    assert any(e["type"] == "spouse" and e["status"] == "divorced" for e in layout["edges"])


def view_names(app, names, view):
    with app.app_context():
        me_id = next(pid for pid, n in names.items() if n == "나")
        return {names[int(n["id"])] for n in build_layout(1, me_id, view=view)["nodes"]}


def test_paternal_view(app, big_family):
    _, names = big_family
    got = view_names(app, names, "paternal")
    assert {"할아버지", "할머니", "아버지", "큰아버지", "큰어머니", "사촌", "고모", "고종사촌",
            "어머니", "새어머니", "나", "아내", "딸", "아들"} <= got
    assert not got & {"외할아버지", "외할머니", "이모", "이종사촌", "장인", "장모", "처제", "남남"}


def test_maternal_view(app, big_family):
    _, names = big_family
    got = view_names(app, names, "maternal")
    assert {"외할아버지", "외할머니", "어머니", "이모", "이종사촌", "나", "아내", "딸", "아들", "아버지"} <= got
    assert not got & {"할아버지", "큰아버지", "사촌", "고모", "새어머니", "장인", "처제", "남남"}


def test_inlaw_view(app, big_family):
    _, names = big_family
    got = view_names(app, names, "inlaw")
    assert got == {"아내", "장인", "장모", "처제", "나", "딸", "아들"}


def test_view_buttons_and_errors(app, client, admin, big_family):
    login(client, "관리자", "19700101", "111111")
    page = client.get("/tree").get_data(as_text=True)
    for label in ("전체", "친가", "외가", "처가"):
        assert f">{label}</button>" in page
    assert client.get("/tree/data?view=paternal").status_code == 200
    assert client.get("/tree/data?view=weird").status_code == 400
    assert 'data-view="maternal"' in client.get("/tree?view=maternal").get_data(as_text=True)


def test_view_unavailable_without_parents(client, admin):
    login(client, "관리자", "19700101", "111111")
    page = client.get("/tree").get_data(as_text=True)
    assert ">친가</button>" not in page  # 부모가 없으면 버튼도 없음
    assert client.get("/tree/data?view=paternal").status_code == 404


def test_titles_and_me(app, client, admin):
    with app.app_context():
        me = db.session.get(User, admin).person
        dad = mk_person("아빠", "male", "19400101")
        uncle = mk_person("큰집", "male", "19350101")
        grandpa = mk_person("할배", "male")
        parent(dad, me); parent(grandpa, dad); parent(grandpa, uncle)
        db.session.commit()
    login(client, "관리자", "19700101", "111111")
    data = client.get("/tree/data").get_json()
    nodes = {n["name"]: n for n in data["nodes"]}
    assert nodes["큰집"]["title"] == "큰아버지"
    assert nodes["관리자"]["me"] is True and nodes["관리자"]["title"] == ""
    assert data["me"] == nodes["관리자"]["id"]


def test_other_group_excluded(app, admin):
    with app.app_context():
        other = FamilyGroup(name="다른 집안")
        db.session.add(other)
        db.session.flush()
        mk_person("남", group=other.id)
        db.session.commit()
        me_id = db.session.get(User, admin).person_id
        names = {n["name"] for n in build_layout(1, me_id)["nodes"]}
    assert "남" not in names and "관리자" in names


def test_tree_endpoints(app, client, admin):
    assert client.get("/tree").status_code == 302
    assert client.get("/tree/data").status_code == 302
    login(client, "관리자", "19700101", "111111")
    assert client.get("/").headers["Location"].endswith("/tree")
    page = client.get("/tree").get_data(as_text=True)
    assert "d3-7.9.0.min.js" in page and "family-chart" not in page
    assert client.get("/tree?main=9999").status_code == 404


def test_large_family_is_fast(app, admin):
    """6세대, 300명 정도에서도 1초 안에 배치."""
    with app.app_context():
        me = db.session.get(User, admin).person
        gen = [me]
        count = 0
        for g in range(6):
            nxt = []
            for i, p in enumerate(gen):
                if count > 300:
                    break
                sp = mk_person(f"배우자{g}-{i}", "female")
                spouse(p, sp)
                for k in range(3):
                    c = mk_person(f"자녀{g}-{i}-{k}", "male" if k % 2 == 0 else "female", f"{1950 + g * 20}0{k + 1}01")
                    parent(p, c); parent(sp, c)
                    nxt.append(c)
                    count += 1
            gen = nxt
        db.session.commit()
        t = time.perf_counter()
        layout = build_layout(1, me.id)
        elapsed = time.perf_counter() - t
    assert elapsed < 1.0, elapsed
    assert_no_overlap(layout["nodes"])
