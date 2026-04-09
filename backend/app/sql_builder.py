from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pypika.queries import QueryBuilder


@dataclass(frozen=True)
class BuiltQuery:
    sql: str
    params: tuple[Any, ...]


def _percent_to_asyncpg(sql: str) -> str:
    # PyPika parameterized SQL renders placeholders as %s.
    # asyncpg expects positional $1, $2... placeholders.
    out: list[str] = []
    i = 0
    idx = 1
    while i < len(sql):
        if i + 1 < len(sql) and sql[i] == "%" and sql[i + 1] == "s":
            out.append(f"${idx}")
            idx += 1
            i += 2
            continue
        out.append(sql[i])
        i += 1
    return "".join(out)


def build_query(query: QueryBuilder, params: Iterable[Any] | None = None) -> BuiltQuery:
    raw = query.get_sql(quote_char=None, dialect="postgresql")
    sql = _percent_to_asyncpg(raw)
    return BuiltQuery(sql=sql, params=tuple(params or ()))
