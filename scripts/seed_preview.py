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
from app.models import Person, User, db  # noqa: E402

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
    db.session.add(Person(family_group_id=1, name="박순자", gender="female", birth_date=None, is_deceased=True, created_by=admin.id))

    for name, birth, gender in [("김민수", "19850312", "male"), ("이영희", "19900520", "female")]:
        db.session.add(User(name=name, birth_date=birth, gender=gender, pin_hash=hash_pin("123456")))
    db.session.commit()

print(f"테스트 데이터를 만들었어요: {db_path}")
