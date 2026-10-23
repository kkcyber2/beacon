# beacon

A news reader that shows one story per event instead of one per outlet.

Feeds duplicate relentlessly: four wires, one announcement, four headlines. Beacon parses RSS and Atom, scores every pair of items, and merges near-duplicates by union-find — then shows which sources corroborate the story and which version printed first.

**KK (Conan Sultan Khan)** · [github.com/kkcyber2](https://github.com/kkcyber2) · kkdev9715@gmail.com

## Run it

```bash
python -m beacon.server --port 8000
# open http://127.0.0.1:8000
```

No dependencies. Three fictional feeds are bundled so it runs offline.

```bash
python -m pytest tests/ -q
# 32 passed
```

The bundled demo merges 8 items into 5 stories, including one corroborated by all three wires:

```
  [3] 'Northgate Bank reports record quarter as rates stay …'  ← harbour, meridian, northgate
  [2] 'Regulator opens inquiry into Northgate overdraft fee…'  ← meridian, northgate
  [1] 'Northgate names new chief risk officer'
```

## The clustering, and why it is not the obvious implementation

**Union-find, not greedy first-match.** Greedy clustering compares each item to the current cluster's *lead*. When A matches B and B matches C but A and C do not, greedy splits the chain in two — and the result depends on the order the feeds arrive in. Beacon unions every qualifying pair, so a chain collapses into one cluster and the output is order-independent. There is a test that asserts exactly this (`test_clustering_is_order_independent`).

**Similarity blends two measures.** Overlap coefficient alone lets a long headline fully absorb a short one; Jaccard alone punishes legitimate length differences. The blend (0.6 / 0.4) handles both, and there are tests for each failure mode.

**Time attenuates rather than contributes.** Two identical headlines a week apart are usually different events — a recurring earnings cycle, an anniversary. So temporal distance multiplies the score down instead of adding to it.

**Entities break ties that text cannot.** "Apple sues Epic" and "Epic sues Apple" share every token. Only the entity sets separate them, which is why `similarity()` takes them into account.

## Endpoints

```
GET /api/feed?threshold=0.62   clusters + stats + per-feed errors
GET /api/stream                Server-Sent Events, 5 updates then "done"
GET /                          the reader
```

One malformed feed never blanks the page: `parse_many` isolates the failure, the API reports it under `errors`, and `stats.feeds_failed` names it.

## Structure

```
beacon/dedupe.py   normalisation, stemmer, similarity, union-find clustering
beacon/feeds.py    RSS + Atom parsing, HTML stripping, per-feed error isolation
beacon/server.py   JSON API, SSE stream, static files, traversal guard
beacon/demo.py     fictional demo feeds
static/            the reader
tests/             32 tests over parsing, scoring and clustering
```

## Notes on the front end

The one light, editorial surface in this collection, deliberately: a broadsheet, not a dashboard. Paper texture is a CSS gradient, not an image. The threshold slider is labelled by outcome ("Consolidated feed" → "Diverse sources") rather than by number, because "higher merges less" is a puzzle, not an instruction.

## Licence

MIT — see [LICENSE](LICENSE).
