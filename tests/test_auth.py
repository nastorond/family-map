from datetime import timedelta

from sqlalchemy import select

from app import create_app
from app.models import Person, User, db, utcnow
from app.validation import parse_birth_date
from tests.conftest import login, signup

import pytest


def get_user(app, name):
    with app.app_context():
        return db.session.scalar(select(User).where(User.name == name))


# --- 생년월일 ---

@pytest.mark.parametrize("raw,expected", [("19850312", "19850312"), ("1985-03-12", "19850312"), ("1985.3.12".replace(".3.", ".03."), "19850312")])
def test_parse_birth_date_ok(raw, expected):
    assert parse_birth_date(raw) == expected


@pytest.mark.parametrize("raw", ["850312", "19851340", "20230229", "18000101", "29991231", ""])
def test_parse_birth_date_rejects(raw):
    with pytest.raises(ValueError):
        parse_birth_date(raw)


# --- 가입 ---

def test_signup_creates_pending_user(app, client):
    res = signup(client)
    assert res.status_code == 200
    assert "승인 대기" in res.get_data(as_text=True)
    user = get_user(app, "홍길동")
    assert user.status == "pending"
    assert user.person_id is None
    assert user.pin_hash != "123456"


def test_signup_rejects_duplicate(client):
    signup(client)
    res = signup(client)
    assert res.status_code == 400
    assert "이미 있어요" in res.get_data(as_text=True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"pin": "1234"},
        {"pin": "123456", "pin_confirm": "654321"},
        {"birth_date": "19851340"},
        {"gender": ""},
        {"name": "  "},
    ],
)
def test_signup_validation(app, client, kwargs):
    res = signup(client, **kwargs)
    assert res.status_code == 400
    assert get_user(app, "홍길동") is None


# --- 로그인 ---

def test_pending_user_cannot_log_in(client):
    signup(client)
    res = login(client, "홍길동", "19850312", "123456")
    assert "승인 대기" in res.get_data(as_text=True)
    assert client.get("/").status_code == 302


def test_unknown_user_gets_generic_error(client):
    res = login(client, "없는사람", "19900101", "123456")
    assert res.status_code == 401


def test_lock_after_five_failures(app, client, admin):
    for i in range(4):
        res = login(client, "관리자", "19700101", "000000")
        assert res.status_code == 401
        assert f"남은 시도 {4 - i}번" in res.get_data(as_text=True)

    res = login(client, "관리자", "19700101", "000000")
    assert res.status_code == 423

    # 잠긴 동안은 맞는 PIN도 거절
    res = login(client, "관리자", "19700101", "111111")
    assert res.status_code == 423

    # 잠금 시간이 지나면 다시 로그인 가능
    with app.app_context():
        user = db.session.get(User, admin)
        user.locked_until = utcnow() - timedelta(seconds=1)
        db.session.commit()
    res = login(client, "관리자", "19700101", "111111")
    assert res.status_code == 302


def test_success_resets_failed_attempts(app, client, admin):
    login(client, "관리자", "19700101", "000000")
    login(client, "관리자", "19700101", "111111")
    with app.app_context():
        assert db.session.get(User, admin).failed_attempts == 0


# --- 관리자 ---

def test_member_cannot_open_admin(app, client, admin):
    signup(client)
    login(client, "관리자", "19700101", "111111")
    uid = get_user(app, "홍길동").id
    client.post(f"/admin/users/{uid}/approve", data={"target": "new"})
    client.post("/logout")

    login(client, "홍길동", "19850312", "123456")
    assert client.get("/admin/users").status_code == 403


def test_not_logged_in_redirects(client):
    assert client.get("/admin/users").status_code == 302


def test_approve_as_new_person(app, client, admin):
    signup(client)
    login(client, "관리자", "19700101", "111111")
    uid = get_user(app, "홍길동").id
    res = client.post(f"/admin/users/{uid}/approve", data={"target": "new"})
    assert res.status_code == 302

    with app.app_context():
        user = db.session.get(User, uid)
        assert user.status == "approved"
        assert user.person.name == "홍길동"
        assert user.person.gender == "male"
        assert user.person.created_by == admin

    client.post("/logout")
    res = login(client, "홍길동", "19850312", "123456")
    assert res.status_code == 302
    assert "홍길동님" in client.get("/").get_data(as_text=True)


def test_approve_links_existing_person_and_shows_candidate(app, client, admin):
    with app.app_context():
        existing = Person(family_group_id=1, name="홍길동", gender="male", birth_date="19850312")
        db.session.add(existing)
        db.session.commit()
        pid = existing.id

    signup(client)
    login(client, "관리자", "19700101", "111111")
    page = client.get("/admin/users").get_data(as_text=True)
    assert "같은 사람일 수 있음" in page

    uid = get_user(app, "홍길동").id
    client.post(f"/admin/users/{uid}/approve", data={"target": str(pid)})
    with app.app_context():
        assert db.session.get(User, uid).person_id == pid
        assert db.session.scalars(select(Person).where(Person.name == "홍길동")).all().__len__() == 1


def test_cannot_link_person_that_already_has_account(app, client, admin):
    signup(client)
    login(client, "관리자", "19700101", "111111")
    uid = get_user(app, "홍길동").id
    with app.app_context():
        admin_person_id = db.session.get(User, admin).person_id
    client.post(f"/admin/users/{uid}/approve", data={"target": str(admin_person_id)})
    assert get_user(app, "홍길동").status == "pending"


def test_reject_deletes_signup(app, client, admin):
    signup(client)
    login(client, "관리자", "19700101", "111111")
    uid = get_user(app, "홍길동").id
    client.post(f"/admin/users/{uid}/reject")
    assert get_user(app, "홍길동") is None


def test_admin_unlock(app, client, admin):
    signup(client)
    login(client, "관리자", "19700101", "111111")
    uid = get_user(app, "홍길동").id
    client.post(f"/admin/users/{uid}/approve", data={"target": "new"})
    with app.app_context():
        user = db.session.get(User, uid)
        user.locked_until = utcnow() + timedelta(minutes=30)
        db.session.commit()
    client.post(f"/admin/users/{uid}/unlock")
    assert get_user(app, "홍길동").locked_until is None


# --- 보안 설정 ---

def test_csrf_required_when_enabled(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'csrf.db'}",
        }
    )
    res = app.test_client().post("/login", data={"name": "a", "birth_date": "19900101", "pin": "123456"})
    assert res.status_code == 400
    with app.app_context():
        db.engine.dispose()
