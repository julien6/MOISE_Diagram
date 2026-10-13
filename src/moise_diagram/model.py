"""Data model of a MOISE+ organizational specification (Hübner, Sichman and Boissier, SBIA 2002).

The model mirrors the paper: a structural specification (roles, inheritance,
groups with their links, compatibilities and cardinalities), a functional
specification (social schemes made of goals, plans, missions and mission
preferences), a deontic specification (permissions and obligations), plus an
optional organizational entity (agents, role adoptions and mission commitments).
"""
from __future__ import annotations
from dataclasses import dataclass, field

SOC = 'soc'
"""Identifier of the predefined abstract root role: every role specializes it."""

UNBOUNDED = None
"""Value of ``Cardinality.max`` when there is no upper bound (written ``*``)."""


class DiagramError(ValueError):
    """Invalid source with a line-number diagnostic."""


@dataclass(frozen=True)
class Cardinality:
    min: int
    max: int | None

    def __str__(self) -> str:
        return f'{self.min}..{"*" if self.max is None else self.max}'


@dataclass
class Role:
    id: str
    label: str | None = None
    abstract: bool = False
    line: int = 0

    @property
    def text(self) -> str:
        return self.label if self.label is not None else self.id


@dataclass
class Group:
    """Group specification: the tuple <R, SG, L_intra, L_inter, C_intra, C_inter, np, ng> of the paper."""
    id: str
    label: str | None = None
    line: int = 0

    @property
    def text(self) -> str:
        return self.label if self.label is not None else self.id


@dataclass
class Inheritance:
    """``sub`` specializes ``parent`` (written parent ⊏ sub in the paper)."""
    sub: str
    parent: str
    line: int = 0


@dataclass
class Composition:
    """A role (np) or sub-group (ng) cardinality inside a group specification."""
    group: str
    member: str
    cardinality: Cardinality
    subgroups: bool = False
    line: int = 0


@dataclass
class Link:
    """``link(source, target, type)`` in the intra- or inter-group links of ``group``."""
    group: str
    source: str
    target: str
    type: str
    scope: str
    line: int = 0


@dataclass
class Compatibility:
    """``role_a ⋈ role_b`` in the intra- or inter-group compatibilities of ``group``."""
    group: str
    role_a: str
    role_b: str
    scope: str
    line: int = 0


@dataclass
class Goal:
    id: str
    label: str | None = None
    anonymous: bool = False
    line: int = 0


@dataclass
class Plan:
    """``goal =rate child1 op child2 op ...`` with op one of sequence, choice or parallel."""
    goal: str
    operator: str
    children: list[str]
    rate: float | None = None
    line: int = 0


@dataclass
class Mission:
    id: str
    label: str | None = None
    cardinality: Cardinality = Cardinality(1, UNBOUNDED)
    goals: list[str] = field(default_factory=list)
    scheme: str | None = None
    line: int = 0


@dataclass
class Scheme:
    """Social scheme <G, M, P, mo, nm>: the goal tree rooted at ``root`` and its missions."""
    id: str
    root: str
    label: str | None = None
    goals: list[str] = field(default_factory=list)
    missions: list[str] = field(default_factory=list)
    line: int = 0


@dataclass
class Preference:
    """``better ≺ worse``: missions of ``better`` have social preference."""
    better: str
    worse: str
    line: int = 0


@dataclass
class Norm:
    """``per(role, mission, tc)`` or ``obl(role, mission, tc)``."""
    kind: str
    role: str
    mission: str
    time_constraint: str = 'Any'
    line: int = 0


@dataclass
class Agent:
    id: str
    label: str | None = None
    line: int = 0

    @property
    def text(self) -> str:
        return self.label if self.label is not None else self.id


@dataclass
class Plays:
    agent: str
    role: str
    group: str
    line: int = 0


@dataclass
class Commits:
    agent: str
    mission: str
    line: int = 0


@dataclass
class OrganizationDiagram:
    """Validated model of a ``.moise`` document. Dictionaries keep declaration order."""
    title: str = 'MOISE+'
    roles: dict[str, Role] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
    inheritance: list[Inheritance] = field(default_factory=list)
    compositions: list[Composition] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    compatibilities: list[Compatibility] = field(default_factory=list)
    goals: dict[str, Goal] = field(default_factory=dict)
    plans: dict[str, Plan] = field(default_factory=dict)
    schemes: dict[str, Scheme] = field(default_factory=dict)
    missions: dict[str, Mission] = field(default_factory=dict)
    preferences: list[Preference] = field(default_factory=list)
    norms: list[Norm] = field(default_factory=list)
    agents: dict[str, Agent] = field(default_factory=dict)
    plays: list[Plays] = field(default_factory=list)
    commits: list[Commits] = field(default_factory=list)

    def parents(self, role: str) -> list[str]:
        """Direct super-roles; a role without declared parents specializes ``soc``."""
        if role == SOC:
            return []
        declared = [i.parent for i in self.inheritance if i.sub == role]
        return declared or [SOC]

    def ancestors(self, role: str) -> set[str]:
        """The role and every role it specializes, transitively (always includes ``soc``)."""
        seen, todo = set(), [role]
        while todo:
            current = todo.pop()
            if current not in seen:
                seen.add(current)
                todo.extend(self.parents(current))
        return seen

    def subgroups(self, group: str) -> set[str]:
        """The group and all its sub-groups, transitively."""
        seen, todo = set(), [group]
        while todo:
            current = todo.pop()
            if current not in seen:
                seen.add(current)
                todo.extend(c.member for c in self.compositions if c.group == current and c.member in self.groups)
        return seen

    def norms_of(self, role: str) -> list[tuple[Norm, bool]]:
        """Norms that apply to ``role``, each with ``True`` when it is inherited (paper eqs. 8-9).

        A role receives the permissions and obligations of every role it specializes.
        """
        ancestors = self.ancestors(role)
        return [(n, n.role != role) for n in self.norms if n.role in ancestors]

    def missions_of_goal(self, goal: str) -> list[str]:
        return [m.id for m in self.missions.values() if goal in m.goals]
