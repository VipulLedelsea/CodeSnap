"""Text helpers shared by findings and reports."""
import re


def normalized_line(line):
    """Normalize source spacing without changing spaces inside quoted values."""
    text = line.lstrip()
    out, quote, space = [], None, False
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            out.append(char)
            if char == "\\" and index + 1 < len(text):
                index += 1
                out.append(text[index])
            elif char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 1
                    out.append(text[index])
                else:
                    quote = None
        elif char in ("'", '"', '`'):
            if space and out:
                out.append(" ")
            space, quote = False, char
            out.append(char)
        elif char.isspace():
            space = True
        else:
            if space and out:
                out.append(" ")
            space = False
            out.append(char)
        index += 1
    return ''.join(out)


def _delimited_rows(text):
    """Conservatively protect nonstandard raw strings and embedded text bodies."""
    patterns = [
        (r'(?<![\w])(?:br|r)(?P<hash>\#{0,})"', lambda m: '"' + m.group('hash')),
        (r'R"(?P<delimiter>[^ ()\\\t\r\n]{0,16})\(', lambda m: ')' + m.group('delimiter') + '"'),
        (r'(?<![\w$])(?P<dollar>\$(?:[A-Za-z_]\w*)?\$)(?![\w])', lambda m: m.group('dollar')),
        (r'(?m)@["\'](?=[ \t]*$)', lambda m: ('"@' if m.group()[1] == '"' else "'@")),
        (r'\[(?P<equals>=*)\[', lambda m: ']' + m.group('equals') + ']'),
        (r'<!\[CDATA\[', lambda m: ']]>'),
        (r'(?i)<pre\b[^>]*>', lambda m: '</pre>'),
    ]
    protected = set()
    for pattern, terminator in patterns:
        cursor = 0
        rx = re.compile(pattern)
        while (match := rx.search(text, cursor)) is not None:
            endmark = terminator(match)
            end = text.find(endmark, match.end())
            stop = len(text) if end < 0 else end + len(endmark)
            first = text.count('\n', 0, match.start())
            last = text.count('\n', 0, stop)
            protected.update(range(first, last + 1))
            cursor = max(stop, match.end())
    return protected


def literal_continuations(text):
    """Rows in multiline literals or legacy embedded data stay verbatim.

    This deliberately errs toward withholding spacing edits. Source can be
    invalid, and an unterminated quote is not permission to format its body.
    """
    protected, quote = _delimited_rows(text), None
    lines = text.split('\n')
    data_end, sas_data = None, False
    paired, depth = None, 0
    for row, line in enumerate(lines):
        if data_end is not None:
            protected.add(row)
            if line.lstrip('\t') == data_end:
                data_end = None
            continue
        if sas_data:
            protected.add(row)
            if line.strip() in (';', ';;;;'):
                sas_data = False
            continue
        if not quote and paired is None:
            here = re.search(r"<<[-~]?\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_]\w*))", line)
            if here:
                end = next(value for value in here.groups() if value is not None)
                # Distinguish a here-document from an ordinary shift expression.
                if any(future.lstrip('\t') == end for future in lines[row+1:]):
                    data_end = end
            if re.match(r'^\s*(?:DATALINES4?|CARDS4?)\s*;\s*$', line, re.I):
                sas_data = True
            if re.search(r'(?<![\w])\d+[hH]', line):
                protected.add(row)  # Fortran Hollerith data includes unquoted spaces.
            special = re.search(r"(?<![\w])(?:q[qwrx]?\s*([\[({<])|q'([\[({<])|%[qQwWiIrx]([\[({<]))", line, re.I)
            if special:
                opening = next(value for value in special.groups() if value is not None)
                paired = (opening, {'[':']','(':')','{':'}','<':'>'}[opening])
                depth = 1
                start = special.end()
            else:
                start = 0
        else:
            start = 0
        if paired is not None:
            protected.add(row)
            i = start
            while i < len(line):
                char = line[i]
                if char == '\\':
                    i += 2
                    continue
                if char == paired[0]: depth += 1
                if char == paired[1]: depth -= 1
                if depth == 0:
                    paired = None
                    break
                i += 1
            continue
        if quote:
            protected.add(row)
        i = 0
        while i < len(line):
            char = line[i]
            if quote:
                if char == '\\':
                    i += 2
                    continue
                if line.startswith(quote, i):
                    if len(quote) == 1 and quote != '`' and line.startswith(quote * 2, i):
                        i += 2
                        continue
                    i += len(quote)
                    quote = None
                    continue
            elif char in ("'", '"', '`'):
                quote = char * 3 if char != '`' and line.startswith(char * 3, i) else char
                i += len(quote)
                continue
            i += 1
    return protected



def shorten_at_boundary(text, limit=88):
    """Keep a complete sentence or comma clause; preserve text without a safe boundary."""
    if len(text) <= limit:
        return text
    boundaries = list(re.finditer(r"[.!?](?=\s|$)|,(?=\s)", text[:limit + 1]))
    if not boundaries:
        return text
    end = boundaries[-1].end()
    return text[:end].rstrip(", ")
