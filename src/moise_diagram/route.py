"""Post-layout routing that draws what Graphviz cannot: the line styles of Fig. 2 of the MOISE+ paper.

Rendering runs in three steps: ``dot -Tdot`` computes the layout, this module rewrites the geometry of
marked edges, and ``neato -n2`` draws the result exactly as positioned. Edges are marked through their
``id`` attribute:

``mx_bus_*``
    inheritance edges, redrawn as right-angled "bus" lines: a trunk below the parent, a horizontal bar
    shared by all its sub-roles, and a vertical drop to each sub-role;
``mx_wave_*``
    inter-group links and compatibilities, redrawn as wavy lines;
``mx_card_*``
    compositions, whose cardinality label is placed away from nodes, edges and other labels;
``mx_line_*``
    goal decompositions (Fig. 3), redrawn as straight lines from the centre of the parent's bars
    (or bottom) to the top of the subgoal.
"""
from __future__ import annotations
import math
import re
from dataclasses import dataclass, field

ARROW = 14.0      # length of an arrowhead with arrowsize=1.4, in points
WAVELENGTH = 90.0
AMPLITUDE = 3.0
CHAR_WIDTH = 5.2  # average width of a 10 pt italic serif character, in points

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|->|--|[{}\[\];,=:]|(?:[^\s{}\[\];,=:"<>-]|-(?![->]))+|\s+', re.S)

Point = tuple[float, float]


@dataclass
class _Statement:
    head: list[str]
    attrs: list[list[str]]
    start: int
    end: int
    changed: bool = False

    def get(self, key: str) -> str | None:
        return next((_unquote(v) for k, v in self.attrs if k == key), None)

    def set(self, key: str, value: str | None) -> None:
        """Set an attribute to a quoted value, or remove it when ``value`` is None."""
        self.attrs = [a for a in self.attrs if a[0] != key]
        if value is not None:
            self.attrs.append([key, '"' + value.replace('"', '\\"') + '"'])
        self.changed = True


@dataclass
class _Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def overlap(self, other: _Box) -> float:
        width = min(self.x1, other.x1) - max(self.x0, other.x0)
        height = min(self.y1, other.y1) - max(self.y0, other.y0)
        return width * height if width > 0 and height > 0 else 0.0

    def contains(self, p: Point) -> bool:
        return self.x0 <= p[0] <= self.x1 and self.y0 <= p[1] <= self.y1


@dataclass
class _Edge:
    statement: _Statement
    tail: str
    head: str
    prefix: list[str] = field(default_factory=list)
    points: list[Point] = field(default_factory=list)


def route(laid_out: str) -> str:
    """Rewrite the output of ``dot -Tdot`` so that ``neato -n2`` draws bus, wavy and placed labels."""
    statements = _parse(laid_out)
    nodes = {}
    edges = []
    for s in statements:
        if '->' in s.head:
            edge = _Edge(s, _unquote(s.head[0]), _unquote(s.head[s.head.index('->') + 1]))
            edge.prefix, edge.points = _parse_pos(s.get('pos') or '')
            edges.append(edge)
        elif s.head and s.head[0] not in ('graph', 'node', 'edge', 'subgraph') and s.get('pos'):
            x, y = map(float, s.get('pos').split(','))
            width, height = float(s.get('width') or 0) * 72, float(s.get('height') or 0) * 72
            nodes[_unquote(s.head[0])] = _Box(x - width / 2, y - height / 2, x + width / 2, y + height / 2)
    marked = lambda kind: [e for e in edges if (e.statement.get('id') or '').startswith(f'mx_{kind}_') and e.points]
    _route_buses(marked('bus'), nodes)
    _route_lines(marked('line'), nodes)
    for edge in marked('wave'):
        edge.points = _wave(edge.points)
        _store(edge)
    _place_cardinalities(marked('card'), edges, nodes)
    output = laid_out
    for s in sorted((s for s in statements if s.changed), key=lambda s: s.start, reverse=True):
        attrs = ',\n\t\t'.join(f'{k}={v}' for k, v in s.attrs)
        output = output[:s.start] + f'[{attrs}]' + output[s.end:]
    return output


# -- inheritance as bus lines -------------------------------------------------------------------

def _route_buses(edges: list[_Edge], nodes: dict[str, _Box]) -> None:
    """Draw each parent's inheritance edges as one trunk, one horizontal bar and vertical drops."""
    by_parent: dict[str, list[_Edge]] = {}
    for edge in edges:
        if edge.tail in nodes and edge.head in nodes:
            by_parent.setdefault(edge.tail, []).append(edge)
    bars: list[tuple[float, float, float]] = []
    for parent, children in by_parent.items():
        box = nodes[parent]
        px, bottom = (box.x0 + box.x1) / 2, box.y0
        highest = max(nodes[e.head].y1 for e in children)
        xs = [px] + [(nodes[e.head].x0 + nodes[e.head].x1) / 2 for e in children]
        low, high = min(xs), max(xs)
        y = bottom - max(ARROW + 4, (bottom - highest) / 2)
        # Keep bars of different parents at the same height from overlapping.
        while any(abs(y - by) < 3 and low < bx1 and bx0 < high for by, bx0, bx1 in bars):
            y -= 6
        if y < highest + 4:
            continue
        bars.append((y, low, high))
        for edge in children:
            child = nodes[edge.head]
            cx = (child.x0 + child.x1) / 2
            corners = [(px, bottom - ARROW), (px, y), (cx, y), (cx, child.y1)]
            edge.prefix = [f's,{_fmt(px)},{_fmt(bottom)}'] if edge.statement.get('arrowtail') else []
            edge.points = _polyline([p for i, p in enumerate(corners) if i == 0 or p != corners[i - 1]])
            _store(edge)


def _route_lines(edges: list[_Edge], nodes: dict[str, _Box]) -> None:
    for edge in edges:
        if edge.tail in nodes and edge.head in nodes:
            # Keep the heights where Graphviz attached the edge (the bars' port), centred on each node.
            tail, head = nodes[edge.tail], nodes[edge.head]
            start = ((tail.x0 + tail.x1) / 2, edge.points[0][1])
            end = ((head.x0 + head.x1) / 2, edge.points[-1][1])
            edge.prefix, edge.points = [], _polyline([start, end])
            _store(edge)


def _polyline(corners: list[Point]) -> list[Point]:
    """Straight segments expressed as cubic Bézier control points."""
    points = [corners[0]]
    for a, b in zip(corners, corners[1:]):
        points += [_lerp(a, b, 1 / 3), _lerp(a, b, 2 / 3), b]
    return points


# -- wavy inter-group lines ---------------------------------------------------------------------

def _wave(points: list[Point]) -> list[Point]:
    """Offset the curve by a sine wave whose ends stay on the original endpoints (and arrowheads)."""
    samples = _sample(points)
    lengths = [0.0]
    for a, b in zip(samples, samples[1:]):
        lengths.append(lengths[-1] + math.dist(a, b))
    total = lengths[-1]
    if total < 8:
        return points
    periods = max(1, round(total / WAVELENGTH))
    amplitude = min(AMPLITUDE, total / 8)
    count = 8 * periods
    wavy = []
    for j in range(count + 1):
        s = total * j / count
        p, (tx, ty) = _at(samples, lengths, s)
        offset = amplitude * math.sin(2 * math.pi * periods * s / total)
        wavy.append((p[0] - ty * offset, p[1] + tx * offset))
    return _catmull_rom(wavy)


def _catmull_rom(points: list[Point]) -> list[Point]:
    result = [points[0]]
    for i in range(len(points) - 1):
        p0, p1, p2 = points[max(i - 1, 0)], points[i], points[i + 1]
        p3 = points[min(i + 2, len(points) - 1)]
        result += [(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6),
                   (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6), p2]
    return result


# -- cardinality labels -------------------------------------------------------------------------

def _place_cardinalities(cards: list[_Edge], edges: list[_Edge], nodes: dict[str, _Box]) -> None:
    """Put each cardinality near its member end, on the free side of the line, away from other labels."""
    sampled = {id(e): _sample(e.points, step=3) for e in edges}
    placed: list[_Box] = []
    for edge in cards:
        text = re.sub(r'<[^>]*>', '', edge.statement.get('taillabel') or '')
        width, height = CHAR_WIDTH * len(text) + 4, 12.0
        own = sampled[id(edge)]
        others = [p for e in edges if e is not edge for p in sampled[id(e)]]
        samples = _sample(edge.points)
        lengths = [0.0]
        for a, b in zip(samples, samples[1:]):
            lengths.append(lengths[-1] + math.dist(a, b))
        best = None
        candidates = []
        distances = [d for d in (6, 10, 18, 28, 40, 54, 70) if d <= lengths[-1]] or [lengths[-1] / 2]
        for rank, distance in enumerate(distances):
            (x, y), (tx, ty) = _at(samples, lengths, distance)
            nx, ny = -ty, tx
            for extra in (2, 9, 16):
                for side in (1, -1):
                    gap = width / 2 * abs(nx) + height / 2 * abs(ny) + extra
                    candidates.append((x + side * nx * gap, y + side * ny * gap, rank + (side < 0) * 0.5 + extra / 7))
        member = nodes.get(edge.tail)
        if member:
            # Beside the member's lower corners, as Fig. 2 does for "defense 1..1".
            for cx in (member.x1 + width / 2 + 2, member.x0 - width / 2 - 2):
                candidates.append((cx, member.y0 + height / 2 + 1, 3))
        for cx, cy, preference in candidates:
            box = _Box(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)
            margin = _Box(box.x0 - 3, box.y0 - 3, box.x1 + 3, box.y1 + 3)
            # A label must not cover anything, and must be closer to its own line than to any other.
            nearest_own = min(_distance(box, p) for p in own)
            nearest_other = min((_distance(box, p) for p in others), default=math.inf)
            score = (1000 * sum(box.overlap(n) for n in nodes.values())
                     + 1000 * sum(margin.overlap(b) for b in placed)
                     + 50 * sum(margin.contains(p) for p in others) + 50 * sum(box.contains(p) for p in own)
                     + 30 * (nearest_other < nearest_own + 4) + preference)
            if best is None or score < best[0]:
                best = (score, box)
        if best:
            box = best[1]
            placed.append(box)
            edge.statement.set('tail_lp', f'{_fmt((box.x0 + box.x1) / 2)},{_fmt((box.y0 + box.y1) / 2)}')


# -- geometry helpers ---------------------------------------------------------------------------

def _distance(box: _Box, p: Point) -> float:
    """Distance from a point to a rectangle (0 inside)."""
    return math.hypot(max(box.x0 - p[0], 0, p[0] - box.x1), max(box.y0 - p[1], 0, p[1] - box.y1))


def _lerp(a: Point, b: Point, t: float) -> Point:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _bezier(p: list[Point], t: float) -> Point:
    u = 1 - t
    return (u ** 3 * p[0][0] + 3 * u * u * t * p[1][0] + 3 * u * t * t * p[2][0] + t ** 3 * p[3][0],
            u ** 3 * p[0][1] + 3 * u * u * t * p[1][1] + 3 * u * t * t * p[2][1] + t ** 3 * p[3][1])


def _sample(points: list[Point], step: float | None = None) -> list[Point]:
    """Points along a piecewise cubic Bézier curve; ``step`` (in points) controls the density."""
    result = [points[0]] if points else []
    for i in range(0, len(points) - 3, 3):
        segment = points[i:i + 4]
        count = 16 if step is None else max(2, int(sum(math.dist(a, b) for a, b in zip(segment, segment[1:])) / step))
        result += [_bezier(segment, k / count) for k in range(1, count + 1)]
    return result


def _at(samples: list[Point], lengths: list[float], s: float) -> tuple[Point, Point]:
    """Point and unit tangent at arc length ``s`` along a sampled curve."""
    i = next((k for k in range(1, len(lengths)) if lengths[k] >= s), len(lengths) - 1)
    a, b = samples[i - 1], samples[i]
    span = lengths[i] - lengths[i - 1] or 1.0
    norm = math.dist(a, b) or 1.0
    return _lerp(a, b, (s - lengths[i - 1]) / span), ((b[0] - a[0]) / norm, (b[1] - a[1]) / norm)


def _fmt(value: float) -> str:
    return f'{value:.2f}'


def _store(edge: _Edge) -> None:
    edge.statement.set('pos', ' '.join(edge.prefix + [f'{_fmt(x)},{_fmt(y)}' for x, y in edge.points]))


def _parse_pos(pos: str) -> tuple[list[str], list[Point]]:
    prefix, points = [], []
    for item in pos.split():
        if item[:2] in ('s,', 'e,'):
            prefix.append(item)
        else:
            x, y = item.split(',')[:2]
            points.append((float(x), float(y)))
    return prefix, points


# -- minimal reader for Graphviz's DOT output ---------------------------------------------------

def _unquote(token: str) -> str:
    if token.startswith('"'):
        return re.sub(r'\\(.)', r'\1', token[1:-1].replace('\\\n', '').replace('\\\r\n', ''))
    return token


def _tokens(text: str) -> list[tuple[str, int, int]]:
    """Tokens with their spans; HTML strings ``<...>`` are matched with their nesting."""
    tokens, pos = [], 0
    while pos < len(text):
        if text[pos] == '<':
            depth, end = 0, pos
            while True:
                depth += {'<': 1, '>': -1}.get(text[end], 0)
                end += 1
                if depth == 0:
                    break
            tokens.append((text[pos:end], pos, end))
            pos = end
            continue
        match = _TOKEN.match(text, pos)
        if not match:
            raise ValueError(f'cannot read Graphviz output near {text[pos:pos + 30]!r}')
        if not match.group().isspace():
            tokens.append((match.group(), pos, match.end()))
        pos = match.end()
    return tokens


def _parse(text: str) -> list[_Statement]:
    """Every attribute list of a DOT file, with the statement head that precedes it."""
    tokens, statements, head, i = _tokens(text), [], [], 0
    while i < len(tokens):
        value, start, _ = tokens[i]
        if value in (';', '{', '}'):
            head = []
        elif value == '[':
            attrs, i = [], i + 1
            while tokens[i][0] != ']':
                if tokens[i][0] in (',', ';'):
                    i += 1
                    continue
                attrs.append([tokens[i][0], tokens[i + 2][0]])
                i += 3
            statements.append(_Statement(head, attrs, start, tokens[i][2]))
            head = []
        else:
            head.append(value)
        i += 1
    return statements
