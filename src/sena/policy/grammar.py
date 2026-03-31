"""Documentation constants for the policy DSL grammar."""

LOGICAL_OPERATORS = {"and", "or", "not"}
COMPARISON_OPERATORS = {
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
}
RESERVED_KEYS = LOGICAL_OPERATORS | COMPARISON_OPERATORS | {"field"}
