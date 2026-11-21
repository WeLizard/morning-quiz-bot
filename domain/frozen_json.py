"""Read-only views of parsed JSON for data shared between callers.

A FrozenDict/FrozenList can only come from ``freeze`` over already parsed JSON,
so code that checks ``type(x) is dict`` for untrusted input may accept them
explicitly without accepting arbitrary dict subclasses.
"""
from __future__ import annotations

from typing import Any


def _frozen_refuse(self, *args, **kwargs):
    raise TypeError("read-only case document; use CompiledCase.document() for a mutable copy")


def thaw(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, list):
        return [thaw(v) for v in value]
    return value


class FrozenDict(dict):
    """A dict that refuses mutation. ``copy``/``deepcopy`` give plain mutable copies."""
    __slots__ = ()
    __setitem__ = __delitem__ = __ior__ = _frozen_refuse
    clear = pop = popitem = setdefault = update = _frozen_refuse

    def __copy__(self):
        return dict(self)

    def __deepcopy__(self, memo):
        return thaw(self)

    def __reduce__(self):
        return (dict, (thaw(self),))


class FrozenList(list):
    """A list that refuses mutation. ``copy``/``deepcopy`` give plain mutable copies."""
    __slots__ = ()
    __setitem__ = __delitem__ = __iadd__ = __imul__ = _frozen_refuse
    append = extend = insert = pop = remove = clear = sort = reverse = _frozen_refuse

    def __copy__(self):
        return list(self)

    def __deepcopy__(self, memo):
        return thaw(self)

    def __reduce__(self):
        return (list, (thaw(self),))


def freeze(value: Any) -> Any:
    """Deeply frozen copy of parsed JSON (plain dicts/lists only)."""
    if type(value) is dict:
        return FrozenDict((k, freeze(v)) for k, v in value.items())
    if type(value) is list:
        return FrozenList(freeze(v) for v in value)
    return value
