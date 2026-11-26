#!/usr/bin/env python3
"""Build the FTSE 100 CEO LinkedIn engagement dashboard.

Pulls the latest successful run of the Apify posts task (and, if set, the
followers task), matches posts to the CEO cohort in data/cohort.csv, and
writes the page to site/index.html plus a monthly snapshot in data/history/.

Run locally against saved exports with:
    python scripts/build.py --posts posts.json --followers profiles.json
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import statistics
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.apify.com/v2"
COHORT = ROOT / "data" / "cohort.csv"
FALLBACK = ROOT / "data" / "followers_fallback.csv"
TEMPLATE = ROOT / "scripts" / "template.html"
SITE = ROOT / "site"
HISTORY = ROOT / "data" / "history"


# ---------- helpers ----------
def slug(url):
    url = (url or "").strip().strip("`")
    if "/in/" not in url:
        return None
    return urllib.parse.unquote(re.sub(r"/+$", "", url).split("/in/")[-1]).lower()


def norm(name):
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    name = re.sub(r"\b(dr|mbe|obe|cbe|sir|dame)\b", "", name)
    name = re.sub(r"[^a-z ]", "", name)
    return re.sub(r"\s+", " ", name).strip()


def to_int(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace("+", "").strip()
    return int(s) if s.isdigit() else None


def engagement(post):
    e = post.get("engagement") or {}
    return (e.get("total_reactions") or 0) + (e.get("comments") or 0) + (e.get("shares") or 0)


def apify_items(task_id, token, label):
    """Items from the latest SUCCEEDED run of an Apify task."""
    query = urllib.parse.urlencode({"status": "SUCCEEDED", "clean": "true", "format": "json"})
    url = f"{API}/actor-tasks/{urllib.parse.quote(task_id, safe='~')}/runs/last/dataset/items?{query}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            items = json.load(resp)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            sys.exit(
                f"No successful run found for the {label} task ({task_id}). "
                "Run the task once in the Apify console, let it finish, then re-run this workflow."
            )
        if err.code in (401, 403):
            sys.exit("Apify rejected the token. Check the APIFY_TOKEN secret.")
        raise
    if not items:
        sys.exit(f"The latest {label} run returned no items. Check the task input in Apify and run it again.")
    return items


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_csv(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- build ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts", help="Local posts export (JSON) instead of Apify")
    ap.add_argument("--followers", help="Local profile export (JSON) instead of Apify")
    ap.add_argument("--as-of", help="Build date, YYYY-MM-DD (default: today, UTC)")
    ap.add_argument("--window-days", type=int, default=365, help="Rolling window length (default 365)")
    args = ap.parse_args()

    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else dt.datetime.now(dt.timezone.utc).date()
    start = as_of - dt.timedelta(days=args.window_days)
    token = os.environ.get("APIFY_TOKEN", "").strip()

    # posts
    if args.posts:
        posts = load_json(args.posts)
    else:
        task = os.environ.get("APIFY_POSTS_TASK_ID", "").strip()
        if not token or not task:
            sys.exit("Set APIFY_TOKEN and APIFY_POSTS_TASK_ID, or pass --posts.")
        posts = apify_items(task, token, "posts")

    # followers (optional)
    profiles = []
    if args.followers:
        profiles = load_json(args.followers)
    else:
        ftask = os.environ.get("APIFY_FOLLOWERS_TASK_ID", "").strip()
        if token and ftask:
            profiles = apify_items(ftask, token, "followers")

    # cohort
    cohort = read_csv(COHORT)
    by_slug, by_name = {}, {}
    for c in cohort:
        key = (c["company"], c["ceo"])
        s = slug(c.get("linkedin_url"))
        if s:
            by_slug[s] = key
        by_name.setdefault(norm(c["ceo"]), []).append(key)

    def match(url, name):
        s = slug(url)
        if s and s in by_slug:
            return by_slug[s]
        hits = by_name.get(norm(name), [])
        return hits[0] if len(hits) == 1 else None

    # posts -> cohort (original posts inside the window, de-duplicated)
    seen, per_ceo, unmatched = set(), {}, {}
    for p in posts:
        if p.get("is_repost"):
            continue
        posted = (p.get("posted_at") or "")[:10]
        if not posted or not (start.isoformat() <= posted <= as_of.isoformat()):
            continue
        pid = (p.get("_metadata") or {}).get("post_id") or p.get("post_url")
        if pid in seen:
            continue
        seen.add(pid)
        a = p.get("author") or {}
        key = match(a.get("linkedinUrl"), a.get("name"))
        if key:
            per_ceo.setdefault(key, []).append(engagement(p))
        elif "follower" not in (a.get("headline") or "").lower():
            nm = a.get("name") or "unknown"
            unmatched[nm] = unmatched.get(nm, 0) + 1

    # followers: fresh scrape first, then last known count
    fallback = {(r["company"], r["ceo"]): r for r in read_csv(FALLBACK)}
    fresh = {}
    for pr in profiles:
        if "error" in pr:
            continue
        count = to_int(pr.get("followerCount", pr.get("followers")))
        if count is None:
            continue
        name = pr.get("fullName") or f"{pr.get('firstName') or ''} {pr.get('lastName') or ''}"
        key = match(pr.get("linkedinUrl"), name)
        if key:
            fresh[key] = count
    for key, count in fresh.items():
        fallback[key] = {"company": key[0], "ceo": key[1], "followers": count, "as_of": as_of.isoformat()}

    new_flags = {(c["company"], c["ceo"]) for c in cohort if (c.get("new_to_cohort") or "").strip().upper() == "Y"}
    rows = []
    for (company, ceo), vals in per_ceo.items():
        fb = fallback.get((company, ceo))
        foll = to_int(fb["followers"]) if fb else None
        mean = statistics.mean(vals)
        rows.append({
            "name": ceo,
            "company": company,
            "mean": round(mean),
            "median": round(statistics.median(vals)),
            "n": len(vals),
            "foll": foll,
            "rate": round(mean / foll * 1000, 1) if foll else None,
            "new": (company, ceo) in new_flags,
        })
    rows.sort(key=lambda r: r["mean"], reverse=True)
    if not rows:
        sys.exit("No cohort posts found in the window. Check the posts task input covers the cohort URLs.")

    # write outputs
    meta = {
        "as_of": as_of.isoformat(),
        "window_start": start.isoformat(),
        "ceos_ranked": len(rows),
        "posts": sum(r["n"] for r in rows),
        "with_followers": sum(1 for r in rows if r["foll"]),
    }
    SITE.mkdir(exist_ok=True)
    HISTORY.mkdir(parents=True, exist_ok=True)
    fmt = lambda d: f"{d.day} {d.strftime('%B %Y')}"
    page = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__TITLE_SUFFIX__", as_of.strftime("%b %Y"))
            .replace("__WINDOW__", f"Rolling 12 months &middot; {fmt(start)} to {fmt(as_of)}")
            .replace("__N__", str(len(rows)))
            .replace("__GEN__", fmt(as_of))
            .replace("__DATA__", json.dumps(rows, ensure_ascii=False)))
    (SITE / "index.html").write_text(page, encoding="utf-8")
    snapshot = {"meta": meta, "rows": rows}
    (SITE / "data.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    (HISTORY / f"{as_of:%Y-%m}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(FALLBACK, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["company", "ceo", "followers", "as_of"])
        w.writeheader()
        w.writerows(sorted(fallback.values(), key=lambda r: (r["company"], r["ceo"])))

    # profile URLs to paste into the Apify task inputs, kept in step with cohort.csv
    urls = [c["linkedin_url"] for c in cohort if c.get("linkedin_url")]
    (ROOT / "data" / "apify_urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")

    # summary
    no_posts = [c["ceo"] for c in cohort if c.get("linkedin_url") and (c["company"], c["ceo"]) not in per_ceo]
    no_foll = [r["name"] for r in rows if not r["foll"]]
    new_names = sorted(((n, k) for n, k in unmatched.items() if k >= 2), key=lambda x: -x[1])
    lines = [
        f"## FTSE 100 CEO dashboard, {fmt(as_of)}",
        f"- CEOs ranked: **{meta['ceos_ranked']}**, original posts: **{meta['posts']}**",
        f"- Window: {fmt(start)} to {fmt(as_of)}",
        f"- Fresh follower counts this run: {len(fresh)}; ranked CEOs with no count: {', '.join(no_foll) or 'none'}",
        f"- Cohort CEOs with a URL but no posts in the window: {len(no_posts)}",
        "- Posters not on the cohort list (2+ posts, check for new appointments): "
        + (", ".join(f"{n} ({k})" for n, k in new_names) or "none"),
    ]
    print("\n".join(lines))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
