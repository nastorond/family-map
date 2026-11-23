from sqlalchemy import select

from app.auth import hash_pin
from app.models import Person, Relation, User, db
from tests.conftest import add, login, person_by_name, relations


def rel_id(app, a_name, b_name):
    with app.app_context():
        a, b = person_by_name(app, a_name), person_by_name(app, b_name)
        return db.session.scalar(select(Relation.id).where(
            ((Relation.person_a_id == a.id) & (Relation.person_b_id == b.id))
            | ((Relation.person_a_id == b.id) & (Relation.person_b_id == a.id))
        ))


def second_member(app, member, client):
    """홍길동의 아버지로 연결된 두 번째 일반 계정 (김아빠, 19550101, PIN 222222)으로 로그인."""
    with app.app_context():
        dad = Person(family_group_id=1, name="김아빠", gender="male", birth_date="19550101")
        db.session.add(dad)
        db.session.flush()
        db.session.add(User(name="김아빠", birth_date="19550101", gender="male",
                            pin_hash=hash_pin("222222"), status="approved", person=dad))
        db.session.add(Relation(family_group_id=1, type="parent_child", person_a_id=dad.id,
                                person_b_id=member, kind="biological"))
        db.session.commit()
    client.post("/logout")
    login(client, "김아빠", "19550101", "222222")


# --- 관계 끊기 ---

def test_creator_can_unlink_relation(app, as_member, member):
    add(as_member, member, "child", name="아이")
    rid = rel_id(app, "홍길동", "아이")
    res = as_member.post(f"/people/relations/{rid}/delete", data={"back": str(member)})
    assert res.status_code == 302 and res.headers["Location"].endswith(f"/people/{member}")
    assert relations(app) == []
    assert person_by_name(app, "아이") is not None  # 사람은 남는다


def test_other_member_cannot_unlink(app, as_member, member):
    add(as_member, member, "child", name="아이")
    rid = rel_id(app, "홍길동", "아이")
    second_member(app, member, as_member)
    assert as_member.post(f"/people/relations/{rid}/delete").status_code == 403
    assert len(relations(app)) == 2  # 아이 관계 + 김아빠 관계


def test_admin_can_unlink_anything(app, client, admin, member):
    login(client, "관리자", "19700101", "111111")
    with app.app_context():
        r = Relation(family_group_id=1, type="spouse", person_a_id=min(admin, member), person_b_id=max(admin, member), status="married")
        db.session.add(r)
        db.session.commit()
        rid = r.id
    assert client.post(f"/people/relations/{rid}/delete").status_code == 302


def test_unlink_hidden_relation_404(app, as_member, member):
    with app.app_context():
        a, b = Person(family_group_id=1, name="남1"), Person(family_group_id=1, name="남2")
        db.session.add_all([a, b])
        db.session.flush()
        r = Relation(family_group_id=1, type="spouse", person_a_id=a.id, person_b_id=b.id, status="married")
        db.session.add(r)
        db.session.commit()
        rid = r.id
    assert as_member.post(f"/people/relations/{rid}/delete").status_code == 404


# --- 관계 세부 바꾸기 ---

def test_update_kind_and_status(app, as_member, member):
    add(as_member, member, "parent", name="엄마", gender="female")
    add(as_member, member, "spouse", name="아내", gender="female")
    as_member.post(f"/people/relations/{rel_id(app, '엄마', '홍길동')}/update", data={"kind": "step"})
    as_member.post(f"/people/relations/{rel_id(app, '홍길동', '아내')}/update", data={"status": "divorced"})
    rels = relations(app)
    assert ("parent_child", "엄마", "홍길동", "step", None) in rels
    assert ("spouse", "홍길동", "아내", None, "divorced") in rels
    assert as_member.post(f"/people/relations/{rel_id(app, '엄마', '홍길동')}/update", data={"kind": "nope"}).status_code == 400


def test_update_respects_two_bio_parents(app, as_member, member):
    add(as_member, member, "parent", name="아빠", gender="male")
    add(as_member, member, "parent", name="엄마", gender="female")
    add(as_member, member, "parent", name="새엄마", gender="female", kind="step")
    as_member.post(f"/people/relations/{rel_id(app, '새엄마', '홍길동')}/update", data={"kind": "biological"})
    assert ("parent_child", "새엄마", "홍길동", "step", None) in relations(app)


# --- 사람 삭제 ---

def test_creator_can_delete_person_and_relations(app, as_member, member):
    add(as_member, member, "child", name="아이")
    kid = person_by_name(app, "아이")
    add(as_member, kid.id, "spouse", name="사위")
    res = as_member.post(f"/people/{kid.id}/delete")
    assert res.status_code == 302 and res.headers["Location"].endswith("/tree")
    assert person_by_name(app, "아이") is None
    assert relations(app) == []
    page = as_member.get("/tree").get_data(as_text=True)
    assert "아이님을 삭제했어요. 연결된 관계 2개도 함께 지웠어요." in page


def test_cannot_delete_person_with_account(app, client, admin, member):
    login(client, "관리자", "19700101", "111111")
    res = client.post(f"/people/{member}/delete")
    assert res.status_code == 302
    assert person_by_name(app, "홍길동") is not None


def test_other_member_cannot_delete(app, as_member, member):
    add(as_member, member, "child", name="아이")
    kid = person_by_name(app, "아이")
    second_member(app, member, as_member)
    assert as_member.post(f"/people/{kid.id}/delete").status_code == 403
    assert person_by_name(app, "아이") is not None


def test_detail_shows_controls_only_when_allowed(app, as_member, member):
    add(as_member, member, "child", name="아이")
    kid = person_by_name(app, "아이")
    mine = as_member.get(f"/people/{member}").get_data(as_text=True)
    assert "연결 끊기" in mine and "이 사람 삭제" not in mine  # 나는 가입한 계정이라 삭제 불가
    assert "이 사람 삭제" in as_member.get(f"/people/{kid.id}").get_data(as_text=True)

    second_member(app, member, as_member)
    other = as_member.get(f"/people/{member}").get_data(as_text=True)
    assert "/people/relations/" not in other.split("자녀")[1].split("형제자매")[0]  # 남이 만든 자녀 관계는 관리 못 함
    assert "이 사람 삭제" not in as_member.get(f"/people/{kid.id}").get_data(as_text=True)
