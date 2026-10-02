"""Offline column-one regression matrix for every supplied legacy language fixture."""
from pathlib import Path
import pytest
from PIL import Image
from render import render_code
from core import analysis,spacing
from core.langpacks.specs import PACKS
from test_langpacks import CASES,SPECIAL,LP

BASE=Path(__file__).parent/'samples'
MATRIX=[(case[1],LP/case[0]) for case in CASES+SPECIAL]
MATRIX += [(p.suffix.lstrip('.'),p) for group in ('cobol','legacy') for p in sorted((BASE/group).iterdir())
           if p.is_file() and p.suffix.lower() in {'.cbl','.cpy','.bms','.jcl','.java','.cpp','.cs','.sql','.jsp','.aspx','.sps'}]
IDS=[f'{kind}:{path.name}' for kind,path in MATRIX]


def test_matrix_covers_every_supported_language_pack():
    assert {pack['id'] for pack in PACKS} <= {kind for kind,_ in MATRIX}


@pytest.mark.parametrize('kind,path',MATRIX,ids=IDS)
def test_cleaning_preserves_observed_legacy_layout(kind,path):
    text=path.read_text()
    assert analysis.clean_source(text,analysis.source_mode([text])).splitlines()==text.strip('\n').splitlines()


@pytest.mark.parametrize('kind,path',MATRIX,ids=IDS)
def test_confirmed_columns_never_accept_a_shifted_legacy_row(kind,path,tmp_path):
    text='\n'.join(path.read_text().splitlines()[:24])
    png=render_code(text,tmp_path/'frame.png',font_size=16)
    with Image.open(png) as image: width=image.width
    profile=spacing.profile(png.read_bytes(),[0,0,1,1],28/width)
    bound=spacing.bind(png,profile)
    assert bound['confirmed']
    wrong='\n'.join('   '+line if line.strip() and '\t' not in line else line for line in text.split('\n'))
    fixed,meta,_=analysis.measured_frame(None,png,wrong)
    original=text.split('\n');actual=fixed.split('\n')
    assert len(original)==len(actual)
    measured=0
    for i,state in enumerate(meta['spacing']['line_status']):
        if state=='measured':
            measured+=1
            assert actual[i]==original[i],(i+1,original[i],actual[i])
    assert measured>=3,(kind,path.name,meta['spacing'])


@pytest.mark.parametrize('source',[
    '100 A = A + 1\n200 B = B + 1\n300 C = C + 1',
    '  100 CONTINUE\n  200 GO TO 300\n  300 STOP',
])
def test_midfile_source_labels_are_not_editor_gutters(source):
    assert analysis.clean_source(source,analysis.source_mode([source]))==source


@pytest.mark.parametrize('source,protected',[
    ('cat <<\'END\'\n# return value\n    |   data with spaces\nEND\necho done',{1,2,3}),
    ('DATA legacy;\nDATALINES;\n100   value  one\n200   value  two\n300   value  three\n;\nRUN;',{2,3,4,5}),
    ('      DATA LABEL / 5HA  B /\n      END',{0}),
    ("SELECT q'[A ' B  C]' FROM dual;",{0}),
    ('my $value = q{A  B};',{0}),
    ('my $value = qr{A  B};',{0}),
])
def test_legacy_embedded_data_is_protected_from_spacing_edits(source,protected):
    from core.text import literal_continuations
    assert protected <= literal_continuations(source)
    cleaned=analysis.clean_source(source,analysis.source_mode([source]))
    assert cleaned==source


@pytest.mark.parametrize('source,protected',[
    ('my $value = q{first\n   {nested  body}\n   last};\nprint $value;',{0,1,2}),
    ("SELECT q'[first\n    A ' B  C\n    last]' FROM dual;",{0,1,2}),
    ('cat <<-END\n\tA  B\n\tEND\necho done',{1,2}),
    ('DATA legacy;\nCARDS4;\nA  B;\nC  D;\n;;;;\nRUN;',{2,3,4}),
])
def test_multiline_legacy_data_keeps_its_whitespace(source,protected):
    from core.text import literal_continuations
    from core.analysis import _dedup_best
    assert literal_continuations(source)==protected
    assert analysis.clean_source(source,analysis.source_mode([source]))==source
    changed=source.replace('  ',' ')
    assert _dedup_best([source,changed])==[source,changed]


@pytest.mark.parametrize('language,text',[
    ('COBOL free', 'IDENTIFICATION DIVISION.\nPROGRAM-ID. TESTER.\nPROCEDURE DIVISION.\n    DISPLAY "A  B"\n    MOVE ZERO TO TOTAL\n    STOP RUN.'),
    ('RPG free', '**FREE\ndcl-s total packed(9:2);\nif total > 0;\n    dsply \'A  B\';\n    total = total + 1;\nendif;'),
    ('Fortran free', 'program forecast\n  implicit none\n  integer total\n  total = 1\n  print *, total\nend program forecast'),
    ('Fortran continuation', '      PROGRAM FORECAST\n      INTEGER TOTAL\n      TOTAL = 100 +\n     1        200\n      PRINT *, TOTAL\n      END'),
    ('COBOL continuation', '       IDENTIFICATION DIVISION.\n       PROGRAM-ID. FORECAST.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 TOTAL PIC 9(9).\n       PROCEDURE DIVISION.\n           COMPUTE TOTAL = 100 +\n      -        200\n           STOP RUN.'),
])
@pytest.mark.parametrize('font_size',[16,22])
def test_legacy_free_and_fixed_variants_have_measured_columns(language,text,font_size,tmp_path):
    png=render_code(text,tmp_path/'variant.png',font_size=font_size)
    with Image.open(png) as image: width=image.width
    profile=spacing.profile(png.read_bytes(),[0,0,1,1],28/width)
    assert spacing.bind(png,profile)['confirmed']
    wrong='\n'.join('   '+line for line in text.split('\n'))
    fixed,meta,_=analysis.measured_frame(None,png,wrong)
    expected=text.split('\n')
    assert sum(state=='measured' for state in meta['spacing']['line_status'])>=3
    for index,state in enumerate(meta['spacing']['line_status']):
        if state=='measured':assert fixed.split('\n')[index]==expected[index]
    assert analysis.clean_source(text,analysis.source_mode([text]))==text


def test_informix_form_boxes_are_source_not_editor_indent_guides():
    text='SCREEN\n{\n|   District: [f000        ] |\n}\nATTRIBUTES\nf000 = district.name;'
    assert analysis.clean_source(text,analysis.source_mode([text]))==text
