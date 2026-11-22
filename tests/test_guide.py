from app.models import User, db
from tests.conftest import add, person_by_name
from tests.test_tree import mk_person, spouse

HX = {"HX-Request": "true"}


def test_categories_full_page_and_partial(as_member):
    full = as_member.get("/people/guide").get_data(as_text=True)
    assert "<html" in full and "어느 쪽 가족인가요?" in full
    part = as_member.get("/people/guide", headers=HX).get_data(as_text=True)
    assert "<html" not in part
    for name in ("우리 가족", "친가", "외가", "처가"):  # 홍길동은 남자 → 처가
        assert f"<strong>{name}</strong>" in part


def test_header_opens_popup(as_member):
    page = as_member.get("/tree").get_data(as_text=True)
    assert 'hx-get="/people/guide"' in page and 'id="add-dialog"' in page
    assert "htmx-2.0.4.min.js" in page


def test_paternal_without_father(as_member, member):
    part = as_member.get("/people/guide/paternal", headers=HX).get_data(as_text=True)
    # 아버지는 바로 내 추가 화면으로 (성별 남 미리 선택)
    assert f'href="/people/{member}/add?rel=parent&amp;gender=male&amp;guide=father"' in part
    # 할아버지는 아버지가 먼저 있어야 함. 안내 링크는 바로 아버지 입력 화면으로
    assert "먼저 <b>아버지</b>을(를) 등록해야 해요" in part
    assert part.count(f'/people/{member}/add?rel=parent&amp;gender=male&amp;guide=father') >= 2


def test_paternal_with_father_and_uncles(app, as_member, member):
    add(as_member, member, "parent", name="아버지", gender="male", birth_date="19550101")
    father = person_by_name(app, "아버지")
    part = as_member.get("/people/guide/paternal", headers=HX).get_data(as_text=True)
    assert f'href="/people/{father.id}/add?rel=parent&amp;guide=p_grand"' in part
    assert f'href="/people/{father.id}/add-sibling?gender=male&amp;guide=p_uncle"' in part
    assert "먼저 <b>아버지의 형제자매</b>" in part  # 사촌은 아직

    as_member.post(f"/people/{father.id}/add-sibling", data={"name": "큰아버지", "gender": "male", "birth_date": "19500101"})
    as_member.post(f"/people/{father.id}/add-sibling", data={"name": "고모", "gender": "female", "birth_date": "19580101"})
    part = as_member.get("/people/guide/paternal", headers=HX).get_data(as_text=True)
    assert "2명 중 선택" in part  # 사촌: 큰아버지와 고모 중 누구의 자녀인지

    page = as_member.get("/people/guide/paternal/p_cousin", headers=HX).get_data(as_text=True)
    uncle, aunt = person_by_name(app, "큰아버지"), person_by_name(app, "고모")
    assert "누구의 자녀인가요?" in page
    assert f"/people/{uncle.id}/add?rel=child" in page and f"/people/{aunt.id}/add?rel=child" in page
    assert "큰아버지</span>" in page and "고모</span>" in page  # 나 기준 호칭


def test_add_form_prefilled_from_guide(app, as_member, member):
    add(as_member, member, "parent", name="아버지", gender="male")
    father = person_by_name(app, "아버지")
    page = as_member.get(f"/people/{father.id}/add-sibling?gender=male&guide=p_uncle").get_data(as_text=True)
    assert "나에게 <strong>큰아버지·작은아버지</strong>" in page
    assert 'value="male" checked' in page


def test_inlaw_labels_for_female(app, client, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        user.person.gender = "female"
        h = mk_person("남편", "male")
        spouse(user.person, h)
        db.session.commit()
    from tests.conftest import login
    login(client, "관리자", "19700101", "111111")
    cats = client.get("/people/guide", headers=HX).get_data(as_text=True)
    assert "<strong>시가</strong>" in cats
    part = client.get("/people/guide/inlaw", headers=HX).get_data(as_text=True)
    assert "시아버지·시어머니" in part and "아주버님·시동생·시누이" in part


def test_unknown_category_404(as_member):
    assert as_member.get("/people/guide/nope").status_code == 404
    assert as_member.get("/people/guide/paternal/m_uncle").status_code == 404  # 다른 분류의 유형
