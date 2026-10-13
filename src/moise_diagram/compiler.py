"""MOISE diagram DSL: validated notation compiler, not a normative execution engine."""
from __future__ import annotations
import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess

class DiagramError(ValueError):
    """Invalid source with a line-number diagnostic."""

@dataclass
class OrganizationDiagram:
    title: str = 'MOISE+'
    nodes: dict[str, tuple[str, str, bool]] = field(default_factory=dict)
    statements: list[tuple[int, list[str]]] = field(default_factory=list)


def parse(source: str) -> OrganizationDiagram:
    model = OrganizationDiagram()
    opened = closed = False
    for number, line in enumerate(source.splitlines(), 1):
        try:
            words = shlex.split(line, comments=True)
        except ValueError as exc:
            raise DiagramError(f'line {number}: {exc}') from exc
        if not words:
            continue
        def fail(message: str) -> None:
            raise DiagramError(f'line {number}: {message}')
        if words[0] == '@moise':
            if opened or len(words) > 2:
                fail('expected a single @moise ["title"]')
            opened = True
            if len(words) == 2:
                model.title = words[1]
            continue
        if not opened or closed:
            fail('statement outside @moise ... @end')
        if words == ['@end']:
            closed = True
            continue
        if words[0] in ('role', 'group', 'goal', 'mission', 'agent'):
            if len(words) not in (2, 3, 4):
                fail('expected KIND id ["label"] [abstract]')
            kind, name = words[:2]
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name):
                fail('identifier must match [A-Za-z_][A-Za-z_0-9]*')
            if name.startswith('__'):
                fail('identifiers beginning with __ are reserved')
            if name in model.nodes:
                fail(f'duplicate identifier {name}')
            abstract = words[-1] == 'abstract'
            if abstract and kind != 'role':
                fail('only a role can be abstract')
            if len(words) == 4 and not abstract:
                fail('unexpected node attribute')
            label = words[2] if len(words) >= 3 and words[2] != 'abstract' else name
            model.nodes[name] = (kind, label, abstract)
        else:
            model.statements.append((number, words))
    if not opened or not closed:
        raise DiagramError('expected @moise ... @end')
    def ref(name: str, kind: str, line: int) -> None:
        if name not in model.nodes or model.nodes[name][0] not in kind.split('|'):
            raise DiagramError(f'line {line}: {name} must reference {kind}')
    hierarchy: dict[str, list[str]] = {}
    planned: set[str] = set()
    for line, w in model.statements:
        command = w[0]
        def fail(message: str) -> None:
            raise DiagramError(f'line {line}: {message}')
        if command == 'contains' and len(w) == 4:
            ref(w[1], 'group', line); ref(w[2], 'group|role', line)
            if not re.fullmatch(r'\d+\.\.(\d+|\*)', w[3]):
                fail('expected cardinality min..max or min..*')
            lo, hi = w[3].split('..')
            if hi != '*' and int(lo) > int(hi):
                fail('cardinality minimum exceeds maximum')
            hierarchy.setdefault(w[1], []).append(w[2])
        elif command == 'inherits' and len(w) == 3:
            ref(w[1], 'role', line); ref(w[2], 'role', line)
            hierarchy.setdefault(w[1], []).append(w[2])
        elif command == 'link' and len(w) == 5:
            ref(w[2], 'role', line); ref(w[3], 'role', line)
            if w[1] not in ('acq', 'com', 'aut', 'compat') or w[4] not in ('intra', 'inter'):
                fail('expected link acq|com|aut|compat source target intra|inter')
        elif command == 'plan' and len(w) >= 5:
            ref(w[1], 'goal', line)
            if w[2] not in ('sequence', 'choice', 'parallel'):
                fail('unknown plan operator')
            if w[1] in planned or len(set(w[3:])) != len(w[3:]):
                fail('duplicate plan or child goal')
            planned.add(w[1])
            for child in w[3:]:
                ref(child, 'goal', line)
            hierarchy.setdefault(w[1], []).extend(w[3:])
        elif command == 'goals' and len(w) >= 3:
            ref(w[1], 'mission', line)
            for name in w[2:]:
                ref(name, 'goal', line)
        elif command in ('per', 'obl') and len(w) == 4:
            ref(w[1], 'role', line); ref(w[2], 'mission', line)
        elif command == 'plays' and len(w) == 4:
            ref(w[1], 'agent', line); ref(w[2], 'role', line); ref(w[3], 'group', line)
        elif command == 'commits' and len(w) == 3:
            ref(w[1], 'agent', line); ref(w[2], 'mission', line)
        else:
            fail(f'unknown or malformed statement: {command}')
    visiting: set[str] = set()
    done: set[str] = set()
    def visit(name: str) -> None:
        if name in visiting:
            raise DiagramError(f'cycle involving {name}')
        if name in done:
            return
        visiting.add(name)
        for child in hierarchy.get(name, []):
            visit(child)
        visiting.remove(name); done.add(name)
    for name in model.nodes:
        visit(name)
    return model


def to_dot(model: OrganizationDiagram) -> str:
    q = lambda value: json.dumps(value, ensure_ascii=False)
    lines = ['digraph moise {', 'graph [rankdir=TB, bgcolor="white", fontname="DejaVu Sans", compound=true, nodesep=.5];',
             'node [fontname="DejaVu Sans", color="#244254", style=filled, fillcolor="white"];',
             'edge [fontname="DejaVu Sans", fontsize=10, color="#244254"];', f'label={q(model.title)}; labelloc=t;']
    dimensions = [('SS : structure', ('role', 'group')), ('FS : objectifs et missions', ('goal', 'mission')), ('OE : agents', ('agent',))]
    for i, (label, kinds) in enumerate(dimensions):
        lines += [f'subgraph cluster_{i} {{ label={q(label)}; color="#cedbe1";']
        for name, (kind, label, abstract) in model.nodes.items():
            if kind not in kinds:
                continue
            shape = {'role':'ellipse','group':'box','goal':'ellipse','mission':'plaintext','agent':'box'}[kind]
            if abstract:
                rendered = '<I>' + label.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;') + '</I>'
                attr = f'label=<{rendered}>'
            else:
                attr = f'label={q(label)}'
            lines.append(f'{name} [shape={shape}, {attr}];')
        lines.append('}')
    for index, (_, w) in enumerate(model.statements):
        c = w[0]
        if c == 'contains':
            lines.append(f'{w[1]} -> {w[2]} [dir=both, arrowtail=odiamond, arrowhead=none, headlabel={q(w[3])}];')
        elif c == 'inherits':
            lines.append(f'{w[1]} -> {w[2]} [arrowhead=empty];')
        elif c == 'link':
            lines.append(f'{w[2]} -> {w[3]} [label={q(w[1]+" / "+w[4])}, style={"dashed" if w[4]=="intra" else "solid"}];')
        elif c == 'plan':
            operator = {'sequence':',','choice':'|','parallel':'∥'}[w[2]]
            hub = f'__plan_{index}'
            lines += [f'{hub} [shape=plaintext, label={q(operator)}];', f'{w[1]} -> {hub} [arrowhead=none];']
            for pos, child in enumerate(w[3:],1):
                label = f', label="{pos}"' if w[2] == 'sequence' else ''
                lines.append(f'{hub} -> {child} [arrowhead=none{label}];')
        elif c == 'goals':
            for goal in w[2:]:
                lines.append(f'{w[1]} -> {goal} [style=dotted, arrowhead=none, label="objectif", color="#007a83"];')
        elif c in ('per','obl'):
            lines.append(f'{w[1]} -> {w[2]} [style=dashed, constraint=false, color="#ad6521", label={q(c+" / "+w[3])}];')
        elif c == 'plays':
            lines.append(f'{w[1]} -> {w[2]} [constraint=false, color="#7554a0", label={q("joue / "+w[3])}];')
        elif c == 'commits':
            lines.append(f'{w[1]} -> {w[2]} [constraint=false, color="#007a83", label="engagement"];')
    lines.append('}')
    return '\n'.join(lines)+'\n'


def compile_file(source: Path, output: Path) -> None:
    dot = to_dot(parse(source.read_text(encoding='utf-8')))
    format = output.suffix.lstrip('.').lower()
    if format not in ('dot','svg','png','pdf'):
        raise DiagramError('output must end in .dot, .svg, .png or .pdf')
    if format == 'dot':
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dot, encoding='utf-8')
        return
    executable = shutil.which('dot')
    if not executable:
        raise DiagramError('Graphviz executable dot is required to render diagrams')
    result = subprocess.run([executable, f'-T{format}'], input=dot.encode('utf-8'), capture_output=True, check=False)
    if result.returncode:
        raise DiagramError(result.stderr.decode('utf-8', errors='replace'))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('-o','--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        compile_file(args.source,args.output)
    except (DiagramError, OSError) as exc:
        parser.exit(2, f'{args.source}: {exc}\n')

if __name__ == '__main__':
    main()
