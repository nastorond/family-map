from datetime import datetime, timezone
from typing import Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def utcnow() -> datetime:
    """SQLite에는 시간대 없이 UTC로 저장한다."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


GENDERS = {"male": "남", "female": "여"}
PARENT_KINDS = {"biological": "친생", "adoptive": "입양", "step": "의붓"}
SPOUSE_STATUSES = {"married": "혼인 중", "divorced": "이혼", "widowed": "사별"}


class FamilyGroup(db.Model):
    __tablename__ = "family_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Person(db.Model):
    """가계도의 사람 노드. 가입하지 않은 사람, 고인, 아이도 포함한다."""

    __tablename__ = "persons"
    __table_args__ = (
        CheckConstraint("gender IN ('male', 'female')", name="ck_person_gender"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_group_id: Mapped[int] = mapped_column(ForeignKey("family_groups.id"), index=True)
    name: Mapped[str] = mapped_column(String(50), index=True)
    gender: Mapped[Optional[str]] = mapped_column(String(10))  # 모르면 NULL
    birth_date: Mapped[Optional[str]] = mapped_column(String(8))  # YYYYMMDD, 모르면 NULL
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    is_deceased: Mapped[bool] = mapped_column(default=False)
    # users ↔ persons 순환 참조라 use_alter로 생성 순서 문제를 피한다.
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_person_created_by")
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    family_group: Mapped[FamilyGroup] = relationship()
    # 연결된 계정. 계정 쪽(User.person_id)에만 외래키를 둔다.
    user: Mapped[Optional["User"]] = relationship(
        back_populates="person", foreign_keys="User.person_id", uselist=False
    )


class Relation(db.Model):
    """저장하는 관계는 parent_child, spouse 두 종류뿐이다.

    - parent_child: person_a = 부모, person_b = 자녀. kind로 친생/입양/의붓 구분.
    - spouse: 양방향. person_a_id < person_b_id로 정렬해 저장. status로 혼인 상태 구분.
    """

    __tablename__ = "relations"
    __table_args__ = (
        UniqueConstraint("type", "person_a_id", "person_b_id", name="uq_relation"),
        CheckConstraint("type IN ('parent_child', 'spouse')", name="ck_relation_type"),
        CheckConstraint("person_a_id <> person_b_id", name="ck_relation_self"),
        CheckConstraint(
            "(type = 'parent_child' AND kind IN ('biological', 'adoptive', 'step') AND status IS NULL)"
            " OR (type = 'spouse' AND status IN ('married', 'divorced', 'widowed') AND kind IS NULL)",
            name="ck_relation_detail",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_group_id: Mapped[int] = mapped_column(ForeignKey("family_groups.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    person_a_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    person_b_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    kind: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[Optional[str]] = mapped_column(String(20))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    person_a: Mapped[Person] = relationship(foreign_keys=[person_a_id])
    person_b: Mapped[Person] = relationship(foreign_keys=[person_b_id])


class User(db.Model):
    """로그인 계정. 가입 때 입력한 이름/생년월일/성별을 그대로 갖고,
    관리자가 승인하면서 Person에 연결한다."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("name", "birth_date", name="uq_user_name_birth"),
        CheckConstraint("status IN ('pending', 'approved')", name="ck_user_status"),
        CheckConstraint("role IN ('admin', 'member')", name="ck_user_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    birth_date: Mapped[str] = mapped_column(String(8))
    gender: Mapped[str] = mapped_column(String(10))
    person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("persons.id"), unique=True)
    pin_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    role: Mapped[str] = mapped_column(String(10), default="member")
    failed_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column()

    person: Mapped[Optional[Person]] = relationship(
        back_populates="user", foreign_keys=[person_id]
    )

    def is_locked(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        return self.locked_until is not None and self.locked_until > now
