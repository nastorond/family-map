import pytest

from app import create_app
from app.auth import hash_pin
from app.models import Person, User, db


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
            "WTF_CSRF_ENABLED": False,
        }
    )
    yield app
    with app.app_context():
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(app):
    """승인된 관리자 계정 (이름 관리자, 19700101, PIN 111111)."""
    with app.app_context():
        person = Person(family_group_id=1, name="관리자", gender="male", birth_date="19700101")
        user = User(
            name="관리자",
            birth_date="19700101",
            gender="male",
            pin_hash=hash_pin("111111"),
            status="approved",
            role="admin",
            person=person,
        )
        db.session.add_all([person, user])
        db.session.commit()
        return user.id


def login(client, name, birth_date, pin):
    return client.post("/login", data={"name": name, "birth_date": birth_date, "pin": pin})


def signup(client, name="홍길동", birth_date="19850312", gender="male", pin="123456", pin_confirm=None):
    return client.post(
        "/signup",
        data={
            "name": name,
            "birth_date": birth_date,
            "gender": gender,
            "pin": pin,
            "pin_confirm": pin if pin_confirm is None else pin_confirm,
        },
    )
