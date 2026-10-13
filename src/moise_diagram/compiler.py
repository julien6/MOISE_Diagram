"""Compile MOISE+ organizational specifications written in the MOISE diagram language to diagrams."""
from __future__ import annotations
import argparse
from os import PathLike
from pathlib import Path
import shutil
import subprocess

from .dot import VIEWS, to_dot
from .model import DiagramError
from .parser import parse
from .route import route

FORMATS = ('dot', 'svg', 'png', 'pdf')


def compile_file(source: str | PathLike, output: str | PathLike, views=VIEWS, key: bool = False) -> None:
    """Compile a UTF-8 ``.moise`` file to ``.dot``, ``.svg``, ``.png`` or ``.pdf``.

    The format is taken from the output suffix. ``.dot`` writes the DOT source produced by :func:`to_dot`;
    the other formats require Graphviz (``dot`` and ``neato`` on PATH) and are drawn by :func:`render`.
    """
    source, output = Path(source), Path(output)
    dot = to_dot(parse(source.read_text(encoding='utf-8')), views, key)
    format = output.suffix.lstrip('.').lower()
    if format not in FORMATS:
        raise DiagramError('output must end in .dot, .svg, .png or .pdf')
    if format == 'dot':
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dot, encoding='utf-8')
        return
    image = render(dot, format)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)


def render(dot: str, format: str) -> bytes:
    """Lay out DOT source with ``dot``, redraw the paper's line styles (see :mod:`moise_diagram.route`),
    and draw the result with ``neato -n2`` in ``format`` (``svg``, ``png``, ``pdf`` or any Graphviz format)."""
    laid_out = _graphviz('dot', ['-Tdot'], dot.encode('utf-8')).decode('utf-8')
    return _graphviz('neato', ['-n2', f'-T{format}'], route(laid_out).encode('utf-8'))


def _graphviz(program: str, options: list[str], data: bytes) -> bytes:
    executable = shutil.which(program)
    if not executable:
        raise DiagramError(f'Graphviz executable {program} is required to render diagrams')
    result = subprocess.run([executable, *options], input=data, capture_output=True, check=False)
    if result.returncode:
        raise DiagramError(result.stderr.decode('utf-8', errors='replace'))
    return result.stdout


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point: ``moise-diagram SOURCE -o OUTPUT [--view VIEW ...] [--key]``."""
    parser = argparse.ArgumentParser(prog='moise-diagram', description=__doc__)
    parser.add_argument('source', type=Path, help='input .moise file (UTF-8)')
    parser.add_argument('-o', '--output', required=True, type=Path,
                        help='output file; its suffix (.dot, .svg, .png or .pdf) selects the format')
    parser.add_argument('--view', action='append', choices=VIEWS,
                        help='specification to draw: ss (structural), fs (functional), ds (deontic) or '
                             'oe (organizational entity); repeat to draw several (default: all)')
    parser.add_argument('--key', action='store_true', help='add the legend of the paper\'s figures')
    args = parser.parse_args(argv)
    try:
        compile_file(args.source, args.output, args.view or VIEWS, args.key)
    except (DiagramError, OSError) as exc:
        parser.exit(2, f'{args.source}: {exc}\n')


if __name__ == '__main__':
    main()
