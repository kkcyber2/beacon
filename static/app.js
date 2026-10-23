// Beacon front end. Fetches clusters and re-renders when the threshold moves.

const feed = document.getElementById("feed");
const stats = document.getElementById("stats");
const slider = document.getElementById("threshold");
const tval = document.getElementById("tval");

const pad = (n) => String(n).padStart(2, "0");

function stamp() {
  const d = new Date();
  document.getElementById("stamp").textContent =
    `${d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })} · ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
stamp();

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function renderStory(cluster, index) {
  const article = el("article", "story");

  const rank = el("div", "rank");
  rank.appendChild(el("span", "", String(index + 1).padStart(2, "0")));
  if (cluster.size > 1) {
    const corr = el("span", "corr");
    corr.textContent = `${cluster.size} sources`;
    corr.appendChild(el("small", "", "corroborated"));
    rank.appendChild(corr);
  }
  article.appendChild(rank);

  const body = el("div");
  const h2 = el("h2");
  const link = el("a", "", cluster.lead.title);
  link.href = cluster.lead.url || "#";
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  h2.appendChild(link);
  body.appendChild(h2);

  const byline = el("p", "byline");
  const when = cluster.lead.published
    ? new Date(cluster.lead.published).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "time unknown";
  byline.appendChild(el("span", "src", (cluster.lead.source || "wire").toUpperCase()));
  byline.appendChild(document.createTextNode(` · ${when}`));
  body.appendChild(byline);

  if (cluster.lead.summary) body.appendChild(el("p", "summary", cluster.lead.summary));

  if (cluster.also.length) {
    const ul = el("ul", "also");
    for (const other of cluster.also) {
      const li = el("li");
      const a = el("a", "", other.title);
      a.href = other.url || "#";
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      li.appendChild(a);
      li.appendChild(
        document.createTextNode(` — ${(other.source || "wire").toUpperCase()}`)
      );
      ul.appendChild(li);
    }
    body.appendChild(ul);
  } else {
    body.appendChild(el("p", "solo", "Single source — nothing corroborates this yet."));
  }

  article.appendChild(body);
  article.style.animationDelay = `${Math.min(index * 45, 360)}ms`;
  return article;
}

let inflight = null;
let queued = false;

async function load() {
  const threshold = slider.value;
  tval.textContent = threshold;

  // Coalesce rapid slider moves: at most one request in flight, one queued.
  if (inflight) {
    queued = true;
    return;
  }
  inflight = fetch(`/api/feed?threshold=${threshold}`);

  try {
    const res = await inflight;
    const data = await res.json();

    feed.replaceChildren(...data.clusters.map(renderStory));

    stats.replaceChildren();
    const add = (label, value) => {
      const span = el("span");
      span.appendChild(document.createTextNode(`${label} `));
      span.appendChild(el("b", "", String(value)));
      stats.appendChild(span);
    };
    add("items", data.stats.items);
    add("stories", data.stats.clusters);
    add("merged away", data.stats.merged);
    add("feeds ok", data.stats.feeds_ok);
    if (data.stats.feeds_failed.length) add("feeds failed", data.stats.feeds_failed.join(", "));
  } catch (e) {
    feed.replaceChildren(el("p", "solo", `Could not load the feed: ${e.message}`));
  } finally {
    inflight = null;
    if (queued) {
      queued = false;
      load();
    }
  }
}

slider.addEventListener("input", load);
load();

// Live updates: the server pushes a refreshed cluster set over SSE. Not wired
// into the render path on purpose -- the pushed payload is truncated for the
// stream, so the page re-fetches the full set instead of rendering a partial
// one. A browser without SSE keeps the initial fetch and simply does not update.
if (typeof EventSource !== "undefined") {
  try {
    const es = new EventSource("/api/stream");
    es.addEventListener("update", () => load());
    es.addEventListener("done", () => es.close());
    es.addEventListener("error", () => es.close());
  } catch {
    /* the page already rendered from the fetch */
  }
}
