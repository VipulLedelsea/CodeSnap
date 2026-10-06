"""Remove characters that XML 1.0 forbids, so Word, SVG, Visio and draw.io files stay valid whatever text is captured."""
import re

_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def xml_safe(text):
    """Strip XML-invalid control characters; a vertical tab or form feed becomes a space. Non-strings pass through."""
    if not isinstance(text, str):
        return text
    return _BAD.sub(lambda m: " " if m.group(0) in "\x0b\x0c" else "", text)
