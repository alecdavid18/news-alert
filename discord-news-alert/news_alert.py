"""
High-impact news alert for Discord, using the Myfxbook economic calendar.

Reads Myfxbook's free calendar RSS feed, finds HIGH-impact events that start
within the next ALERT_MINUTES (default 30), and posts one message per release
time to a Discord channel through a webhook. Events already alerted are kept in
sent.json, so students never get the same alert twice.

No extra packages needed: Python 3.9+ standard library only.

Settings (environment variables):
  DISCORD_WEBHOOK_URL  required. The Discord channel webhook URL (keep it secret).
  ALERT_MINUTES        optional, default 30. Minutes before the event to alert.
  COUNTRIES            optional. Comma-separated list of countries to include.
                       Default: major forex economies (see DEFAULT_COUNTRIES).
                       Use "ALL" for every country Myfxbook marks High.
  ROLE_ID              optional. Discord role ID to ping, e.g. your @students role.
  DRY_RUN              optional. "1" prints the message instead of sending it.

Run once:                                   python news_alert.py
Run forever on your own PC/VPS (every min): python news_alert.py --loop
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

FEED_URL = os.environ.get("MYFXBOOK_RSS", "https://www.myfxbook.com/rss/forex-economic-calendar-events")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sent.json")
IST = timezone(timedelta(hours=5, minutes=30))

# Myfxbook titles start with the country name, e.g. "United States Non Farm Payrolls"
COUNTRY_INFO = {
    "United States": ("USD", "🇺🇸"), "Euro Area": ("EUR", "🇪🇺"), "European Union": ("EUR", "🇪🇺"),
    "Germany": ("EUR", "🇩🇪"), "France": ("EUR", "🇫🇷"), "Italy": ("EUR", "🇮🇹"), "Spain": ("EUR", "🇪🇸"),
    "United Kingdom": ("GBP", "🇬🇧"), "Japan": ("JPY", "🇯🇵"), "Australia": ("AUD", "🇦🇺"),
    "Canada": ("CAD", "🇨🇦"), "Switzerland": ("CHF", "🇨🇭"), "New Zealand": ("NZD", "🇳🇿"),
    "China": ("CNY", "🇨🇳"), "India": ("INR", "🇮🇳"),
}
DEFAULT_COUNTRIES = ["United States", "Euro Area", "European Union", "Germany", "United Kingdom",
                     "Japan", "Australia", "Canada", "Switzerland", "New Zealand", "China"]


def env(name, default=""):
    return os.environ.get(name, default).strip()


# ---------- fetching and parsing the Myfxbook feed ----------

def fetch_feed(url=FEED_URL):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (news-alert-bot)",
        "Accept": "application/rss+xml, application/xml, text/xml",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def _cells(description_html):
    """Return the data-row cells as (text, raw_html) pairs from the item's HTML table."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", description_html, flags=re.S | re.I)
    for row in rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S | re.I)
        if len(tds) >= 5:   # data row: Time left | Impact | Previous | Consensus | Actual
            out = []
            for raw in tds:
                text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
                out.append((" ".join(text.split()), raw))
            return out
    return None


def parse_time_left(s):
    """'2h 27min', '25 min', '1 day 3h', '-3683 seconds' -> timedelta (or None)."""
    s = s.strip().lower()
    if not s:
        return None
    sign = -1 if s.startswith("-") else 1
    total = 0
    found = False
    for num, unit in re.findall(r"(\d+)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", s):
        found = True
        n = int(num)
        if unit.startswith("d"):
            total += n * 86400
        elif unit.startswith("h"):
            total += n * 3600
        elif unit.startswith("m"):
            total += n * 60
        else:
            total += n
    return timedelta(seconds=sign * total) if found else None


def parse_feed(xml_text, fetched_at):
    """Return list of events: dict(title, country, impact, time, previous, consensus, actual, link)."""
    if "<!ENTITY" in xml_text:          # refuse XML entity tricks
        raise ValueError("unexpected XML entity declaration in feed")
    root = ET.fromstring(xml_text)
    events = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = item.findtext("description") or ""
        link = (item.findtext("link") or "").strip()
        cells = _cells(desc)
        if not title or not cells:
            continue
        time_left_txt, (impact_txt, impact_raw) = cells[0][0], cells[1]
        impact = impact_txt or ""
        if not impact:  # impact sometimes shown only as an icon/class
            m = re.search(r"(high|medium|low)", impact_raw, re.I)
            impact = m.group(1) if m else ""

        # Event time: prefer the item's pubDate; fall back to fetch time + "Time left"
        t = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                t = parsedate_to_datetime(pub)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                t = t.astimezone(timezone.utc)
            except (TypeError, ValueError):
                t = None
        left = parse_time_left(time_left_txt)
        if left is not None:
            by_left = fetched_at + left
            # if pubDate is missing or disagrees by > 10 min, trust Myfxbook's countdown
            if t is None or abs((t - by_left).total_seconds()) > 600:
                t = by_left
        if t is None:
            continue

        country = next((c for c in sorted(COUNTRY_INFO, key=len, reverse=True) if title.startswith(c)), "")
        events.append({
            "title": title, "country": country, "impact": impact.strip(),
            "time": t, "previous": cells[2][0], "consensus": cells[3][0],
            "actual": cells[4][0], "link": link,
        })
    return events


# ---------- choosing what to send ----------

def already_sent(ev, state):
    """Same event name already alerted within 90 minutes of this time? (tolerates feed drift)"""
    for key, sent_time in state.items():
        if key.split("|", 1)[-1] == ev["title"]:
            try:
                if abs((datetime.fromisoformat(sent_time) - ev["time"]).total_seconds()) < 5400:
                    return True
            except ValueError:
                pass
    return False


def event_key(ev):
    # rounded to the minute so the same event keeps the same key between runs
    return f"{ev['time'].strftime('%Y-%m-%dT%H:%M')}|{ev['title']}"


def find_upcoming(events, now, minutes, countries):
    out = []
    for ev in events:
        if "high" not in ev["impact"].lower():
            continue
        if countries is not None and not any(ev["title"].startswith(c) for c in countries):
            continue
        if now < ev["time"] <= now + timedelta(minutes=minutes):
            out.append(ev)
    return sorted(out, key=lambda e: e["time"])


# ---------- Discord message ----------

def build_message(t, evs, now, role_id):
    unix = int(t.timestamp())
    mins = max(1, round((t - now).total_seconds() / 60))
    ist = t.astimezone(IST).strftime("%I:%M %p IST").lstrip("0")
    lines, ccys = [], set()
    for ev in evs:
        ccy, flag = COUNTRY_INFO.get(ev["country"], ("", "🌐"))
        if ccy:
            ccys.add(ccy)
        line = f"{flag} **{ev['title']}**" + (f" ({ccy})" if ccy else "")
        bits = []
        if ev["consensus"]:
            bits.append(f"Forecast: {ev['consensus']}")
        if ev["previous"]:
            bits.append(f"Previous: {ev['previous']}")
        if bits:
            line += "\n   " + " | ".join(bits)
        lines.append(line)
    pairs = f" on {', '.join(sorted(ccys))} pairs" if ccys else ""
    content = (f"<@&{role_id}> " if role_id else "") + f"🚨 **HIGH-IMPACT NEWS in {mins} min**"
    embed = {
        "title": f"🔴 High-impact news at {ist}",
        "description": "\n".join(lines)
            + f"\n\n🕒 <t:{unix}:t> your time  •  <t:{unix}:R>"
            + f"\n\n⚠️ Expect sharp moves, wider spreads and slippage{pairs}. "
              "Manage open trades and avoid entering right before the release.",
        "color": 0xE53935,
        "footer": {"text": "Source: Myfxbook economic calendar • Educational alert, not trade advice"},
    }
    payload = {"content": content, "embeds": [embed],
               "allowed_mentions": {"roles": [role_id]} if role_id else {"parse": []}}
    return payload


def post_discord(webhook, payload):
    req = urllib.request.Request(webhook, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "news-alert-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


# ---------- state ----------

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state, now):
    cutoff = (now - timedelta(days=8)).isoformat()
    state = {k: v for k, v in state.items() if v >= cutoff}
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)


# ---------- main ----------

def run_once(now=None, xml_text=None):
    now = now or datetime.now(timezone.utc)
    webhook, dry = env("DISCORD_WEBHOOK_URL"), env("DRY_RUN") == "1"
    if not webhook and not dry:
        sys.exit("DISCORD_WEBHOOK_URL is not set")
    minutes = int(env("ALERT_MINUTES", "30") or 30)
    raw_c = env("COUNTRIES")
    countries = None if raw_c.upper() == "ALL" else (
        [c.strip() for c in raw_c.split(",") if c.strip()] if raw_c else DEFAULT_COUNTRIES)
    role_id = env("ROLE_ID")

    if xml_text is None:
        xml_text = fetch_feed()
    events = parse_feed(xml_text, now)
    state = load_state()

    groups = {}
    for ev in find_upcoming(events, now, minutes, countries):
        if already_sent(ev, state):
            continue
        slot = ev["time"].replace(second=0, microsecond=0)
        groups.setdefault(slot, []).append(ev)

    for t, evs in sorted(groups.items()):
        payload = build_message(t, evs, now, role_id)
        if dry:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            post_discord(webhook, payload)
            time.sleep(1)
        for ev in evs:
            state[event_key(ev)] = ev["time"].isoformat()
    save_state(state, now)
    print(f"{now.isoformat()} parsed {len(events)} events, sent {len(groups)} alert(s)")


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            try:
                run_once()
            except Exception as e:  # keep going through network hiccups
                print("error:", e)
            time.sleep(60)
    else:
        run_once()
