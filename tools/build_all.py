"""Build the queue from Oct 24 to Dec 4, 2026 into content_queue_merged.json.
- 3 static posts/day (Oct 29 onward new; Oct 24-28 are the existing posts, retimed and fixed)
- 3 Reels/day from Oct 24
Static images are rendered to content_assets/. Reels are described in the queue and rendered at publish time.
Run from the repository root:  python tools/build_all.py"""
import datetime as dt
import io
import itertools
import json
import os
import random
import re
import sys
import urllib.request
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "content"))
from static_30 import STATIC  # noqa: E402
from reels_30 import HUMOR, FACTS, TIPS  # noqa: E402
from gap_content import STATIC_PRE, TITLES_PRE, PILLARS_PRE, HUMOR_PRE, FACTS_PRE, TIPS_PRE  # noqa: E402

ET = ZoneInfo("America/New_York")
MAIN_START = dt.date(2026, 11, 5)
REEL_START = dt.date(2026, 10, 24)
STATIC_START = dt.date(2026, 10, 29)
END = dt.date(2026, 12, 4)
FONT = os.path.join(ROOT, "assets", "Anton-Regular.ttf")
UA = {"User-Agent": "Mozilla/5.0 (german-shepherd-publisher)"}
FOLLOW = "Follow @germanshepherdco for daily German Shepherd content 🐾"
SLOT_OF = ["morning", "afternoon", "evening"]

photos = [p for p in json.load(open(os.path.join(ROOT, "content", "photo_pool.json"), encoding="utf-8"))
          if "german shepherd" in p["alt"].lower()]
videos = json.load(open(os.path.join(ROOT, "content", "video_pool.json"), encoding="utf-8"))
tags = json.load(open(os.path.join(ROOT, "content", "hashtag_bank.json"), encoding="utf-8"))["clusters"]
cal = {r["date"]: r for r in json.load(open(os.path.join(ROOT, "calendar_plan.json"), encoding="utf-8"))[:30]}

random.Random(2026).shuffle(photos)
used = set()
counter = itertools.count(1)

PREFS = [
    (r"SNOW|COLD|WINTER|WHITE", r"snow|white|winter"), (r"PUPPY|FIRST NIGHT|LAND SHARK|TEETH", r"puppy"),
    (r"SLEEP|NAP|PILLOW|BED", r"sleep|lying|resting|laying"), (r"BLACK", r"black"),
    (r"SUNRISE|WALK|NIGHT", r"walk|sunrise|sunset|golden|path|trail"), (r"RAIN|WET|BATH", r"wet|rain|water"),
    (r"CHILD|NEWBORN|BABY|LITTLE ONES", r"child|boy|girl|baby|kid"), (r"LAP|HEAD ON|FLOOR", r"lap|owner|woman|man|person"),
]


def pick_photo(label):
    pref = next((rx for pat, rx in PREFS if re.search(pat, label.upper())), None)
    puppy_ok = bool(pref and "puppy" in pref)
    pools = []
    if pref:
        pools.append([p for p in photos if re.search(pref, p["alt"].lower())])
    pools.append([p for p in photos if puppy_ok or "puppy" not in p["alt"].lower()])
    pools.append(photos)
    for pool in pools:
        for p in pool:
            if p["id"] not in used:
                used.add(p["id"])
                return p
    raise RuntimeError("ran out of photos")


def download(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()


def wrap_lines(draw, text, font, max_w):
    lines, cur = [], ""
    for w in text.split():
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _cover(im, W, H):
    s = max(W / im.width, H / im.height)
    r = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    x, y = (r.width - W) // 2, int((r.height - H) * 0.35)
    return r.crop((x, y, x + W, y + H))


def render_static(photo, overlay, out_path):
    W, H = 1080, 1350
    im = Image.open(io.BytesIO(download(photo["src"]))).convert("RGB")
    if im.width / im.height >= 1.15:  # landscape: blurred backdrop, whole dog visible
        bg = _cover(im, W, H).filter(ImageFilter.GaussianBlur(28))
        bg = Image.blend(bg, Image.new("RGB", (W, H), "black"), 0.2)
        fg = im.resize((W, int(im.height * W / im.width)), Image.LANCZOS)
        bg.paste(fg, (0, (H - fg.height) // 2 + 60))
        canvas = bg
    else:
        canvas = _cover(im, W, H)
    shade = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(shade)
    for y in range(520):
        gd.line([(0, y), (W, y)], fill=int(190 * (1 - y / 520)))
    for y in range(H - 170, H):
        gd.line([(0, y), (W, y)], fill=int(170 * (y - (H - 170)) / 170))
    canvas = Image.composite(Image.new("RGB", (W, H), "black"), canvas, shade)
    d = ImageDraw.Draw(canvas)
    size = 96
    while True:
        f = ImageFont.truetype(FONT, size)
        lines = wrap_lines(d, overlay.upper(), f, W - 150)
        if len(lines) <= 4 or size <= 56:
            break
        size -= 6
    y = 80
    for ln in lines:
        w = d.textlength(ln, font=f)
        d.text(((W - w) / 2, y), ln, font=f, fill="white", stroke_width=6, stroke_fill="black")
        y += int(size * 1.12)
    bf = ImageFont.truetype(FONT, 34)
    brand = "GERMAN SHEPHERD CO"
    d.text(((W - d.textlength(brand, font=bf)) / 2, H - 70), brand, font=bf, fill=(255, 216, 77), stroke_width=3, stroke_fill="black")
    canvas.save(out_path, quality=84, optimize=True)


def hashtags(cluster_names, n, offset):
    seen, out = set(), []
    for name in cluster_names:
        for t in tags[name]:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return " ".join(out[(offset + i) % len(out)] for i in range(n))


def static_cluster(title, slot):
    t = title.upper()
    if slot == "morning":
        return ["viral_memes"]
    if slot == "afternoon":
        if re.search(r"1899|STEPHANITZ|K9|WORK|LINE|SADDLE|SABLE|SHEPHERDS|VETERAN|HERO", t):
            return ["working_dog_heritage", "emotional_tributes"]
        return ["emotional_tributes"]
    if re.search(r"PHOTO|ROLL CALL|PACK|SLEEP|THANKFUL|NICKNAME|TILT|TALK|LAND SHARK|GLOW|QUIRK|WRAP", t):
        return ["viral_memes", "radar_ears_and_puppy"]
    return ["working_dog_heritage", "viral_memes"]


# Peak US audience windows (Eastern time; the West Coast is 3 hours behind). Weekends start later.
WEEKDAY = {"morning": (7, 30), "reel1": (10, 30), "afternoon": (13, 0), "reel2": (16, 30), "evening": (19, 30), "reel3": (21, 30)}
WEEKEND = {"morning": (9, 0), "reel1": (11, 30), "afternoon": (13, 30), "reel2": (17, 0), "evening": (19, 30), "reel3": (21, 30)}


def item_base(d, slot):
    hh, mm = (WEEKEND if d.weekday() >= 5 else WEEKDAY)[slot]
    ts = int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET).timestamp())
    u = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    label = dt.datetime(d.year, d.month, d.day, hh, mm).strftime("%I:%M %p").lstrip("0") + " ET"
    return {"day": (d - dt.date(2026, 10, 22)).days + 1, "date_str": d.isoformat(), "slot": slot, "time_est": label,
            "utc_hour": u.hour, "utc_minute": u.minute, "platforms": ["facebook", "instagram"],
            "timestamp_unix": ts, "status": "ready"}


def new_static(d, si, overlay, body, title, pillar, off):
    slot = SLOT_OF[si]
    photo = pick_photo(overlay)
    fname = f"p{next(counter):03d}_{d.strftime('%m%d')}_{slot}.jpg"
    render_static(photo, overlay, os.path.join(ROOT, "content_assets", fname))
    it = item_base(d, slot)
    it.update({"type": "image", "content_type": pillar, "title": title, "image_path": "content_assets/" + fname,
               "caption": body + "\n\n" + hashtags(static_cluster(title, slot), 5, off + si),
               "pexels": {"kind": "photo", "id": photo["id"], "photographer": photo["photographer"]}})
    return it


def new_reel(d, ri, kind, tup, vi):
    hook, payoff, body = tup
    slot = ("reel1", "reel2", "reel3")[ri]
    if kind == "humor" and vi[0] < len(videos):
        v = videos[vi[0]]
        vi[0] += 1
        src = {"kind": "video", "id": v["id"], "photographer": v["photographer"]}
    else:
        p = pick_photo(hook + " " + payoff)
        src = {"kind": "photo", "id": p["id"], "photographer": p["photographer"]}
    cluster = ["viral_memes"] if kind == "humor" else ["working_dog_heritage", "viral_memes"]
    it = item_base(d, slot)
    it.update({"type": "reel", "content_type": "reel_" + kind, "title": hook.title(), "hook": hook, "payoff": payoff,
               "source": src, "duration": 12,
               "caption": body + "\n\n" + FOLLOW + "\n\n" + hashtags(cluster, 5, d.toordinal() + ri)})
    return it


os.makedirs(os.path.join(ROOT, "content_assets"), exist_ok=True)
queue_path = os.path.join(ROOT, "content_queue.json")
existing = json.load(open(queue_path, encoding="utf-8"))
# Keep what already exists; drop any earlier generated batch so reruns never duplicate.
existing = [i for i in existing if not str(i.get("image_path", "")).startswith("content_assets/p0") and i.get("type") != "reel"]

# --- fixes to previously queued posts: no product pitches, honest wording, retime to peak slots ---
FIX = {
    "Custom Ear Crewneck Preview": "Pop quiz: which sound gets your shepherd running the fastest? 📡\n\n1️⃣ The snack drawer  2️⃣ The leash clip  3️⃣ Car keys\n\nVote with a 1, 2 or 3 below! 👇\n\n#gsdears #pointyearsclub #germanshepherdoftheday #gsdcommunity #shepherdears",
    "German Shedder Coffee Fuel": "Monday evening debrief: powered by coffee and covered in German Shepherd fur. ☕🐾\n\nBe honest: how many dog hairs have you found in your coffee this week?\n\nDrop a ☕ if your drink has been 'seasoned' by a shepherd.\n\n#germanshepherdfunny #gsdhumor #gsdlife #shepherdlife #germanshepherdmom",
    "Loyal Guardian Vintage Tee": "Bred to work. Born to protect. Bound by loyalty. 🛡️\n\nThe German Shepherd breed was developed in Germany in the late 1800s as a herding and working dog, and that drive to have a job is still in every shepherd today.\n\nWhat job does your shepherd take the most seriously? 👇\n\n#gsdheritage #workingdog #shepherdpower #gsdguarddog #germanshepherdclub",
    "Weekly Pack Wrap-Up": "Another week with the pack done. 🐾\n\nWhat's the funniest thing your shepherd did this week? Tell us in the comments. We love reading these.\n\n#gsdcommunity #germanshepherdlove #gsdlife #shepherdlife #germanshepherdfamily",
}
NEW_IMG = {"German Shepherd Moms Are Built Different": "GSD MOMS: BUILT DIFFERENT", "Weekly Pack Wrap-Up": "WEEKLY PACK WRAP-UP"}
for it in existing:
    if it.get("status") in ("published", "withdrawn"):
        continue
    if it["title"] in FIX:
        it["caption"] = FIX[it["title"]]
    if it["title"] in NEW_IMG:
        ph = pick_photo(NEW_IMG[it["title"]])
        fname = f"p{next(counter):03d}_{it['date_str'][5:].replace('-', '')}_{it['slot']}.jpg"
        render_static(ph, NEW_IMG[it["title"]], os.path.join(ROOT, "content_assets", fname))
        it["image_path"] = "content_assets/" + fname
        it["pexels"] = {"kind": "photo", "id": ph["id"], "photographer": ph["photographer"]}
    d = dt.date.fromisoformat(it["date_str"])
    if d >= REEL_START and it["slot"] in SLOT_OF:  # Oct 23 stays as queued
        nb = item_base(d, it["slot"])
        for k in ("time_est", "utc_hour", "utc_minute", "timestamp_unix"):
            it[k] = nb[k]

new, vi = [], [0]
d = REEL_START
while d <= END:
    k = d.isoformat()
    if STATIC_START <= d < MAIN_START:
        n = (d - STATIC_START).days
        for si in range(3):
            overlay, body = STATIC_PRE[n * 3 + si]
            new.append(new_static(d, si, overlay, body, TITLES_PRE[n][si], PILLARS_PRE[si], n))
    elif d >= MAIN_START:
        n = (d - MAIN_START).days
        for si in range(3):
            overlay, body = STATIC[n * 3 + si]
            new.append(new_static(d, si, overlay, body, cal[k][SLOT_OF[si]]["title"], cal[k][SLOT_OF[si]]["pillar"], n))
    if d < MAIN_START:
        n = (d - REEL_START).days
        kinds = [("humor", HUMOR_PRE[n]), ("fact", FACTS_PRE[n]), ("tip", TIPS_PRE[n])]
    else:
        n = (d - MAIN_START).days
        kinds = [("humor", HUMOR[n]), ("fact", FACTS[n]), ("tip", TIPS[n])]
    random.Random(d.toordinal()).shuffle(kinds)
    for ri, (kind, tup) in enumerate(kinds):
        new.append(new_reel(d, ri, kind, tup, vi))
    d += dt.timedelta(days=1)

queue = sorted(existing + new, key=lambda i: i["timestamp_unix"])
json.dump(queue, open(os.path.join(ROOT, "content_queue_merged.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("new items:", len(new), "| static:", sum(1 for i in new if i["type"] == "image"),
      "| reels:", sum(1 for i in new if i["type"] == "reel"), "| videos used:", vi[0],
      "| ready total:", sum(1 for i in queue if i["status"] == "ready"))
