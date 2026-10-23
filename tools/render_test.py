"""Render one Reel exactly as the scheduler would, without posting anything (used by the Reel render check workflow)."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import publish_job as pj  # noqa: E402

queue = json.load(open("content_queue.json", encoding="utf-8"))
reels = [i for i in queue if i.get("type") == "reel" and i.get("status") == "ready"]
picks = [next(r for r in reels if r["source"]["kind"] == "video"), next(r for r in reels if r["source"]["kind"] == "photo")]
os.makedirs("out", exist_ok=True)
for n, item in enumerate(picks):
    path = pj.prepare_reel(item)
    dst = f"out/test_{n}_{item['source']['kind']}.mp4"
    os.replace(path, dst)
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,duration", "-of", "csv=p=0", dst],
                          capture_output=True, text=True).stdout
    print(dst, os.path.getsize(dst) // 1024, "KB |", info.replace("\n", " | "))
