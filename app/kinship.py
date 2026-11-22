"""나를 기준으로 다른 사람의 호칭과 촌수를 계산한다.

저장된 관계(부모-자녀, 배우자)를 그래프로 보고, 나에서 상대까지의 최단 경로를 구한 뒤
경로를 단계 토큰으로 바꾼다.

  P: 부모로 올라감   C: 자녀로 내려감   S: 배우자   B: 형제자매 (P 다음 바로 C)

예) 큰아버지 = [P, B], 사촌 = [P, B, C], 조카 = [B, C], 장인 = [S, P]

자주 쓰는 경로는 호칭 표로 바꾸고, 표에 없으면 "아버지의 누나의 아들"처럼 풀어서 쓴다.
촌수는 배우자를 거치지 않는 혈족만 계산한다 (P, C는 1촌, B는 2촌).
"""
from collections import defaultdict, deque
from dataclasses import dataclass

from sqlalchemy import select

from .models import Person, Relation, db


@dataclass
class Kin:
    title: str
    chon: int | None  # 혈족이 아니면 None
    tokens: tuple[str, ...]


class FamilyGraph:
    def __init__(self, gid: int):
        self.people: dict[int, Person] = {
            p.id: p for p in db.session.scalars(select(Person).where(Person.family_group_id == gid))
        }
        self.parents = defaultdict(set)
        self.children = defaultdict(set)
        self.spouses = defaultdict(set)
        self.parent_kind: dict[tuple[int, int], str] = {}  # (부모, 자녀) -> kind
        self.spouse_status: dict[tuple[int, int], str] = {}  # (작은 id, 큰 id) -> status
        for r in db.session.scalars(select(Relation).where(Relation.family_group_id == gid)):
            if r.type == "parent_child":
                self.parents[r.person_b_id].add(r.person_a_id)
                self.children[r.person_a_id].add(r.person_b_id)
                self.parent_kind[(r.person_a_id, r.person_b_id)] = r.kind
            else:
                self.spouses[r.person_a_id].add(r.person_b_id)
                self.spouses[r.person_b_id].add(r.person_a_id)
                self.spouse_status[(r.person_a_id, r.person_b_id)] = r.status

    def restrict(self, keep: set[int]) -> None:
        """keep에 든 사람과 그 사이 관계만 남긴다."""
        self.people = {k: v for k, v in self.people.items() if k in keep}
        for rel in (self.parents, self.children, self.spouses):
            for k in list(rel):
                if k not in keep:
                    del rel[k]
                else:
                    rel[k] = rel[k] & keep

    def _neighbors(self, pid: int):
        # 같은 길이면 혈연 경로가 먼저 잡히도록 배우자를 마지막에 본다.
        for x in sorted(self.parents[pid]):
            yield "P", x
        for x in sorted(self.children[pid]):
            yield "C", x
        for x in sorted(self.spouses[pid]):
            yield "S", x

    def paths_from(self, src: int) -> dict[int, list[tuple[str, int]]]:
        """src에서 닿는 모든 사람까지의 최단 경로 [(단계, 도착 id), ...]."""
        prev: dict[int, tuple[int, str] | None] = {src: None}
        queue = deque([src])
        while queue:
            cur = queue.popleft()
            for step, nxt in self._neighbors(cur):
                if nxt not in prev:
                    prev[nxt] = (cur, step)
                    queue.append(nxt)
        paths = {}
        for pid in prev:
            path = []
            node = pid
            while prev[node] is not None:
                before, step = prev[node]
                path.append((step, node))
                node = before
            paths[pid] = list(reversed(path))
        return paths


def to_tokens(path: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """P 바로 다음 C를 형제자매 B로 합친다."""
    out = []
    i = 0
    while i < len(path):
        step, node = path[i]
        if step == "P" and i + 1 < len(path) and path[i + 1][0] == "C":
            out.append(("B", path[i + 1][1]))
            i += 2
        else:
            out.append((step, node))
            i += 1
    return out


def _older(a: Person, b: Person) -> bool | None:
    """a가 b보다 나이가 많으면 True. 모르면 None."""
    if not (a.birth_date and b.birth_date) or a.birth_date == b.birth_date:
        return None
    return a.birth_date < b.birth_date


def sibling_word(me: Person, sib: Person) -> str:
    older = _older(sib, me)
    if sib.gender is None:
        return "형제자매"
    if older is None or me.gender is None:
        return "남자 형제" if sib.gender == "male" else "여자 형제"
    if older:
        if sib.gender == "male":
            return "형" if me.gender == "male" else "오빠"
        return "누나" if me.gender == "male" else "언니"
    return "남동생" if sib.gender == "male" else "여동생"


def _by_gender(p: Person, male: str, female: str, unknown: str) -> str:
    return {"male": male, "female": female}.get(p.gender, unknown)


def step_word(prev: Person, step: str, node: Person) -> str:
    if step == "P":
        return _by_gender(node, "아버지", "어머니", "부모")
    if step == "C":
        return _by_gender(node, "아들", "딸", "자녀")
    if step == "S":
        return _by_gender(node, "남편", "아내", "배우자")
    return sibling_word(prev, node)


def describe(me: Person, path: list[tuple[str, int]], people: dict[int, Person]) -> Kin:
    tokens = to_tokens(path)
    keys = tuple(t for t, _ in tokens)
    nodes = [me] + [people[n] for _, n in tokens]
    chon = None if "S" in keys else sum(2 if t == "B" else 1 for t in keys)

    title = _table_title(keys, nodes)
    if title is None:
        words = [step_word(nodes[i], keys[i], nodes[i + 1]) for i in range(len(keys))]
        title = "의 ".join(words) if words else "나"
    return Kin(title=title, chon=chon, tokens=keys)


def _table_title(keys: tuple[str, ...], n: list[Person]) -> str | None:
    me, last = n[0], n[-1]
    g = last.gender
    if not keys:
        return "나"
    # 아버지 쪽이면 친가, 어머니 쪽이면 외가
    side = None
    if keys[0] == "P":
        side = {"male": "친", "female": "외"}.get(n[1].gender)

    if keys == ("P",):
        return _by_gender(last, "아버지", "어머니", "부모")
    if keys == ("P", "P") and side and g:
        return ("" if side == "친" else "외") + _by_gender(last, "할아버지", "할머니", "")
    if keys == ("P", "P", "P") and side and g:
        return ("" if side == "친" else "외") + _by_gender(last, "증조할아버지", "증조할머니", "")
    if keys == ("C",):
        return _by_gender(last, "아들", "딸", "자녀")
    if keys == ("C", "C"):
        return _by_gender(last, "손자", "손녀", "손주")
    if keys == ("C", "C", "C"):
        return _by_gender(last, "증손자", "증손녀", "증손주")
    if keys == ("S",):
        return _by_gender(last, "남편", "아내", "배우자")
    if keys == ("B",):
        return sibling_word(me, last)

    if keys == ("P", "B") and side and g:
        parent = n[1]
        if side == "친":
            if g == "female":
                return "고모"
            older = _older(last, parent)
            return {True: "큰아버지", False: "작은아버지"}.get(older, "삼촌")
        return "외삼촌" if g == "male" else "이모"
    if keys == ("P", "B", "S") and side and n[2].gender:
        uncle = n[2]
        if side == "친":
            if uncle.gender == "female":
                return "고모부"
            older = _older(uncle, n[1])
            return {True: "큰어머니", False: "작은어머니"}.get(older, "숙모")
        return "외숙모" if uncle.gender == "male" else "이모부"
    if keys == ("P", "B", "C") and side and n[2].gender:
        via = n[2]
        if side == "친":
            return "사촌" if via.gender == "male" else "고종사촌"
        return "외사촌" if via.gender == "male" else "이종사촌"
    if keys == ("P", "P", "B") and side == "친" and n[2].gender == "male" and g:
        if g == "female":
            return "고모할머니"
        older = _older(last, n[2])
        return {True: "큰할아버지", False: "작은할아버지"}.get(older, "종조할아버지")

    if keys == ("B", "C"):
        return _by_gender(last, "조카", "조카딸", "조카")
    if keys == ("B", "S") and me.gender and n[1].gender:
        sib = n[1]
        older = _older(sib, me)
        if sib.gender == "male":  # 형제의 아내
            if me.gender == "female":
                return "올케"
            return {True: "형수", False: "제수"}.get(older)
        # 자매의 남편
        if me.gender == "male":
            return {True: "매형", False: "매제"}.get(older)
        return {True: "형부", False: "제부"}.get(older)
    if keys == ("S", "P") and me.gender and g:
        if me.gender == "male":
            return "장인" if g == "male" else "장모"
        return "시아버지" if g == "male" else "시어머니"
    if keys == ("S", "B") and me.gender and g:
        spouse = n[1]
        older = _older(last, spouse)
        if me.gender == "male":  # 아내의 형제자매
            if g == "male":
                return "처남"
            return {True: "처형", False: "처제"}.get(older)
        # 남편의 형제자매
        if g == "female":
            return "시누이"
        return {True: "아주버님", False: "시동생"}.get(older)
    if keys == ("C", "S") and g:
        return "사위" if g == "male" else "며느리"
    return None


def kinships_from(me: Person) -> dict[int, Kin]:
    """나에서 닿는 모든 사람의 호칭/촌수. 이어지지 않은 사람은 빠진다."""
    graph = FamilyGraph(me.family_group_id)
    return {
        pid: describe(me, path, graph.people) for pid, path in graph.paths_from(me.id).items()
    }


def chon_label(kin: Kin) -> str:
    if kin.tokens == ("S",):
        return "무촌"
    if kin.chon is None:
        return "인척" if kin.tokens else ""
    return f"{kin.chon}촌" if kin.chon else ""
