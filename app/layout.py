"""집안 전체 가계도 배치. 직계뿐 아니라 삼촌, 사촌, 사돈까지 한 화면에 그린다.

서버에서 좌표를 계산하고, 브라우저(static/tree.js)는 받은 좌표대로 SVG를 그리기만 한다.

1. 세대: 나를 0으로 두고 부모는 -1, 자녀는 +1, 배우자는 같은 세대 (BFS).
2. 묶음(unit): 같은 세대의 배우자, 같은 자녀를 둔 부모를 한 덩어리로 묶어 옆에 붙인다.
3. 순서: 세대별로 줄을 세운 뒤, 부모/자녀 위치의 평균(barycenter)으로 몇 번 다시 정렬해
   선이 덜 꼬이게 한다.
4. 가로 위치: 자녀는 부모 밑, 부모는 자녀 위로 끌어당기면서 겹치지 않게 민다.
5. 나와 이어지지 않은 사람들은 오른쪽에 따로 그린다.
"""
from collections import defaultdict, deque

from .kinship import FamilyGraph
from .models import Relation, db

CARD_W = 128
CARD_H = 60
GAP_IN = 14   # 묶음 안 (부부 사이)
GAP_OUT = 34  # 묶음 사이
LAYER_H = 130
COMP_GAP = 120


class ViewUnavailable(Exception):
    pass


def view_anchor(graph: FamilyGraph, me_id: int, view: str) -> int | None:
    """친가는 아버지, 외가는 어머니, 처가/시가는 배우자. 친생/혼인 중을 먼저 고른다."""
    if view in ("paternal", "maternal"):
        want = "male" if view == "paternal" else "female"
        ps = [p for p in graph.parents[me_id] if graph.people[p].gender == want]
        ps.sort(key=lambda p: (graph.parent_kind.get((p, me_id)) != "biological", p))
        return ps[0] if ps else None
    if view == "inlaw":
        ss = sorted(graph.spouses[me_id])
        ss.sort(key=lambda s: graph.spouse_status.get((min(s, me_id), max(s, me_id))) != "married")
        return ss[0] if ss else None
    return None


def side_members(graph: FamilyGraph, anchor: int) -> set[int]:
    """anchor와 그 조상들, 조상들의 모든 자손, 그리고 그 사람들의 배우자."""
    ancestors, q = {anchor}, deque([anchor])
    while q:
        for p in graph.parents[q.popleft()]:
            if p not in ancestors:
                ancestors.add(p)
                q.append(p)
    core, q = set(ancestors), deque(ancestors)
    while q:
        for c in graph.children[q.popleft()]:
            if c not in core:
                core.add(c)
                q.append(c)
    return core | {s for p in core for s in graph.spouses[p]}


def available_views(gid: int, me) -> list[tuple[str, str]]:
    graph = FamilyGraph(gid)
    inlaw = {"male": "처가", "female": "시가"}.get(me.gender, "배우자 쪽")
    views = [("all", "전체")]
    for key, label in (("paternal", "친가"), ("maternal", "외가"), ("inlaw", inlaw)):
        if view_anchor(graph, me.id, key) is not None:
            views.append((key, label))
    return views


def build_layout(gid: int, me_id: int, kins: dict | None = None, view: str = "all") -> dict:
    kins = kins or {}
    graph = FamilyGraph(gid)
    if view != "all":
        anchor = view_anchor(graph, me_id, view)
        if anchor is None:
            raise ViewUnavailable(view)
        graph.restrict(side_members(graph, anchor))
    people = graph.people
    rel_info = _relation_info(gid)

    # 연결 요소: 내가 있는 요소를 먼저
    comps, seen = [], set()
    starts = ([me_id] if me_id in people else []) + sorted(people)
    for s in starts:
        if s in seen:
            continue
        comp, q = {s}, deque([s])
        while q:
            cur = q.popleft()
            for nxt in graph.parents[cur] | graph.children[cur] | graph.spouses[cur]:
                if nxt not in comp:
                    comp.add(nxt)
                    q.append(nxt)
        seen |= comp
        comps.append((s, comp))

    nodes, edges = [], []
    offset = 0.0
    for root, comp in comps:
        pos, gens = _layout_component(graph, comp, root)
        if not pos:
            continue
        min_x = min(x for x, _ in pos.values()) - CARD_W / 2
        max_x = max(x for x, _ in pos.values()) + CARD_W / 2
        shift = offset - min_x
        pos = {pid: (x + shift, y) for pid, (x, y) in pos.items()}
        offset += (max_x - min_x) + COMP_GAP
        nodes += [_node(people[pid], x, y, pid == me_id, kins.get(pid)) for pid, (x, y) in pos.items()]
        edges += _edges(graph, comp, pos, gens, rel_info)

    return {
        "card": {"w": CARD_W, "h": CARD_H},
        "nodes": nodes,
        "edges": edges,
        "me": str(me_id),
    }


# --- 내부 ---

def _relation_info(gid: int) -> dict:
    """(type, a, b) -> kind/status"""
    info = {}
    for r in db.session.query(Relation).filter(Relation.family_group_id == gid):
        info[(r.type, r.person_a_id, r.person_b_id)] = r.kind or r.status
    return info


def _node(p, x, y, is_me, kin) -> dict:
    return {
        "id": str(p.id),
        "x": round(x, 1),
        "y": round(y, 1),
        "name": p.name,
        "gender": p.gender or "",
        "birth": p.birth_date[:4] if p.birth_date else "",
        "deceased": p.is_deceased,
        "title": kin.title if kin and kin.tokens else "",
        "me": is_me,
    }


def _layout_component(graph: FamilyGraph, comp: set[int], root: int):
    people = graph.people

    # 1. 세대
    gen = {root: 0}
    q = deque([root])
    while q:
        cur = q.popleft()
        steps = [(p, -1) for p in sorted(graph.parents[cur])]
        steps += [(c, 1) for c in sorted(graph.children[cur])]
        steps += [(s, 0) for s in sorted(graph.spouses[cur])]
        for nxt, d in steps:
            if nxt in comp and nxt not in gen:
                gen[nxt] = gen[cur] + d
                q.append(nxt)
    top = min(gen.values())
    gen = {p: g - top for p, g in gen.items()}  # 맨 윗세대가 y=0

    # 2. 묶음 (union-find)
    parent = {p: p for p in comp}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    partner = defaultdict(set)  # 묶음 안에서 옆에 붙어야 하는 상대
    for p in comp:
        for s in graph.spouses[p]:
            if s in comp and gen[s] == gen[p]:
                union(p, s)
                partner[p].add(s)
        for c in graph.children[p]:
            ps = [x for x in graph.parents[c] if x in comp and gen[x] == gen[p]]
            for other in ps:
                if other != p:
                    union(p, other)
                    partner[p].add(other)

    groups = defaultdict(list)
    for p in comp:
        groups[find(p)].append(p)
    units = {uid: _order_members(sorted(m), partner, people) for uid, m in groups.items()}
    unit_of = {p: uid for uid, ms in units.items() for p in ms}
    ugen = {uid: gen[ms[0]] for uid, ms in units.items()}

    up, down = defaultdict(set), defaultdict(set)
    for c in comp:
        for p in graph.parents[c]:
            if p in comp and gen[p] == gen[c] - 1:
                up[unit_of[c]].add(unit_of[p])
                down[unit_of[p]].add(unit_of[c])

    def ubirth(uid):
        return min((people[p].birth_date or "99999999") for p in units[uid])

    # 3. 초기 순서: 위 세대부터 DFS (자녀 먼저, 그다음 사돈 쪽 부모)
    layers = defaultdict(list)
    visited = set()

    def visit(uid):
        stack = [uid]
        while stack:
            u = stack.pop()
            if u in visited:
                continue
            visited.add(u)
            layers[ugen[u]].append(u)
            nxt = sorted(down[u], key=ubirth) + sorted(up[u], key=ubirth)
            stack.extend(reversed([n for n in nxt if n not in visited]))

    for uid in sorted(units, key=lambda u: (ugen[u], ubirth(u))):
        visit(uid)

    gens_sorted = sorted(layers)
    index = {}

    def reindex():
        for g in gens_sorted:
            for i, u in enumerate(layers[g]):
                index[u] = i

    reindex()
    for _ in range(6):
        for g in gens_sorted[1:]:
            layers[g].sort(key=lambda u: _bary(u, up, index))
            reindex()
        for g in reversed(gens_sorted[:-1]):
            layers[g].sort(key=lambda u: _bary(u, down, index))
            reindex()

    # 4. 가로 위치
    width = {u: len(ms) * CARD_W + (len(ms) - 1) * GAP_IN for u, ms in units.items()}
    offset_in = {}  # 사람 -> 묶음 중심에서의 x 오프셋
    for u, ms in units.items():
        left = -width[u] / 2 + CARD_W / 2
        for i, p in enumerate(ms):
            offset_in[p] = left + i * (CARD_W + GAP_IN)

    cx = {}
    for g in gens_sorted:
        x = 0.0
        for u in layers[g]:
            cx[u] = x + width[u] / 2
            x += width[u] + GAP_OUT

    def px(p):
        return cx[unit_of[p]] + offset_in[p]

    def want_from_parents(u):
        vals = []
        for m in units[u]:
            ps = [p for p in graph.parents[m] if p in comp and gen[p] == gen[m] - 1]
            if ps:
                vals.append(sum(px(p) for p in ps) / len(ps) - offset_in[m])
        return sum(vals) / len(vals) if vals else None

    def want_from_children(u):
        vals = []
        members = set(units[u])
        for m in units[u]:
            for c in graph.children[m]:
                if c not in comp or gen[c] != gen[m] + 1:
                    continue
                ps = [p for p in graph.parents[c] if p in members]
                anchor = sum(offset_in[p] for p in ps) / len(ps)
                vals.append(px(c) - anchor)
        return sum(vals) / len(vals) if vals else None

    for _ in range(12):
        for g in gens_sorted:
            _resolve(layers[g], cx, width, want_from_parents)
        for g in reversed(gens_sorted):
            _resolve(layers[g], cx, width, want_from_children)

    pos = {p: (px(p), gen[p] * LAYER_H) for p in comp}
    return pos, gen


def _order_members(members: list[int], partner, people) -> list[int]:
    """묶음 안 순서. 2명이면 남자 왼쪽, 여러 명이면 배우자가 많은 사람을 가운데."""
    if len(members) == 1:
        return members
    if len(members) == 2:
        a, b = members
        if people[a].gender == "female" or people[b].gender == "male":
            return [b, a]
        return [a, b]
    center = max(members, key=lambda m: (len(partner[m]), -m))
    rest = [m for m in members if m != center]
    left = rest[0::2]
    right = rest[1::2]
    return list(reversed(left)) + [center] + right


def _bary(u, nbrs, index):
    ns = nbrs[u]
    if not ns:
        return index[u]
    return sum(index[n] for n in ns) / len(ns)


def _resolve(layer, cx, width, want):
    """원하는 위치로 끌어당기되, 순서를 지키고 겹치지 않게."""
    if not layer:
        return
    desired = []
    for u in layer:
        w = want(u)
        desired.append(cx[u] if w is None else w)
    n = len(layer)
    sep = [0.0] + [(width[layer[i - 1]] + width[layer[i]]) / 2 + GAP_OUT for i in range(1, n)]
    fwd = desired[:]
    for i in range(1, n):
        fwd[i] = max(fwd[i], fwd[i - 1] + sep[i])
    bwd = desired[:]
    for i in range(n - 2, -1, -1):
        bwd[i] = min(bwd[i], bwd[i + 1] - sep[i + 1])
    for i, u in enumerate(layer):
        cx[u] = (fwd[i] + bwd[i]) / 2


def _edges(graph: FamilyGraph, comp, pos, gen, rel_info) -> list[dict]:
    edges = []
    half_h = CARD_H / 2
    # 부부선
    done = set()
    for p in comp:
        for s in graph.spouses[p]:
            key = (min(p, s), max(p, s))
            if s not in comp or key in done:
                continue
            done.add(key)
            (x1, y1), (x2, y2) = sorted([pos[p], pos[s]])
            status = rel_info.get(("spouse", *key), "married")
            if y1 == y2:
                d = f"M{x1 + CARD_W / 2:.1f},{y1:.1f}H{x2 - CARD_W / 2:.1f}"
            else:
                d = f"M{x1:.1f},{y1:.1f}L{x2:.1f},{y2:.1f}"
            edges.append({"type": "spouse", "status": status, "d": d})

    # 부모 → 자녀: 같은 자녀를 둔 부모들의 가운데에서 내려온다
    for c in comp:
        ps = [p for p in graph.parents[c] if p in comp]
        if not ps:
            continue
        cxp, cyp = pos[c]
        normal = [p for p in ps if gen[p] == gen[c] - 1]
        for p in ps:
            if p not in normal:  # 세대가 꼬인 경우: 그냥 직선
                x, y = pos[p]
                edges.append({"type": "child", "kind": rel_info.get(("parent_child", p, c)),
                              "d": f"M{x:.1f},{y + half_h:.1f}L{cxp:.1f},{cyp - half_h:.1f}"})
        if not normal:
            continue
        xs = [pos[p][0] for p in normal]
        y0 = pos[normal[0]][1]
        ax = sum(xs) / len(xs)
        start_y = y0 if len(normal) > 1 else y0 + half_h  # 부부면 부부선 가운데에서
        mid_y = y0 + half_h + (LAYER_H - CARD_H) / 2
        kinds = {rel_info.get(("parent_child", p, c)) for p in normal}
        kind = "biological" if "biological" in kinds else (kinds.pop() if kinds else None)
        edges.append({
            "type": "child",
            "kind": kind,
            "d": f"M{ax:.1f},{start_y:.1f}V{mid_y:.1f}H{cxp:.1f}V{cyp - half_h:.1f}",
        })
    return edges
