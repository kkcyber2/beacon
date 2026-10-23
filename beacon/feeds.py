"""Feed parsing: RSS 2.0 and Atom, without a parser dependency.

Written against `xml.etree` with explicit handling for the three things that
break naive feed readers: namespaces, CDATA in descriptions, and dates in both
formats.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape

from .dedupe import Item, parse_time

ATOM = "{http://www.w3.org/2005/Atom}"


class FeedError(ValueError):
    """The document is not a feed we can read."""


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return unescape((node.text or "").strip())


def _strip_html(raw: str) -> str:
    """Descriptions arrive as HTML; a reader wants the text."""
    if not raw:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", unescape(no_tags)).strip()


def parse(raw: str | bytes, source: str = "") -> list[Item]:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FeedError(f"not well-formed XML: {exc}") from exc

    if root.tag.endswith("rss") or root.find("channel") is not None:
        return _parse_rss(root, source)
    if root.tag == f"{ATOM}feed":
        return _parse_atom(root, source)
    raise FeedError(f"unrecognised root element {root.tag!r}")


def _parse_rss(root: ET.Element, source: str) -> list[Item]:
    channel = root.find("channel")
    if channel is None:
        raise FeedError("rss document has no channel")
    out: list[Item] = []
    for entry in channel.findall("item"):
        title = _text(entry.find("title"))
        if not title:
            continue
        link = _text(entry.find("link"))
        guid = _text(entry.find("guid")) or link or title
        out.append(
            Item(
                id=guid,
                title=title,
                summary=_strip_html(_text(entry.find("description"))),
                source=source,
                url=link,
                published=parse_time(_text(entry.find("pubDate")) or None),
            )
        )
    return out


def _parse_atom(root: ET.Element, source: str) -> list[Item]:
    out: list[Item] = []
    for entry in root.findall(f"{ATOM}entry"):
        title = _text(entry.find(f"{ATOM}title"))
        if not title:
            continue
        link = ""
        for ln in entry.findall(f"{ATOM}link"):
            if ln.get("rel", "alternate") == "alternate":
                link = ln.get("href", "")
                break
        ident = _text(entry.find(f"{ATOM}id")) or link or title
        out.append(
            Item(
                id=ident,
                title=title,
                summary=_strip_html(
                    _text(entry.find(f"{ATOM}summary")) or _text(entry.find(f"{ATOM}content"))
                ),
                source=source,
                url=link,
                published=parse_time(
                    _text(entry.find(f"{ATOM}updated")) or _text(entry.find(f"{ATOM}published")) or None
                ),
            )
        )
    return out


@dataclass
class FeedResult:
    source: str
    ok: bool
    items: list[Item]
    error: str | None = None


def parse_many(feeds: dict[str, str | bytes]) -> list[FeedResult]:
    """Parse a batch, isolating failure.

    One broken feed must not blank the page, so errors are per-feed and reported
    alongside the ones that worked.
    """
    results: list[FeedResult] = []
    for source, raw in feeds.items():
        try:
            results.append(FeedResult(source=source, ok=True, items=parse(raw, source)))
        except FeedError as exc:
            results.append(FeedResult(source=source, ok=False, items=[], error=str(exc)))
    return results
