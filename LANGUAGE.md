# MOISE Diagram — langage textuel et compilateur

MOISE Diagram est un DSL de dessin inspiré de PlantUML. Un fichier UTF-8 `.moise` décrit les éléments organisationnels et leurs relations ; le compilateur les valide et produit un diagramme par placement automatique Graphviz. Il ne dépend pas des environnements MARL et ne lance aucun entraînement.

## Première compilation

Depuis le dossier du package :

```bash
python -m moise_diagram examples/gouter.moise -o examples/gouter.svg
```

Les extensions disponibles sont `.svg`, `.png`, `.pdf` et `.dot`. Le format DOT est le code intermédiaire éditable. Le rendu nécessite l'exécutable `dot` de Graphviz, déjà disponible sur cette machine. Après installation du paquet autonome `packages/moise-diagram`, l'entrée `moise-diagram` fournit la même commande.

```text
@moise "Organisation du goûter"
group gouter "Groupe goûter"
role preparateur "Préparateur"
role serveur "Serveur"
contains gouter preparateur 1..1
contains gouter serveur 1..2
link com preparateur serveur intra

goal pret "Goûter prêt"
goal biscuits "Biscuits disposés"
goal verres "Verres disposés"
plan pret parallel biscuits verres
mission m_biscuits "Mission biscuits"
mission m_verres "Mission verres"
goals m_biscuits biscuits
goals m_verres verres
per preparateur m_biscuits Any
obl serveur m_verres Any
@end
```

## Grammaire

Une instruction par ligne. Les commentaires commencent par `#`, hors des chaînes. Les labels entre guillemets peuvent contenir des espaces et des accents. Les identifiants sont uniques, de la forme `[A-Za-z_][A-Za-z_0-9]*` ; le préfixe `__` est réservé. Les références peuvent précéder les déclarations.

| Instruction | Signification |
| --- | --- |
| `@moise ["titre"]` … `@end` | Délimitation du document |
| `group id ["label"]` | Groupe |
| `role id ["label"] [abstract]` | Rôle, éventuellement abstrait |
| `goal id ["label"]` | Objectif |
| `mission id ["label"]` | Mission |
| `agent id ["label"]` | Agent de l'entité organisationnelle |
| `contains groupe rôle_ou_groupe min..max` | Composition, maximum numérique ou `*` |
| `inherits enfant parent` | Héritage entre rôles |
| `link acq\|com\|aut\|compat source cible intra\|inter` | Relation entre rôles et portée |
| `plan objectif sequence\|choice\|parallel enfant1 enfant2 ...` | Décomposition en au moins deux sous-objectifs |
| `goals mission objectif1 objectif2 ...` | Objectifs composant la mission |
| `per rôle mission condition` | Permission |
| `obl rôle mission condition` | Obligation, qui implique une permission |
| `plays agent rôle groupe` | Adoption d'un rôle dans un groupe |
| `commits agent mission` | Engagement de mission |

`Any` est la condition temporelle toujours applicable. Une autre condition est un label opaque, éventuellement entre guillemets : le compilateur ne l'évalue pas.

## Conventions visuelles

Les groupes sont des rectangles, les rôles des ellipses, les rôles abstraits sont en italique. La composition porte un losange ouvert du côté du groupe, avec la cardinalité. L'héritage pointe vers le parent par un triangle ouvert.

Les objectifs sont des ellipses. Les opérateurs sont `,` pour la séquence, `|` pour le choix et `∥` pour le parallèle. Les positions d'une séquence sont numérotées pour conserver son ordre, indépendamment du placement graphique. Les missions sont annotées et reliées à leurs objectifs.

Les liens entre rôles portent explicitement leur type et leur portée. Les permissions et obligations sont orange ; les engagements sont turquoise et les adoptions de rôle violettes. Ces couleurs, les panneaux de dimensions, les traits mission–objectif et les surcouches agent–rôle/mission sont des conventions de ce DSL, pas des symboles officiels supplémentaires de MOISE+. Le rendu reprend les conventions principales de l'article SBIA 2002, sans prétendre reproduire chaque style de trait historique.

## Validation et limites

Le compilateur refuse les instructions mal formées, les doublons d'identifiants, les références absentes ou du mauvais type, les cardinalités inversées, les plans dupliqués et les cycles de composition, héritage ou décomposition. Les erreurs indiquent la ligne concernée quand elle est identifiable.

Il s'agit d'un compilateur de schémas, pas d'un moteur d'exécution ou d'un vérificateur complet MOISE+. Il ne vérifie pas l'effectif des groupes, l'autorisation effective de chaque engagement, les compatibilités, la satisfaisabilité des obligations ni l'atteinte des objectifs. L'implication obligation–permission et les implications entre types de liens ne sont pas matérialisées par ajout de nouvelles arêtes. Les schémas sociaux sont représentés par leurs arbres d'objectifs et missions ; leurs instances multiples et leurs autres attributs ne sont pas encore décrits.

Pour montrer une évolution temporelle, conserver la spécification et compiler plusieurs fichiers avec des instructions `plays` ou `commits` différentes. Le compilateur ne fabrique pas ces engagements à partir des résultats du simulateur.

## Tests

```bash
python -m pytest tests/test_compiler.py -q
```

Les tests couvrent les erreurs sémantiques et les rendus SVG/PDF réels, lorsque Graphviz est installé. Les exemples livrés sont des schémas explicatifs, sans résultats expérimentaux.
