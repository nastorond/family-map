import click
from flask import Flask
from sqlalchemy import select

from .auth import find_user, hash_pin
from .models import GENDERS, FamilyGroup, Person, User, db
from .validation import parse_birth_date, validate_pin


def register(app: Flask) -> None:
    app.cli.add_command(create_admin)


@click.command("create-admin")
@click.option("--name", prompt="이름")
@click.option("--birth-date", prompt="생년월일 8자리")
@click.option("--gender", prompt="성별", type=click.Choice(list(GENDERS)))
@click.option("--pin", prompt="PIN 6자리", hide_input=True, confirmation_prompt=True)
def create_admin(name: str, birth_date: str, gender: str, pin: str) -> None:
    """첫 관리자 계정을 만든다 (승인 상태, Person 노드 포함)."""
    try:
        birth_date = parse_birth_date(birth_date)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="--birth-date")
    if err := validate_pin(pin):
        raise click.BadParameter(err, param_hint="--pin")
    name = name.strip()
    if find_user(name, birth_date):
        raise click.ClickException("같은 이름과 생년월일의 계정이 이미 있어요.")

    group = db.session.scalar(select(FamilyGroup).order_by(FamilyGroup.id).limit(1))
    person = Person(family_group_id=group.id, name=name, gender=gender, birth_date=birth_date)
    user = User(
        name=name,
        birth_date=birth_date,
        gender=gender,
        pin_hash=hash_pin(pin),
        status="approved",
        role="admin",
        person=person,
    )
    db.session.add_all([person, user])
    db.session.flush()
    person.created_by = user.id
    db.session.commit()
    click.echo(f"관리자 {name} 계정을 만들었어요.")
