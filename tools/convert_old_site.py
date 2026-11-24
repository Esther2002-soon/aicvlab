#!/usr/bin/env python3
"""Convert the mirrored WordPress site (AICV lab) into Jekyll data files + WebP images.

Run:  python3 -I convert_old_site.py <old_site_root> <new_site_root>

- Images are never down-scaled. JPEG -> lossy WebP q92, PNG -> lossless WebP.
- Nothing is translated. Chinese titles are kept as they were on the old site.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import yaml
from bs4 import BeautifulSoup, NavigableString
from PIL import Image, ImageOps

ROOT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
UP = ROOT / "wp-content" / "uploads"
IMG_OUT = OUT / "assets" / "img"
DATA = OUT / "_data"
DATA.mkdir(parents=True, exist_ok=True)

OrderedDict = dict  # plain dicts keep insertion order and dump cleanly to YAML
CJK = "㐀-鿿　-〿＀-￯"
LOG = []


def log(msg):
    LOG.append(msg)


# --------------------------------------------------------------------------- images
_index = {}
for _p in UP.rglob("*"):
    if _p.is_file():
        _name = unquote(_p.name.split("?")[0]).lower()
        _index.setdefault((str(_p.parent.relative_to(UP)), _name), []).append(_p)
        _index.setdefault(("*", _name), []).append(_p)

_img_cache = {}
_used_names = set()


def _area(p):
    try:
        with Image.open(p) as im:
            return im.size[0] * im.size[1]
    except Exception:
        return -1


def resolve_source(rel):
    rel = unquote(rel.split("?")[0])
    m = re.search(r"wp-content/uploads/(.+)$", rel)
    if not m:
        return None
    sub = m.group(1)
    d, name = os.path.split(sub)
    cands = _index.get((d, name.lower())) or _index.get(("*", name.lower())) or []
    cands = [c for c in cands if _area(c) > 0]
    if not cands:
        return None
    return max(cands, key=_area)


def slugify(name):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower()
    return s[:60] or "img"


def convert_image(rel, bucket):
    """Return dict(src, w, h) for a WordPress upload path, converting to WebP."""
    if rel in _img_cache:
        return _img_cache[rel]
    src = resolve_source(rel)
    if src is None:
        log(f"MISSING image: {rel}")
        _img_cache[rel] = None
        return None
    stem = slugify(Path(unquote(src.name.split("?")[0])).stem)
    ym = re.search(r"uploads/(\d{4})/(\d{2})/", str(src).replace("\\", "/"))
    prefix = f"{ym.group(1)}{ym.group(2)}-" if ym else ""
    name = f"{prefix}{stem}"
    n = 1
    base = name
    while (bucket, name) in _used_names:
        n += 1
        name = f"{base}-{n}"
    _used_names.add((bucket, name))
    dest_dir = IMG_OUT / bucket
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}.webp"
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        is_png = src.name.split("?")[0].lower().endswith(".png")
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
        if is_png:
            im.save(dest, "WEBP", lossless=True, method=4)
        else:
            im.save(dest, "WEBP", quality=92, method=6)
    res = {"src": f"assets/img/{bucket}/{name}.webp", "w": w, "h": h, "_src": str(src)}
    _img_cache[rel] = res
    return res


def ahash(path):
    with Image.open(path) as im:
        g = ImageOps.exif_transpose(im).convert("L").resize((8, 8))
        px = list(g.get_flattened_data()) if hasattr(g, "get_flattened_data") else list(g.getdata())
    avg = sum(px) / 64
    return sum((1 << i) for i, v in enumerate(px) if v > avg)


def hamming(a, b):
    return bin(a ^ b).count("1")


# --------------------------------------------------------------------------- html walking
def content(page):
    p = ROOT / page / "index.html" if page else ROOT / "index.html"
    s = BeautifulSoup(p.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    c = s.select_one(".entry-content") or s.select_one("article") or s
    for x in c.select("script,style,.sharedaddy,#jp-post-flair,.wordads-ad-wrapper"):
        x.decompose()
    return c


def orig_rel(img):
    u = img.get("data-orig-file") or img.get("src", "")
    u = unquote(u.split("?")[0])
    if "aicvlab2019.wordpress.com/" in u:
        u = u.split("aicvlab2019.wordpress.com/", 1)[-1]
    return u.replace("../", "")


def events(c):
    """Flatten an entry-content tree into ordered events."""
    for el in c.descendants:
        if isinstance(el, NavigableString):
            continue
        n = el.name
        if n in ("h1", "h2", "h3", "h4", "h5", "h6"):
            t = el.get_text(" ", strip=True)
            if t:
                yield ("h", n, t)
        elif n == "p" and not el.find_parent(["li", "figcaption"]):
            t = el.get_text(" ", strip=True)
            if t:
                yield ("p", t)
        elif n == "li":
            t = el.get_text(" ", strip=True)
            if t:
                yield ("li", t)
        elif n == "img":
            rel = orig_rel(el)
            if "wp-content/uploads" in rel:
                yield ("img", rel)
        elif n == "iframe":
            u = el.get("src") or el.get("data-src") or ""
            m = re.search(r"youtube(?:-nocookie)?\.com/embed/([\w-]+)", u)
            if m:
                yield ("yt", m.group(1))
        elif n == "a" and el.get("href") and not el.find("img"):
            if el.find_parent(["p", "li"]) is None or True:
                yield ("a", el.get_text(" ", strip=True), el["href"])


def dump_yaml(name, obj):
    with open(DATA / name, "w", encoding="utf-8") as f:
        f.write("# Generated by tools/convert_old_site.py from the old WordPress site. Safe to edit by hand.\n")
        yaml.safe_dump(obj, f, allow_unicode=True, sort_keys=False, width=1000)


def clean_imgs(items):
    return [{k: v for k, v in i.items() if not k.startswith("_")} for i in items if i]


# --------------------------------------------------------------------------- news
def year_from_title(t):
    m = re.search(r"\b(20\d\d)\b", t)
    return int(m.group(1)) if m else None


def upload_year(rel):
    m = re.search(r"uploads/(\d{4})/", rel)
    return int(m.group(1)) if m else None


def parse_news():
    items = []
    cur = None
    for ev in events(content("news")):
        if ev[0] == "h":
            title = ev[2]
            if title in ("Newspaper", "News On Youtube") or title.startswith("Read More"):
                if title.startswith("Read More") and cur is not None:
                    pass
                cur = cur if title != "Newspaper" else cur
                continue
            m = re.match(r"\[(\d{4})/(\d{1,2})(?:/(\d{1,2}))?\]\s*(.*)", title)
            cur = {"date": "", "year": None, "title": title, "images": [], "videos": [], "text": "", "links": []}
            if m:
                y, mo, d, rest = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
                cur["year"] = y
                cur["date"] = f"{y}.{mo:02d}" + (f".{int(d):02d}" if d else "")
                cur["title"] = rest or title
            items.append(cur)
        elif cur is None:
            continue
        elif ev[0] == "img":
            cur["images"].append(ev[1])
        elif ev[0] == "yt":
            cur["videos"].append(ev[1])
        elif ev[0] == "p":
            if not re.match(r"^https?://\S+$", ev[1]):
                cur["text"] = (cur["text"] + " " + ev[1]).strip()
            else:
                cur["links"].append({"label": "Link", "url": ev[1]})
        elif ev[0] == "a":
            if ev[2].startswith("http") and "wordpress.com" not in ev[2]:
                cur["links"].append({"label": ev[1] or "Link", "url": ev[2]})
    # infer years
    prev_year = None
    for it in items:
        if it["year"] is None:
            it["year"] = year_from_title(it["title"])
        if it["year"] is None:
            for rel in it["images"]:
                uy = upload_year(rel)
                if uy:
                    it["year"] = uy
                    break
        if it["year"] is None:
            it["year"] = prev_year
        if it["year"] is None:
            it["year"] = 2020
        prev_year = it["year"]
        if not it["date"]:
            it["date"] = str(it["year"])
    return items


def build_news(items):
    by_year = OrderedDict()
    for it in items:
        imgs = [convert_image(r, "news") for r in it["images"]]
        rec = OrderedDict()
        rec["date"] = it["date"]
        rec["title"] = it["title"]
        if it["text"]:
            rec["text"] = it["text"]
        if imgs and any(imgs):
            rec["images"] = clean_imgs(imgs)
        if it["videos"]:
            rec["videos"] = list(dict.fromkeys(it["videos"]))
        # drop duplicate links
        seen = set()
        links = []
        for l in it["links"]:
            if l["url"] not in seen:
                seen.add(l["url"])
                links.append(l)
        if links:
            rec["links"] = links
        by_year.setdefault(it["year"], []).append(rec)
    years = sorted(by_year, reverse=True)
    return [{"year": y, "items": by_year[y]} for y in years]


# --------------------------------------------------------------------------- awards
def split_bilingual(t):
    t = re.sub(r"\s+", " ", t).strip()
    if not re.search(f"[{CJK}]", t):
        return t, ""
    for m in re.finditer(r"\s+(?=[A-Za-z0-9“\"])", t):
        rest = t[m.end():]
        if not re.search(f"[{CJK}]", rest):
            return rest.strip(), t[: m.start()].strip()
    return "", t


def tier_of(t):
    if re.search(r"第一名|一等獎|First place|Winner|Champion|冠軍|(?<![\d])1st\b", t, re.I):
        return "gold"
    if re.search(r"第二名|二等獎|Second place|(?<![\d])2nd\b", t, re.I):
        return "silver"
    if re.search(r"第三名|三等獎|Third place|(?<![\d])3rd\b", t, re.I):
        return "bronze"
    return ""


def parse_awards():
    c = content("adivisor")
    out, on = [], False
    for ev in events(c):
        if ev[0] == "h":
            on = ev[2].lower().startswith("honors")
            continue
        if on and ev[0] == "li":
            out.append(ev[1])
    res, prev = [], None
    for t in out:
        years = [int(y) for y in re.findall(r"(?<!\d)(20\d\d)(?!\d)", t)]
        m = re.search(r"(?<!\d)(1[01]\d)年度", t)
        if m:
            years.append(int(m.group(1)) + 1911)
        y = max(years) if years else prev
        prev = y
        en, zh = split_bilingual(t)
        rec = OrderedDict()
        rec["year"] = y
        rec["title"] = en or zh
        if en and zh:
            rec["zh"] = zh
        tr = tier_of(t)
        if tr:
            rec["tier"] = tr
        res.append(rec)
    return res


def award_certificates(news_items):
    """Certificate images on the old Award page that are not already shown under News."""
    known = []
    for it in news_items:
        for rel in it["images"]:
            r = _img_cache.get(rel)
            if r:
                known.append(ahash(r["_src"]))
    home_imgs = [e[1] for e in events(content("")) if e[0] == "img"]
    for rel in home_imgs:
        src = resolve_source(rel)
        if src:
            known.append(ahash(src))
    left, seen = [], []
    for ev in events(content("award")):
        if ev[0] != "img":
            continue
        src = resolve_source(ev[1])
        if not src:
            continue
        h = ahash(src)
        if any(hamming(h, k) <= 4 for k in known + seen):
            continue
        seen.append(h)
        name = unquote(src.name)
        ym = re.search(r"(?<!\d)(20[012]\d)(?!\d)", name)
        year = int(ym.group(1)) if ym else upload_year(ev[1]) or 2020
        left.append((year, ev[1]))
    return left


# --------------------------------------------------------------------------- people
def parse_people():
    t = ""
    for ev in events(content("member")):
        if ev[0] in ("p", "li", "h"):
            t += " " + ev[-1]
    t = re.sub(r"\s+", " ", t)
    text = content("member").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    def section(a, b):
        m = re.search(re.escape(a) + r"(.*?)" + (re.escape(b) if b else r"$"), text)
        return m.group(1).strip() if m else ""

    def split_names(s):
        names = []
        for part in [x.strip() for x in s.split("｜") if x.strip()]:
            toks = re.split(r"\s+", part)
            if len(toks) > 1 and re.search(f"[{CJK}]", part) and re.search(r"[A-Za-z]", part):
                cur = []
                for tk in toks:
                    if cur and (bool(re.search(f"[{CJK}]", tk)) != bool(re.search(f"[{CJK}]", cur[-1]))):
                        names.append(" ".join(cur))
                        cur = []
                    cur.append(tk)
                if cur:
                    names.append(" ".join(cur))
            else:
                names.append(part.replace(" ", "") if re.fullmatch(f"[{CJK} ]+", part) else part)
        return names

    phd = split_names(section("Ph.D. Students", "Master Students"))
    ms = split_names(section("Master Students", "Ph.D. Alumni"))

    def alumni(s):
        parts = re.split(r"(\d{3})學年度｜", s)
        out = []
        for i in range(1, len(parts) - 1, 2):
            roc = int(parts[i])
            names = split_names(parts[i + 1])
            out.append({"roc": roc, "label": f"{roc + 1911}–{roc + 1912}", "names": names})
        return out

    phd_al = alumni(section("Ph.D. Alumni", "Master Alumni"))
    ms_al = alumni(section("Master Alumni", None))
    return {
        "advisor": {"name": "Jun-Wei Hsieh", "zh": "謝君偉", "title": "Professor, College of AI, National Yang Ming Chiao Tung University"},
        "current": [
            {"group": "Ph.D. Students", "people": [{"name": n} for n in phd]},
            {"group": "Master Students", "people": [{"name": n} for n in ms]},
        ],
        "alumni": [
            {"group": "Ph.D. Alumni", "years": phd_al},
            {"group": "Master Alumni", "years": ms_al},
        ],
    }


# --------------------------------------------------------------------------- albums
def parse_albums():
    events_l, cur = [], None
    for ev in events(content("albums")):
        if ev[0] in ("h", "p") and re.match(r"^\d{4}/\d{1,2}(/\d{1,2})?\s", ev[-1]):
            m = re.match(r"^(\d{4})/(\d{1,2})(?:/(\d{1,2}))?\s+(.*)", ev[-1])
            y, mo, d, title = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
            cur = {"year": y, "date": f"{y}.{mo:02d}" + (f".{int(d):02d}" if d else ""), "title": title, "images": [], "note": ""}
            events_l.append(cur)
        elif cur is not None and ev[0] == "img":
            cur["images"].append(ev[1])
        elif cur is not None and ev[0] == "p":
            cur["note"] = (cur["note"] + " " + ev[1]).strip()
    by_year = OrderedDict()
    for e in events_l:
        imgs = [convert_image(r, "gallery") for r in e["images"]]
        rec = OrderedDict(date=e["date"], title=e["title"])
        if e["note"]:
            rec["note"] = e["note"]
        rec["images"] = clean_imgs(imgs)
        by_year.setdefault(e["year"], []).append(rec)
    return [{"year": y, "events": by_year[y]} for y in sorted(by_year, reverse=True)]


# --------------------------------------------------------------------------- courses / demos / coding
def parse_courses():
    groups = OrderedDict()
    for ev in events(content("classes")):
        if ev[0] == "h":
            t = ev[2]
            m = re.match(r"^【\s*(.+?)\s*】\s*(.*)$", t)
            series, title = (m.group(1), m.group(2)) if m else ("Other", t)
            cur = {"title": title or t, "video": None}
            groups.setdefault(series, []).append(cur)
        elif ev[0] == "yt" and groups:
            list(groups.values())[-1][-1]["video"] = ev[1]
    return [{"series": s, "lectures": [l for l in ls if l["video"]]} for s, ls in groups.items()]


def parse_demos():
    out, cur = [], None
    for ev in events(content("resource")):
        if ev[0] == "h":
            cur = {"title": ev[2], "videos": [], "images": [], "text": ""}
            out.append(cur)
        elif cur is None:
            continue
        elif ev[0] == "yt":
            cur["videos"].append(ev[1])
        elif ev[0] == "img":
            cur["images"].append(ev[1])
        elif ev[0] == "p":
            cur["text"] = (cur["text"] + " " + ev[1]).strip()
    res = []
    for d in out:
        rec = OrderedDict(title=d["title"])
        if d["text"]:
            rec["text"] = d["text"]
        if d["videos"]:
            rec["videos"] = d["videos"]
        imgs = [convert_image(r, "demo") for r in d["images"]]
        if any(imgs):
            rec["images"] = clean_imgs(imgs)
        res.append(rec)
    return res


def parse_coding():
    idx = content("coding-practice")
    entries = []
    for a in idx.select("a.wp-block-button__link"):
        t = a.get_text(" ", strip=True)
        href = a.get("href", "")
        slug = href.split("/")[-2] if href.endswith("index.html") else href.strip("/").split("/")[-1]
        entries.append((t, slug))
    res = []
    for title, slug in entries:
        if not (ROOT / slug / "index.html").exists():
            log(f"coding page missing: {slug}")
            continue
        rec = OrderedDict(title=re.sub(r"\s*:\s*", ": ", title, count=1))
        paras, imgs, links = [], [], []
        for ev in events(content(slug)):
            if ev[0] == "p":
                paras.append(ev[1])
            elif ev[0] == "li":
                paras.append("- " + ev[1])
            elif ev[0] == "img":
                imgs.append(ev[1])
            elif ev[0] == "a" and ev[2].startswith("http") and "wordpress.com" not in ev[2]:
                links.append({"label": ev[1] or ev[2], "url": ev[2]})
        paras = [p for p in paras if not p.startswith("Search this web")]
        rec["text"] = paras
        im = [convert_image(r, "coding") for r in imgs]
        if any(im):
            rec["images"] = clean_imgs(im)
        seen, ls = set(), []
        for l in links:
            if l["url"] not in seen:
                seen.add(l["url"])
                ls.append(l)
        if ls:
            rec["links"] = ls
        res.append(rec)
    return res


# --------------------------------------------------------------------------- home / advisor
def parse_advisor():
    sec, cur = None, None
    prof = OrderedDict(education=[], experience=[], fields=[])
    for ev in events(content("adivisor")):
        if ev[0] == "h":
            h = ev[2].lower()
            sec = "education" if h.startswith("education") else "experience" if h.startswith("experience") else "fields" if h.startswith("professional") else None
            continue
        if sec and ev[0] in ("p", "li"):
            prof[sec].append(ev[1].replace("​", "").strip())
    return prof


def main():
    log("== images index: %d files" % sum(1 for k in _index if k[0] != "*"))
    news_items = parse_news()
    news = build_news(news_items)
    dump_yaml("news.yml", news)

    awards = parse_awards()
    certs = award_certificates(news_items)
    cert_by_year = {}
    for y, rel in certs:
        r = convert_image(rel, "awards")
        if r:
            cert_by_year.setdefault(y, []).append({k: v for k, v in r.items() if not k.startswith("_")})
    by_year = OrderedDict()
    for a in awards:
        by_year.setdefault(a["year"], []).append({k: v for k, v in a.items() if k != "year"})
    all_years = sorted(set(by_year) | set(cert_by_year), reverse=True, key=lambda y: (y is None, y))
    dump_yaml(
        "awards.yml",
        [{"year": y, "items": by_year.get(y, []), "certificates": cert_by_year.get(y, [])} for y in all_years],
    )

    dump_yaml("people.yml", parse_people())
    dump_yaml("gallery.yml", parse_albums())
    dump_yaml("courses.yml", parse_courses())
    dump_yaml("demos.yml", parse_demos())
    dump_yaml("coding_practice.yml", parse_coding())

    adv = parse_advisor()
    ph = convert_image("wp-content/uploads/2020/03/jun-wei-hsieh-270x270_c-2.jpg", "people") or convert_image(
        "wp-content/uploads/2020/03/jun-wei-hsieh-270x270_c-1.jpg", "people"
    )
    hero = convert_image("wp-content/uploads/2020/03/1398312.jpg", "site")
    adv["photo"] = {k: v for k, v in (ph or {}).items() if not k.startswith("_")}
    adv["name"] = "Jun-Wei Hsieh"
    adv["zh"] = "謝君偉"
    adv["title"] = "Professor, College of AI, National Yang Ming Chiao Tung University, Taiwan"
    dump_yaml("advisor.yml", adv)
    if hero:
        log(f"hero image {hero['w']}x{hero['h']} -> {hero['src']}")

    # equipment photos
    eq = OrderedDict()
    for key, rel in [
        ("rack1", "wp-content/uploads/2021/02/13589108052754.jpg"),
        ("rack2", "wp-content/uploads/2021/02/13589109763739.jpg"),
        ("gpu", "wp-content/uploads/2020/03/equipment1.png"),
        ("uav", "wp-content/uploads/2020/03/equipment2.jpg"),
        ("imac", "wp-content/uploads/2020/03/equipment3.jpeg"),
        ("printer", "wp-content/uploads/2020/03/equipment4.jpeg"),
        ("laptop", "wp-content/uploads/2020/03/equipment5.jpeg"),
        ("jetson", "wp-content/uploads/2020/03/equipment6.jpg"),
    ]:
        r = convert_image(rel, "equipment")
        eq[key] = {k: v for k, v in (r or {}).items() if not k.startswith("_")}
    dump_yaml("equipment_photos.yml", eq)

    # summary
    sizes = sum(p.stat().st_size for p in IMG_OUT.rglob("*.webp"))
    src_sizes = sum(Path(v["_src"]).stat().st_size for v in _img_cache.values() if v)
    log(f"images converted: {sum(1 for v in _img_cache.values() if v)}  webp={sizes/1e6:.1f} MB  source={src_sizes/1e6:.1f} MB")
    print("\n".join(LOG))


if __name__ == "__main__":
    main()
