from functools import lru_cache

LANG_BY_EXT = {
    "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "hh": "cpp", "hxx": "cpp", "h": "cpp", "c": "cpp",
    "cs": "c_sharp", "java": "java",
}
LANG_BY_NAME = {"c++": "cpp", "cpp": "cpp", "c": "cpp", "c#": "c_sharp", "csharp": "c_sharp", "c sharp": "c_sharp",
                "java": "java"}


def lang_for(language: str = "", extension: str = "") -> str | None:
    ext = (extension or "").lower().lstrip(".")
    if ext in LANG_BY_EXT:
        return LANG_BY_EXT[ext]
    name = (language or "").strip().lower()
    for key, lang in LANG_BY_NAME.items():
        if name == key or name.startswith(key + " "):
            return lang
    return None


@lru_cache(maxsize=None)
def parser_for(lang: str):
    import tree_sitter as ts
    if lang == "cpp":
        import tree_sitter_cpp as mod
    elif lang == "c_sharp":
        import tree_sitter_c_sharp as mod
    elif lang == "java":
        import tree_sitter_java as mod
    else:
        raise KeyError(lang)
    return ts.Parser(ts.Language(mod.language()))


def available() -> bool:
    try:
        parser_for("java")
        return True
    except Exception:
        return False


import re as _re

_CPP_EXTENSIONS = _re.compile(r"\b(far|near|huge|_far|_near|_huge|__far|__near|__huge|_pascal|__pascal|_cdecl|"
                              r"_export|__export|_loadds|__loadds|_saveregs|_interrupt|__interrupt|_fastcall)\b")


def prepare(code: str, lang: str) -> str:
    if lang == "cpp":
        return _CPP_EXTENSIONS.sub(lambda m: " " * len(m.group(0)), code)
    return code


def parse(code: str, lang: str):
    return parser_for(lang).parse(prepare(code, lang).encode("utf-8", errors="replace"))
