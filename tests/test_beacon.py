"""Tests for feed parsing and clustering.

Clustering is where the real bugs live, so most of this file is about it.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from beacon.dedupe import Cluster, Item, cluster, normalise, parse_time, similarity, stem, tokens
from beacon.feeds import FeedError, parse, parse_many

T0 = datetime(2026, 3, 2, 9, 0)


def item(id_, title, hours=0, source="wire", entities=None, url=None):
    return Item(
        id=id_,
        title=title,
        source=source,
        url=url or f"https://example.com/{id_}",
        published=T0 + timedelta(hours=hours),
        entities=set(entities or []),
    )


RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Wire</title>
<item><title>Bank reports record quarter</title>
  <link>https://ex.com/1</link>
  <description><![CDATA[<p>Profits <b>rose</b> 40%.</p>]]></description>
  <pubDate>Mon, 02 Mar 2026 09:00:00 GMT</pubDate></item>
<item><title>Second story</title><link>https://ex.com/2</link>
  <description>Plain text</description>
  <pubDate>2026-03-02T10:30:00Z</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom wire</title>
<entry><title>Regulator opens inquiry</title>
  <link rel="alternate" href="https://ex.com/a1"/>
  <id>tag:ex.com,2026:a1</id>
  <summary>An inquiry was opened.</summary>
  <updated>2026-03-02T11:00:00Z</updated></entry>
</feed>"""


# --------------------------------------------------------------------- parsing
class TestFeeds:
    def test_rss_items_are_extracted(self):
        items = parse(RSS, "wire")
        assert len(items) == 2
        assert items[0].title == "Bank reports record quarter"
        assert items[0].url == "https://ex.com/1"

    def test_cdata_html_is_stripped_to_text(self):
        items = parse(RSS, "wire")
        assert "<p>" not in items[0].summary
        assert "Profits" in items[0].summary
        assert "rose" in items[0].summary

    def test_rfc2822_and_iso_dates_both_parse(self):
        items = parse(RSS, "wire")
        assert items[0].published == datetime(2026, 3, 2, 9, 0)
        assert items[1].published == datetime(2026, 3, 2, 10, 30)

    def test_atom_entries_are_extracted(self):
        items = parse(ATOM, "atom-wire")
        assert len(items) == 1
        assert items[0].title == "Regulator opens inquiry"
        assert items[0].url == "https://ex.com/a1"
        assert items[0].published == datetime(2026, 3, 2, 11, 0)

    def test_malformed_xml_raises_feed_error(self):
        with pytest.raises(FeedError, match="well-formed"):
            parse("<rss><channel>", "broken")

    def test_non_feed_xml_raises_feed_error(self):
        with pytest.raises(FeedError, match="unrecognised"):
            parse("<html><body/></html>", "x")

    def test_rss_without_channel_raises(self):
        with pytest.raises(FeedError, match="channel"):
            parse('<?xml version="1.0"?><rss version="2.0"></rss>', "x")

    def test_item_without_title_is_dropped(self):
        raw = """<rss><channel>
        <item><link>https://ex.com/no-title</link></item>
        <item><title>Keep me</title></item></channel></rss>"""
        assert [i.title for i in parse(raw)] == ["Keep me"]

    def test_guid_is_preferred_as_id(self):
        raw = """<rss><channel><item>
        <title>T</title><guid>urn:1</guid><link>https://ex.com/z</link>
        </item></channel></rss>"""
        assert parse(raw)[0].id == "urn:1"

    def test_link_is_used_when_guid_absent(self):
        raw = """<rss><channel><item><title>T</title>
        <link>https://ex.com/z</link></item></channel></rss>"""
        assert parse(raw)[0].id == "https://ex.com/z"

    def test_one_broken_feed_does_not_break_the_batch(self):
        results = parse_many({"good": RSS, "bad": "<nope", "atom": ATOM})
        status = {r.source: r.ok for r in results}
        assert status == {"good": True, "bad": False, "atom": True}
        assert len(results[1].items) == 0
        assert results[1].error


# -------------------------------------------------------------------- normalise
class TestText:
    def test_accents_and_case_fold(self):
        assert normalise("Café  Society") == "cafe society"

    def test_stopwords_removed_and_stemmed(self):
        t = tokens("Refunds were issued to the customers")
        assert "refund" in t          # stemmed
        assert "customer" in t
        assert "the" not in t
        assert "were" not in t

    def test_stemmer_leaves_short_words_alone(self):
        assert stem("bus") == "bus"
        assert stem("refunds") == "refund"

    def test_parse_time_handles_garbage(self):
        assert parse_time("not a date") is None
        assert parse_time(None) is None

    def test_parse_time_normalises_to_utc(self):
        assert parse_time("2026-03-02T11:00:00+02:00") == datetime(2026, 3, 2, 9, 0)


# ------------------------------------------------------------------ clustering
class TestSimilarity:
    def test_identical_titles_score_one(self):
        a = item("a", "Bank reports record quarter")
        b = item("b", "Bank reports record quarter")
        assert similarity(a, b) == 1.0

    def test_unrelated_titles_score_low(self):
        a = item("a", "Bank reports record quarter")
        b = item("b", "Earthquake strikes coastal region")
        assert similarity(a, b) < 0.2

    def test_short_and_long_headline_about_same_event_still_match(self):
        a = item("a", "Regulator opens inquiry into bank")
        b = item("b", "Regulator opens inquiry into bank over mis-sold products and fees")
        assert similarity(a, b) > 0.6

    def test_same_words_reordered_scores_high_but_is_caught_by_entities(self):
        # "Apple sues Epic" vs "Epic sues Apple" share all tokens. They are
        # different stories, which is exactly why entity sets matter.
        a = item("a", "Apple sues Epic", entities=["apple"])
        b = item("b", "Epic sues Apple", entities=["epic"])
        assert similarity(a, b) > 0.5      # text alone cannot separate them
        assert "apple" not in b.entities   # but the entity sets do

    def test_time_gap_attenuates(self):
        a = item("a", "Bank reports record quarter", hours=0)
        b = item("b", "Bank reports record quarter", hours=1)
        c = item("c", "Bank reports record quarter", hours=200)
        assert similarity(a, b) > similarity(a, c)
        assert similarity(a, c) < 0.5


class TestClustering:
    def test_same_story_across_sources_collapses(self):
        items = [
            item("a", "Bank reports record quarter", source="wire"),
            item("b", "Bank reports record quarter profits", source="paper", hours=1),
            item("c", "Bank reports record quarter", source="tv", hours=2),
        ]
        clusters = cluster(items)
        assert len(clusters) == 1
        assert set(clusters[0].sources) == {"wire", "paper", "tv"}

    def test_different_stories_stay_separate(self):
        items = [
            item("a", "Bank reports record quarter"),
            item("b", "Wildfire forces evacuations in the north"),
        ]
        assert len(cluster(items)) == 2

    def test_chain_merges_through_the_middle(self):
        # A~B and B~C but A and C are below threshold. Greedy first-match
        # clustering splits this into two; union-find must produce one.
        a = item("a", "Central bank raises interest rates sharply")
        b = item("b", "Central bank raises interest rates sharply today")
        c = item("c", "Central bank raises interest rates sharply today amid pressure")
        assert similarity(a, c) < similarity(a, b)
        assert len(cluster([a, b, c], threshold=0.6)) == 1

    def test_clustering_is_order_independent(self):
        items = [
            item("a", "Bank reports record quarter"),
            item("b", "Bank reports record quarter profits", hours=1),
            item("c", "Wildfire forces evacuations", hours=2),
            item("d", "Bank reports record quarter", hours=3, source="tv"),
        ]
        sizes_a = sorted(len(c.items) for c in cluster(items))
        sizes_b = sorted(len(c.items) for c in cluster(list(reversed(items))))
        assert sizes_a == sizes_b == [1, 3]

    def test_lead_is_the_earliest_item(self):
        items = [
            item("later", "Bank reports record quarter", hours=5),
            item("first", "Bank reports record quarter", hours=0),
        ]
        assert cluster(items)[0].lead.id == "first"

    def test_lead_tie_breaks_on_shorter_title(self):
        items = [
            item("long", "Bank reports record quarter and raises guidance", hours=0),
            item("short", "Bank reports record quarter", hours=0),
        ]
        assert cluster(items)[0].lead.id == "short"

    def test_sources_deduplicated_and_sorted(self):
        items = [
            item("a", "Bank reports record quarter", source="wire"),
            item("b", "Bank reports record quarter", source="wire", hours=1),
            item("c", "Bank reports record quarter", source="tv", hours=2),
        ]
        assert cluster(items)[0].sources == ["tv", "wire"]

    def test_clusters_ordered_by_corroboration_then_recency(self):
        big = [
            item("a", "Bank reports record quarter", hours=0),
            item("b", "Bank reports record quarter", hours=1),
            item("c", "Bank reports record quarter", hours=2),
        ]
        small = [item("d", "Wildfire forces evacuations", hours=0)]
        ordered = cluster(small + big)
        assert ordered[0].size == 3
        assert ordered[1].size == 1

    def test_empty_input_returns_empty(self):
        assert cluster([]) == []

    def test_threshold_is_respected(self):
        items = [
            item("a", "Bank reports record quarter"),
            item("b", "Bank reports quarter profit rise"),
        ]
        assert len(cluster(items, threshold=0.95)) == 2
        assert len(cluster(items, threshold=0.30)) == 1

    def test_cluster_serialises_with_also_listed(self):
        items = [
            item("a", "Bank reports record quarter", source="wire"),
            item("b", "Bank reports record quarter", source="tv", hours=1),
        ]
        payload = cluster(items)[0].as_dict()
        assert payload["size"] == 2
        assert len(payload["also"]) == 1
        assert payload["lead"]["id"] == "a"
