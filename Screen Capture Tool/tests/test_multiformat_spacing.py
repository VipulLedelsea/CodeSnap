"""Source-format tests: do not imply framework runtime/compiler validation."""
import pytest
from PIL import Image
from render import render_code
from core import analysis, spacing
from core.text import literal_continuations
from core.transcription_formats import GROUPS, TECHNOLOGIES

SOURCES = {
    'Kotlin': 'package sample\nclass Account {\n    val balance = 12\n    fun total() = balance\n}',
    'Scala': 'object Account {\n    val balance = 12\n    def total = balance\n}',
    'Groovy': 'class Account {\n    def balance = 12\n    def total() { return balance }\n}',
    'F#': 'let result =\n    match value with\n    |   Some amount -> amount\n    |   None -> 0',
    'VB.NET': 'Module Account\n    Sub Main()\n        Dim total As Integer = 12\n        Console.WriteLine(total)\n    End Sub\nEnd Module',
    'Go': 'package main\nimport "fmt"\nfunc main() {\n    total := 12\n    fmt.Println(total)\n}',
    'Rust': 'fn main() {\n    let total = 12;\n    println!("total: {}", total);\n}',
    'Swift': 'struct Account {\n    let total: Int\n    func printTotal() {\n        print(total)\n    }\n}',
    'Objective-C': '#import <Foundation/Foundation.h>\n@implementation Account\n- (int)total {\n    return 12;\n}\n@end',
    'Dart': 'class Account {\n    final int total = 12;\n    void show() {\n        print(total);\n    }\n}',
    'TypeScript': 'interface Account {\n    total: number;\n}\nconst account: Account = { total: 12 };',
    'TSX': 'export function Account() {\n    return (\n        <span>{12}</span>\n    );\n}',
    'HTML': '<html>\n    <body>\n        |   keep this text\n        <p>A  B</p>\n    </body>\n</html>',
    'Vue': '<template>\n    <p>{{ total }}</p>\n</template>\n<script>\n    export default { data: () => ({ total: 12 }) };\n</script>',
    'CSS': '.account {\n    display: grid;\n    grid-template-columns: 1fr  2fr;\n}',
    'Sass': '$space: 12px\n.account\n    margin: $space\n    color: red',
    'LESS': '@space: 12px;\n.account {\n    margin: @space;\n}',
    'XML/XSLT': '<?xml version="1.0"?>\n<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">\n    <xsl:template match="/">\n        <p>A  B</p>\n    </xsl:template>\n</xsl:stylesheet>',
    'JSON': '{\n    "total": 12,\n    "label": "A  B"\n}',
    'JSP/JSTL': '<%@ page language="java" %>\n<c:forEach items="${accounts}" var="account">\n    <p>${account.total}</p>\n</c:forEach>',
    'Razor': '@page\n@model AccountModel\n<div>\n    @Model.Total\n</div>',
    'Velocity': '#set($total = 12)\n#if($total > 0)\n    $total\n#end',
    'FreeMarker': '<#assign total = 12>\n<#if total gt 0>\n    ${total}\n</#if>',
    'Handlebars/Mustache': '{{#accounts}}\n    <p>{{total}}</p>\n{{/accounts}}',
    'ActionScript': 'package {\n    public class Account {\n        public var total:int = 12;\n    }\n}',
    'ABAP': 'REPORT zaccount.\nDATA total TYPE i.\ntotal = 12.\nIF total > 0.\n    WRITE total.\nENDIF.',
    'Apex': 'public class AccountService {\n    public Integer total() {\n        return 12;\n    }\n}',
    'X++': 'class AccountService {\n    public int total() {\n        return 12;\n    }\n}',
    'AL': 'codeunit 50100 AccountService\n{\n    procedure Total(): Integer\n    begin\n        exit(12);\n    end;\n}',
    'PeopleCode': 'Local number &total;\n&total = 12;\nIf &total > 0 Then\n    MessageBox(0, "", 0, 0, &total);\nEnd-If;',
    'Power Fx': 'With(\n    {total: 12},\n    If(total > 0, total, 0)\n)',
    'R': 'total <- 12\nif (total > 0) {\n    print(total)\n}',
    'XQuery': 'xquery version "1.0";\nfor $account in doc("accounts.xml")/accounts/account\n    where $account/total > 0\n    return $account',
    'MDX': 'SELECT\n    {[Measures].[Total]} ON COLUMNS,\n    {[Account].[Account].Members} ON ROWS\nFROM [Accounts]',
    'DAX': 'PositiveTotal =\n    CALCULATE(\n        SUM(Accounts[Total]),\n        Accounts[Total] > 0\n    )',
    'Ruby': 'class Account\n    def total\n        12\n    end\nend',
    'Tcl': 'proc total {} {\n    set value 12\n    return $value\n}',
    'Lua': 'local total = 12\nif total > 0 then\n    print(total)\nend',
    'awk': 'BEGIN {\n    total = 0\n}\n{ total += $1 }\nEND { print total }',
    'sed': '/account/ {\n    s/old/new/g\n    p\n}',
    'FOCUS': 'TABLE FILE ACCOUNTS\nSUM TOTAL\nBY ACCOUNT\nWHERE TOTAL GT 0;\nEND',
    'Ideal': 'PROGRAM ACCOUNT\n    SET TOTAL = 12\n    IF TOTAL > 0\n        TRANSMIT TOTAL\n    ENDIF\nENDPROGRAM',
    'DDS': '     A          R ACCOUNT\n     A            TOTAL          9S 2\n     A            LABEL         20A',
    'LotusScript': 'Sub Initialize\n    Dim total As Integer\n    total = 12\n    Print total\nEnd Sub',
    'Formula language': 'total := 12;\nlabel := "A  B";\n@If(total > 0; label; "")',
    'Clarion': 'Account PROCEDURE\nTotal LONG\n    CODE\n    Total = 12\n    RETURN',
    'SQL PL': 'CREATE PROCEDURE ACCOUNT ()\nBEGIN\n    DECLARE total INTEGER DEFAULT 12;\n    VALUES total;\nEND',
    'Pro*C': '#include <stdio.h>\nint main(void) {\n    EXEC SQL BEGIN DECLARE SECTION;\n    int total;\n    EXEC SQL END DECLARE SECTION;\n    return 0;\n}',
}

@pytest.mark.parametrize('name', SOURCES)
def test_visible_layout_survives_cleanup(name):
    source = SOURCES[name]
    assert analysis.clean_source(source, analysis.source_mode([source])) == source

@pytest.mark.parametrize('name', SOURCES)
def test_column_measurements_are_source_format_independent(name, tmp_path):
    source = SOURCES[name]
    image = render_code(source, tmp_path/'source.png', font_size=16)
    with Image.open(image) as frame:
        width = frame.width
    assert spacing.bind(image, spacing.profile(image.read_bytes(), [0,0,1,1], 28/width))['confirmed']
    shifted = '\n'.join('   '+line for line in source.split('\n'))
    repaired, meta, _ = analysis.measured_frame(None, image, shifted)
    expected = source.split('\n'); actual = repaired.split('\n')
    assert len(expected) == len(actual)
    measured = 0
    for row, status in enumerate(meta['spacing']['line_status']):
        if status == 'measured':
            measured += 1
            assert actual[row] == expected[row]
    assert measured >= 2, (name, meta['spacing'])

@pytest.mark.parametrize('source', [
    'let value = r##"first\n    |   A " B\nlast"##;',
    'auto value = R"tag(first\n    |   A " B\nlast)tag";',
    'DO $body$\n    |   raw body\n$body$;',
    '$value = @"\n    |   A " B\n"@',
    'local value = [==[first\n    |   A " B\nlast]==]',
    '<![CDATA[first\n    |   raw body\nlast]]>',
    '<pre>first\n    |   raw body\nlast</pre>',
    'value = %q{first\n    |   A \" B\nlast}',
    'my $value = qx{first\n    |   raw body\nlast};',
])
def test_raw_data_body_is_never_cleaned_or_measured_as_code(source):
    assert 1 in literal_continuations(source)
    assert analysis.clean_source(source, analysis.source_mode([source])) == source


def test_requested_capture_scope_is_explicit_and_has_no_duplicate_names():
    assert len(GROUPS) == 16
    assert len(TECHNOLOGIES) == len(set(TECHNOLOGIES))
    assert {'CA Gen','Synon/2E','FileMaker','Ab Initio','Power Fx','BPEL'} <= set(TECHNOLOGIES)
