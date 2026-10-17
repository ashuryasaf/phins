"""Language layer for the unified business plan.

The document, deck, appendices, charts and factor panel are authored once in
English in :mod:`services.business_plan_document`,
:mod:`services.business_plan_charts` and :mod:`services.business_plan_model`.
Every user-facing string passes through a :class:`Translator`; the Hebrew
edition is the same render with ``lang="he"`` and the dictionary in
:mod:`services.business_plan_i18n_he`.

Figures are never translated: placeholders such as ``{seed}`` stay inside
the translated sentence and are filled from the same plan dict, so the
Hebrew page binds to exactly the same ``data-bp`` paths and the same content
hash as the English one.

A translator records every string it could not translate (``misses``); the
contract test renders the Hebrew edition and asserts that set is empty, so
"fully Hebrew" is a tested property rather than a hope.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Dict, Iterable, Mapping, Optional, Set

__all__ = [
    "LANGS",
    "RTL_LANGS",
    "Translator",
    "current",
    "language_context",
    "translator",
]

LANGS = ("en", "he")
RTL_LANGS = ("he",)

_PLACEHOLDER = re.compile(r"\{[a-z_0-9]+\}")
_PROSE = re.compile(r"[A-Za-z]{2,}")


class Translator:
    """Callable ``t(text) -> text`` for one language.

    English is the identity. Any other language looks the text up in its
    table; a miss is recorded and the English text is returned, so a page
    never breaks because of a missing sentence — the test does.
    """

    def __init__(self, lang: str, table: Optional[Mapping[str, str]] = None):
        lang = str(lang or "en").strip().lower()
        if lang not in LANGS:
            raise ValueError(f"unsupported business-plan language: {lang!r}")
        self.lang = lang
        self.rtl = lang in RTL_LANGS
        self.table: Mapping[str, str] = table if table is not None else _table_for(lang)
        # translated values are returned unchanged when they come back
        # through a second layer (e.g. a chart header reused as a table header)
        self._values = frozenset(self.table.values())
        self.misses: Set[str] = set()

    def __call__(self, text: Optional[str]) -> str:
        if text is None:
            return ""
        if self.lang == "en" or text == "":
            return text
        if not _PROSE.search(_PLACEHOLDER.sub("", text)):
            # pure placeholders / figures / punctuation have no language
            return text
        out = self.table.get(text)
        if out is None:
            if text in self._values:
                return text
            self.misses.add(text)
            return text
        return out

    def all(self, items: Iterable[str]) -> list:
        return [self(i) for i in items]


def _table_for(lang: str) -> Mapping[str, str]:
    if lang == "he":
        from services.business_plan_i18n_he import HE
        return HE
    return {}


_CURRENT: ContextVar[Optional[Translator]] = ContextVar("phins_business_plan_translator", default=None)
_EN = Translator("en", table={})


def translator(lang: str = "en") -> Translator:
    """A fresh translator for ``lang`` (misses are tracked per instance)."""
    return Translator(lang)


def current() -> Translator:
    """The translator of the render in progress (English when none is set)."""
    return _CURRENT.get() or _EN


class language_context:
    """``with language_context(t): ...`` makes ``t`` the current translator."""

    def __init__(self, t: Translator):
        self._t = t
        self._token = None

    def __enter__(self) -> Translator:
        self._token = _CURRENT.set(self._t)
        return self._t

    def __exit__(self, *exc) -> None:
        if self._token is not None:
            _CURRENT.reset(self._token)
            self._token = None
