import os
import sys
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime

# Credentials from environment (set in GitHub Secrets)
FB_PAGE_ID = os.getenv("FB_PAGE_ID") or "1393452917180828"
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID") or "17841417121544192"
META_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY") or "iqbal-jewel/german-shepherd-publisher"
GITHUB_REF_NAME = os.getenv("GITHUB_REF_NAME") or "main"

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

QUEUE_FILE = "content_queue.json"

def get_raw_github_url(relative_asset_path):
    filename = os.path.basename(relative_asset_path)
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_REF_NAME}/content_assets/{filename}"

def publish_facebook_photo(caption, image_path, raw_url):
    # Try uploading local file multipart first
    if os.path.exists(image_path):
        import mimetypes
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        content_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        filename = os.path.basename(image_path)
        
        with open(image_path, "rb") as f:
            file_bytes = f.read()
            
        body = bytearray()
        def add_field(name, val):
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode("utf-8"))
            
        add_field("caption", caption)
        add_field("access_token", META_TOKEN)
        
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="source"; filename="{filename}"\r\n'.encode("utf-8"))
        body.extend(f'Content-Type: {content_type}\r\n\r\n'.encode("utf-8"))
        body.extend(file_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        
        url = f"{BASE_URL}/{FB_PAGE_ID}/photos"
        req = urllib.request.Request(url, data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        # Fallback to URL upload
        url = f"{BASE_URL}/{FB_PAGE_ID}/photos"
        data = urllib.parse.urlencode({
            "url": raw_url,
            "caption": caption,
            "access_token": META_TOKEN
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

def publish_instagram_photo(caption, raw_url):
    print(f"Creating Instagram media container using image URL: {raw_url}")
    # Step 1: Create Container
    container_url = f"{BASE_URL}/{IG_ACCOUNT_ID}/media"
    data = urllib.parse.urlencode({
        "image_url": raw_url,
        "caption": caption,
        "access_token": META_TOKEN
    }).encode("utf-8")
    req = urllib.request.Request(container_url, data=data)
    with urllib.request.urlopen(req) as resp:
        container_res = json.loads(resp.read().decode("utf-8"))
        
    creation_id = container_res.get("id")
    if not creation_id:
        raise Exception(f"Failed to create Instagram container: {container_res}")
        
    print(f"Container created (ID: {creation_id}). Waiting 5 seconds before publishing...")
    time.sleep(5)
    
    # Step 2: Publish Container
    publish_url = f"{BASE_URL}/{IG_ACCOUNT_ID}/media_publish"
    pub_data = urllib.parse.urlencode({
        "creation_id": creation_id,
        "access_token": META_TOKEN
    }).encode("utf-8")
    req2 = urllib.request.Request(publish_url, data=pub_data)
    with urllib.request.urlopen(req2) as resp2:
        return json.loads(resp2.read().decode("utf-8"))

def main():
    if not META_TOKEN:
        print("ERROR: META_PAGE_ACCESS_TOKEN is missing from environment.")
        sys.exit(1)

    if not os.path.exists(QUEUE_FILE):
        print(f"ERROR: {QUEUE_FILE} not found.")
        sys.exit(1)

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    # Find next pending item
    next_item = None
    for item in queue:
        if item.get("status") in ["ready", "pending", "ready_to_schedule", "scheduled_on_facebook"]:
            # If it's already published on both, skip
            if item.get("instagram_published") and item.get("facebook_published"):
                continue
            next_item = item
            break

    if not next_item:
        print("No pending posts found in queue. All caught up!")
        sys.exit(0)

    print(f"Processing post: '{next_item.get('title')}' for slot {next_item.get('time_est')}...")
    caption = next_item.get("caption")
    asset_filename = os.path.basename(next_item.get("image_path", "day1_stick_figure_meme.jpg"))
    local_image = os.path.join("content_assets", asset_filename)
    raw_url = get_raw_github_url(local_image)

    platforms = next_item.get("platforms", ["facebook", "instagram"])

    # 1. Publish to Facebook if not already published
    if "facebook" in platforms and not next_item.get("facebook_published"):
        print("Publishing to Facebook Page...")
        try:
            fb_res = publish_facebook_photo(caption, local_image, raw_url)
            next_item["facebook_published"] = True
            next_item["fb_live_id"] = fb_res.get("id")
            print(f"  -> Facebook Success! ID: {fb_res.get('id')}")
        except Exception as e:
            print(f"  -> Facebook Error: {e}")

    # 2. Publish to Instagram if not already published
    if "instagram" in platforms and not next_item.get("instagram_published"):
        print("Publishing to Instagram (@germanshepherdco)...")
        try:
            ig_res = publish_instagram_photo(caption, raw_url)
            next_item["instagram_published"] = True
            next_item["ig_live_id"] = ig_res.get("id")
            print(f"  -> Instagram Success! ID: {ig_res.get('id')}")
        except Exception as e:
            print(f"  -> Instagram Error: {e}")

    next_item["status"] = "published"
    next_item["published_at_utc"] = datetime.utcnow().isoformat()

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2)

    print("Post execution completed and queue updated!")

if __name__ == "__main__":
    main()
