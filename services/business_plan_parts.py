"""Chapters of the unified business plan an admin can include or leave out.

A share link freezes the allow-list at the moment it is sent. The page served
to that link's viewer is filtered before it leaves the server: a chapter that
was not chosen is not in the HTML, and a factor that was not chosen as
adjustable is not in the factor catalog the page builds its controls from.
The planning model itself is unchanged — hidden chapters do not move a
figure, and a locked factor stays on the snapshot baseline.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

__all__ = [
    "PARTS",
    "PartsError",
    "filter_share_html",
    "freeze_adjustable",
    "freeze_visible_parts",
    "normalize_visible_parts",
    "part_ids",
    "parts_catalog",
]

# kind "id" matches an element id; "class" matches a class token. A part may
# name several elements (the deck is its heading plus the slide grid).
PARTS: Tuple[Dict[str, Any], ...] = (
    {"id": "banner", "en": "Opening banner", "he": "כותרת הפתיחה", "match": ({"class": "bp-banner"},)},
    {"id": "kpis", "en": "Headline figures", "he": "נתוני הכותרת", "match": ({"class": "bp-kpis"},)},
    {"id": "plan-exec", "en": "1 · Executive summary", "he": "1 · תקציר מנהלים", "match": ({"id": "plan-exec"},)},
    {"id": "plan-company", "en": "2 · Company and method", "he": "2 · החברה והשיטה", "match": ({"id": "plan-company"},)},
    {"id": "plan-market", "en": "3 · Market and OECD map", "he": "3 · שוק ומפת OECD", "match": ({"id": "plan-market"},)},
    {"id": "plan-product", "en": "4 · Products and solutions", "he": "4 · מוצרים ופתרונות", "match": ({"id": "plan-product"},)},
    {"id": "plan-technology", "en": "5 · Technology", "he": "5 · טכנולוגיה", "match": ({"id": "plan-technology"},)},
    {"id": "plan-gtm", "en": "6 · Go-to-market", "he": "6 · יציאה לשוק", "match": ({"id": "plan-gtm"},)},
    {"id": "plan-financials", "en": "7 · Financial plan", "he": "7 · תוכנית פיננסית", "match": ({"id": "plan-financials"},)},
    {"id": "plan-capital", "en": "8 · Capital plan and the round", "he": "8 · תוכנית הון והסבב", "match": ({"id": "plan-capital"},)},
    {"id": "plan-risks", "en": "9 · Risks and mitigations", "he": "9 · סיכונים", "match": ({"id": "plan-risks"},)},
    {"id": "plan-governance", "en": "10 · Governance and milestones", "he": "10 · ממשל ואבני דרך", "match": ({"id": "plan-governance"},)},
    {"id": "plan-founder", "en": "11 · Founder credentials", "he": "11 · רקע המייסד", "match": ({"id": "plan-founder"},)},
    {"id": "founder-photo", "en": "Founder photo", "he": "תמונת המייסד", "match": ({"class": "bp-founder-photo"},)},
    {"id": "part-deck", "en": "Investor deck (slideshow)", "he": "מצגת למשקיעים", "match": ({"id": "part-deck"}, {"class": "bp-deck"})},
    {"id": "appendix-a", "en": "Appendix A · Actuarial basis", "he": "נספח A · בסיס אקטוארי", "match": ({"id": "appendix-a"},)},
    {"id": "appendix-b", "en": "Appendix B · Carrier and reinsurance", "he": "נספח B · מבטח וביטוח משנה", "match": ({"id": "appendix-b"},)},
    {"id": "appendix-c", "en": "Appendix C · Regulatory pathway", "he": "נספח C · מסלול רגולטורי", "match": ({"id": "appendix-c"},)},
    {"id": "appendix-d", "en": "Appendix D · Technology standard", "he": "נספח D · תקן טכנולוגי", "match": ({"id": "appendix-d"},)},
    {"id": "appendix-e", "en": "Appendix E · Data integrity", "he": "נספח E · שלמות נתונים", "match": ({"id": "appendix-e"},)},
    {"id": "appendix-f", "en": "Appendix F · Financial tables", "he": "נספח F · טבלאות פיננסיות", "match": ({"id": "appendix-f"},)},
    {"id": "appendix-g", "en": "Appendix G · Milestone calendar", "he": "נספח G · לוח אבני דרך", "match": ({"id": "appendix-g"},)},
    {"id": "appendix-h", "en": "Appendix H · Glossary", "he": "נספח H · מונחון", "match": ({"id": "appendix-h"},)},
    {"id": "appendix-i", "en": "Appendix I · Sources and resources", "he": "נספח I · מקורות", "match": ({"id": "appendix-i"},)},
    {"id": "factor-panel", "en": "Adjustable factors panel", "he": "לוח הגורמים המתכווננים", "match": ({"id": "bp-factor-panel"},)},
)

_PLAN_SECTIONS = tuple(p["id"] for p in PARTS if p["id"].startswith("plan-"))
_APPENDICES = tuple(p["id"] for p in PARTS if p["id"].startswith("appendix-"))
_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})
_FACTORS_RE = re.compile(
    r'(<script\b[^>]*\bid="bp-factors"[^>]*>)(.*?)(</script>)', re.IGNORECASE | re.DOTALL
)


class PartsError(ValueError):
    """The requested document structure is not a known part list."""


def part_ids() -> List[str]:
    return [p["id"] for p in PARTS]


def parts_catalog() -> List[Dict[str, str]]:
    """Id plus both labels, for the admin tools."""
    return [{"id": p["id"], "label": p["en"], "label_he": p["he"]} for p in PARTS]


def normalize_visible_parts(raw: Any) -> Optional[List[str]]:
    """``None`` means every part. A list is the allow-list, in catalog order.

    An empty list is valid and means no chapter is included.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw.strip().lower() in ("", "all", "*"):
            return None
        raw = [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, (list, tuple)):
        raise PartsError("visible_parts must be a list of part ids or 'all'.")
    known = set(part_ids())
    chosen: List[str] = []
    for item in raw:
        pid = str(item)
        if pid not in known:
            raise PartsError(f"Unknown document part: {pid}")
        if pid not in chosen:
            chosen.append(pid)
    order = part_ids()
    return [pid for pid in order if pid in set(chosen)]


def freeze_visible_parts(raw: Any) -> List[str]:
    """Concrete allow-list stored on a share, so a later chapter is not added."""
    chosen = normalize_visible_parts(raw)
    return list(part_ids()) if chosen is None else chosen


def freeze_adjustable(raw: Optional[Sequence[str]]) -> List[str]:
    """Concrete factor allow-list. ``None`` freezes every current factor."""
    from services.business_plan_model import FACTORS

    if raw is None:
        return [spec["id"] for spec in FACTORS]
    return [str(fid) for fid in raw]


def _hidden_matchers(hidden: Set[str]) -> Tuple[List[Mapping[str, str]], Set[str]]:
    matchers: List[Mapping[str, str]] = []
    removed_ids: Set[str] = set()
    for part in PARTS:
        if part["id"] not in hidden:
            continue
        for spec in part["match"]:
            matchers.append(spec)
            if "id" in spec:
                removed_ids.add(spec["id"])
    if all(pid in hidden for pid in _PLAN_SECTIONS):
        matchers.append({"id": "part-plan"})
        removed_ids.add("part-plan")
    if all(pid in hidden for pid in _APPENDICES):
        matchers.append({"id": "part-appendices"})
        removed_ids.add("part-appendices")
    return matchers, removed_ids


def _attr_map(attrs: Sequence[Tuple[str, Optional[str]]]) -> Dict[str, str]:
    return {str(key).lower(): (value or "") for key, value in attrs}


def _matches(attr: Mapping[str, str], spec: Mapping[str, str]) -> bool:
    if "id" in spec and attr.get("id") == spec["id"]:
        return True
    if "class" in spec and spec["class"] in attr.get("class", "").split():
        return True
    return False


class _Stripper(HTMLParser):
    def __init__(self, matchers: Sequence[Mapping[str, str]], removed_ids: Set[str]):
        super().__init__(convert_charrefs=False)
        self._matchers = matchers
        self._removed_ids = removed_ids
        self._skip = 0
        self.out: List[str] = []

    def _drop(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> bool:
        attr = _attr_map(attrs)
        if any(_matches(attr, spec) for spec in self._matchers):
            return True
        if tag.lower() == "a":
            href = attr.get("href", "")
            if href.startswith("#") and href[1:] in self._removed_ids:
                return True
        return False

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        if self._skip:
            if tag.lower() not in _VOID:
                self._skip += 1
            return
        if self._drop(tag, attrs):
            if tag.lower() not in _VOID:
                self._skip = 1
            return
        self.out.append(self.get_starttag_text())

    def handle_startendtag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        if self._skip or self._drop(tag, attrs):
            return
        self.out.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            if tag.lower() not in _VOID:
                self._skip -= 1
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._skip:
            self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip:
            self.out.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if not self._skip:
            self.out.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        if not self._skip:
            self.out.append(f"<!{decl}>")


def _limit_factor_catalog(html: str, allowed: Set[str]) -> str:
    def repl(match: re.Match) -> str:
        try:
            data = json.loads(match.group(2))
        except json.JSONDecodeError:
            return match.group(0)
        if isinstance(data, list):
            data = [
                item for item in data
                if isinstance(item, dict) and str(item.get("id")) in allowed
            ]
        body = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        return match.group(1) + body + match.group(3)

    return _FACTORS_RE.sub(repl, html, count=1)


def filter_share_html(
    html: str,
    *,
    visible_parts: Optional[Sequence[str]] = None,
    viewer_adjustable: Optional[Sequence[str]] = None,
) -> str:
    """Return the page with unchosen chapters and factor controls removed.

    ``visible_parts is None`` leaves the structure untouched (a legacy share
    that predates the composition snapshot). A list removes every other part.
    ``viewer_adjustable is None`` leaves the factor catalog untouched; a list
    keeps only those controls, and an empty list removes the panel.
    """
    hidden: Set[str] = set()
    if visible_parts is not None:
        allowed = set(visible_parts)
        hidden = {pid for pid in part_ids() if pid not in allowed}
    if viewer_adjustable is not None and len(viewer_adjustable) == 0:
        hidden.add("factor-panel")
    if hidden:
        matchers, removed_ids = _hidden_matchers(hidden)
        parser = _Stripper(matchers, removed_ids)
        parser.feed(html)
        parser.close()
        html = "".join(parser.out)
    if viewer_adjustable is not None:
        html = _limit_factor_catalog(html, set(viewer_adjustable))
    return html
