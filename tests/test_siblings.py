import pytest
from sqlalchemy import select

from app.models import Person, Relation, db
from app.people import sibling_title
from tests.conftest import add, person_by_name, relations


def add_sib(client, pid, **fields):
    data = {"name": "형제", "gender": "", "birth_date": "", "phone": ""}
    data.update(fields)
    return client.post(f"/people/{pid}/add-sibling", data=data)


@pytest.mark.parametrize(
    "me,sib,expected",
    [
        (("male", "19850312"), ("male", "19800101"), "형"),
        (("female", "19850312"), ("male", "19800101"), "오빠"),
        (("male", "19850312"), ("female", "19800101"), "누나"),
        (("female", "19850312"), ("female", "19800101"), "언니"),
        (("male", "19850312"), ("male", "19900101"), "남동생"),
        (("female", "19850312"), ("female", "19900101"), "여동생"),
        (("male", None), ("female", "19900101"), "여자 형제"),
        ((None, "19850312"), (None, "19900101"), "형제자매"),
    ],
)
def test_sibling_title(me, sib, expected):
    a = Person(name="나", gender=me[0], birth_date=me[1])
    b = Person(name="형제", gender=sib[0], birth_date=sib[1])
    assert sibling_title(a, b) == expected


def test_add_sibling_shares_both_parents(app, as_member, member):
    add(as_member, member, "parent", name="아버지", gender="male")
    add(as_member, member, "parent", name="어머니", gender="female")
    res = add_sib(as_member, member, name="누나", gender="female", birth_date="19800101")
    assert res.status_code == 302

    rels = relations(app)
    assert ("parent_child", "아버지", "누나", "biological", None) in rels
    assert ("parent_child", "어머니", "누나", "biological", None) in rels
    page = as_member.get(f"/people/{member}").get_data(as_text=True)
    assert ">누나<" in page  # 호칭
    assert "한쪽 부모만 같음" not in page


def test_half_sibling(app, as_member, member):
    add(as_member, member, "parent", name="아버지", gender="male")
    add(as_member, member, "parent", name="어머니", gender="female")
    father = person_by_name(app, "아버지")
    res = add_sib(as_member, member, name="이복동생", gender="male", birth_date="19950101", share=str(father.id))
    assert res.status_code == 302
    rels = relations(app)
    assert ("parent_child", "아버지", "이복동생", "biological", None) in rels
    assert not any(r[1] == "어머니" and r[2] == "이복동생" for r in rels)
    page = as_member.get(f"/people/{member}").get_data(as_text=True)
    assert "남동생" in page and "한쪽 부모만 같음" in page


def test_add_sibling_without_parents_creates_parents(app, as_member, member):
    res = add_sib(as_member, member, name="여동생", gender="female", father_name="홍판서")
    assert res.status_code == 302
    rels = relations(app)
    assert ("parent_child", "홍판서", "홍길동", "biological", None) in rels
    assert ("parent_child", "홍판서", "여동생", "biological", None) in rels
    assert ("parent_child", "이름 모름", "홍길동", "biological", None) in rels
    assert ("parent_child", "이름 모름", "여동생", "biological", None) in rels
    mom = person_by_name(app, "이름 모름")
    assert mom.gender == "female"
    # 두 번째 형제는 새로 만든 부모를 그대로 쓴다
    add_sib(as_member, member, name="막내", share="all")
    with app.app_context():
        assert len(db.session.scalars(select(Person).where(Person.name == "홍판서")).all()) == 1
    assert ("parent_child", "홍판서", "막내", "biological", None) in relations(app)


def test_link_existing_person_as_sibling(app, as_member, member):
    add(as_member, member, "parent", name="아버지", gender="male")
    add(as_member, member, "spouse", name="김철수", gender="male", birth_date="19800101")
    other = person_by_name(app, "김철수")

    res = add_sib(as_member, member, name="김철수", birth_date="19800101")
    assert "같은 사람일 수 있는" in res.get_data(as_text=True)

    res = as_member.post(f"/people/{member}/add-sibling", data={"link_to": str(other.id)})
    assert res.status_code == 302
    assert ("parent_child", "아버지", "김철수", "biological", None) in relations(app)

    # 자기 자신은 안 됨
    res = as_member.post(f"/people/{member}/add-sibling", data={"link_to": str(member)})
    assert res.status_code == 400


def test_sibling_validation(app, as_member, member):
    assert add_sib(as_member, member, name="").status_code == 400
    add(as_member, member, "parent", name="아버지", gender="male")
    assert add_sib(as_member, member, name="누구", share="9999").status_code == 400
