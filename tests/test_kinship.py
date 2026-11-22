import pytest

from app.kinship import chon_label, kinships_from
from app.models import Person, User, db
from tests.conftest import login
from tests.test_tree import mk_person, parent, spouse


@pytest.fixture
def kin(app, admin):
    """나(남, 1985) 기준 큰 집안. {이름: (호칭, 촌수표시)}"""
    with app.app_context():
        P = {}

        def m(name, gender=None, birth=None):
            P[name] = mk_person(name, gender, birth)
            return P[name]

        m("나", "male", "19850312")
        m("아버지", "male", "19550101"); m("어머니", "female", "19570101")
        m("할아버지", "male", "19250101"); m("할머니", "female", "19270101")
        m("외할아버지", "male", "19300101")
        m("증조할아버지", "male", "19000101")
        m("큰할아버지", "male", "19200101"); m("고모할머니", "female", "19290101")
        m("큰아버지", "male", "19500101"); m("큰어머니", "female", "19520101")
        m("작은아버지", "male", "19600101"); m("삼촌", "male")
        m("고모", "female", "19580101"); m("고모부", "male")
        m("사촌", "male", "19800101"); m("고종사촌", "female", "19830101")
        m("외삼촌", "male", "19590101"); m("이모", "female", "19610101"); m("이모부", "male")
        m("외사촌", "female", "19900101"); m("이종사촌", "male", "19920101")
        m("누나", "female", "19820101"); m("매형", "male", "19790101")
        m("남동생", "male", "19880101"); m("제수", "female", "19900101")
        m("조카", "male", "20100101")
        m("아내", "female", "19870101"); m("장인", "male", "19600101"); m("장모", "female")
        m("처제", "female", "19900101"); m("처남", "male", "19850101")
        m("아들", "male", "20120101"); m("며느리", "female", "20120202"); m("손자", "male")
        m("모르는사람", None)
        m("누나의시어머니", "female")

        parent(P["증조할아버지"], P["할아버지"]); parent(P["증조할아버지"], P["큰할아버지"])
        parent(P["증조할아버지"], P["고모할머니"])
        parent(P["할아버지"], P["아버지"]); parent(P["할머니"], P["아버지"])
        spouse(P["할아버지"], P["할머니"])
        parent(P["외할아버지"], P["어머니"])
        for c in ("큰아버지", "작은아버지", "삼촌", "고모"):
            parent(P["할아버지"], P[c])
        spouse(P["큰아버지"], P["큰어머니"]); spouse(P["고모"], P["고모부"])
        parent(P["큰아버지"], P["사촌"]); parent(P["고모"], P["고종사촌"])
        for c in ("외삼촌", "이모"):
            parent(P["외할아버지"], P[c])
        spouse(P["이모"], P["이모부"])
        parent(P["외삼촌"], P["외사촌"]); parent(P["이모"], P["이종사촌"])
        for c in ("나", "누나", "남동생"):
            parent(P["아버지"], P[c]); parent(P["어머니"], P[c])
        spouse(P["아버지"], P["어머니"])
        spouse(P["누나"], P["매형"]); spouse(P["남동생"], P["제수"])
        parent(P["남동생"], P["조카"])
        spouse(P["나"], P["아내"])
        for c in ("아내", "처제", "처남"):
            parent(P["장인"], P[c]); parent(P["장모"], P[c])
        parent(P["나"], P["아들"]); parent(P["아내"], P["아들"])
        spouse(P["아들"], P["며느리"]); parent(P["아들"], P["손자"])
        parent(P["누나의시어머니"], P["매형"])
        db.session.commit()

        kins = kinships_from(P["나"])
        names = {p.id: name for name, p in P.items()}
        return {names[pid]: (k.title, chon_label(k)) for pid, k in kins.items()}


@pytest.mark.parametrize(
    "name,title,chon",
    [
        ("나", "나", ""),
        ("아버지", "아버지", "1촌"), ("어머니", "어머니", "1촌"),
        ("할아버지", "할아버지", "2촌"), ("할머니", "할머니", "2촌"),
        ("외할아버지", "외할아버지", "2촌"),
        ("증조할아버지", "증조할아버지", "3촌"),
        ("큰할아버지", "큰할아버지", "4촌"), ("고모할머니", "고모할머니", "4촌"),
        ("큰아버지", "큰아버지", "3촌"), ("작은아버지", "작은아버지", "3촌"), ("삼촌", "삼촌", "3촌"),
        ("고모", "고모", "3촌"), ("큰어머니", "큰어머니", "인척"), ("고모부", "고모부", "인척"),
        ("사촌", "사촌", "4촌"), ("고종사촌", "고종사촌", "4촌"),
        ("외삼촌", "외삼촌", "3촌"), ("이모", "이모", "3촌"), ("이모부", "이모부", "인척"),
        ("외사촌", "외사촌", "4촌"), ("이종사촌", "이종사촌", "4촌"),
        ("누나", "누나", "2촌"), ("남동생", "남동생", "2촌"),
        ("매형", "매형", "인척"), ("제수", "제수", "인척"),
        ("조카", "조카", "3촌"),
        ("아내", "아내", "무촌"), ("장인", "장인", "인척"), ("장모", "장모", "인척"),
        ("처제", "처제", "인척"), ("처남", "처남", "인척"),
        ("아들", "아들", "1촌"), ("며느리", "며느리", "인척"), ("손자", "손자", "2촌"),
    ],
)
def test_titles(kin, name, title, chon):
    assert kin[name] == (title, chon)


def test_fallback_is_descriptive(kin):
    # 표에 없는 관계는 풀어서 쓴다: 누나 → 남편 → 어머니
    assert kin["누나의시어머니"][0] == "누나의 남편의 어머니"


def test_unconnected_person_missing(kin):
    assert "모르는사람" not in kin


def test_female_me_titles(app, admin):
    with app.app_context():
        me = mk_person("나", "female", "19900101")
        bro = mk_person("오빠", "male", "19870101")
        bro_wife = mk_person("올케", "female")
        sis = mk_person("언니", "female", "19880101")
        sis_h = mk_person("형부", "male")
        h = mk_person("남편", "male", "19880101")
        hp = mk_person("시어머니", "female")
        hb_old = mk_person("아주버님", "male", "19850101")
        hs = mk_person("시누이", "female", "19920101")
        dad = mk_person("아빠", "male")
        for c in (me, bro, sis):
            parent(dad, c)
        spouse(bro, bro_wife); spouse(sis, sis_h); spouse(me, h)
        for c in (h, hb_old, hs):
            parent(hp, c)
        db.session.commit()
        kins = kinships_from(me)
        titles = {db.session.get(Person, pid).name: k.title for pid, k in kins.items()}
    for name in ("오빠", "올케", "언니", "형부", "남편", "시어머니", "아주버님", "시누이"):
        assert titles[name] == name


def test_kinship_shown_on_detail_and_tree(app, client, admin):
    with app.app_context():
        me = db.session.get(User, admin).person
        dad = mk_person("아빠", "male", "19400101")
        uncle = mk_person("큰집", "male", "19350101")
        grandpa = mk_person("할배", "male")
        parent(dad, me); parent(grandpa, dad); parent(grandpa, uncle)
        db.session.commit()
        uncle_id = uncle.id
    login(client, "관리자", "19700101", "111111")
    page = client.get(f"/people/{uncle_id}").get_data(as_text=True)
    assert "큰아버지" in page and "3촌" in page
    data = client.get("/tree/data").get_json()
    titles = {n["name"]: n["title"] for n in data["nodes"]}
    assert titles["큰집"] == "큰아버지" and titles["관리자"] == ""


def test_pick_page(app, client, admin):
    with app.app_context():
        me = db.session.get(User, admin).person
        dad = mk_person("아빠", "male")
        mk_person("남남")
        parent(dad, me)
        db.session.commit()
    login(client, "관리자", "19700101", "111111")
    page = client.get("/people").get_data(as_text=True)
    assert "아버지의 형제자매" in page  # 아빠 줄의 형제자매 추가 안내
    assert "나와 연결 안 됨" in page
    assert page.index("관리자") < page.index("아빠") < page.index("남남")
