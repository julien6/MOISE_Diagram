# MOISE Diagram

Package Python autonome pour décrire et dessiner des organisations MOISE+ à partir d'un langage textuel inspiré de PlantUML. Aucune dépendance à CORA, JAX, MARL ou à une bibliothèque Python tierce à l'exécution. Graphviz (`dot`) est requis pour SVG, PNG et PDF ; la production DOT fonctionne sans Graphviz.

## Installation

Depuis un clone du dépôt :

```bash
python -m pip install .
```

Pour le développement : `python -m pip install -e '.[test]'`.
Le dossier peut être copié dans un autre dépôt et installé directement avec `python -m pip install .`.

## Python

```python
from pathlib import Path
from moise_diagram import parse, to_dot, compile_file

organization = parse('''@moise "Mon organisation"
group team "Équipe"
role executor "Exécutant"
contains team executor 1..*
@end''')
print(to_dot(organization))
compile_file(Path("organization.moise"), Path("organization.svg"))
```

API publique : `OrganizationDiagram`, `DiagramError`, `parse(source)`, `to_dot(model)` et `compile_file(source_path, output_path)`.

## CLI

```bash
moise-diagram examples/gouter.moise -o gouter.svg
python -m moise_diagram examples/gouter.moise -o gouter.pdf
```

## Tests et distribution

Depuis ce dossier :

```bash
python -m pytest tests -q
python -m pip wheel --no-deps . -w dist
```

Le compilateur valide les références, les types, les cardinalités et les cycles. Il génère une notation graphique ; il n'exécute pas les obligations, ne valide pas tous les engagements d'agents et ne constitue pas un moteur MOISE+ complet. Les surcouches agent–mission et les couleurs sont des extensions de visualisation.

La syntaxe complète est documentée dans `LANGUAGE.md`. La licence de distribution figure dans `LICENSE`.
