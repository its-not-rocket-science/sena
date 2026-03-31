from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable


def op_eq(left: Any, right: Any) -> bool:
    return left == right


def op_neq(left: Any, right: Any) -> bool:
    return left != right


def op_gt(left: Any, right: Any) -> bool:
    return left > right


def op_gte(left: Any, right: Any) -> bool:
    return left >= right


def op_lt(left: Any, right: Any) -> bool:
    return left < right


def op_lte(left: Any, right: Any) -> bool:
    return left <= right


def op_in(left: Any, right: Iterable[Any]) -> bool:
    return left in right


def op_not_in(left: Any, right: Iterable[Any]) -> bool:
    return left not in right


def op_contains(left: Iterable[Any], right: Any) -> bool:
    return right in left


ALLOWED_OPERATORS: dict[str, Callable[..., bool]] = {
    "eq": op_eq,
    "neq": op_neq,
    "gt": op_gt,
    "gte": op_gte,
    "lt": op_lt,
    "lte": op_lte,
    "in": op_in,
    "not_in": op_not_in,
    "contains": op_contains,
}
