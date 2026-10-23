"""Build a Reel (1080x1920, H.264 + silent AAC) from a Pexels video or photo.

Text timeline: hook -> payoff (both at the top) -> follow CTA card (bottom, last 3 seconds).
Everything is relative to the repository root so the same code runs locally and in GitHub Actions.
"""
import json
import glob
import os
import random
import shutil
import subprocess
import textwrap
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK = ".render"
FONT = "assets/Anton-Regular.ttf"
FOLLOW = "FOLLOW @germanshepherdco\nFOR DAILY SHEPHERD CONTENT"
UA = {"User-Agent": "Mozilla/5.0 (german-shepherd-publisher)"}


def ensure_ffmpeg():
    """GitHub's Ubuntu runners do not include ffmpeg; install it on demand (only when a Reel is rendered)."""
    if shutil.which("ffmpeg"):
        return
    print("Installing ffmpeg...")
    subprocess.run(["sudo", "apt-get", "update", "-qq"], check=True)
    subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "ffmpeg"], check=True)


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=dict(UA, **(headers or {})))
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def fetch_source(src, pexels_key):
    """src: {"kind": "video"|"photo", "id": int}. Returns a local file path."""
    os.makedirs(os.path.join(ROOT, WORK), exist_ok=True)
    auth = {"Authorization": pexels_key}
    if src["kind"] == "video":
        info = json.loads(_get(f"https://api.pexels.com/videos/videos/{src['id']}", auth))
        files = [f for f in info["video_files"] if f["file_type"] == "video/mp4" and f["width"] <= 1920]
        files.sort(key=lambda f: abs((f["height"] or 0) - 1920))
        link, ext = files[0]["link"], "mp4"
    else:
        info = json.loads(_get(f"https://api.pexels.com/v1/photos/{src['id']}", auth))
        link, ext = info["src"]["large2x"], "jpg"
    path = os.path.join(WORK, f"src_{src['kind']}_{src['id']}.{ext}")
    with open(os.path.join(ROOT, path), "wb") as f:
        f.write(_get(link))
    return path


def _textfile(name, text, width):
    path = os.path.join(WORK, name)
    with open(os.path.join(ROOT, path), "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(textwrap.wrap(text, width=width)))
    return path.replace("\\", "/")


def pick_music(seed):
    """Pick one of the bundled royalty-free tracks at random (repeatable for the same seed)."""
    tracks = sorted(glob.glob(os.path.join(ROOT, "assets", "music", "*.mp3")))
    return os.path.relpath(random.Random(seed).choice(tracks), ROOT).replace("\\", "/") if tracks else None


def render_reel(src_path, kind, hook, payoff, out_path, duration=12, cta=FOLLOW, music=None):
    ensure_ffmpeg()
    os.makedirs(os.path.join(ROOT, WORK), exist_ok=True)
    hook_f = _textfile("hook.txt", hook, 22)
    pay_f = _textfile("payoff.txt", payoff, 24)
    cta_f = os.path.join(WORK, "cta.txt").replace("\\", "/")
    with open(os.path.join(ROOT, cta_f), "w", encoding="utf-8", newline="") as f:
        f.write(cta)
    t_pay = round(duration * 0.3, 1)
    t_cta = duration - 3.0
    style = (f"fontfile={FONT}:fontcolor=white:borderw=6:bordercolor=black:shadowx=2:shadowy=3:"
             "shadowcolor=black@0.6:line_spacing=14:text_align=center")
    text = (
        f"drawtext=textfile={hook_f}:{style}:fontsize=82:x=(w-text_w)/2:y=200:enable='between(t,0.3,{t_pay})',"
        f"drawtext=textfile={pay_f}:{style}:fontsize=76:x=(w-text_w)/2:y=200:enable='between(t,{t_pay},{t_cta})',"
        f"drawbox=x=190:y=1560:w=700:h=116:color=black@0.5:t=fill:enable='gte(t,{t_cta})',"
        f"drawtext=textfile={cta_f}:fontfile={FONT}:fontcolor=#FFD84D:borderw=3:bordercolor=black:line_spacing=8:"
        f"text_align=center:fontsize=33:x=(w-text_w)/2:y=1580:enable='gte(t,{t_cta})'"
    )
    if kind == "photo":
        fc = (
            "[0:v]split=2[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,eq=brightness=-0.08[bg];"
            "[b]scale=1080:-2:flags=lanczos[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p,"
            "zoompan=z='min(1.0+0.0007*on,1.14)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,"
            + text + "[v]"
        )
        inp = ["-loop", "1", "-framerate", "30", "-i", src_path]
    else:
        fc = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p," + text + "[v]"
        inp = ["-stream_loop", "-1", "-i", src_path]
    audio_in = ["-stream_loop", "-1", "-i", music] if music else ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    afilter = [f"afade=t=out:st={duration - 1.5}:d=1.5"] if music else []
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inp + audio_in + [
        "-t", str(duration), "-filter_complex", fc, "-map", "[v]", "-map", "1:a"] + (["-af", ",".join(afilter)] if afilter else []) + [
        "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True, cwd=ROOT)
    return out_path
