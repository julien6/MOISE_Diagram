"""Graphviz rendering that follows the graphical notation of the MOISE+ paper.

The structural specification is drawn like Fig. 2 of the paper, social schemes like Fig. 3 (with a goal
table like Table 1), and the deontic specification as the paper writes it: lists of per/obl predicates.
The paper gives no graphical notation for the deontic specification; the ``graph`` and ``matrix`` styles
and the integrated ``ds_links`` mode are conventions of this tool.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import re

from .model import SOC, DiagramError, Goal, OrganizationDiagram

VIEWS = ('ss', 'fs', 'ds', 'oe')
"""Views that can be rendered: structural, functional, deontic and organizational entity."""

DS_STYLES = ('list', 'graph', 'matrix')
"""Renderings of the deontic specification: predicate list (as in the paper), role-mission graph, matrix."""

SANS, MONO, SERIF = 'Helvetica', 'Courier', 'Times'
LINK_HEADS = {'acq': 'vee', 'com': 'dot', 'aut': 'normal'}
BAR_WIDTH = 44


def to_dot(model: OrganizationDiagram, views=VIEWS, key: bool = False, ds_style: str = 'list',
           ds_inherited: bool = False, ds_links: bool = False) -> str:
    """Render a validated model as Graphviz DOT source.

    ``views`` selects the specifications to draw, among ``ss``, ``fs``, ``ds`` and ``oe``;
    ``key`` adds the legends (those of the paper's figures for the structural and functional views).
    ``ds_style`` draws the deontic view as a predicate ``list``, a role-mission ``graph`` or a ``matrix``;
    ``ds_inherited`` adds the norms that roles inherit (paper eqs. 8-9); ``ds_links`` draws the norms as
    edges from the roles of the structural view to the missions of the functional view (both must be drawn).
    """
    unknown = sorted(set(views) - set(VIEWS))
    if unknown:
        raise DiagramError(f'unknown view {", ".join(unknown)}; expected {", ".join(VIEWS)}')
    if ds_style not in DS_STYLES:
        raise DiagramError(f'unknown deontic style {ds_style}; expected {", ".join(DS_STYLES)}')
    links = ds_links and model.norms and 'ss' in views and 'fs' in views and model.schemes
    lines = ['digraph moise {',
             f'graph [fontname="{SANS}", fontsize=16, label={_q(model.title)}, labelloc=t, nodesep=0.35, ranksep=0.55, splines=polyline, outputorder=edgesfirst];',
             f'node [fontname="{SANS}", fontsize=12, color=black, style=filled, fillcolor=white];',
             f'edge [fontname="{SERIF}", fontsize=10, color=black];']
    drawn = set()
    if 'ss' in views and (len(model.roles) > 1 or model.groups):
        lines += _structural(model)
        drawn.add('ss')
        if links:
            # An invisible spacer between the structural and functional views leaves room for the norm curves.
            width = min(3.0, 0.8 + 0.12 * len(_applied(model, ds_inherited)))
            lines.append(f'"__ds_corridor" [shape=box, style=invis, label="", width={width:.2f}, height=0.1, fixedsize=true];')
    if 'fs' in views and model.schemes:
        lines += _functional(model, mission_ports=bool(links))
        drawn.add('fs')
    if 'ds' in views and model.norms:
        lines += _deontic(model, ds_style, ds_inherited)
    if links:
        lines += _deontic_links(model, ds_inherited)
    if 'oe' in views and model.agents:
        lines += _entity(model)
    if key and 'ss' in drawn:
        roots = [g for g in model.groups if not any(c.member == g for c in model.compositions)]
        lines += _structural_key(roots[0] if roots else list(model.roles)[-1])
    if key and 'fs' in drawn:
        scheme = next(iter(model.schemes.values()))
        tables = [f'__goals_{scheme.id}'] * any(model.goals[g].label for g in scheme.goals) + [f'__missions_{scheme.id}'] * bool(scheme.missions)
        lines += _functional_key(tables[0] if tables else _deepest(model, scheme.root))
    if key and model.norms and (links or ('ds' in views and ds_style == 'graph')):
        first = model.missions[model.norms[0].mission]
        anchor = f'__missions_{first.scheme}' if links else f'__ds_mission_{first.id}'
        lines += _deontic_key(anchor, ds_inherited)
    lines.append('}')
    return '\n'.join(lines) + '\n'


# -- helpers ------------------------------------------------------------------------------------

def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _h(value: str) -> str:
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _italic(text: str, size: int = 10) -> str:
    return f'<FONT FACE="{SERIF}" POINT-SIZE="{size}"><I>{_h(text)}</I></FONT>' if text else ''


def _table(rows: list[str], padding: int = 1) -> str:
    return f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="{padding}">{"".join(rows)}</TABLE>>'


def _cluster(name: str, label: str, body: list[str], style: str = 'dashed') -> list[str]:
    return [f'subgraph cluster_{name} {{', f'label={_q(label)}; style={style}; color=gray60;', *body, '}']


def _rate(rate: float | None) -> str:
    """Success degree as written in the paper: ``.8`` rather than ``0.8``."""
    if rate is None:
        return ''
    text = f'{rate:g}'
    return text[1:] if text.startswith('0.') else text


def _missions(ids: list[str]) -> str:
    """Compress mission lists as in Fig. 3: m1, m2, m3 -> ``m1,2,3``."""
    matches = [re.fullmatch(r'(.*?)(\d+)', i) for i in ids]
    if len(ids) > 1 and all(matches) and len({m[1] for m in matches}) == 1:
        return matches[0][1] + ','.join(m[2] for m in matches)
    return ','.join(ids)


def _bars(count: int, colspan: int = 1) -> str:
    """Horizontal bars drawn under a goal: one for choice, two for parallelism."""
    bar = f'<TR><TD HEIGHT="1" WIDTH="{BAR_WIDTH}" BGCOLOR="black"></TD></TR>'
    rows = '<TR><TD HEIGHT="2"></TD></TR>'.join([bar] * count)
    return (f'<TR><TD COLSPAN="{colspan}" PORT="op" CELLPADDING="0">'
            f'<TABLE BORDER="0" CELLSPACING="0" CELLPADDING="0">{rows}</TABLE></TD></TR>')


# -- structural specification (Fig. 2) ----------------------------------------------------------

def _role_node(node: str, text: str, abstract: bool) -> str:
    inner = f'<I>{_h(text)}</I>' if abstract else _h(text)
    return f'{_q(node)} [shape=box, style="rounded,filled", label=<<B>{inner}</B>>];'


def _group_node(node: str, text: str) -> str:
    return f'{_q(node)} [shape=tab, fontname="{MONO}", fontsize=13, label={_q(text)}];'


def _scope(scope: str, name: str) -> str:
    """Line style of a link or compatibility: dashed for intra-group, wavy (drawn by route.py) for inter-group."""
    return 'style=dashed' if scope == 'intra' else f'style=solid, id="mx_wave_{name}"'


def _structural(model: OrganizationDiagram) -> list[str]:
    body = [_role_node(r.id, r.text, r.abstract) for r in model.roles.values()]
    body += [_group_node(g.id, g.text) for g in model.groups.values()]
    # The mx_* ids mark edges whose geometry route.py redraws after layout (see that module).
    for role in model.roles:
        for parent in model.parents(role):
            body.append(f'{_q(parent)} -> {_q(role)} [dir=back, arrowtail=onormal, arrowsize=1.4, weight=4, '
                        f'id={_q(f"mx_bus_{parent}_{role}")}];')
    for i, c in enumerate(model.compositions):
        head = 'odiamonddot' if c.subgroups else 'odiamond'
        body.append(f'{_q(c.member)} -> {_q(c.group)} [arrowhead={head}, arrowsize=1.4, '
                    f'taillabel=<{_italic(str(c.cardinality))}>, labeldistance=1.6, id="mx_card_{i}"];')
    for i, link in enumerate(model.links):
        body.append(f'{_q(link.source)} -> {_q(link.target)} [arrowhead={LINK_HEADS[link.type]}, '
                    f'{_scope(link.scope, f"link{i}")}, constraint=false];')
    for i, c in enumerate(model.compatibilities):
        body.append(f'{_q(c.role_a)} -> {_q(c.role_b)} [arrowhead=diamond, penwidth=2, '
                    f'{_scope(c.scope, f"compat{i}")}, constraint=false];')
    return _cluster('ss', 'SS: structural specification', body)


# -- functional specification (Fig. 3, Table 1) -------------------------------------------------

def _goal_node(model: OrganizationDiagram, goal: Goal) -> str:
    plan = model.plans.get(goal.id)
    bars = {'choice': 1, 'parallel': 2}.get(plan.operator, 0) if plan else 0
    if goal.anonymous and not bars:
        return f'{_q(goal.id)} [shape=point, width=0.04, fillcolor=black, ordering=out];'
    if goal.anonymous:
        label = _table([_bars(bars)], padding=0)
    else:
        label = _table([
            f'<TR><TD ROWSPAN="2"><B>{_h(goal.id)}</B></TD>'
            f'<TD ALIGN="LEFT" VALIGN="BOTTOM">{_italic(_missions(model.missions_of_goal(goal.id)))}</TD></TR>',
            f'<TR><TD ALIGN="LEFT" VALIGN="TOP">{_italic(_rate(plan.rate if plan else None))}</TD></TR>',
            _bars(bars, colspan=2) if bars else ''])
    return f'{_q(goal.id)} [shape=plaintext, ordering=out, label={label}];'


def _plan_edges(model: OrganizationDiagram, goal: Goal) -> list[str]:
    plan = model.plans.get(goal.id)
    if not plan:
        return []
    tail = f'{_q(goal.id)}:op' if plan.operator != 'sequence' else _q(goal.id)
    return [f'{tail} -> {_q(child)} [arrowhead=none, id={_q(f"mx_line_{goal.id}_{child}")}];' for child in plan.children]


def _text_table(node: str, header: list[str], rows: list[list[str]], ports: list[str] | None = None) -> str:
    """A table in the style of the paper's Table 1: italic header between horizontal rules.

    ``ports`` names the first cell of each row, so that edges can point at a row.
    """
    lines = ['<TR>' + ''.join(f'<TD ALIGN="LEFT" BORDER="1" SIDES="TB">{_italic(h, 12)}</TD>' for h in header) + '</TR>']
    for i, row in enumerate(rows):
        sides = ' BORDER="1" SIDES="B"' if i == len(rows) - 1 else ''
        cells = [f'<TD ALIGN="LEFT"{sides}{f" PORT={_q(ports[i])}" if ports and j == 0 else ""}>{text}</TD>'
                 for j, text in enumerate(row)]
        lines.append('<TR>' + ''.join(cells) + '</TR>')
    return f'{_q(node)} [shape=plaintext, label={_table(lines, padding=2)}];'


def _deepest(model: OrganizationDiagram, goal: str) -> str:
    """The goal at the greatest depth below ``goal``."""
    level, deepest = [goal], goal
    while level:
        deepest = level[0]
        level = [c for g in level if g in model.plans for c in model.plans[g].children]
    return deepest


def _functional(model: OrganizationDiagram, mission_ports: bool = False) -> list[str]:
    body = []
    for index, scheme in enumerate(model.schemes.values()):
        goals = [model.goals[g] for g in scheme.goals]
        inner = [_goal_node(model, g) for g in goals]
        for g in goals:
            inner += _plan_edges(model, g)
        tables = []
        missions_table = None
        described = [g for g in model.goals.values() if g.label and g.id in scheme.goals]
        if described:
            tables.append(_text_table(f'__goals_{scheme.id}', ['goal', 'description'],
                                      [[f'<B>{_h(g.id)}</B>', _h(g.label)] for g in described]))
        if scheme.missions:
            missions = [model.missions[m] for m in scheme.missions]
            labeled = any(m.label for m in missions)
            missions_table = _text_table(f'__missions_{scheme.id}', ['mission'] + ['description'] * labeled + ['agents'],
                                         [[_italic(m.id, 12)] + [_h(m.label or '')] * labeled + [str(m.cardinality)]
                                          for m in missions], ports=[f'm_{m.id}' for m in missions])
            # With deontic links the missions table comes first (left), next to the structural view.
            tables.insert(0, missions_table) if mission_ports else tables.append(missions_table)
        # Tables go below the goal tree (invisible edges from the leaves) so they never push it around.
        deepest = _deepest(model, scheme.root)
        for table in tables:
            inner += [table, f'{_q(deepest)} -> {table.split(" ", 1)[0]} [style=invis];']
        title = f'social scheme {scheme.id}' + (f': {scheme.label}' if scheme.label else '')
        body += _cluster(f'fs_{index}', title, ['ordering=out;', *inner], style='rounded')
    if model.preferences:
        rows = '<BR ALIGN="LEFT"/>'.join(f'{_italic(p.better, 12)} ≺ {_italic(p.worse, 12)}' for p in model.preferences)
        body.append(f'"__preferences" [shape=plaintext, label=<<I>preferences</I><BR/>{rows}<BR ALIGN="LEFT"/>>];')
    return _cluster('fs', 'FS: functional specification', body)


# -- deontic specification and organizational entity --------------------------------------------

@dataclass(frozen=True)
class _Applied:
    """A norm as it applies to one role; ``source`` is the role it is inherited from, if any."""
    kind: str
    role: str
    mission: str
    time_constraint: str
    source: str | None = None


def _applied(model: OrganizationDiagram, inherited: bool) -> list[_Applied]:
    """Declared norms, permissions first as in the paper, then (optionally) the inherited ones (eqs. 8-9)."""
    result = [_Applied(n.kind, n.role, n.mission, n.time_constraint)
              for n in sorted(model.norms, key=lambda n: n.kind != 'per')]
    seen = {(a.kind, a.role, a.mission, a.time_constraint) for a in result}
    if inherited:
        for role in model.roles:
            for norm, is_inherited in model.norms_of(role):
                key = (norm.kind, role, norm.mission, norm.time_constraint)
                if is_inherited and key not in seen:
                    seen.add(key)
                    result.append(_Applied(*key, source=norm.role))
    return result


def _norm_edge(tail: str, head: str, norm: _Applied, extra: str = '') -> str:
    """Obligation: solid line, filled arrowhead. Permission: dashed line, open arrowhead. Inherited: grey.

    ``tail`` and ``head`` are DOT endpoints, already quoted (they may carry ports).
    """
    style = 'solid, arrowhead=normal' if norm.kind == 'obl' else 'dashed, arrowhead=onormal'
    color = ', color=gray55, fontcolor=gray45' if norm.source else ''
    label = f', label=<{_italic(norm.time_constraint)}>' if norm.time_constraint != 'Any' else ''
    return f'{tail} -> {head} [style={style}, arrowsize=1.2{color}{label}, constraint=false{extra}];'


def _deontic(model: OrganizationDiagram, style: str, inherited: bool) -> list[str]:
    norms = _applied(model, inherited)
    title = 'DS: deontic specification'
    if style == 'graph':
        return _cluster('ds', title, _deontic_graph(model, norms))
    if style == 'matrix':
        return _cluster('ds', title, [_deontic_matrix(model, norms, inherited)])
    rows = []
    for n in norms:
        text = (f'<I>{n.kind}</I>({_h(model.roles[n.role].text)}, {_italic(n.mission, 12)}, '
                f'{_h(n.time_constraint)})')
        if n.source:
            text = f'<FONT COLOR="gray45">{text}   <I>inherited from {_h(model.roles[n.source].text)}</I></FONT>'
        rows.append(f'<TR><TD ALIGN="LEFT">{text}</TD></TR>')
    return _cluster('ds', title, [f'"__norms" [shape=plaintext, label={_table(rows, padding=2)}];'])


def _mission_node(node: str, mission) -> str:
    detail = f'<BR/><FONT POINT-SIZE="9">{_h(str(mission.cardinality))}</FONT>'
    return f'{_q(node)} [shape=plaintext, label=<{_italic(mission.id, 13)}{detail}>];'


def _deontic_graph(model: OrganizationDiagram, norms: list[_Applied]) -> list[str]:
    """Roles (drawn as in Fig. 2) above missions (grouped by social scheme), linked by their norms."""
    roles = list(dict.fromkeys(r for r in model.roles if any(n.role == r for n in norms)))
    body = [_role_node(f'__ds_role_{r}', model.roles[r].text, model.roles[r].abstract) for r in roles]
    body.append('{rank=same; ' + '; '.join(_q(f'__ds_role_{r}') for r in roles) + ';}')
    used = {n.mission for n in norms}
    for index, scheme in enumerate(model.schemes.values()):
        missions = [m for m in scheme.missions if m in used]
        if missions:
            inner = [_mission_node(f'__ds_mission_{m}', model.missions[m]) for m in missions]
            inner.append('{rank=same; ' + '; '.join(_q(f'__ds_mission_{m}') for m in missions) + ';}')
            body += _cluster(f'ds_{index}', f'social scheme {scheme.id}', ['labelloc=b;', *inner], style='rounded')
    # Invisible edges keep every role above every mission; the norm edges themselves do not constrain layout.
    body += [f'{_q(f"__ds_role_{n.role}")} -> {_q(f"__ds_mission_{n.mission}")} [style=invis];' for n in norms]
    body += [_norm_edge(_q(f'__ds_role_{n.role}'), _q(f'__ds_mission_{n.mission}'), n) for n in norms]
    return body


def _deontic_matrix(model: OrganizationDiagram, norms: list[_Applied], inherited: bool) -> str:
    """Roles x missions table; each cell holds the strongest norm (O over P), grey when only inherited."""
    schemes = [s for s in model.schemes.values() if s.missions]
    missions = [m for s in schemes for m in s.missions]
    roles = [r for r in model.roles if any(n.role == r for n in norms)]
    cells: dict[tuple[str, str], list[_Applied]] = {}
    for n in norms:
        cells.setdefault((n.role, n.mission), []).append(n)
    header = ('<TR><TD ROWSPAN="2" ALIGN="LEFT" VALIGN="BOTTOM"><I>role</I></TD>'
              + ''.join(f'<TD COLSPAN="{len(s.missions)}"><I>social scheme {_h(s.id)}</I></TD>' for s in schemes)
              + '</TR><TR>' + ''.join(f'<TD>{_italic(m, 12)}</TD>' for m in missions) + '</TR>')
    rows = [header]
    for role in roles:
        text = _h(model.roles[role].text)
        row = f'<TD ALIGN="LEFT"><B>{f"<I>{text}</I>" if model.roles[role].abstract else text}</B></TD>'
        for mission in missions:
            entries = cells.get((role, mission), [])
            strongest = [e for e in entries if e.kind == 'obl'] or entries
            if not strongest:
                row += '<TD> </TD>'
                continue
            letter = 'O' if strongest[0].kind == 'obl' else 'P'
            constraints = sorted({e.time_constraint for e in strongest} - {'Any'})
            content = f'<B>{letter}</B>' + ''.join(f'<BR/>{_italic(t, 8)}' for t in constraints)
            if all(e.source for e in strongest):
                content = f'<FONT COLOR="gray55">{content}</FONT>'
            row += f'<TD>{content}</TD>'
        rows.append(f'<TR>{row}</TR>')
    legend = '<B>O</B> obligation    <B>P</B> permission' + ('    <FONT COLOR="gray55"><B>O P</B></FONT> inherited' if inherited else '')
    rows.append(f'<TR><TD COLSPAN="{len(missions) + 1}" ALIGN="LEFT" BORDER="0"><FONT POINT-SIZE="10">{legend}</FONT></TD></TR>')
    table = (f'<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4" COLOR="gray40">'
             f'{"".join(rows)}</TABLE>>')
    return f'"__ds_matrix" [shape=plaintext, label={table}];'


DEFERRED = '// mx_deferred '
"""Prefix of edge statements kept out of the layout and drawn after it by route.py (``render`` passes them on)."""


def _deontic_links(model: OrganizationDiagram, inherited: bool) -> list[str]:
    """Integrated mode: norms drawn from the SS role nodes to the rows of the FS missions tables (paper Fig. 1).

    The edges are emitted as DOT comments so that they do not influence the layout (Graphviz would reserve
    room for each long edge); route.py draws them afterwards as S-curves from the right side of the role to
    the left of the mission's row (``mx_row`` of ``mx_rows`` table rows, header included).
    """
    lines = []
    for i, n in enumerate(_applied(model, inherited)):
        scheme = model.schemes[model.missions[n.mission].scheme]
        attributes = f', id="mx_link_{i}", mx_row={scheme.missions.index(n.mission) + 1}, mx_rows={len(scheme.missions) + 1}'
        lines.append(DEFERRED + _norm_edge(_q(n.role), _q(f'__missions_{scheme.id}'), n, attributes))
    return lines


def _deontic_key(anchor: str, inherited: bool) -> list[str]:
    """Legend of the deontic edges, which are a convention of this tool (the paper has no DS notation)."""
    rows = [('obligation', ['style=solid, arrowhead=normal, arrowsize=1.2']),
            ('permission', ['style=dashed, arrowhead=onormal, arrowsize=1.2'])]
    if inherited:
        rows.append(('inherited', ['style=solid, arrowhead=normal, arrowsize=1.2, color=gray55',
                                   'style=dashed, arrowhead=onormal, arrowsize=1.2, color=gray55']))
    body, previous = [], _q(anchor)
    for i, (label, edges) in enumerate(rows):
        nodes, lines = _key_cells(f'__kds{i}', label, edges)
        body += lines + [f'{a} -> {b} [style=invis];' for a, b in zip(nodes, nodes[1:])
                         if not (a.endswith('a"') and b.endswith('b"'))]
        body += ['{rank=same; ' + '; '.join(nodes) + ';}', f'{previous} -> {nodes[0]} [style=invis];']
        previous = nodes[0]
    return _cluster('key_ds', 'key', body, style='rounded')


def _entity(model: OrganizationDiagram) -> list[str]:
    rows = []
    for agent in model.agents.values():
        plays = '<BR/>'.join(f'{_h(model.roles[p.role].text)} in <FONT FACE="{MONO}">{_h(model.groups[p.group].text)}</FONT>'
                             for p in model.plays if p.agent == agent.id)
        commits = ', '.join(_italic(c.mission, 12) for c in model.commits if c.agent == agent.id)
        rows.append([f'<B>{_h(agent.text)}</B>', plays, commits])
    return _cluster('oe', 'OE: organizational entity', [_text_table('__agents', ['agent', 'plays', 'commits'], rows)])


# -- keys -----------------------------------------------------------------------------------------

def _key_cells(prefix: str, label: str, edges: list[str]) -> tuple[list[str], list[str]]:
    """Legend cells: a caption followed by sample edges between invisible anchors; returns (nodes, lines)."""
    nodes = [f'"{prefix}"']
    lines = [f'"{prefix}" [shape=plaintext, height=0.25, label={_q(label)}];']
    for i, attributes in enumerate(edges):
        if attributes.startswith('caption:'):
            node = f'"{prefix}_{i}"'
            lines.append(f'{node} [shape=plaintext, height=0.25, width=1.1, fixedsize=true, label={_q(attributes[8:])}];')
            nodes.append(node)
            continue
        a, b = f'"{prefix}_{i}a"', f'"{prefix}_{i}b"'
        lines += [f'{n} [shape=box, style=invis, label="", width=0.35, height=0.1, fixedsize=true];' for n in (a, b)]
        lines.append(f'{a} -> {b} [tailclip=false, headclip=false, {attributes}];')
        nodes += [a, b]
    return nodes, lines


def _structural_key(anchor: str) -> list[str]:
    """Legend of Fig. 2 in two columns, placed below ``anchor`` so it does not share ranks with the diagram."""
    left = [('inheritance:', ['arrowhead=onormal, arrowsize=1.4']),
            ('composition:', [f'arrowhead=odiamond, arrowsize=1.4, xlabel=<{_italic("min..max")}>']),
            ('sub-groups scope:', ['arrowhead=odiamonddot, arrowsize=1.4'])]
    right = [('links', ['caption:intra-group', 'caption:inter-group']),
             *[(name, [f'arrowhead={head}, style=dashed', f'arrowhead={head}, {_scope("inter", f"key_{name}")}'])
               for name, head in LINK_HEADS.items()],
             ('compat', ['arrowhead=diamond, penwidth=2, style=dashed',
                         f'arrowhead=diamond, penwidth=2, {_scope("inter", "key_compat")}'])]
    samples = (['"__kss_role"', '"__kss_abstract"', '"__kss_group"'],
               [_role_node('__kss_role', 'role', False), _role_node('__kss_abstract', 'Abs Role', True),
                _group_node('__kss_group', 'group')])
    body, previous = [], [None, None]
    for row, (l, r) in enumerate(zip(left + [None] * (len(right) - len(left)), right)):
        cells = [_key_cells(f'__kss{row}l', *l) if l else samples if row == len(left) else ([], []),
                 _key_cells(f'__kss{row}r', *r)]
        nodes = [n for cell_nodes, _ in cells for n in cell_nodes]
        body += [line for _, lines in cells for line in lines]
        body += [f'{a} -> {b} [style=invis];' for a, b in zip(nodes, nodes[1:]) if not (a.endswith('a"') and b.endswith('b"'))]
        body.append('{rank=same; ' + '; '.join(nodes) + ';}')
        for column, (cell_nodes, _) in enumerate(cells):
            # Chain each column separately so both stay vertically aligned.
            if cell_nodes and previous[column]:
                body.append(f'{previous[column]} -> {cell_nodes[0]} [style=invis];')
            if cell_nodes:
                previous[column] = cell_nodes[0]
    body.append(f'{_q(anchor)} -> "__kss0l" [style=invis];')
    return _cluster('key_ss', 'key', body, style='rounded')


def _functional_key(anchor: str) -> list[str]:
    """Legend of Fig. 3, placed below ``anchor``."""
    goal = _table([f'<TR><TD ROWSPAN="2"><B>goal</B></TD><TD ALIGN="LEFT">{_italic("missions")}</TD></TR>',
                   f'<TR><TD ALIGN="LEFT">{_italic("success rate")}</TD></TR>'])
    body = [f'"__kfs_goal" [shape=plaintext, label={goal}];']
    tops = ['"__kfs_goal"']
    for name, bars in (('sequence', 0), ('choice', 1), ('parallelism', 2)):
        top = f'"__kfs_{name}"'
        if bars:
            body.append(f'{top} [shape=plaintext, label={_table([_bars(bars)], padding=0)}];')
        else:
            body.append(f'{top} [shape=point, width=0.04, fillcolor=black];')
        tail = f'{top}:op' if bars else top
        body += [f'"__kfs_{name}{i}" [shape=point, style=invis];' for i in (1, 2)]
        body += [f'{tail} -> "__kfs_{name}{i}" [arrowhead=none, id="mx_line_key_{name}{i}"];' for i in (1, 2)]
        body += [f'"__kfs_{name}_caption" [shape=plaintext, label={_q(name)}];',
                 *(f'"__kfs_{name}{i}" -> "__kfs_{name}_caption" [style=invis];' for i in (1, 2))]
        tops.append(top)
    body.append('{rank=same; ' + '; '.join(tops) + ';}')
    body += [f'{a} -> {b} [style=invis];' for a, b in zip(tops, tops[1:])]
    body.append(f'{_q(anchor)} -> "__kfs_goal" [style=invis];')
    return _cluster('key_fs', 'key', body, style='rounded')
