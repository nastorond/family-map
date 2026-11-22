"""화면 확인용 테스트 데이터를 instance/preview.db에 만든다. 실제 가족 데이터가 아니다.

    .\\.venv\\Scripts\\python scripts\\seed_preview.py

테스트 계정
- 관리자: 이름 테스트관리자 / 생년월일 19700101 / PIN 111111
- 승인 대기: 김민수(19850312), 이영희(19900520) / PIN 123456
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
db_path = ROOT / "instance" / "preview.db"
os.environ["DATABASE_PATH"] = str(db_path)
os.environ.setdefault("SECRET_KEY", "preview-only")

for suffix in ("", "-wal", "-shm"):
    Path(f"{db_path}{suffix}").unlink(missing_ok=True)

from app import create_app  # noqa: E402
from app.auth import hash_pin  # noqa: E402
from app.models import Person, Relation, User, db  # noqa: E402

app = create_app()
with app.app_context():
    admin_person = Person(family_group_id=1, name="테스트관리자", gender="male", birth_date="19700101")
    admin = User(
        name="테스트관리자", birth_date="19700101", gender="male",
        pin_hash=hash_pin("111111"), status="approved", role="admin", person=admin_person,
    )
    db.session.add_all([admin_person, admin])
    db.session.flush()
    admin_person.created_by = admin.id

    # 누군가 먼저 등록해 둔 사람 (김민수 가입 때 "같은 사람일 수 있음"으로 보여야 함)
    db.session.add(Person(family_group_id=1, name="김민수", gender="male", birth_date="19850312", created_by=admin.id))

    # 가계도 확인용 3~4세대
    def person(name, gender, birth=None, deceased=False):
        p = Person(family_group_id=1, name=name, gender=gender, birth_date=birth,
                   is_deceased=deceased, created_by=admin.id)
        db.session.add(p)
        db.session.flush()
        return p

    def rel(rtype, a, b, kind=None, status=None):
        if rtype == "spouse":
            a, b = sorted((a, b), key=lambda x: x.id)
            status = status or "married"
        else:
            kind = kind or "biological"
        db.session.add(Relation(family_group_id=1, type=rtype, person_a_id=a.id, person_b_id=b.id,
                                kind=kind, status=status, created_by=admin.id))

    grandpa = person("김덕배", "male", "19200505", deceased=True)
    father = person("김영수", "male", "19450301", deceased=True)
    mother = person("박순자", "female", None, deceased=True)
    brother = person("김철수", "male", "19680815")
    wife = person("이정희", "female", "19720110")
    kid1 = person("김하늘", "female", "20000401")
    kid2 = person("김바다", None, "20030909")  # 성별 모름
    rel("parent_child", grandpa, father)
    rel("spouse", father, mother)
    for child in (admin_person, brother):
        rel("parent_child", father, child)
        rel("parent_child", mother, child)
    rel("spouse", admin_person, wife)
    for child in (kid1, kid2):
        rel("parent_child", admin_person, child)
        rel("parent_child", wife, child)

    for name, birth, gender in [("김민수", "19850312", "male"), ("이영희", "19900520", "female")]:
        db.session.add(User(name=name, birth_date=birth, gender=gender, pin_hash=hash_pin("123456")))
    db.session.commit()

print(f"테스트 데이터를 만들었어요: {db_path}")
