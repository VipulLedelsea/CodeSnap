from core.model import ProgramStore
from core.report import quality
from core import deepdive
from core.model.ingest import artifact_type_for


def test_content_comparison_preserves_quoted_spaces_and_order(tmp_path):
    source = tmp_path/'original.rexx';source.write_text("route_1:\n  say 'A  B'\nroute_2:\n  return 0\n")
    with ProgramStore.create('Benchmark', root=tmp_path/'programs') as s:
        s.add_artifact('routes.rexx', transcription="route_1:\n say 'A B'\nroute_2:\n return 0")
        result = quality.measure(s, {'routes.rexx': source})
        row = result['files'][0]
        assert row['matched'] == 3 and row['expected'] == 4
        assert row['differences'][0]['kind'] == 'replace'
        assert 'original-file content differs' in ' '.join(quality.summary(s)['blockers'])


def test_removed_and_superseded_source_cannot_contribute_to_benchmark(tmp_path):
    source = tmp_path/'original.cbl';source.write_text('A\nB\n')
    with ProgramStore.create('Benchmark', root=tmp_path/'programs') as s:
        s.add_artifact('source.cbl', transcription='A\nB')
        quality.measure(s, {'source.cbl': source})
        s.add_artifact('source.cbl', transcription='A\nC')
        b = quality.current_benchmark(s)
        assert b['files'] == [] and b['stale'] == ['source.cbl']
        s.delete_artifact(s.current_artifact('source.cbl')['id'])
        b = quality.current_benchmark(s)
        assert not b['files'] and not b['stale']
        assert 'source.cbl' not in str(quality.blocks(s))


def test_review_is_bound_to_current_text_even_without_new_version(tmp_path):
    with ProgramStore.create('Review', root=tmp_path/'programs') as s:
        aid = s.add_artifact('source.rexx', transcription='return 0')
        s.set_meta('deepdive', {str(aid): {'hash': deepdive._hash('return 0'), 'facts': []}})
        assert str(aid) in deepdive.current_reviews(s)
        s._db.execute('UPDATE artifact SET transcription=? WHERE id=?', ('return 1',aid));s._db.commit()
        assert not deepdive.current_reviews(s)


def test_bms_source_is_not_classified_as_rendered_screen():
    assert artifact_type_for({'extension': '.bms', 'artifact_type': 'ui_screen'}, True) == 'code'
    assert artifact_type_for({'artifact_type': 'ui_screen'}, False) == 'ui_screen'


def test_layout_acceptance_must_describe_the_current_source(tmp_path):
    original = tmp_path/'map.bms'
    original.write_text('MAP      DFHMSD TYPE=MAP\nA        DFHMDI SIZE=(24,80)\nF        DFHMDF POS=(1,1),LENGTH=1\n')
    text = original.read_text().replace('MAP      ', 'MAP       ')
    with ProgramStore.create('Layout', root=tmp_path/'programs') as s:
        aid = s.add_artifact('map.bms', language='CICS BMS map', transcription=text)
        s.set_status(aid,'structured')
        quality.measure(s, {'map.bms': original})
        assert any('column layout' in b for b in quality.summary(s)['blockers'])
        s.set_meta('source_layout_validation', {'map.bms': {'confirmed': True, 'transcription_sha256': quality.source_hash(text)}})
        assert not any('column layout' in b for b in quality.summary(s)['blockers'])
        s.set_meta('source_layout_validation', {'map.bms': {'confirmed': True, 'transcription_sha256': 'stale'}})
        assert any('column layout' in b for b in quality.summary(s)['blockers'])
