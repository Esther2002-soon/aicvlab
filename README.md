# AICV Lab website

Static site for the AICV Lab (National Yang Ming Chiao Tung University), built with Jekyll and served by GitHub Pages.
The layout is adapted from <https://github.com/mingching/mingching.github.io> (MIT License, see `LICENSE`).

## One-time setup

1. Create a repository, push these files to the `main` branch.
2. **Settings > Pages > Build and deployment > Source: GitHub Actions.**
3. Create a free account at <https://serpapi.com>, copy the API key from the dashboard.
4. **Settings > Secrets and variables > Actions > New repository secret**, name `SERPAPI_API_KEY`, value is the key.
   Never put the key in a file, the repository is public.
5. **Actions > Update publications from Google Scholar > Run workflow.** This fills the Publications section.
   The site is rebuilt automatically afterwards. Later it runs by itself every day at 03:00 Taiwan time.
6. Optional. Open `_config.yml` and set `url` to the final address, for example `https://YOUR-USER.github.io`.

If the repository is named `YOUR-USER.github.io` the site lives at `https://YOUR-USER.github.io/`.
Any other repository name becomes a project site at `https://YOUR-USER.github.io/REPO/`, the build handles that path automatically.
Moving from a personal account to the lab account later only needs steps 1 to 5 again.

## How publications are updated

`scripts/fetch_scholar.py` reads Professor Hsieh's Google Scholar profile (ID `mXUOEzwAAAAJ`) through SerpApi, 100 papers per request,
and writes `_data/scholar_publications.json` and `_data/scholar_stats.json`.

* The files are rewritten only when something changed (a new paper, a new citation count). Unchanged days make no commit.
* If Scholar returns nothing, or the list shrinks by more than 10 percent, the run fails and keeps the old data.
  GitHub then emails the repository owner about the failed run.
* Cost. 365 papers need 4 requests per run, about 120 per month. The SerpApi free plan allows 250 per month.
  If the lab ever grows past roughly 800 papers, change the schedule in `.github/workflows/update-scholar.yml` to every second day.
* Titles link to Google Scholar. Authors are shown the way Scholar lists them, long author lists end with "...".
* GitHub pauses scheduled workflows in a repository with no activity for 60 days. The daily data commits normally keep it alive,
  if the Publications section stops updating, open the Actions tab and press "Enable workflow".

Run it by hand on your own computer:

```bash
SERPAPI_API_KEY=your_key python3 scripts/fetch_scholar.py --data-dir _data
```

## Editing content

Everything is data, no HTML editing is needed. Edit, commit, the site rebuilds.

| What | File |
|---|---|
| Lab name, address | `_data/lab.yml` |
| Advisor biography | `_data/advisor.yml` |
| News (grouped by year, newest first) | `_data/news.yml` |
| Awards (grouped by year) | `_data/awards.yml` |
| Students and alumni | `_data/people.yml` |
| GPU servers | `_data/equipment.yml` |
| Gallery | `_data/gallery.yml` |
| Course videos, demos | `_data/courses.yml`, `_data/demos.yml` |
| Datasets, coding practice | `_data/resources.yml`, `_data/coding_practice.yml` |
| Navigation bar | `_data/navigation.yml` |

**Add a member photo.** Put a photo in `assets/img/people/` (square works best, WebP or JPG) and add one line to the person in `_data/people.yml`:

```yaml
- name: 劉昊然
  photo: assets/img/people/liu-haoran.webp
```

People without a `photo` show an empty placeholder circle.

**Add a news item.** Copy an entry under the current year in `_data/news.yml`. `images`, `videos` (YouTube IDs) and `links` are optional.
A new year needs a new `- year:` block at the top.

**Images.** Convert to WebP at the original resolution, for example `cwebp -q 92 in.jpg -o out.webp`, and set `w` and `h` to the pixel size.

**Do not publish remote access details.** `_data/equipment.yml` lists models and counts only. IP addresses and AnyDesk IDs must never go into this repository.

## Local preview

```bash
bundle _2.6.7_ install
bundle _2.6.7_ exec jekyll serve --watch
```

Then open <http://127.0.0.1:4000/>. Add `?theme=dark` to the address to check dark mode.

## About `tools/`

`tools/convert_old_site.py` is the one-off script that converted the old WordPress site into the files under `_data/` and `assets/img/`.
It is kept for reference only and is not part of the site build.
