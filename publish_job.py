import os
import sys
import json
import time
import mimetypes
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

# Credentials from environment (set in GitHub Secrets)
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID")
META_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY") or "iqbal-jewel/german-shepherd-publisher"
GITHUB_REF_NAME = os.getenv("GITHUB_REF_NAME") or "main"

BASE_URL = "https://graph.facebook.com/v21.0"
QUEUE_FILE = "content_queue.json"

# Scheduling rules
MIN_GAP_SECONDS = 30 * 60       # never publish two posts closer than this (spreads out a catch-up)
STALE_SECONDS = 36 * 3600       # a slot missed by more than this is skipped, not posted late
OVERDUE_ALERT_SECONDS = 90 * 60  # a due post this late makes the run fail so GitHub emails you
MAX_ATTEMPTS = 20               # a post failing this many times stops retrying and is flagged
MAX_POSTS_PER_RUN = 1
SKIP_STATUSES = ("published", "withdrawn", "missed", "failed")


class MetaError(Exception):
    pass


def graph(method, path, params=None, body=None, headers=None):
    url = f"{BASE_URL}/{path}"
    data = body
    if method == "GET":
        url += "?" + urllib.parse.urlencode(dict(params or {}, access_token=META_TOKEN))
    elif data is None:
        data = urllib.parse.urlencode(dict(params or {}, access_token=META_TOKEN)).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise MetaError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")


def norm(text):
    return " ".join((text or "").split())[:80].lower()


def save_queue(queue):
    tmp = QUEUE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
    os.replace(tmp, QUEUE_FILE)


def live_captions():
    """Captions already live on the Page and on Instagram: id by normalized caption."""
    fb = {}
    for p in graph("GET", f"{FB_PAGE_ID}/posts", {"fields": "id,message", "limit": 50}).get("data", []):
        if p.get("message"):
            fb[norm(p["message"])] = p["id"]
    try:  # Reels are listed separately from regular posts
        for p in graph("GET", f"{FB_PAGE_ID}/video_reels", {"fields": "id,description", "limit": 50}).get("data", []):
            if p.get("description"):
                fb[norm(p["description"])] = p["id"]
    except MetaError as e:
        print(f"(could not list Facebook reels for the duplicate check: {e})")
    ig = {}
    for p in graph("GET", f"{IG_ACCOUNT_ID}/media", {"fields": "id,caption", "limit": 50}).get("data", []):
        if p.get("caption"):
            ig[norm(p["caption"])] = p["id"]
    return fb, ig


def publish_facebook_photo(caption, image_path):
    boundary = "----PodPublisherBoundary7MA4YWxkTrZu0gW"
    with open(image_path, "rb") as f:
        file_bytes = f.read()
    content_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    body = bytearray()
    for name, val in (("caption", caption), ("access_token", META_TOKEN)):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(val.encode("utf-8") + b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="source"; filename="{os.path.basename(image_path)}"\r\n'.encode())
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return graph("POST", f"{FB_PAGE_ID}/photos", body=bytes(body),
                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})


def publish_instagram_photo(caption, raw_url):
    container = graph("POST", f"{IG_ACCOUNT_ID}/media", {"image_url": raw_url, "caption": caption})
    creation_id = container.get("id")
    if not creation_id:
        raise MetaError(f"No Instagram container id: {container}")
    status = None
    for _ in range(20):
        time.sleep(3)
        status = graph("GET", creation_id, {"fields": "status_code"}).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise MetaError(f"Instagram container status {status}")
    if status != "FINISHED":
        raise MetaError(f"Instagram container not ready (last status {status})")
    return graph("POST", f"{IG_ACCOUNT_ID}/media_publish", {"creation_id": creation_id})


def upload_binary(url, path):
    """Resumable-upload endpoints used by Facebook and Instagram Reels (single-chunk upload)."""
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"OAuth {META_TOKEN}")
    req.add_header("offset", "0")
    req.add_header("file_size", str(len(data)))
    req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise MetaError(f"upload HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")


def publish_facebook_reel(caption, video_path, draft=False):
    start = graph("POST", f"{FB_PAGE_ID}/video_reels", {"upload_phase": "start"})
    video_id, upload_url = start.get("video_id"), start.get("upload_url")
    if not video_id or not upload_url:
        raise MetaError(f"Facebook reel start failed: {start}")
    upload_binary(upload_url, video_path)
    graph("POST", f"{FB_PAGE_ID}/video_reels", {
        "upload_phase": "finish", "video_id": video_id,
        "video_state": "DRAFT" if draft else "PUBLISHED", "description": caption})
    for _ in range(30):
        time.sleep(5)
        status = graph("GET", video_id, {"fields": "status"}).get("status", {})
        if status.get("video_status") == "error":
            raise MetaError(f"Facebook reel processing error: {status}")
        if status.get("video_status") in ("ready", "published") or status.get("publishing_phase", {}).get("status") == "complete":
            break
    return {"id": video_id}


def publish_instagram_reel(caption, video_path, publish=True):
    container = graph("POST", f"{IG_ACCOUNT_ID}/media", {
        "media_type": "REELS", "upload_type": "resumable", "caption": caption, "share_to_feed": "true"})
    creation_id, upload_url = container.get("id"), container.get("uri")
    if not creation_id or not upload_url:
        raise MetaError(f"Instagram reel container failed: {container}")
    upload_binary(upload_url, video_path)
    status = None
    for _ in range(40):
        time.sleep(5)
        status = graph("GET", creation_id, {"fields": "status_code,status"}).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise MetaError(f"Instagram reel status {status}")
    if status != "FINISHED":
        raise MetaError(f"Instagram reel not ready (last status {status})")
    if not publish:
        return {"id": creation_id, "unpublished": True}
    return graph("POST", f"{IG_ACCOUNT_ID}/media_publish", {"creation_id": creation_id})


def prepare_reel(item):
    """Download the Pexels source and render the Reel. Returns the local mp4 path."""
    import reel_render
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        raise MetaError("PEXELS_API_KEY is missing; cannot render the Reel")
    src = item["source"]
    src_path = reel_render.fetch_source(src, key)
    out = os.path.join(reel_render.WORK, f"reel_{item['timestamp_unix']}.mp4")
    reel_render.render_reel(src_path, src["kind"], item["hook"], item["payoff"], out, item.get("duration", 12),
                            music=reel_render.pick_music(item["timestamp_unix"]))
    return os.path.join(reel_render.ROOT, out)


def is_done(item):
    return all(item.get(f"{p}_published") for p in item.get("platforms", ["facebook", "instagram"]))


def last_published_unix(queue):
    latest = 0
    for item in queue:
        ts = item.get("published_at_utc")
        if ts:
            latest = max(latest, int(datetime.fromisoformat(ts).timestamp()))
    return latest


def run_once():
    missing = [n for n, v in (("META_PAGE_ACCESS_TOKEN", META_TOKEN), ("FB_PAGE_ID", FB_PAGE_ID),
                              ("IG_ACCOUNT_ID", IG_ACCOUNT_ID)) if not v]
    if missing:
        print(f"ERROR: missing environment values: {', '.join(missing)}")
        sys.exit(1)
    if not os.path.exists(QUEUE_FILE):
        print(f"ERROR: {QUEUE_FILE} not found.")
        sys.exit(1)
    return _pass()


def _pass():

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    now = int(time.time())
    print(f"Current UTC: {datetime.fromtimestamp(now, timezone.utc):%Y-%m-%d %H:%M}")

    # Slots missed by too long are skipped so a gap never turns into a late burst.
    changed = False
    for item in queue:
        if item.get("status") in SKIP_STATUSES or is_done(item):
            continue
        if item["timestamp_unix"] < now - STALE_SECONDS:
            item["status"] = "missed"
            print(f"Skipping stale slot: '{item['title']}' ({item['date_str']} {item['slot']})")
            changed = True
    if changed:
        save_queue(queue)

    pending = sorted(
        (i for i in queue if i.get("status") not in SKIP_STATUSES and not is_done(i)),
        key=lambda i: i["timestamp_unix"],
    )
    due = [i for i in pending if i["timestamp_unix"] <= now]
    if not due:
        if pending:
            nxt = pending[0]
            print(f"Nothing due. Next: '{nxt['title']}' at {nxt['date_str']} {nxt['time_est']}.")
        else:
            print("Queue is empty: add more posts to content_queue.json.")
        return 0, False

    # Guard against re-posting something that is already live (e.g. a run that posted but could not save).
    fb_live, ig_live = live_captions()

    errors = 0
    posted = 0
    for item in due:
        if posted >= MAX_POSTS_PER_RUN:
            break
        caption = item["caption"]
        key = norm(caption)
        platforms = item.get("platforms", ["facebook", "instagram"])

        if "facebook" in platforms and not item.get("facebook_published") and key in fb_live:
            item["facebook_published"] = True
            item["fb_live_id"] = fb_live[key]
            print(f"'{item['title']}' is already live on Facebook; recording it, not re-posting.")
            save_queue(queue)
        if "instagram" in platforms and not item.get("instagram_published") and key in ig_live:
            item["instagram_published"] = True
            item["ig_live_id"] = ig_live[key]
            print(f"'{item['title']}' is already live on Instagram; recording it, not re-posting.")
            save_queue(queue)

        needs_fb = "facebook" in platforms and not item.get("facebook_published")
        needs_ig = "instagram" in platforms and not item.get("instagram_published")
        if not (needs_fb or needs_ig):
            item["status"] = "published"
            item.setdefault("published_at_utc", datetime.now(timezone.utc).isoformat())
            save_queue(queue)
            continue

        if now - last_published_unix(queue) < MIN_GAP_SECONDS:
            print("Last post was under 30 minutes ago; waiting for the next run.")
            break

        is_reel = item.get("type") == "reel"
        item["attempts"] = item.get("attempts", 0) + 1
        if item["attempts"] > MAX_ATTEMPTS:
            item["status"] = "failed"
            print(f"GIVING UP on '{item['title']}' after {MAX_ATTEMPTS} attempts: {item.get('last_error')}")
            errors += 1
            save_queue(queue)
            continue
        print(f"Posting {'Reel' if is_reel else 'post'} '{item['title']}' (slot {item['date_str']} {item['time_est']})")
        if is_reel:
            try:
                video_path = prepare_reel(item)
            except Exception as e:
                errors += 1
                item["last_error"] = f"render: {e}"
                print(f"  Reel render ERROR: {e}")
                save_queue(queue)
                continue
        else:
            asset = os.path.basename(item["image_path"])
            local_image = os.path.join("content_assets", asset)
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_REF_NAME}/content_assets/{asset}"

        # Save after every platform so a later failure can never cause a repost.
        if needs_fb:
            try:
                res = publish_facebook_reel(caption, video_path) if is_reel else publish_facebook_photo(caption, local_image)
                item["facebook_published"] = True
                item["fb_live_id"] = res.get("post_id") or res.get("id")
                item["published_at_utc"] = datetime.now(timezone.utc).isoformat()
                print(f"  Facebook OK: {item['fb_live_id']}")
            except Exception as e:
                errors += 1
                item["last_error"] = f"facebook: {e}"
                print(f"  Facebook ERROR: {e}")
            save_queue(queue)
        if needs_ig:
            try:
                res = publish_instagram_reel(caption, video_path) if is_reel else publish_instagram_photo(caption, raw_url)
                item["instagram_published"] = True
                item["ig_live_id"] = res.get("id")
                item["published_at_utc"] = datetime.now(timezone.utc).isoformat()
                print(f"  Instagram OK: {item['ig_live_id']}")
            except Exception as e:
                errors += 1
                item["last_error"] = f"instagram: {e}"
                print(f"  Instagram ERROR: {e}")
            save_queue(queue)

        if is_done(item):
            item["status"] = "published"
            item.pop("last_error", None)
        save_queue(queue)
        if item.get("facebook_published") or item.get("instagram_published"):
            posted += 1  # a total failure must not block the next due post

    overdue = [i for i in queue if i.get("status") not in SKIP_STATUSES and not is_done(i)
               and i["timestamp_unix"] < now - OVERDUE_ALERT_SECONDS]
    for i in overdue:
        print(f"ALERT: overdue by {(now - i['timestamp_unix']) // 60} min: '{i['title']}' ({i['date_str']} {i['time_est']})")
    return errors, bool(overdue)


def commit_queue(message):
    """Save the queue to GitHub right away (loop mode), so a crash can never lose what was already posted."""
    import subprocess
    run = lambda *a: subprocess.run(a, capture_output=True, text=True)  # noqa: E731
    run("git", "add", QUEUE_FILE)
    if run("git", "diff", "--staged", "--quiet").returncode == 0:
        return
    run("git", "-c", "user.name=github-actions[bot]", "-c", "user.email=github-actions[bot]@users.noreply.github.com",
        "commit", "-m", message)
    for attempt in range(4):
        r = run("git", "pull", "--rebase", "-X", "theirs", "origin", "main")
        if r.returncode == 0 and run("git", "push", "origin", "main").returncode == 0:
            return
        run("git", "rebase", "--abort")
        time.sleep(3 * (attempt + 1))
    print("WARNING: could not push the queue; the end-of-run commit step will retry.")


def main():
    """One pass by default. With --loop N the job stays alive for N minutes and checks the queue every
    minute, so posts go out within about a minute of their slot even when GitHub drops scheduled runs."""
    args = sys.argv[1:]
    if "--loop" not in args:
        errors, overdue = run_once()
        sys.exit(1 if (errors or overdue) else 0)
    minutes = float(args[args.index("--loop") + 1])
    deadline = time.time() + minutes * 60
    total_errors, last_overdue = 0, False
    while time.time() < deadline:
        before = open(QUEUE_FILE, "rb").read()
        try:
            errors, last_overdue = run_once()
            total_errors += errors
        except SystemExit:
            raise
        except Exception as e:  # keep the loop alive through any unexpected problem
            total_errors += 1
            print(f"Unexpected error: {e}")
        if open(QUEUE_FILE, "rb").read() != before:
            commit_queue("chore: update published queue")
        time.sleep(60)
    sys.exit(1 if (total_errors and last_overdue) or last_overdue else 0)


if __name__ == "__main__":
    main()
