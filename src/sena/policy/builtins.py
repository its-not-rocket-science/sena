from __future__ import annotations

import re
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


def op_starts_with(left: Any, right: str) -> bool:
    return isinstance(left, str) and left.startswith(right)


def op_ends_with(left: Any, right: str) -> bool:
    return isinstance(left, str) and left.endswith(right)


def op_matches_regex(left: Any, right: str) -> bool:
    return isinstance(left, str) and re.fullmatch(right, left) is not None


def op_exists(left: Any, right: bool) -> bool:
    return bool(left is not None) is bool(right)


def op_between(left: Any, right: tuple[Any, Any] | list[Any]) -> bool:
    lower, upper = right
    return lower <= left <= upper


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
    "starts_with": op_starts_with,
    "ends_with": op_ends_with,
    "matches_regex": op_matches_regex,
    "exists": op_exists,
    "between": op_between,
}
