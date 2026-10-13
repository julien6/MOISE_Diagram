"""Parser and validator for the MOISE diagram language."""
from __future__ import annotations
import re
from typing import NamedTuple

from .model import (SOC, Agent, Cardinality, Commits, Compatibility, Composition, DiagramError, Goal, Group,
                    Inheritance, Link, Mission, Norm, OrganizationDiagram, Plan, Plays, Preference, Role, Scheme)

IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
CARDINALITY = re.compile(r'(\d+)\.\.(\d+|\*)')
OPERATORS = {',': 'sequence', '|': 'choice', '||': 'parallel', '∥': 'parallel'}
LINK_TYPES = ('acq', 'com', 'aut')
SCOPES = ('intra', 'inter')
DECLARATIONS = ('role', 'group', 'goal', 'mission', 'agent', 'scheme')

_TOKEN = re.compile(r'''\s+|(?P<comment>\#.*)|(?P<dq>"(?:[^"\\]|\\.)*")|(?P<sq>'[^']*')
                        |(?P<op>\|\||∥|[(),|=])|(?P<word>[^\s"'(),|=\#∥]+)|(?P<bad>["'])''', re.X)


class Token(NamedTuple):
    text: str
    quoted: bool = False
    op: bool = False


def tokenize(line: str, number: int) -> list[Token]:
    """Split a line into words, quoted strings and plan punctuation; ``#`` starts a comment."""
    tokens, pos = [], 0
    while pos < len(line):
        match = _TOKEN.match(line, pos)
        if match.lastgroup == 'comment':
            break
        if match.lastgroup == 'bad':
            raise DiagramError(f'line {number}: unterminated string')
        if match.lastgroup == 'dq':
            tokens.append(Token(re.sub(r'\\(.)', r'\1', match.group()[1:-1]), quoted=True))
        elif match.lastgroup == 'sq':
            tokens.append(Token(match.group()[1:-1], quoted=True))
        elif match.lastgroup == 'op':
            tokens.append(Token(match.group(), op=True))
        elif match.lastgroup == 'word':
            tokens.append(Token(match.group()))
        pos = match.end()
    return tokens


def parse(source: str) -> OrganizationDiagram:
    """Parse and validate MOISE diagram source text; raise DiagramError on the first problem."""
    return _Parser(source).model


class _Parser:
    def __init__(self, source: str) -> None:
        self.model = OrganizationDiagram()
        self.model.roles[SOC] = Role(SOC, abstract=True)
        self.kinds: dict[str, str] = {SOC: 'role'}
        self.parent_plan: dict[str, tuple[str, int]] = {}
        self.anonymous = 0
        statements = self.read(source)
        for line, tokens in statements:
            if tokens[0].text in DECLARATIONS and not tokens[0].quoted:
                self.declare(line, tokens)
        for line, tokens in statements:
            if tokens[0].text not in DECLARATIONS or tokens[0].quoted:
                self.statement(line, tokens)
        self.check_structure()
        self.check_schemes()
        self.check_entity()

    # -- reading --------------------------------------------------------------------------------

    def read(self, source: str) -> list[tuple[int, list[Token]]]:
        statements, opened, closed = [], False, False
        for number, text in enumerate(source.splitlines(), 1):
            tokens = tokenize(text, number)
            if not tokens:
                continue
            if tokens[0].text == '@moise':
                if opened or len(tokens) > 2 or any(t.op for t in tokens):
                    raise DiagramError(f'line {number}: expected a single @moise ["title"]')
                opened = True
                if len(tokens) == 2:
                    self.model.title = tokens[1].text
                continue
            if not opened or closed:
                raise DiagramError(f'line {number}: statement outside @moise ... @end')
            if [t.text for t in tokens] == ['@end']:
                closed = True
                continue
            statements.append((number, tokens))
        if not opened or not closed:
            raise DiagramError('expected @moise ... @end')
        return statements

    @staticmethod
    def fail(line: int, message: str) -> None:
        raise DiagramError(f'line {line}: {message}')

    def ref(self, name: str, kind: str, line: int) -> str:
        """Check that ``name`` is declared with one of the ``|``-separated kinds."""
        if self.kinds.get(name) not in kind.split('|'):
            self.fail(line, f'{name} must reference {kind}')
        return name

    def cardinality(self, text: str, line: int) -> Cardinality:
        match = CARDINALITY.fullmatch(text)
        if not match:
            self.fail(line, 'expected cardinality min..max or min..*')
        low, high = int(match[1]), None if match[2] == '*' else int(match[2])
        if high is not None and low > high:
            self.fail(line, 'cardinality minimum exceeds maximum')
        return Cardinality(low, high)

    # -- declarations ---------------------------------------------------------------------------

    def declare(self, line: int, tokens: list[Token]) -> None:
        kind, words = tokens[0].text, [t.text for t in tokens]
        if any(t.op for t in tokens):
            self.fail(line, f'unexpected punctuation in {kind} declaration; quote labels containing ( ) , | =')
        if len(tokens) < 2:
            self.fail(line, f'expected {kind} id')
        name = words[1]
        if not IDENTIFIER.fullmatch(name):
            self.fail(line, 'identifier must match [A-Za-z_][A-Za-z_0-9]*')
        if name.startswith('__'):
            self.fail(line, 'identifiers beginning with __ are reserved')
        if name == SOC:
            self.fail(line, 'soc is the predefined root role and cannot be declared')
        if name in self.kinds:
            self.fail(line, f'duplicate identifier {name}')
        rest = tokens[2:]
        if kind != 'role' and rest and not rest[-1].quoted and rest[-1].text == 'abstract':
            self.fail(line, 'only a role can be abstract')
        if kind == 'scheme':
            if len(rest) not in (1, 2):
                self.fail(line, 'expected scheme id root_goal ["label"]')
            label = rest[1].text if len(rest) == 2 else None
            self.model.schemes[name] = Scheme(name, rest[0].text, label, line=line)
        else:
            flag = {'role': lambda t: t.text == 'abstract', 'mission': lambda t: bool(CARDINALITY.fullmatch(t.text))}.get(kind)
            option = rest.pop() if rest and flag and not rest[-1].quoted and flag(rest[-1]) else None
            if len(rest) > 1:
                expected = {'role': ' [abstract]', 'mission': ' [min..max]'}.get(kind, '')
                self.fail(line, f'expected {kind} id ["label"]{expected}')
            label = rest[0].text if rest else None
            if kind == 'role':
                self.model.roles[name] = Role(name, label, option is not None, line)
            elif kind == 'group':
                self.model.groups[name] = Group(name, label, line)
            elif kind == 'goal':
                self.model.goals[name] = Goal(name, label, line=line)
            elif kind == 'mission':
                cardinality = self.cardinality(option.text, line) if option else Mission(name).cardinality
                self.model.missions[name] = Mission(name, label, cardinality, line=line)
            else:
                self.model.agents[name] = Agent(name, label, line)
        self.kinds[name] = kind

    # -- statements -----------------------------------------------------------------------------

    def statement(self, line: int, tokens: list[Token]) -> None:
        command = tokens[0].text
        if command == 'plan' and not tokens[0].quoted:
            return self.plan(line, tokens)
        if any(t.op for t in tokens):
            self.fail(line, f'unexpected "{next(t.text for t in tokens if t.op)}"; quote labels containing ( ) , | =')
        w = [t.text for t in tokens]
        m, n = self.model, len(w)
        if command == 'inherits' and n == 3:
            sub, parent = self.ref(w[1], 'role', line), self.ref(w[2], 'role', line)
            if sub == SOC:
                self.fail(line, 'soc is the root role and cannot inherit')
            if sub == parent:
                self.fail(line, f'role {sub} cannot inherit from itself')
            if any(i.sub == sub and i.parent == parent for i in m.inheritance):
                self.fail(line, f'duplicate inheritance {sub} {parent}')
            m.inheritance.append(Inheritance(sub, parent, line))
        elif command == 'contains' and 3 <= n <= 5:
            group, member = self.ref(w[1], 'group', line), self.ref(w[2], 'group|role', line)
            options = w[3:]
            subgroups = bool(options) and options[-1] == 'subgroups'
            if subgroups:
                options.pop()
            if len(options) > 1:
                self.fail(line, 'expected contains group member [min..max] [subgroups]')
            cardinality = self.cardinality(options[0], line) if options else Cardinality(0, None)
            if member in m.roles and m.roles[member].abstract:
                self.fail(line, f'abstract role {member} cannot be played in a group')
            if subgroups and member in m.groups:
                self.fail(line, 'the subgroups scope only applies to roles')
            if member == group:
                self.fail(line, f'group {group} cannot contain itself')
            if any(c.group == group and c.member == member for c in m.compositions):
                self.fail(line, f'{member} is already part of group {group}')
            m.compositions.append(Composition(group, member, cardinality, subgroups, line))
        elif command == 'link' and n == 6:
            group = self.ref(w[1], 'group', line)
            source, target = self.ref(w[2], 'role', line), self.ref(w[3], 'role', line)
            if w[4] not in LINK_TYPES or w[5] not in SCOPES:
                self.fail(line, 'expected link group source target acq|com|aut intra|inter')
            m.links.append(Link(group, source, target, w[4], w[5], line))
        elif command == 'compat' and n == 5:
            group = self.ref(w[1], 'group', line)
            role_a, role_b = self.ref(w[2], 'role', line), self.ref(w[3], 'role', line)
            if w[4] not in SCOPES:
                self.fail(line, 'expected compat group role_a role_b intra|inter')
            if role_a == role_b:
                self.fail(line, 'compatibility is reflexive: a role is always compatible with itself')
            m.compatibilities.append(Compatibility(group, role_a, role_b, w[4], line))
        elif command == 'goals' and n >= 3:
            mission = m.missions[self.ref(w[1], 'mission', line)]
            for goal in w[2:]:
                self.ref(goal, 'goal', line)
                if goal in mission.goals:
                    self.fail(line, f'goal {goal} is already in mission {mission.id}')
                mission.goals.append(goal)
        elif command == 'prefer' and n == 3:
            better, worse = self.ref(w[1], 'mission', line), self.ref(w[2], 'mission', line)
            if better == worse:
                self.fail(line, 'a mission cannot be preferred to itself')
            m.preferences.append(Preference(better, worse, line))
        elif command in ('per', 'obl') and n in (3, 4):
            role, mission = self.ref(w[1], 'role', line), self.ref(w[2], 'mission', line)
            m.norms.append(Norm(command, role, mission, w[3] if n == 4 else 'Any', line))
        elif command == 'plays' and n == 4:
            agent, role, group = self.ref(w[1], 'agent', line), self.ref(w[2], 'role', line), self.ref(w[3], 'group', line)
            if any(p.agent == agent and p.role == role and p.group == group for p in m.plays):
                self.fail(line, f'{agent} already plays {role} in {group}')
            m.plays.append(Plays(agent, role, group, line))
        elif command == 'commits' and n == 3:
            m.commits.append(Commits(self.ref(w[1], 'agent', line), self.ref(w[2], 'mission', line), line))
        else:
            self.fail(line, f'unknown or malformed statement: {command}')

    def plan(self, line: int, tokens: list[Token]) -> None:
        if len(tokens) < 3 or tokens[1].op or tokens[2].text != '=' or not tokens[2].op:
            self.fail(line, 'expected plan goal =[rate] subgoal op subgoal ...')
        goal = self.ref(tokens[1].text, 'goal', line)
        rest, rate = tokens[3:], None
        if rest and not rest[0].op and not rest[0].quoted and re.fullmatch(r'\d*\.?\d+', rest[0].text):
            rate = float(rest.pop(0).text)
            if not 0 < rate <= 1:
                self.fail(line, 'success rate must be in (0, 1]')
        tree, end = self.expression(rest, 0, line)
        if end != len(rest):
            self.fail(line, f'unexpected "{rest[end].text}" in plan')
        if isinstance(tree, str):
            self.fail(line, 'a plan needs at least two subgoals')
        self.add_plan(goal, tree, rate, line)

    def expression(self, tokens: list[Token], pos: int, line: int) -> tuple[object, int]:
        """Parse ``term (op term)*`` where every op of one level is the same; return (tree, position)."""
        first, pos = self.term(tokens, pos, line)
        terms, operator = [first], None
        while pos < len(tokens) and tokens[pos].op and tokens[pos].text in OPERATORS:
            current = OPERATORS[tokens[pos].text]
            if operator and current != operator:
                self.fail(line, 'mixing plan operators requires parentheses')
            operator = current
            term, pos = self.term(tokens, pos + 1, line)
            terms.append(term)
        return (first if operator is None else (operator, terms)), pos

    def term(self, tokens: list[Token], pos: int, line: int) -> tuple[object, int]:
        if pos >= len(tokens):
            self.fail(line, 'incomplete plan')
        token = tokens[pos]
        if token.op and token.text == '(':
            tree, pos = self.expression(tokens, pos + 1, line)
            if pos >= len(tokens) or tokens[pos].text != ')':
                self.fail(line, 'missing ) in plan')
            return tree, pos + 1
        if token.op or token.quoted:
            self.fail(line, f'unexpected "{token.text}" in plan')
        return self.ref(token.text, 'goal', line), pos + 1

    def add_plan(self, goal: str, tree: tuple, rate: float | None, line: int) -> None:
        operator, terms = tree
        if goal in self.model.plans:
            self.fail(line, f'goal {goal} already has a plan')
        children = []
        for term in terms:
            if isinstance(term, tuple):
                self.anonymous += 1
                child = f'__goal{self.anonymous}'
                self.model.goals[child] = Goal(child, anonymous=True, line=line)
                self.add_plan(child, term, None, line)
            else:
                child = term
            if child in children or child in self.parent_plan:
                owner = goal if child in children else self.parent_plan[child][0]
                self.fail(line, f'goal {child} is already a subgoal of {owner}')
            if child == goal:
                self.fail(line, f'goal {goal} cannot be its own subgoal')
            self.parent_plan[child] = (goal, line)
            children.append(child)
        self.model.plans[goal] = Plan(goal, operator, children, rate, line)

    # -- global checks --------------------------------------------------------------------------

    def check_structure(self) -> None:
        m = self.model
        _check_acyclic(_edges((i.sub, i.parent, i.line) for i in m.inheritance), 'inheritance')
        _check_acyclic(_edges((c.group, c.member, c.line) for c in m.compositions if c.member in m.groups), 'group composition')
        _check_acyclic(_edges((p.better, p.worse, p.line) for p in m.preferences), 'mission preference')

    def check_schemes(self) -> None:
        m = self.model
        _check_acyclic(_edges((p.goal, c, p.line) for p in m.plans.values() for c in p.children), 'goal decomposition')
        owner: dict[str, str] = {}
        for scheme in m.schemes.values():
            root = self.ref(scheme.root, 'goal', scheme.line)
            if root in self.parent_plan:
                self.fail(scheme.line, f'root goal {root} of scheme {scheme.id} is a subgoal of {self.parent_plan[root][0]}')
            if root in owner:
                self.fail(scheme.line, f'goal {root} is already the root of scheme {owner[root]}')
            todo = [root]
            while todo:
                goal = todo.pop(0)
                owner[goal] = scheme.id
                scheme.goals.append(goal)
                todo.extend(m.plans[goal].children if goal in m.plans else [])
        for goal in m.goals.values():
            if goal.id not in owner:
                self.fail(goal.line, f'goal {goal.id} is not part of any social scheme')
        for mission in m.missions.values():
            if not mission.goals:
                self.fail(mission.line, f'mission {mission.id} has no goals')
            schemes = list(dict.fromkeys(owner[g] for g in mission.goals))
            if len(schemes) > 1:
                self.fail(mission.line, f'mission {mission.id} mixes goals of schemes {" and ".join(schemes)}')
            mission.scheme = schemes[0]
            m.schemes[schemes[0]].missions.append(mission.id)

    def check_entity(self) -> None:
        m = self.model
        members = {(c.group, c.member) for c in m.compositions if not c.subgroups}
        for p in m.plays:
            if m.roles[p.role].abstract:
                self.fail(p.line, f'abstract role {p.role} cannot be played')
            if (p.group, p.role) not in members:
                self.fail(p.line, f'role {p.role} is not part of group {p.group}')
        for agent in m.agents:
            played = [p for p in m.plays if p.agent == agent]
            for i, first in enumerate(played):
                for second in played[i + 1:]:
                    if not compatible(m, first, second):
                        self.fail(second.line, f'{agent} cannot play both {first.role} in {first.group} and '
                                               f'{second.role} in {second.group}: roles are not compatible')
        for c in m.commits:
            roles = {p.role for p in m.plays if p.agent == c.agent}
            if not any(n.mission == c.mission for r in roles for n, _ in m.norms_of(r)):
                self.fail(c.line, f'{c.agent} cannot commit to {c.mission}: none of its roles has a permission or obligation for it')


def compatible(model: OrganizationDiagram, first: Plays, second: Plays) -> bool:
    """Whether one agent may play both role adoptions, following the compatibility rules of the paper.

    ``⋈`` is reflexive and transitive, is inherited by sub-roles (on both sides), and has a scope:
    intra-group when the groups are the same or nested, inter-group otherwise.
    """
    if first.role == second.role:
        return True
    a, b = model.subgroups(first.group), model.subgroups(second.group)
    nested = first.group in b or second.group in a
    scope = 'intra' if nested else 'inter'
    candidates = [c for c in model.compatibilities if c.scope == scope and (
        {first.group, second.group} <= model.subgroups(c.group) if nested
        else first.group in model.subgroups(c.group) or second.group in model.subgroups(c.group))]

    def reachable(start: str, goal: str) -> bool:
        seen, todo = set(), [start]
        while todo:
            role = todo.pop()
            if role == goal:
                return True
            if role in seen:
                continue
            seen.add(role)
            ancestors = model.ancestors(role)
            todo.extend(r for c in candidates if c.role_a in ancestors
                        for r in model.roles if c.role_b in model.ancestors(r))
        return False

    return reachable(first.role, second.role) or reachable(second.role, first.role)


def _edges(triples) -> dict[str, list[tuple[str, int]]]:
    graph: dict[str, list[tuple[str, int]]] = {}
    for source, target, line in triples:
        graph.setdefault(source, []).append((target, line))
    return graph


def _check_acyclic(graph: dict[str, list[tuple[str, int]]], relation: str) -> None:
    """Iterative depth-first search; report the line of the edge that closes a cycle."""
    state: dict[str, int] = {}
    for start in graph:
        if start in state:
            continue
        state[start] = 1
        stack = [(start, iter(graph.get(start, [])))]
        while stack:
            node, children = stack[-1]
            for child, line in children:
                if state.get(child) == 1:
                    raise DiagramError(f'line {line}: cycle in {relation} involving {child}')
                if child not in state:
                    state[child] = 1
                    stack.append((child, iter(graph.get(child, []))))
                    break
            else:
                state[node] = 2
                stack.pop()
