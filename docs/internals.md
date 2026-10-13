# Compiler internals

This guide is for contributors who want to understand or extend the compiler.

## Repository layout

```text
.
├── src/moise_diagram/
│   ├── __init__.py        # public API re-exports and __version__
│   ├── __main__.py        # `python -m moise_diagram`
│   ├── model.py           # dataclasses mirroring the MOISE+ tuples, DiagramError
│   ├── parser.py          # tokenizer, parser and every semantic check
│   ├── dot.py             # Graphviz rendering in the paper's notation, keys
│   ├── route.py           # post-layout geometry: bus lines, wavy lines, straight plans, labels
│   └── compiler.py        # compile_file(), render() and the command line
├── tests/test_compiler.py # pytest suite
├── examples/
│   ├── soccer.moise       # transcription of the paper's soccer team
│   └── snack.moise        # small example using all four views
├── docs/                  # API reference, this guide, rendered images
├── LANGUAGE.md            # language reference
└── pyproject.toml         # packaging (setuptools), console script, pytest config
```

## Pipeline

```text
 .moise ──parse()──▶ OrganizationDiagram ──to_dot()──▶ DOT ──dot -Tdot──▶ laid-out DOT ──route()──▶ routed DOT ──neato -n2──▶ SVG / PNG / PDF
```

`parse` runs these steps, implemented in `parser._Parser`:

1. **`read`.** Tokenizes each line and handles `@moise` and `@end`.
2. **`declare`.** Runs on every declaration (`role`, `group`, `goal`, `mission`, `agent`, `scheme`) before any other statement, so references may precede declarations.
3. **`statement` / `plan`.** Check each relation statement and fill the model.
4. **`check_structure`.** Rejects cycles in inheritance, group composition and mission preference.
5. **`check_schemes`.** Rejects cycles in goal decomposition, then assigns goals and missions to social schemes.
6. **`check_entity`.** Checks role adoptions, compatibilities and commitments.

### Tokenizer

`tokenize` uses a single regular expression and produces `Token(text, quoted, op)` values:

- double- or single-quoted strings, with `\"` escapes inside double quotes;
- the plan punctuation `( ) , | || ∥ =`;
- words;
- `#` comments, which end the line.

The `quoted` flag is what lets a label read `"abstract"` without making the role abstract. Statements other than `plan` reject punctuation tokens.

### Plans

`_Parser.expression` and `_Parser.term` form a small recursive-descent parser:

```text
expression := term (op term)*      all ops on one level must be the same
term       := goal_id | "(" expression ")"
```

The result is a nested tuple `(operator, [terms])`. `add_plan` turns it into `Plan` objects, creating an anonymous goal (`__goal1`, `__goal2`, …) for each nested level. While doing so it enforces the tree property: one plan per goal, and one parent per goal.

### Semantic rules

The rules taken from the paper are implemented in two places:

- **`OrganizationDiagram.parents` and `ancestors`** (`model.py`) make `soc` the implicit parent of every role without a declared parent, and compute inheritance closures.
- **`compatible`** (`parser.py`) decides whether one agent may hold two role adoptions:
  - it picks the scope: `intra` when the groups are equal or nested, `inter` otherwise;
  - it keeps the compatibilities declared in a group that covers the two adoptions;
  - it searches for a path ρa → … → ρb in either direction. A compatibility `x ⋈ y` lets `a` reach `b` whenever x is an ancestor of a and y an ancestor of b, which implements inheritance on both sides.

`_check_acyclic` is an iterative depth-first search. Deep hierarchies therefore cannot hit Python's recursion limit, and errors point to the line of the edge that closes the cycle.

### Rendering

`dot.to_dot` writes one cluster per view (`cluster_ss`, `cluster_fs` with one sub-cluster per scheme, `cluster_ds`, `cluster_oe`), followed by the optional keys.

- **Identifiers** are always quoted with `json.dumps`, so names such as `node` or `graph` are safe.
- **Labels** in HTML-like labels are escaped by `_h`.
- **SS.**
  - Roles use `shape=box, style=rounded` and groups `shape=tab`.
  - Inheritance edges go parent → child with `dir=back, arrowtail=onormal` and `weight=4`, which keeps `soc` at the top and sub-roles close to their parents.
  - Compositions go member → group with `odiamond` (`odiamonddot` for the sub-groups scope), which places groups at the bottom as in Fig. 2.
  - Links and compatibilities use `constraint=false`, so they do not affect the layout.
- **FS.**
  - Each goal is a borderless HTML table: the identifier on the left, missions above right, the success degree below right, and an optional row of one or two 1-pixel bars, exposed as port `op`. Edges leave from `goal:op` for choice and parallelism.
  - Schemes set `ordering=out` so that sequences keep their order.
  - The goal and mission tables hang below the deepest goal through an invisible edge, so they do not distort the tree.
- **Keys.** Keys are clusters of captions and sample edges between invisible fixed-size anchors (`tailclip=false, headclip=false` sets the length of the sample lines). They hang below the diagram through an invisible edge, so their rows do not share ranks with it.

The global graph uses `splines=polyline`, so the edges that are not redrawn afterwards keep a straight-segment look while still avoiding nodes.

### Rendering pipeline

Graphviz cannot draw three features of Fig. 2 and Fig. 3: wavy lines, inheritance lines that share a bus, and plan lines that meet at the center of the operator bars. Its `taillabel` placement also lets cardinalities overlap. `compiler.render` therefore runs three steps:

1. **`dot -Tdot`** computes the layout. The result is the same graph with `pos`, `width` and `height` on every node and a Bézier `pos` on every edge (`s,x,y` and `e,x,y` give the arrowhead tips).
2. **`route.route`** reads that output with a small tokenizer (quoted strings, nested HTML labels, punctuation) and rewrites the attribute lists of the edges that `to_dot` marked through their `id`:
   - `mx_bus_*` (inheritance): for each parent, a trunk starts under the parent's single arrowhead, a horizontal bar sits halfway to its highest sub-role, and a vertical segment drops to each sub-role. Bars of different parents that would coincide are shifted by 6 pt. If there is no room between the ranks, the original curve is kept.
   - `mx_wave_*` (inter-group links and compatibilities): the curve is sampled, then offset along its normal by `3 · sin(2πk·s/L)`. The number of periods `k` is one per 90 pt of length, and the amplitude is reduced on very short edges. The wave vanishes at both ends, so endpoints and arrowheads are unchanged. Catmull-Rom interpolation turns the samples back into Bézier control points.
   - `mx_line_*` (plans): each line is a straight segment from the horizontal center of the parent, at the height where Graphviz attached it to the bars' port, to the top center of the subgoal.
   - `mx_card_*` (compositions): candidate positions run along the line from the member end (6 to 70 pt), on both sides and at three distances, plus spots beside the member's lower corners. Each candidate is scored by its overlap with nodes and already placed labels, the number of points of other lines within 3 pt, any crossing of its own line, and whether another line is closer than its own. The best candidate becomes the edge's `tail_lp`.
3. **`neato -n2`** renders the graph using the given positions unchanged, clusters and HTML labels included.

All coordinates are in points, with the y axis pointing up as in Graphviz output.

## Extending the language

To add a statement, for example a mission description attribute:

1. **Model.** Add the field or dataclass in `model.py` and, if needed, a collection on `OrganizationDiagram`.
2. **Parse.** Add a branch to `_Parser.statement` matched on the keyword *and* the word count. Use `self.ref(name, 'kind|kind', line)` for references and `self.fail(line, message)` for errors.
3. **Check.** Put global rules in one of the `check_*` methods. Use `_check_acyclic` for relations that must be acyclic.
4. **Render.** Draw it in the matching view function of `dot.py`, and in the key if it has a graphical symbol.
5. **Test.** Add accepting and rejecting cases to `tests/test_compiler.py`. The parametrized lists `test_reject_bad_statements`, `test_reject_inconsistent_specifications` and `test_reject_organizational_entity` are the easiest place.
6. **Document.** Update [LANGUAGE.md](../LANGUAGE.md): the mapping table, the statement summary, the section on the statement, the graphical notation and the error table.

## Tests

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

The suite checks:

- the soccer example against the paper (model and rendering);
- defaults, tokenization and nested plans;
- every syntax error, every inconsistency (cycles, scheme membership, missions), and every check on the organizational entity, both accepting and rejecting cases;
- quoting of DOT keywords, view selection and keys;
- the routing, on two different layouts of the soccer example (all views, and the structure alone): inheritance lines are orthogonal and share one bar, inter-group lines are wavy and keep their endpoints, plan lines are straight, and no cardinality overlaps another cardinality or any other line;
- the command line;
- real SVG and PDF rendering of both examples, which is skipped when Graphviz is not installed.

## Known issues

- **Routing after layout.** Graphviz positions the nodes before the bus lines are drawn. A vertical drop to a sub-role several ranks below its parent can therefore cross intermediate nodes. The placement of cardinalities minimizes conflicts but cannot create space where there is none: on very dense diagrams, increase `nodesep` or `ranksep` in the DOT output.
- **Layout.** Element placement is automatic and may differ from the paper's hand-drawn figures. To fine-tune it, compile to `.dot` and edit the result.
