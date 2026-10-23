"""Render every queued Reel to reels_preview/ so you can watch them on this PC (nothing is posted)."""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
for line in open(r"D:\POD\.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
import publish_job as pj  # noqa: E402

out = os.path.join(ROOT, "reels_preview")
os.makedirs(out, exist_ok=True)
queue = json.load(open("content_queue.json", encoding="utf-8"))
reels = [i for i in queue if i.get("type") == "reel" and i["status"] == "ready"]
for n, it in enumerate(reels, 1):
    name = f"{it['date_str']}_{it['time_est'].split()[0].replace(':', '')}{it['time_est'].split()[1]}_{it['content_type'][5:]}_{re.sub(r'[^A-Za-z0-9]+', '-', it['title'])[:40]}.mp4"
    dst = os.path.join(out, name)
    if os.path.exists(dst):
        continue
    try:
        shutil.copy(pj.prepare_reel(it), dst)
        print(f"[{n}/{len(reels)}] {name}", flush=True)
    except Exception as e:
        print(f"[{n}/{len(reels)}] FAILED {name}: {e}", flush=True)
print("done", flush=True)
