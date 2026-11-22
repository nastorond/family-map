import pytest
from sqlalchemy import select

from app.auth import hash_pin
from app.models import Person, Relation, User, db
from app.validation import parse_phone
from tests.conftest import login


@pytest.fixture
def member(app, admin):
    """승인된 일반 계정 (홍길동, 19850312, PIN 123456). person id를 돌려준다."""
    with app.app_context():
        person = Person(family_group_id=1, name="홍길동", gender="male", birth_date="19850312", created_by=admin)
        user = User(
            name="홍길동", birth_date="19850312", gender="male",
            pin_hash=hash_pin("123456"), status="approved", person=person,
        )
        db.session.add_all([person, user])
        db.session.commit()
        return person.id


@pytest.fixture
def as_member(client, member):
    login(client, "홍길동", "19850312", "123456")
    return client


def add(client, pid, rel, **fields):
    data = {"rel": rel, "name": "이름", "gender": "", "birth_date": "", "phone": ""}
    data.update(fields)
    return client.post(f"/people/{pid}/add", data=data)


def relations(app):
    with app.app_context():
        return [
            (r.type, r.person_a.name, r.person_b.name, r.kind, r.status)
            for r in db.session.scalars(select(Relation).order_by(Relation.id))
        ]


def person_by_name(app, name):
    with app.app_context():
        return db.session.scalar(select(Person).where(Person.name == name))


# --- 전화번호 ---

@pytest.mark.parametrize("raw,expected", [
    ("01012345678", "010-1234-5678"),
    ("010-1234-5678", "010-1234-5678"),
    ("0212345678", "02-1234-5678"),
    ("021234567", "02-123-4567"),
    ("0311234567", "031-123-4567"),
    ("", None),
])
def test_parse_phone(raw, expected):
    assert parse_phone(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "1012345678", "010123456789"])
def test_parse_phone_rejects(raw):
    with pytest.raises(ValueError):
        parse_phone(raw)


# --- 상세 / 홈 ---

def test_home_redirects_to_my_detail(as_member, member):
    res = as_member.get("/")
    assert res.status_code == 302
    assert res.headers["Location"].endswith(f"/people/{member}")
    page = as_member.get(f"/people/{member}").get_data(as_text=True)
    assert "홍길동" in page and ">나<" in page


def test_detail_404_for_other_group(app, as_member):
    with app.app_context():
        from app.models import FamilyGroup
        other = FamilyGroup(name="다른 집안")
        db.session.add(other)
        db.session.flush()
        p = Person(family_group_id=other.id, name="남")
        db.session.add(p)
        db.session.commit()
        pid = p.id
    assert as_member.get(f"/people/{pid}").status_code == 404


# --- 추가 ---

def test_add_parent_child_spouse_with_defaults(app, as_member, member):
    assert add(as_member, member, "parent", name="홍아버지", gender="male", birth_date="19550101").status_code == 302
    assert add(as_member, member, "spouse", name="김배우자", gender="female").status_code == 302
    assert add(as_member, member, "child", name="홍아이", phone="01011112222").status_code == 302

    assert relations(app) == [
        ("parent_child", "홍아버지", "홍길동", "biological", None),
        ("spouse", "홍길동", "김배우자", None, "married"),
        ("parent_child", "홍길동", "홍아이", "biological", None),
    ]
    child = person_by_name(app, "홍아이")
    assert child.phone == "010-1111-2222"
    assert child.birth_date is None and child.gender is None

    page = as_member.get(f"/people/{member}").get_data(as_text=True)
    for name in ("홍아버지", "김배우자", "홍아이"):
        assert name in page


def test_add_with_relation_detail(app, as_member, member):
    add(as_member, member, "parent", name="새엄마", gender="female", kind="step")
    add(as_member, member, "spouse", name="전배우자", gender="female", status="divorced")
    rels = relations(app)
    assert ("parent_child", "새엄마", "홍길동", "step", None) in rels
    assert ("spouse", "홍길동", "전배우자", None, "divorced") in rels
    page = as_member.get(f"/people/{member}").get_data(as_text=True)
    assert "의붓" in page and "이혼" in page


def test_add_validation(app, as_member, member):
    assert add(as_member, member, "parent", name="").status_code == 400
    assert add(as_member, member, "parent", name="누구", birth_date="19551340").status_code == 400
    assert add(as_member, member, "parent", name="누구", phone="123").status_code == 400
    assert add(as_member, member, "sibling", name="누구").status_code == 400
    assert add(as_member, member, "parent", name="누구", kind="weird").status_code == 400
    assert relations(app) == []


def test_at_most_two_biological_parents(app, as_member, member):
    add(as_member, member, "parent", name="아버지")
    add(as_member, member, "parent", name="어머니")
    assert add(as_member, member, "parent", name="세번째").status_code == 400
    # 입양/의붓 부모는 더 등록할 수 있다
    assert add(as_member, member, "parent", name="양부", kind="adoptive").status_code == 302


def test_siblings_are_computed(app, as_member, member):
    add(as_member, member, "parent", name="아버지")
    father = person_by_name(app, "아버지")
    add(as_member, father.id, "child", name="동생")
    page = as_member.get(f"/people/{member}").get_data(as_text=True)
    assert "형제자매" in page and "동생" in page


# --- 중복 후보 ---

def test_duplicate_candidate_shown_before_saving(app, as_member, member):
    add(as_member, member, "parent", name="박순자", gender="female", birth_date="19560303")
    add(as_member, member, "child", name="아이")
    child = person_by_name(app, "아이")

    # 아이 화면에서 할머니를 다시 등록하려는 상황: 같은 이름+생년월일
    res = add(as_member, child.id, "parent", name="박순자", gender="female", birth_date="19560303")
    page = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "같은 사람일 수 있는" in page and "이름·생년월일 같음" in page
    with app.app_context():
        assert len(db.session.scalars(select(Person).where(Person.name == "박순자")).all()) == 1


def test_link_to_candidate(app, as_member, member):
    add(as_member, member, "parent", name="아버지", gender="male")
    father = person_by_name(app, "아버지")
    add(as_member, member, "spouse", name="아내", gender="female")
    wife = person_by_name(app, "아내")

    res = as_member.post(f"/people/{wife.id}/add", data={"rel": "child", "link_to": str(member)})
    assert res.status_code == 302
    assert ("parent_child", "아내", "홍길동", "biological", None) in relations(app)

    # 이미 있는 관계를 다시 걸면 거절
    res = as_member.post(f"/people/{wife.id}/add", data={"rel": "child", "link_to": str(member)})
    assert res.status_code == 400
    # 자손을 부모로 걸면 거절
    res = as_member.post(f"/people/{father.id}/add", data={"rel": "parent", "link_to": str(member)})
    assert res.status_code == 400


def test_confirm_new_creates_separate_person(app, as_member, member):
    add(as_member, member, "parent", name="김철수", birth_date="19500101")
    res = add(as_member, member, "child", name="김철수", birth_date="19500101", confirm_new="1")
    assert res.status_code == 302
    with app.app_context():
        assert len(db.session.scalars(select(Person).where(Person.name == "김철수")).all()) == 2


def test_name_only_candidate_when_birth_unknown(app, as_member, member):
    add(as_member, member, "parent", name="박순자", is_deceased="1")
    res = add(as_member, member, "spouse", name="박순자")
    assert "생년월일 확인 필요" in res.get_data(as_text=True)
    # 생년월일이 둘 다 있고 다르면 후보가 아니다
    add(as_member, member, "child", name="이민호", birth_date="20100101")
    res = add(as_member, member, "child", name="이민호", birth_date="20120202")
    assert res.status_code == 302


# --- 수정 권한 ---

def test_member_can_edit_self_and_own_registrations(app, as_member, member):
    add(as_member, member, "child", name="아이")
    child = person_by_name(app, "아이")

    res = as_member.post(f"/people/{member}/edit", data={"name": "홍길동", "gender": "male", "birth_date": "19850312", "phone": "01099998888"})
    assert res.status_code == 302
    assert person_by_name(app, "홍길동").phone == "010-9999-8888"

    res = as_member.post(f"/people/{child.id}/edit", data={"name": "아이", "is_deceased": "1"})
    assert res.status_code == 302
    assert person_by_name(app, "아이").is_deceased is True


def test_member_cannot_edit_others(app, as_member, admin):
    with app.app_context():
        admin_pid = db.session.get(User, admin).person_id
    assert as_member.get(f"/people/{admin_pid}/edit").status_code == 403
    assert as_member.post(f"/people/{admin_pid}/edit", data={"name": "바꿈"}).status_code == 403
    # 수정은 못 해도 관계 추가는 할 수 있다
    assert add(as_member, admin_pid, "child", name="관리자자녀").status_code == 302


def test_admin_can_edit_anyone(app, client, admin, member):
    login(client, "관리자", "19700101", "111111")
    res = client.post(f"/people/{member}/edit", data={"name": "홍길동", "gender": "male", "birth_date": "19850313"})
    assert res.status_code == 302
    assert person_by_name(app, "홍길동").birth_date == "19850313"
