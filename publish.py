#!/usr/bin/env python3
"""Add an episode to the KBN Florida Employee Rights Weekly feed and rebuild feed.xml and index.html.

Usage:
  python3 publish.py --mp3 /path/to/episode.mp3 --date 2026-11-23 \
      --title "Employment Law Weekly, November 16 through November 22, 2026" \
      --notes-html notes.html --notes-text notes.txt

Run with no arguments (or --rebuild) to regenerate feed.xml and index.html only.
Keeps the newest MAX_EPISODES episodes and deletes older MP3 files.
"""
import argparse, html, json, os, shutil, subprocess
from datetime import datetime
from email.utils import format_datetime
from zoneinfo import ZoneInfo

BASE = "https://law4employees.github.io/Podcast/"
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "episodes.json")
EP_DIR = os.path.join(ROOT, "episodes")
MAX_EPISODES = 26

SHOW_TITLE = "KBN Florida Employee Rights Weekly"
SHOW_DESC = ("Employee Rights Weekly from Kwall Barack Nadeau (employeerights.com). Each Monday: new Eleventh Circuit "
             "and Florida appellate employment decisions, plus new EEOC, DOL and NLRB guidance. "
             "Created with AI. Not legal advice. Check every source before relying on it.")


def duration_seconds(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, check=True)
    return int(round(float(out.stdout.strip())))


def hms(sec):
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def load():
    if os.path.exists(DATA):
        with open(DATA) as f:
            return json.load(f)
    return []


def save(eps):
    with open(DATA, "w") as f:
        json.dump(eps, f, indent=2)


def build(eps):
    eps = sorted(eps, key=lambda e: e["date"], reverse=True)
    items = []
    for e in eps:
        dt = datetime.strptime(e["date"], "%Y-%m-%d").replace(hour=5, tzinfo=ZoneInfo("America/New_York"))
        url = BASE + "episodes/" + e["file"]
        items.append(f"""    <item>
      <title>{html.escape(e['title'])}</title>
      <description><![CDATA[{e['notes_html']}]]></description>
      <itunes:summary>{html.escape(e['notes_text'][:3900])}</itunes:summary>
      <pubDate>{format_datetime(dt)}</pubDate>
      <enclosure url="{url}" length="{e['bytes']}" type="audio/mpeg"/>
      <guid isPermaLink="false">{html.escape(e['file'])}</guid>
      <itunes:duration>{hms(e['seconds'])}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
      <itunes:episodeType>full</itunes:episodeType>
    </item>""")
    now = format_datetime(datetime.now(ZoneInfo("America/New_York")))
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{SHOW_TITLE}</title>
    <link>{BASE}</link>
    <atom:link href="{BASE}feed.xml" rel="self" type="application/rss+xml"/>
    <description>{html.escape(SHOW_DESC)}</description>
    <language>en-us</language>
    <lastBuildDate>{now}</lastBuildDate>
    <itunes:author>Kwall Barack Nadeau</itunes:author>
    <itunes:summary>{html.escape(SHOW_DESC)}</itunes:summary>
    <itunes:image href="{BASE}cover.jpg"/>
    <image><url>{BASE}cover.jpg</url><title>{SHOW_TITLE}</title><link>{BASE}</link></image>
    <itunes:category text="Government"/>
    <itunes:explicit>false</itunes:explicit>
    <itunes:type>episodic</itunes:type>
    <itunes:block>Yes</itunes:block>
{chr(10).join(items)}
  </channel>
</rss>
"""
    with open(os.path.join(ROOT, "feed.xml"), "w") as f:
        f.write(feed)

    rows = "\n".join(
        f'<li><strong>{html.escape(e["title"])}</strong> ({hms(e["seconds"])})<br>'
        f'<audio controls preload="none" src="episodes/{e["file"]}"></audio>'
        f'<details><summary>Show notes</summary>{e["notes_html"]}</details></li>' for e in eps)
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{SHOW_TITLE}</title>
<link rel="alternate" type="application/rss+xml" title="{SHOW_TITLE}" href="feed.xml">
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#1b2333;line-height:1.5}}
header{{display:flex;gap:1.25rem;align-items:center}} header img{{width:140px;height:140px;border-radius:8px}}
ul{{list-style:none;padding:0}} li{{border-top:1px solid #dde2ea;padding:1rem 0}} audio{{width:100%;margin:.5rem 0}}
code{{background:#eef1f6;padding:.15rem .35rem;border-radius:4px;word-break:break-all}}
</style></head><body>
<header><img src="cover.jpg" alt=""><div><h1>{SHOW_TITLE}</h1>
<p>{html.escape(SHOW_DESC)}</p></div></header>
<p>Podcast feed: <code>{BASE}feed.xml</code></p>
<ul>
{rows}
</ul>
</body></html>
"""
    with open(os.path.join(ROOT, "index.html"), "w") as f:
        f.write(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mp3")
    ap.add_argument("--date")
    ap.add_argument("--title")
    ap.add_argument("--notes-html")
    ap.add_argument("--notes-text")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    eps = load()
    if a.mp3:
        os.makedirs(EP_DIR, exist_ok=True)
        name = f"Employment-Law-Weekly-{a.date}.mp3"
        dest = os.path.join(EP_DIR, name)
        if os.path.abspath(a.mp3) != dest:
            shutil.copyfile(a.mp3, dest)
        with open(a.notes_html) as f:
            notes_html = f.read()
        with open(a.notes_text) as f:
            notes_text = f.read()
        eps = [e for e in eps if e["file"] != name]
        eps.append({"date": a.date, "title": a.title, "file": name,
                    "bytes": os.path.getsize(dest), "seconds": duration_seconds(dest),
                    "notes_html": notes_html, "notes_text": notes_text})
        eps.sort(key=lambda e: e["date"], reverse=True)
        for old in eps[MAX_EPISODES:]:
            p = os.path.join(EP_DIR, old["file"])
            if os.path.exists(p):
                os.remove(p)
        eps = eps[:MAX_EPISODES]
        save(eps)
    build(eps)
    print("feed.xml and index.html rebuilt with", len(eps), "episode(s)")
    if a.mp3:
        print("Episode URL:", BASE + "episodes/" + name)


if __name__ == "__main__":
    main()
