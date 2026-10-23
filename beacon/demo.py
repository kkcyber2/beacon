"""Demo feeds so the reader runs with no network access.

Three fictional wires reporting overlapping events, which is what makes the
clustering visible: the top of the page should show one story with three
sources, not three stories.
"""
from __future__ import annotations

_ITEM = """<item><title>{title}</title><link>https://{source}.example/{n}</link>
<description><![CDATA[<p>{body}</p>]]></description>
<pubDate>{date}</pubDate></item>"""


def _feed(source: str, entries: list[tuple[str, str, str]]) -> str:
    items = "".join(
        _ITEM.format(title=t, body=b, date=d, source=source, n=i)
        for i, (t, b, d) in enumerate(entries)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<rss version="2.0"><channel><title>{source}</title>{items}</channel></rss>'
    )


NORTHGATE = _feed(
    "northgate",
    [
        (
            "Northgate Bank reports record quarter as rates stay high",
            "Net interest income rose 41% to a record, the bank said, beating consensus.",
            "Mon, 02 Mar 2026 09:00:00 GMT",
        ),
        (
            "Regulator opens inquiry into Northgate overdraft fees",
            "The financial regulator has opened a formal inquiry into the fee structure.",
            "Mon, 02 Mar 2026 11:15:00 GMT",
        ),
        (
            "Northgate names new chief risk officer",
            "Appointment effective from April.",
            "Sun, 01 Mar 2026 16:40:00 GMT",
        ),
    ],
)

MERIDIAN = _feed(
    "meridian",
    [
        (
            "Northgate Bank reports record quarter",
            "Profits at the lender jumped on the back of higher rates.",
            "Mon, 02 Mar 2026 09:20:00 GMT",
        ),
        (
            "Inquiry opened into Northgate overdraft charges",
            "Watchdog confirms a formal inquiry.",
            "Mon, 02 Mar 2026 11:40:00 GMT",
        ),
        (
            "Coastal wildfire forces evacuations in the north",
            "Around 4,000 residents were moved overnight.",
            "Mon, 02 Mar 2026 07:05:00 GMT",
        ),
    ],
)

HARBOUR = _feed(
    "harbour",
    [
        (
            "Record quarter at Northgate as high rates lift income",
            "The bank posted its strongest quarter on record.",
            "Mon, 02 Mar 2026 09:45:00 GMT",
        ),
        (
            "Wildfire evacuations continue as winds shift",
            "Firefighters report the blaze is 20% contained.",
            "Mon, 02 Mar 2026 08:30:00 GMT",
        ),
    ],
)

DEMO_FEEDS: dict[str, str] = {
    "northgate": NORTHGATE,
    "meridian": MERIDIAN,
    "harbour": HARBOUR,
}
