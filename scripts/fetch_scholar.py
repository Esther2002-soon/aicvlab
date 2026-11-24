#!/usr/bin/env python3
"""Sync a Google Scholar profile into Jekyll data files, through SerpApi.

Writes (inside --data-dir)
    scholar_publications.json   all papers, grouped by year
    scholar_stats.json          citations, h-index, i10-index

Environment
    SERPAPI_API_KEY      required (create a free key at serpapi.com, store it as a GitHub secret)
    GOOGLE_SCHOLAR_ID    optional, defaults to Professor Hsieh's profile
    SCHOLAR_FIXTURE_DIR  testing only. Read page_<start>.json files from this folder instead of calling SerpApi.

Behaviour
    * Pages through the whole profile (100 papers per request).
    * Files are rewritten only when the content really changed, so the repository history stays quiet.
    * Safety valve. If the new list is empty, or more than 10 percent smaller than the stored one, nothing is
      written and the script exits with an error. A bad day at Google never wipes the site.
    * Prints "changed=true|false" to $GITHUB_OUTPUT so the workflow knows whether to commit and rebuild.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://serpapi.com/search.json"
DEFAULT_ID = "mXUOEzwAAAAJ"
PAGE_SIZE = 100
MAX_PAGES = 15
SHRINK_LIMIT = 0.90


class ScholarError(RuntimeError):
    pass


def fetch_page(author_id, key, start):
    fixture = os.environ.get("SCHOLAR_FIXTURE_DIR")
    if fixture:
        p = Path(fixture) / f"page_{start}.json"
        if not p.exists():
            return {"error": "Google hasn't returned any results for this query."}
        return json.loads(p.read_text(encoding="utf-8"))
    qs = urllib.parse.urlencode(
        {
            "engine": "google_scholar_author",
            "author_id": author_id,
            "hl": "en",
            "sort": "pubdate",
            "num": PAGE_SIZE,
            "start": start,
            "api_key": key,
        }
    )
    last = None
    for attempt, wait in enumerate((0, 5, 20), 1):
        if wait:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(f"{API}?{qs}", timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code < 500 and e.code != 429:
                raise ScholarError(f"SerpApi answered HTTP {e.code}: {body}")
            last = f"HTTP {e.code}: {body}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = repr(e)
        print(f"  attempt {attempt} failed ({last}), retrying", file=sys.stderr)
    raise ScholarError(f"SerpApi unreachable after retries: {last}")


def collect(author_id, key):
    articles, stats, searches = [], None, 0
    for page in range(MAX_PAGES):
        start = page * PAGE_SIZE
        data = fetch_page(author_id, key, start)
        searches += 1
        err = data.get("error")
        if err:
            if start > 0 and "hasn't returned any results" in err:
                break
            raise ScholarError(f"SerpApi error: {err}")
        if stats is None:
            stats = {}
            for row in (data.get("cited_by") or {}).get("table") or []:
                for k in ("citations", "h_index", "i10_index"):
                    if k in row:
                        stats[k] = int((row[k] or {}).get("all") or 0)
        batch = data.get("articles") or []
        articles.extend(batch)
        print(f"  start={start}: {len(batch)} articles")
        if len(batch) < PAGE_SIZE:
            break
    else:
        raise ScholarError(f"More than {MAX_PAGES * PAGE_SIZE} articles. Raise MAX_PAGES if this is expected.")
    return articles, stats or {}, searches


def normalise(articles):
    seen, items = set(), []
    for a in articles:
        title = (a.get("title") or "").strip()
        cid = a.get("citation_id") or title.lower()
        if not title or cid in seen:
            continue
        seen.add(cid)
        cited = a.get("cited_by") or {}
        year = str(a.get("year") or "").strip()
        items.append(
            {
                "title": title,
                "authors": (a.get("authors") or "").strip(),
                "venue": (a.get("publication") or "").strip(),
                "year": year if year.isdigit() else "Other",
                "cited_by": int(cited.get("value") or 0),
                "link": a.get("link") or "",
                "citation_id": a.get("citation_id") or "",
            }
        )
    by_year = {}
    for it in items:
        by_year.setdefault(it["year"], []).append(it)

    def ykey(y):
        return (1, 0) if y == "Other" else (0, -int(y))

    years = []
    for y in sorted(by_year, key=ykey):
        group = sorted(by_year[y], key=lambda i: (-i["cited_by"], i["title"].lower()))
        for g in group:
            g.pop("year", None)
        years.append({"year": y, "items": group})
    return years, len(items)


def strip_updated(obj):
    return {k: v for k, v in obj.items() if k != "updated"} if isinstance(obj, dict) else obj


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="_data")
    args = ap.parse_args()

    key = os.environ.get("SERPAPI_API_KEY", "").strip()
    author_id = os.environ.get("GOOGLE_SCHOLAR_ID", "").strip() or DEFAULT_ID
    if not key and not os.environ.get("SCHOLAR_FIXTURE_DIR"):
        print("SERPAPI_API_KEY is not set. Add it under Settings > Secrets and variables > Actions.", file=sys.stderr)
        return 1

    data_dir = Path(args.data_dir)
    pub_path, stat_path = data_dir / "scholar_publications.json", data_dir / "scholar_stats.json"
    old_pubs, old_stats = read_json(pub_path) or {}, read_json(stat_path) or {}

    print(f"Fetching Google Scholar profile {author_id}")
    try:
        articles, stats, searches = collect(author_id, key)
    except ScholarError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    years, count = normalise(articles)
    print(f"{count} unique papers, {searches} SerpApi searches used")

    prev = int(old_pubs.get("count") or 0)
    if count == 0:
        print("ERROR: Scholar returned no papers. Keeping the existing data.", file=sys.stderr)
        return 1
    if prev and count < prev * SHRINK_LIMIT:
        print(f"ERROR: list shrank from {prev} to {count} (more than 10 percent). Keeping the existing data.", file=sys.stderr)
        return 1

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_pubs = {"updated": now, "author_id": author_id, "count": count, "years": years}
    new_stats = {
        "updated": now,
        "citations": stats.get("citations", old_stats.get("citations", 0)),
        "h_index": stats.get("h_index", old_stats.get("h_index", 0)),
        "i10_index": stats.get("i10_index", old_stats.get("i10_index", 0)),
    }

    changed = False
    if strip_updated(new_pubs) != strip_updated(old_pubs):
        write_json(pub_path, new_pubs)
        changed = True
        print(f"Updated {pub_path}")
    if strip_updated(new_stats) != strip_updated(old_stats):
        write_json(stat_path, new_stats)
        changed = True
        print(f"Updated {stat_path}")
    if not changed:
        print("No changes.")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
