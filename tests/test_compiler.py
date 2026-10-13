from pathlib import Path
import shutil
import pytest
from moise_diagram import DiagramError, parse, to_dot, compile_file

SOURCE = Path(__file__).resolve().parents[1] / 'examples/gouter.moise'

def test_example_and_semantic_edges():
    model = parse(SOURCE.read_text())
    dot = to_dot(model)
    assert len(model.nodes) == 10
    assert 'arrowtail=odiamond' in dot
    assert 'label="∥"' in dot
    assert 'obl / Any' in dot
    assert 'engagement' in dot

@pytest.mark.parametrize('statement', [
    'contains g r 2..1', 'per missing m Any', 'commits r m',
    'plan a parallel b missing', 'link aut r r nowhere',
    'plan a sequence b b', 'nonsense r',
])
def test_reject_bad_statements(statement):
    source = '@moise\ngroup g\nrole r\nmission m\ngoal a\ngoal b\n'+statement+'\n@end'
    with pytest.raises(DiagramError, match='line'):
        parse(source)

def test_reject_cycles():
    with pytest.raises(DiagramError, match='cycle'):
        parse('@moise\ngroup a\ngroup b\ncontains a b 1..1\ncontains b a 1..1\n@end')

def test_safe_labels_and_abstract():
    dot = to_dot(parse('@moise\nrole r "<x&y>" abstract\n@end'))
    assert '&lt;x&amp;y&gt;' in dot

@pytest.mark.skipif(not shutil.which('dot'), reason='Graphviz is not installed')
def test_actual_svg_and_pdf(tmp_path):
    for suffix, magic in [('svg',b'<?xml'),('pdf',b'%PDF')]:
        output=tmp_path/f'result.{suffix}'
        compile_file(SOURCE,output)
        assert output.read_bytes().startswith(magic)
