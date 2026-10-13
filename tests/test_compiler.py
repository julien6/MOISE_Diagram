from pathlib import Path
import shutil
import pytest
from moise_diagram import DiagramError, compile_file, parse, to_dot
from moise_diagram.compiler import main

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
SOCCER = EXAMPLES / 'soccer.moise'
SNACK = EXAMPLES / 'snack.moise'

STRUCTURE = '''
role player abstract
role back
role goalkeeper
role leader
role coach
inherits back player
inherits leader player
inherits goalkeeper back
group team
group defense
group other
contains team coach 1..2
contains team defense
contains defense back 3..3
contains defense goalkeeper 1..1
contains defense leader 0..1
contains other coach
compat defense leader back intra
scheme s g0
goal g0
goal g1
goal g2
plan g0 = g1, g2
mission m1
mission m2
goals m1 g1
goals m2 g2
obl player m1
per coach m2
'''


def org(body: str) -> str:
    return f'@moise\n{body}\n@end'


def test_soccer_example_follows_the_paper():
    model = parse(SOCCER.read_text(encoding='utf-8'))
    assert model.title == 'Soccer team'
    assert model.parents('coach') == ['soc'] and model.parents('goalkeeper') == ['back']
    assert model.ancestors('goalkeeper') == {'goalkeeper', 'back', 'player', 'soc'}
    assert model.subgroups('team') == {'team', 'defense', 'attack'}
    assert next(c for c in model.compositions if c.member == 'leader' and c.group == 'team').subgroups
    scheme = model.schemes['sg']
    assert len([g for g in scheme.goals if not model.goals[g].anonymous]) == 19
    anonymous = model.plans['g3'].children[0]
    assert model.goals[anonymous].anonymous and model.plans[anonymous].operator == 'parallel'
    assert model.plans['g9'].operator == 'choice' and model.plans['g0'].rate == 0.8
    assert str(model.missions['m1'].cardinality) == '1..4' and model.missions['m1'].scheme == 'sg'
    assert len(model.norms) == 8


def test_soccer_rendering_uses_the_paper_notation():
    dot = to_dot(parse(SOCCER.read_text(encoding='utf-8')))
    assert '"soc" [shape=box, style="rounded,filled", label=<<B><I>soc</I></B>>]' in dot
    assert '"team" [shape=tab' in dot
    assert '"soc" -> "player" [dir=back, arrowtail=onormal' in dot
    assert '"leader" -> "team" [arrowhead=odiamonddot' in dot
    assert '"coach" -> "player" [arrowhead=normal, style=solid' in dot
    assert '"player" -> "coach" [arrowhead=vee, style=solid' in dot
    assert '"player" -> "player" [arrowhead=dot' in dot
    assert '"goalkeeper" -> "back" [arrowhead=normal, style=dashed' in dot
    assert '"leader" -> "back" [arrowhead=diamond, penwidth=2, style=dashed' in dot
    assert 'm1,2,3' in dot and '>.8<' in dot
    assert '"g9":op -> "g7"' in dot
    assert '<I>obl</I>(goalkeeper, ' in dot


def test_defaults():
    model = parse(org('role r\ngroup g\ncontains g r\nscheme s a\ngoal a\nmission m\ngoals m a\nper r m'))
    assert str(model.compositions[0].cardinality) == '0..*'
    assert str(model.missions['m'].cardinality) == '1..*'
    assert model.norms[0].time_constraint == 'Any'


def test_labels_and_tokens():
    model = parse(org('role r "abstract"\nrole q \'a (b), c | d\' abstract  # comment\ngroup g "x # y"'))
    assert model.roles['r'].label == 'abstract' and not model.roles['r'].abstract
    assert model.roles['q'].label == 'a (b), c | d' and model.roles['q'].abstract
    assert model.groups['g'].label == 'x # y'
    assert '&lt;' in to_dot(parse(org('role r "<x&y>" abstract')))


def test_nested_plans():
    model = parse(org('scheme s a\ngoal a\ngoal b\ngoal c\ngoal d\nplan a =1 b, (c | (d || b2))\ngoal b2'))
    first = model.plans['a']
    assert first.operator == 'sequence' and first.children[0] == 'b' and first.rate == 1
    inner = model.plans[first.children[1]]
    assert inner.operator == 'choice' and model.plans[inner.children[1]].operator == 'parallel'


@pytest.mark.parametrize('statement, message', [
    ('contains g r 2..1', 'minimum exceeds'),
    ('contains g r 1-2', 'expected cardinality'),
    ('contains g a', 'abstract role a cannot be played'),
    ('contains g g', 'cannot contain itself'),
    ('contains g r\ncontains g r', 'already part of group'),
    ('contains g h subgroups', 'only applies to roles'),
    ('per missing m', 'missing must reference role'),
    ('commits r m', 'r must reference agent'),
    ('link g r r acq nowhere', 'expected link'),
    ('link g r r compat intra', 'expected link'),
    ('compat g r r intra', 'reflexive'),
    ('inherits r r', 'cannot inherit from itself'),
    ('inherits soc r', 'soc is the root role'),
    ('role soc', 'predefined root role'),
    ('role __x', 'reserved'),
    ('group r', 'duplicate identifier r'),
    ('group h2 abstract', 'only a role can be abstract'),
    ('group h2 x y', 'expected group id'),
    ('plan x = b, missing', 'missing must reference goal'),
    ('plan x = b, b', 'already a subgoal of x'),
    ('plan x = b, c\nplan x = b2, c2', 'already has a plan'),
    ('plan x = b, c | c2', 'requires parentheses'),
    ('plan x = b', 'at least two subgoals'),
    ('plan x =2 b, c', 'success rate'),
    ('plan x = (b, c', 'missing )'),
    ('plan x b, c', 'expected plan goal'),
    ('prefer m m', 'preferred to itself'),
    ('nonsense r', 'unknown or malformed statement: nonsense'),
    ('role r2 (x)', 'unexpected punctuation'),
])
def test_reject_bad_statements(statement, message):
    base = ('role r\nrole a abstract\ngroup g\ngroup h\nmission m\nscheme s x\ngoal x\ngoal b\ngoal c\n'
            'goal b2\ngoal c2\nplan x = b, c, b2, c2\ngoals m b\n')
    if statement.startswith('plan x'):
        base = base.replace('plan x = b, c, b2, c2\n', '')
    with pytest.raises(DiagramError, match='line') as error:
        parse(org(base + statement))
    assert message in str(error.value)


@pytest.mark.parametrize('body, message', [
    ('group a\ngroup b\ncontains a b\ncontains b a', 'cycle in group composition'),
    ('role a\nrole b\ninherits a b\ninherits b a', 'cycle in inheritance'),
    ('mission a\nmission b\nprefer a b\nprefer b a\nscheme s g\ngoal g\ngoals a g\ngoals b g', 'cycle in mission preference'),
    ('scheme s g\ngoal g\ngoal h\ngoal i\nplan h = i, g', 'is a subgoal of h'),
    ('scheme s g\ngoal g\ngoal h', 'goal h is not part of any social scheme'),
    ('scheme s g\nscheme t g\ngoal g', 'already the root of scheme s'),
    ('scheme s g\ngoal g\nmission m', 'mission m has no goals'),
    ('scheme s g\nscheme t h\ngoal g\ngoal h\nmission m\ngoals m g h', 'mixes goals of schemes s and t'),
    ('scheme s g\ngoal g\ngoal a\ngoal b\ngoal c\nplan g = a, b\nplan a = c, g', 'cycle in goal decomposition'),
])
def test_reject_inconsistent_specifications(body, message):
    with pytest.raises(DiagramError, match=message):
        parse(org(body))


@pytest.mark.parametrize('entity, message', [
    ('plays x player team', 'abstract role player cannot be played'),
    ('plays x back team', 'role back is not part of group team'),
    ('plays x coach team\nplays x back defense', 'roles are not compatible'),
    ('plays x back defense\nplays x goalkeeper defense', 'roles are not compatible'),
    ('plays x coach team\ncommits x m1', 'cannot commit to m1'),
    ('commits x m2', 'cannot commit to m2'),
])
def test_reject_organizational_entity(entity, message):
    with pytest.raises(DiagramError, match=message):
        parse(org(STRUCTURE + 'agent x\n' + entity))


@pytest.mark.parametrize('entity', [
    'plays x leader defense\nplays x back defense',          # compat leader ⋈ back (intra)
    'plays x leader defense\nplays x goalkeeper defense',    # inherited on the target side (back ⊏ goalkeeper)
    'plays x back defense\nplays x leader defense',          # either direction
    'plays x coach team\nplays x coach other',               # reflexive
    'plays x back defense\ncommits x m1',                    # obl(player, m1) inherited by back
    'plays x coach team\ncommits x m2',
])
def test_accept_organizational_entity(entity):
    parse(org(STRUCTURE + 'agent x\n' + entity))


def test_inter_group_compatibility():
    entity = 'agent x\nplays x coach other\nplays x leader defense'
    with pytest.raises(DiagramError, match='not compatible'):
        parse(org(STRUCTURE + entity))
    parse(org(STRUCTURE + 'compat other coach leader inter\n' + entity))


def test_document_structure():
    for source, message in [('role r', 'outside'), ('@moise\nrole r', 'expected @moise'),
                            ('@moise\n@moise\n@end', 'single @moise'), ('@moise\n@end\nrole r', 'outside'),
                            ('@moise\nrole r "x\n@end', 'unterminated string')]:
        with pytest.raises(DiagramError, match=message):
            parse(source)
    assert parse('# comment\n@moise "T"\n@end').title == 'T'


def test_dot_keywords_are_quoted_identifiers():
    dot = to_dot(parse(org('role node\nrole edge\ngroup graph\ncontains graph node')))
    assert '"node" [shape=box' in dot and '"node" -> "graph"' in dot


def test_views_and_key():
    model = parse(SOCCER.read_text(encoding='utf-8'))
    structure = to_dot(model, views=['ss'], key=True)
    assert 'cluster_ss' in structure and 'cluster_fs' not in structure and 'cluster_key_ss' in structure
    functional = to_dot(model, views=['fs', 'ds'], key=True)
    assert 'cluster_ss' not in functional and 'cluster_key_fs' in functional and 'cluster_ds' in functional
    with pytest.raises(DiagramError, match='unknown view'):
        to_dot(model, views=['xx'])


def test_cli_writes_dot(tmp_path, capsys):
    output = tmp_path / 'out' / 'snack.dot'
    main([str(SNACK), '-o', str(output), '--view', 'oe'])
    assert 'cluster_oe' in output.read_text(encoding='utf-8')
    bad = tmp_path / 'bad.moise'
    bad.write_text('@moise\nplays a b c\n@end', encoding='utf-8')
    with pytest.raises(SystemExit) as exit_:
        main([str(bad), '-o', str(tmp_path / 'bad.svg')])
    assert exit_.value.code == 2 and 'line 2' in capsys.readouterr().err


@pytest.mark.skipif(not shutil.which('dot'), reason='Graphviz is not installed')
@pytest.mark.parametrize('source', [SOCCER, SNACK])
def test_actual_svg_and_pdf(tmp_path, source):
    for suffix, magic in [('svg', b'<?xml'), ('pdf', b'%PDF')]:
        output = tmp_path / f'result.{suffix}'
        compile_file(source, output, key=True)
        assert output.read_bytes().startswith(magic)


@pytest.mark.skipif(not shutil.which('dot'), reason='Graphviz is not installed')
class TestRouting:
    """Post-layout geometry: bus inheritance, wavy inter-group lines, cardinality placement, straight plans."""

    @pytest.fixture(scope='class', params=[('ss', 'fs', 'ds', 'oe'), ('ss',)], ids=['all', 'ss'])
    def routed(self, request):
        import subprocess
        from moise_diagram.route import _parse, route
        dot = to_dot(parse(SOCCER.read_text(encoding='utf-8')), views=request.param, key=True)
        laid = subprocess.run(['dot', '-Tdot'], input=dot.encode(), capture_output=True, check=True).stdout.decode()
        statements = {s.get('id'): s for s in _parse(route(laid)) if s.get('id')}
        return statements, _parse

    @staticmethod
    def points(statement):
        from moise_diagram.route import _parse_pos
        return _parse_pos(statement.get('pos'))

    def test_inheritance_shares_a_right_angled_bus(self, routed):
        statements, _ = routed
        buses = {}
        for child in ('back', 'leader', 'middle', 'attacker'):
            prefix, points = self.points(statements[f'mx_bus_player_{child}'])
            corners = points[::3]
            assert prefix[0].startswith('s,')                                   # one triangle, at the parent
            assert all(a[0] == b[0] or a[1] == b[1] for a, b in zip(corners, corners[1:]))   # orthogonal
            buses[child] = corners[1][1]
        assert len(set(buses.values())) == 1                                    # one shared horizontal bar

    def test_inter_group_lines_are_wavy_and_keep_their_ends(self, routed):
        from moise_diagram.route import _sample
        statements, _ = routed
        for name in ('mx_wave_link1', 'mx_wave_link2', 'mx_wave_link3', 'mx_wave_key_acq', 'mx_wave_key_compat'):
            prefix, points = self.points(statements[name])
            samples = _sample(points)
            start, end = samples[0], samples[-1]
            deviations = [((end[0] - start[0]) * (p[1] - start[1]) - (end[1] - start[1]) * (p[0] - start[0]))
                          for p in samples]
            assert len(points) > 10 and min(deviations) < 0 < max(deviations), name   # crosses its chord
            assert prefix                                                              # arrowhead kept

    def test_cardinalities_overlap_neither_labels_nor_other_lines(self, routed):
        from moise_diagram.route import _sample
        statements, _ = routed
        boxes = {}
        for name, s in statements.items():
            if name.startswith('mx_card_'):
                x, y = map(float, s.get('tail_lp').split(','))
                boxes[name] = (x - 10, y - 5, x + 10, y + 5)
        assert len(boxes) == 10
        names = list(boxes)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                p, q = boxes[a], boxes[b]
                assert not (p[0] < q[2] and q[0] < p[2] and p[1] < q[3] and q[1] < p[3]), (a, b)
        for name, box in boxes.items():
            for other, s in statements.items():
                if other != name and s.get('pos') and '->' in s.head:
                    for x, y in _sample(self.points(s)[1], step=2):
                        assert not (box[0] < x < box[2] and box[1] < y < box[3]), (name, other)

    def test_plan_lines_are_straight(self, routed):
        statements, _ = routed
        if 'mx_line_g11_g22' in statements:
            _, points = self.points(statements['mx_line_g11_g22'])
            assert len(points) == 4
