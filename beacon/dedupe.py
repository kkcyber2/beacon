"""Feed normalisation and near-duplicate clustering.

Two feeds describe the same event with different headlines. A reader wants one
story, not four. That is the whole problem, and the naive approaches fail:

* exact-title matching catches nothing.
* Jaccard on token sets merges "Apple sues Epic" with "Epic sues Apple".
* Greedy first-match clustering cannot merge a *chain* (A~B, B~C, A!~C), so the
  result depends on input order — the same feed re-ordered gives different clusters.

So the clustering is union-find over all pairs, and similarity is a weighted
combination of title overlap, entity overlap and time proximity.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

STOPWORDS = frozenset(
    """a an the and or but if then than that this these those of in on at to for from
    by with without into over under after before as is are was were be been being
    it its said says say will would could should may might can has have had not no
    new more most about up down out off again once here there when where why how
    all any both each few other some such only own same so too very just""".split()
)

SUFFIXES = ("ing", "edly", "ies", "es", "ed", "ly", "s")


def normalise(text: str) -> str:
    """Fold case, strip accents, collapse whitespace."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def stem(word: str) -> str:
    """A deliberately crude stemmer.

    Full Porter is more accurate but over-stems short news words ("drones" ->
    "drone" is wanted; "buses" -> "bus" is not). Stripping one common suffix is
    enough to make "refunds" match "refund" without mangling anything.
    """
    if len(word) < 5:
        return word
    for suf in SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[: -len(suf)]
    return word


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", normalise(text))
    return {stem(w) for w in words if w not in STOPWORDS and len(w) > 2}


@dataclass
class Item:
    """One feed entry, normalised."""

    id: str
    title: str
    summary: str = ""
    source: str = ""
    url: str = ""
    published: datetime | None = None
    entities: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "published": self.published.isoformat() if self.published else None,
        }


def parse_time(raw: str | None) -> datetime | None:
    """Accept ISO-8601 and RFC-2822; return naive UTC."""
    if not raw:
        return None
    raw = raw.strip()
    # datetime.fromisoformat in 3.11 handles 'Z'
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def similarity(a: Item, b: Item, half_life_hours: float = 18.0) -> float:
    """0..1. Weighted, with time as a *gate* rather than a substitute.

    Two identical headlines a week apart are usually different stories (a
    recurring earnings cycle, an anniversary), so time proximity attenuates the
    score instead of contributing to it independently.
    """
    ta, tb = tokens(a.title), tokens(b.title)
    if not ta or not tb:
        title_sim = 0.0
    else:
        inter = len(ta & tb)
        # Blend of two measures, because each alone is wrong:
        #   overlap coefficient  - a short headline and a long one about the same
        #                          event should still score high, but on its own it
        #                          lets a long headline fully absorb a short one
        #   Jaccard              - penalises the length asymmetry, so "the bank
        #                          reported" and a 20-word headline containing those
        #                          words are not treated as the same story
        overlap = inter / min(len(ta), len(tb))
        jaccard = inter / len(ta | tb)
        title_sim = 0.6 * overlap + 0.4 * jaccard

    # Entity agreement only means something if at least one side names entities.
    # Treating "neither side has entities" as *disagreement* would cap a
    # perfect title match at 0.78 and make the threshold semantics meaningless.
    if a.entities or b.entities:
        union = a.entities | b.entities
        entity_sim = len(a.entities & b.entities) / len(union) if union else 0.0
        score = 0.78 * title_sim + 0.22 * entity_sim
    else:
        score = title_sim

    if a.published and b.published:
        gap = abs((a.published - b.published).total_seconds()) / 3600.0
        if gap > half_life_hours * 3:
            score *= 0.35
        elif gap > half_life_hours:
            score *= 0.7
    return round(min(score, 1.0), 4)


class _UF:
    """Union-find with path compression and union by size."""

    def __init__(self, ids: Iterable[str]) -> None:
        self.parent = {i: i for i in ids}
        self.size = {i: 1 for i in ids}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]


@dataclass
class Cluster:
    items: list[Item]
    score: float

    @property
    def lead(self) -> Item:
        """The item a reader should see: earliest published, then shortest title."""
        return sorted(
            self.items,
            key=lambda i: (i.published or datetime.max, len(i.title)),
        )[0]

    @property
    def sources(self) -> list[str]:
        return sorted({i.source for i in self.items if i.source})

    @property
    def size(self) -> int:
        """Number of items in the cluster, i.e. how many sources corroborate it."""
        return len(self.items)

    def as_dict(self) -> dict:
        return {
            "lead": self.lead.as_dict(),
            "sources": self.sources,
            "size": len(self.items),
            "score": self.score,
            "also": [i.as_dict() for i in self.items if i.id != self.lead.id],
        }


def cluster(items: list[Item], threshold: float = 0.62) -> list[Cluster]:
    """Group near-duplicates. Order-independent by construction."""
    if not items:
        return []

    uf = _UF([i.id for i in items])
    pair_score: dict[tuple[str, str], float] = {}

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            s = similarity(items[i], items[j])
            if s >= threshold:
                pair_score[(items[i].id, items[j].id)] = s
                uf.union(items[i].id, items[j].id)

    groups: dict[str, list[Item]] = {}
    for it in items:
        groups.setdefault(uf.find(it.id), []).append(it)

    out: list[Cluster] = []
    for members in groups.values():
        ids = {m.id for m in members}
        scores = [s for (a, b), s in pair_score.items() if a in ids and b in ids]
        out.append(Cluster(items=members, score=max(scores) if scores else 0.0))

    # Most-corroborated first, then freshest, then title — fully deterministic.
    out.sort(
        key=lambda c: (
            -len(c.items),
            -(c.lead.published.timestamp() if c.lead.published else 0),
            c.lead.title,
        )
    )
    return out
