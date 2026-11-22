import pytest

from app.models import FamilyGroup, Person, Relation, db
from app.tree import build_tree_data
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


def by_name(data):
    ids = {d["id"]: d["data"]["name"] for d in data}
    out = {}
    for d in data:
        out[d["data"]["name"]] = {
            "data": d["data"],
            "parents": sorted(ids[x] for x in d["rels"]["parents"]),
            "spouses": sorted(ids[x] for x in d["rels"]["spouses"]),
            "children": [ids[x] for x in d["rels"]["children"]],
        }
    return out


@pytest.fixture
def family(app, admin):
    with app.app_context():
        dad = mk_person("아버지", "male", "19550101")
        mom = mk_person("어머니", "female", "19570202")
        step = mk_person("새어머니", "female")
        me = mk_person("나", "male", "19850312")
        sis = mk_person("여동생", "female", "19880101")
        wife = mk_person("아내", None)  # 성별 모름
        kid2 = mk_person("둘째", None, "20180101")
        kid1 = mk_person("첫째", "female", "20150101")
        grandma = mk_person("할머니", "female", deceased=True)
        parent(grandma, dad)
        parent(dad, me); parent(mom, me); parent(step, me, "step")
        parent(dad, sis); parent(mom, sis)
        spouse(dad, mom, "divorced"); spouse(dad, step)
        spouse(me, wife)
        parent(me, kid1); parent(wife, kid1); parent(me, kid2)
        db.session.commit()
        return by_name(build_tree_data(1))


def test_parents_limited_to_two_preferring_biological(family):
    assert family["나"]["parents"] == ["아버지", "어머니"]
    # 의붓 관계는 차트에서 빠지므로 새어머니의 자녀에도 없다
    assert family["새어머니"]["children"] == []


def test_relations_are_symmetric(family):
    for name, node in family.items():
        for p in node["parents"]:
            assert name in family[p]["children"]
        for c in node["children"]:
            assert name in family[c]["parents"]
        for s in node["spouses"]:
            assert name in family[s]["spouses"]


def test_children_sorted_by_birth(family):
    assert family["나"]["children"] == ["첫째", "둘째"]
    assert family["아버지"]["spouses"] == ["새어머니", "어머니"]


def test_unknown_gender_inferred_from_partner(family):
    wife = family["아내"]["data"]
    assert wife["gender"] == "F" and wife["gender_unknown"] is True
    kid2 = family["둘째"]["data"]
    assert kid2["gender"] in ("M", "F") and kid2["gender_unknown"] is True
    assert family["나"]["data"]["gender_unknown"] is False


def test_card_fields(family):
    assert family["아버지"]["data"]["birth"] == "1955"
    assert family["할머니"]["data"]["birth"] == ""
    assert family["할머니"]["data"]["deceased"] is True


def test_other_group_excluded(app, admin):
    with app.app_context():
        other = FamilyGroup(name="다른 집안")
        db.session.add(other)
        db.session.flush()
        mk_person("남", group=other.id)
        db.session.commit()
        names = {d["data"]["name"] for d in build_tree_data(1)}
    assert "남" not in names and "관리자" in names


def test_tree_endpoints(app, client, admin):
    assert client.get("/tree").status_code == 302
    assert client.get("/tree/data").status_code == 302

    login(client, "관리자", "19700101", "111111")
    assert client.get("/").headers["Location"].endswith("/tree")
    page = client.get("/tree")
    assert page.status_code == 200
    assert "family-chart-0.9.0.min.js" in page.get_data(as_text=True)

    data = client.get("/tree/data").get_json()
    assert [d["data"]["name"] for d in data] == ["관리자"]

    assert client.get("/tree?main=9999").status_code == 404
