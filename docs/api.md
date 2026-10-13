# Python API and command-line reference

The public API is importable from the top-level package:

```python
from moise_diagram import parse, to_dot, compile_file, OrganizationDiagram, DiagramError, VIEWS
```

The model classes live in `moise_diagram.model`. The language itself is documented in [LANGUAGE.md](../LANGUAGE.md).

## Functions

### `parse(source: str) -> OrganizationDiagram`

Parses the text of a `.moise` document and validates it against the MOISE+ rules.

- **source**: the full document, including the `@moise` and `@end` lines.
- **Returns**: an [`OrganizationDiagram`](#organizationdiagram).
- **Raises**: [`DiagramError`](#diagramerror) on the first problem. The full list of messages is in [LANGUAGE.md](../LANGUAGE.md#validation-rules-and-error-messages).

```python
from moise_diagram import parse, DiagramError

try:
    model = parse(open("org.moise", encoding="utf-8").read())
except DiagramError as error:
    print(f"Invalid organization: {error}")   # e.g. "line 12: x cannot commit to m1: none of its roles ..."
```

### `to_dot(model, views=VIEWS, key=False, ds_style="list", ds_inherited=False, ds_links=False) -> str`

Converts a validated model into Graphviz DOT source, drawn with the paper's notation.

- **views**: the specifications to draw, any of `"ss"` (structural), `"fs"` (functional), `"ds"` (deontic) and `"oe"` (organizational entity). A view with no content is skipped. An unknown view raises `DiagramError`.
- **key**: add the legends: those of Fig. 2 for `ss` and Fig. 3 for `fs`, plus one for the deontic edges when the DS is drawn as a graph or with `ds_links`.
- **ds_style**: draw the DS as a predicate `"list"` (as in the paper), a role → mission `"graph"`, or a roles × missions `"matrix"`. The accepted values are in `moise_diagram.DS_STYLES`; any other value raises `DiagramError`.
- **ds_inherited**: also show the norms that roles inherit from the roles they specialize (paper eqs. 8–9), in grey.
- **ds_links**: draw each norm as an edge from its role in the structural view to its mission in the functional view. This only takes effect when both `ss` and `fs` are drawn.

See [LANGUAGE.md](../LANGUAGE.md#deontic-specification) for pictures of each rendering.

```python
import subprocess
from moise_diagram import parse, to_dot

dot = to_dot(parse(source), views=["ds"], ds_style="matrix", ds_inherited=True)
png = subprocess.run(["dot", "-Tpng", "-Gdpi=200"], input=dot.encode(), capture_output=True, check=True).stdout
```

Plain `dot`, as above, renders everything except what the routing step adds: bus lines, wavy lines, placed cardinalities and the `ds_links` curves. In particular, the `ds_links` edges are emitted as `// mx_deferred` comments that only [`render`](#renderdot-format---bytes) draws. Pass only models returned by `parse`: `to_dot` does not validate its input.

### `compile_file(source, output, views=VIEWS, key=False, *, ds_style="list", ds_inherited=False, ds_links=False) -> None`

Reads a UTF-8 `.moise` file, validates it, and writes the result to `output`. Both paths may be strings or `os.PathLike` objects. The other arguments are passed to `to_dot`. The format is chosen from the output suffix (case-insensitive):

| Suffix | Output | Requires Graphviz |
| --- | --- | --- |
| `.dot` | DOT source text produced by `to_dot` (UTF-8) | No |
| `.svg` | SVG image | Yes |
| `.png` | PNG image | Yes |
| `.pdf` | PDF document | Yes |

The image formats go through [`render`](#renderdot-format---bytes). Missing parent directories are created.

**Raises**:

- `DiagramError` if the source is invalid, an option is invalid, the suffix is not supported, the `dot` or `neato` executable is not on `PATH`, or Graphviz fails (the message is then Graphviz's stderr).
- `OSError` if the source cannot be read or the output cannot be written.

### `render(dot, format) -> bytes`

Defined in `moise_diagram.compiler`. It draws DOT source produced by `to_dot` in any Graphviz output format (`"svg"`, `"png"`, `"pdf"`, …):

1. `dot -Tdot` computes the layout. The `// mx_deferred` edges (from `ds_links`) are left out, so they take up no space in it.
2. `moise_diagram.route.route` redraws the inheritance bus lines, the wavy inter-group lines, the straight plan lines and the cardinality positions. It also adds the deferred edges as S-curves.
3. `neato -n2` renders the positioned graph.

```python
from moise_diagram import parse, to_dot
from moise_diagram.compiler import render

svg = render(to_dot(parse(source), views=["ss", "fs"], ds_links=True), "svg")
```

## The model

`parse` returns an `OrganizationDiagram`. Its dictionaries keep declaration order, and its lists keep source order. Every element records the `line` it comes from.

### `OrganizationDiagram`

| Attribute | Type | Paper concept |
| --- | --- | --- |
| `title` | `str` | Title from `@moise "…"`, or `"MOISE+"` |
| `roles` | `dict[str, Role]` | R<sub>ss</sub>, always including the predefined `soc` |
| `inheritance` | `list[Inheritance]` | ⊏ (explicit statements only) |
| `groups` | `dict[str, Group]` | Group specifications |
| `compositions` | `list[Composition]` | R, SG, np and ng of each group specification |
| `links` | `list[Link]` | L<sup>intra</sup>, L<sup>inter</sup> |
| `compatibilities` | `list[Compatibility]` | C<sup>intra</sup>, C<sup>inter</sup> |
| `schemes` | `dict[str, Scheme]` | Social schemes |
| `goals` | `dict[str, Goal]` | Goals, including anonymous ones created by nested plans |
| `plans` | `dict[str, Plan]` | P, indexed by the decomposed goal |
| `missions` | `dict[str, Mission]` | M, mo and nm |
| `preferences` | `list[Preference]` | ≺ |
| `norms` | `list[Norm]` | per and obl |
| `agents` | `dict[str, Agent]` | Agents of the OE |
| `plays`, `commits` | `list[Plays]`, `list[Commits]` | Role adoptions and mission commitments |

The model also has methods that apply the paper's rules:

| Method | Returns |
| --- | --- |
| `parents(role)` | Direct super-roles; `["soc"]` when none is declared, and `[]` for `soc` |
| `ancestors(role)` | The role and every role it specializes, transitively |
| `subgroups(group)` | The group and all its sub-groups, transitively |
| `missions_of_goal(goal)` | Identifiers of the missions that contain the goal |
| `norms_of(role)` | The norms that apply to the role, as `(Norm, inherited)` pairs: its own norms, and those of the roles it specializes (eqs. 8–9) with `inherited=True` |

### Element classes

The element classes are defined in `moise_diagram.model`. Every class also has a `line: int` field.

| Class | Fields |
| --- | --- |
| `Role` | `id`, `label: str \| None`, `abstract: bool`; `text` property (label, or the id when there is no label) |
| `Group` | `id`, `label`; `text` property |
| `Inheritance` | `sub`, `parent` |
| `Composition` | `group`, `member`, `cardinality: Cardinality`, `subgroups: bool` |
| `Link` | `group`, `source`, `target`, `type` (`acq`/`com`/`aut`), `scope` (`intra`/`inter`) |
| `Compatibility` | `group`, `role_a`, `role_b`, `scope` |
| `Scheme` | `id`, `root`, `label`, `goals: list[str]` (breadth-first from the root), `missions: list[str]` |
| `Goal` | `id`, `label`, `anonymous: bool` (anonymous goals are named `__goal1`, `__goal2`, …) |
| `Plan` | `goal`, `operator` (`sequence`/`choice`/`parallel`), `children: list[str]`, `rate: float \| None` |
| `Mission` | `id`, `label`, `cardinality`, `goals: list[str]`, `scheme: str` |
| `Preference` | `better`, `worse` |
| `Norm` | `kind` (`per`/`obl`), `role`, `mission`, `time_constraint` |
| `Agent` | `id`, `label`; `text` property |
| `Plays` | `agent`, `role`, `group` |
| `Commits` | `agent`, `mission` |
| `Cardinality` | `min: int`, `max: int \| None` (`None` means unbounded); `str()` gives `"1..*"` |

Example: list the missions each role may take, including inherited norms.

```python
model = parse(source)
for role in model.roles.values():
    allowed = {norm.mission for norm, inherited in model.norms_of(role.id)}
    print(role.text, sorted(allowed))
```

The function `moise_diagram.parser.compatible(model, first_plays, second_plays)` exposes the compatibility rule used to check the OE.

### `DiagramError`

A subclass of `ValueError`, raised for every problem with the input. Messages start with `line N:` whenever the problem can be traced to a line, which is every case except a missing `@end`.

## Command line

The package installs a `moise-diagram` console script. `python -m moise_diagram` is equivalent.

```text
usage: moise-diagram [-h] -o OUTPUT [--view {ss,fs,ds,oe}] [--key]
                     [--ds-style {list,graph,matrix}] [--ds-inherited] [--ds-links]
                     source

positional arguments:
  source                input .moise file (UTF-8)

options:
  -o OUTPUT, --output OUTPUT
                        output file; its suffix (.dot, .svg, .png or .pdf) selects the format
  --view {ss,fs,ds,oe}  specification to draw: ss (structural), fs (functional), ds (deontic) or
                        oe (organizational entity); repeat to draw several (default: all)
  --key                 add the legends of the drawn views
  --ds-style {list,graph,matrix}
                        deontic view: list of per/obl predicates as in the paper (default),
                        role-mission graph, or roles x missions matrix
  --ds-inherited        also show the norms that roles inherit from the roles they specialize
  --ds-links            draw the norms as edges from the roles of the structural view to the
                        missions of the functional view (requires both views)
```

| Exit status | Meaning |
| --- | --- |
| `0` | Success |
| `2` | Invalid arguments, invalid source, unsupported format, missing Graphviz, Graphviz failure or I/O error. The error is printed to stderr as `SOURCE: message` |

`main(argv=None)` in `moise_diagram.compiler` runs the same command from Python.

Because the exit status is non-zero on any error, the command works in `make`, CI pipelines and pre-commit hooks:

```make
diagrams/%-structure.svg: specs/%.moise
	moise-diagram $< -o $@ --view ss --key
```
