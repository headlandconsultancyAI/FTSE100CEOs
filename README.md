# FTSE 350 CEO LinkedIn Engagement Ranking

A dashboard that ranks FTSE 350 chief executives (FTSE 100 and FTSE 250) by mean engagement on their own original LinkedIn posts over a rolling 12 months. It rebuilds itself every month from two Apify tasks and publishes to GitHub Pages.

## How it works

- On the 1st of each month, your Apify tasks scrape the CEOs' posts and their follower counts.
- On the 2nd, a GitHub Action pulls the latest successful run of each task, matches posts to the cohort in `data/cohort.csv`, and rebuilds the page.
- Each run saves a snapshot to `data/history/YYYY-MM.json`, so you can compare month on month.

## One-time setup

### 1. Apify

Create two tasks. Use `data/apify_urls.txt` as the list of profile URLs for both.

- **Posts task**, from the LinkedIn posts scraper you already use. Set the posts limit per profile high enough to cover a full year. The busiest CEOs post around 45 times a year, so 60 is safe.
- **Followers task**, from the LinkedIn profile scraper.

Schedule both for the 1st of the month, for example 06:00 and 06:30 UTC.

> **Run both tasks once now, straight after creating them, and let them finish before the first GitHub build.** The build reads the last successful run, so if there isn't one yet, it stops with an error.

### 2. GitHub secrets

In the repo, go to **Settings > Secrets and variables > Actions** and add:

| Secret | Where to find it |
|---|---|
| `APIFY_TOKEN` | Apify Console > Settings > API & Integrations |
| `APIFY_POSTS_TASK_ID` | The posts task's ID, or `username~task-name` |
| `APIFY_FOLLOWERS_TASK_ID` | The followers task's ID. Optional, but without it follower counts don't refresh |

### 3. GitHub Pages

Go to **Settings > Pages** and set **Source** to **GitHub Actions**. On a free GitHub plan, Pages only works on public repos.

The `index.html` at the root of the repo is a static copy of the 25 November 2026 dashboard. Once Pages is switched to GitHub Actions, the site is served from each month's build instead and that file is no longer used.

### 4. First build

Go to **Actions > Monthly dashboard build > Run workflow**. When it's done, the Pages URL shows on the run page. After that it runs by itself every month.

## Keeping it right

- **Index changes.** FTSE Russell reviews the indices in March, June, September and December. When a company joins or leaves, moves between the FTSE 100 and FTSE 250, or a CEO changes, update `data/cohort.csv` (the `index` column says which index each CEO's company is in, and drives the filter on the page). Investment trusts with no CEO are left out. The next build regenerates `data/apify_urls.txt`, so paste the new list into both Apify tasks.
- **New appointments.** Each run's summary lists anyone with two or more posts who isn't on the cohort list. That's your prompt to check for a new CEO.
- **"New" badges.** Put `Y` in the `new_to_cohort` column to show the badge, and clear it once someone's settled in.
- **Missing follower counts.** If a profile isn't returned, the page uses that CEO's last known count from `data/followers_fallback.csv`. You can type a count in there by hand, as was done for Andy Briggs.
- **Keeping the schedule alive.** GitHub pauses scheduled workflows in public repos after 60 days with no activity. The monthly snapshot commit counts as activity, so this one stays awake.

## Run it locally

```bash
python scripts/build.py --posts posts.json --followers profiles.json
```

The page appears in `site/index.html`. Add `--as-of 2026-11-25` to build for a past date. No packages needed beyond Python 3.10+.
