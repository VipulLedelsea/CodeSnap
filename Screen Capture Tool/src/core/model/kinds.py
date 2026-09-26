from pydantic import BaseModel, ConfigDict

ENTITY_KINDS = {
    "program", "module", "file", "class", "interface", "function", "paragraph", "section",
    "field", "copybook", "screen", "ui_element", "table", "column", "data_store",
    "api_endpoint", "external_system", "actor", "transaction", "job", "config_item", "unknown",
}

RELATION_KINDS = {
    "contains", "calls", "imports", "includes", "inherits", "implements", "uses", "reads",
    "writes", "displays", "navigates_to", "invokes_transaction", "connects_to", "depends_on", "same_as",
}

ARTIFACT_TYPES = {"code", "ui_screen", "db_schema", "sql", "config", "api", "job", "web", "other"}

ARTIFACT_STATUSES = {"captured", "transcribed", "validated", "structured", "failed", "superseded"}

ORIGINS = {"extracted", "inferred", "corrected", "placeholder"}

MEMBER_KINDS = {"function", "paragraph", "section", "field", "column", "ui_element"}


class Attrs(BaseModel):
    model_config = ConfigDict(extra="allow")


class TypeAttrs(Attrs):
    language: str | None = None
    bases: list[str] = []
    stereotype: str | None = None
    visibility: str | None = None


class FunctionAttrs(Attrs):
    signature: str | None = None
    params: list[str] = []
    returns: str | None = None
    visibility: str | None = None
    static: bool | None = None


class FieldAttrs(Attrs):
    type: str | None = None
    picture: str | None = None
    level: int | None = None
    visibility: str | None = None


class TableAttrs(Attrs):
    database: str | None = None
    schema_name: str | None = None
    access: str | None = None


class ColumnAttrs(Attrs):
    type: str | None = None
    nullable: bool | None = None
    primary_key: bool | None = None


class ScreenAttrs(Attrs):
    title: str | None = None
    map_name: str | None = None
    url: str | None = None


class EndpointAttrs(Attrs):
    method: str | None = None
    path: str | None = None
    protocol: str | None = None


class TransactionAttrs(Attrs):
    transid: str | None = None
    program: str | None = None


ATTR_MODELS = {
    "class": TypeAttrs, "interface": TypeAttrs, "module": TypeAttrs,
    "function": FunctionAttrs, "paragraph": FunctionAttrs, "section": FunctionAttrs,
    "field": FieldAttrs, "column": ColumnAttrs, "table": TableAttrs,
    "screen": ScreenAttrs, "api_endpoint": EndpointAttrs, "transaction": TransactionAttrs,
}


def check_kind(kind: str, allowed: set, label: str) -> str:
    if kind not in allowed:
        raise ValueError(f"unknown {label}: {kind!r}")
    return kind


def validate_attrs(kind: str, attrs: dict | None) -> dict:
    model = ATTR_MODELS.get(kind, Attrs)
    return model(**(attrs or {})).model_dump(exclude_none=True, exclude_defaults=True)
