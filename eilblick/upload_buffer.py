"""Buffer GraphQL API (separate Eilblick Buffer account) → TikTok + X.

Buffer fetches the video from a public URL. We use an immutable raw.githubusercontent.com
link to the commit on the `review` branch that holds this run's video."""
from __future__ import annotations

import json
import os

import requests

API = "https://api.buffer.com"


def key() -> str | None:
    return os.environ.get("BUFFER_API_KEY")


def gql(query: str, variables: dict | None = None) -> dict:
    r = requests.post(API, headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"},
                      json={"query": query, "variables": variables or {}}, timeout=60)
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"Buffer HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or data.get("errors"):
        raise RuntimeError(f"Buffer {r.status_code}: {json.dumps(data.get('errors') or data)[:400]}")
    return data["data"]


def channels() -> list[dict]:
    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    out = []
    for o in orgs:
        ch = gql("query($id: OrganizationId!) { channels(input: {organizationId: $id}) { id service name } }",
                 {"id": o["id"]})["channels"]
        for c in ch:
            c["organization"] = o.get("name")
            out.append(c)
    return out


def create_video_post(channel_id: str, text: str, video_url: str, due_at_iso: str | None,
                      metadata: dict | None = None, draft: bool = False) -> str:
    mode = "customScheduled" if due_at_iso else ("addToQueue" if draft else "shareNow")
    inp = {"text": text, "channelId": channel_id, "schedulingType": "automatic", "mode": mode,
           "assets": [{"video": {"url": video_url, "metadata": {"thumbnailOffset": 0}}}]}
    if due_at_iso:
        inp["dueAt"] = due_at_iso
    if metadata:
        inp["metadata"] = metadata
    if draft:
        inp["saveToDraft"] = True
    q = """mutation($input: CreatePostInput!) { createPost(input: $input) {
             ... on PostActionSuccess { post { id } }
             ... on MutationError { message } } }"""
    res = gql(q, {"input": inp})["createPost"]
    if "post" not in res:
        raise RuntimeError(f"Buffer createPost: {res.get('message')}")
    return res["post"]["id"]


# ------------------------------------------------------------------ public video URL (GitHub release asset)
def host_video(video, tag: str) -> str:
    """Upload the mp4 as a release asset of this (public) repo → stable public URL for Buffer.
    Releases older than 3 days are removed automatically."""
    from datetime import datetime, timedelta, timezone
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "exportain24-beep/ekkkrtrrrp")
    if not tok:
        raise RuntimeError("no GH_TOKEN for media hosting")
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    base = f"https://api.github.com/repos/{repo}"
    # cleanup
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        for rel in requests.get(f"{base}/releases?per_page=100", headers=h, timeout=30).json():
            if rel.get("tag_name", "").startswith("media-") and \
                    datetime.fromisoformat(rel["created_at"].replace("Z", "+00:00")) < cutoff:
                requests.delete(f"{base}/releases/{rel['id']}", headers=h, timeout=30)
                requests.delete(f"{base}/git/refs/tags/{rel['tag_name']}", headers=h, timeout=30)
    except Exception as e:
        print("  media cleanup skipped:", e)
    r = requests.get(f"{base}/releases/tags/{tag}", headers=h, timeout=30)
    rel = r.json() if r.status_code == 200 else requests.post(
        f"{base}/releases", headers=h, timeout=30,
        json={"tag_name": tag, "name": tag, "body": "Eilblick media for Buffer (auto-deleted after 3 days)",
              "prerelease": True}).json()
    if "upload_url" not in rel:
        raise RuntimeError(f"release create failed: {str(rel)[:200]}")
    name = video.name
    for a in rel.get("assets", []):
        if a["name"] == name:
            return a["browser_download_url"]
    up = rel["upload_url"].split("{")[0]
    with open(video, "rb") as f:
        res = requests.post(f"{up}?name={name}", headers={**h, "Content-Type": "video/mp4"}, data=f, timeout=600)
    if res.status_code >= 400:
        raise RuntimeError(f"asset upload failed {res.status_code}: {res.text[:200]}")
    return res.json()["browser_download_url"]


# ------------------------------------------------------------------ metadata via introspection
_META: dict = {}


def _input_fields(type_name: str) -> dict:
    q = 'query($n: String!) { __type(name: $n) { inputFields { name type { name kind ofType { name kind } } } } }'
    t = gql(q, {"n": type_name}).get("__type") or {}
    out = {}
    for f in t.get("inputFields") or []:
        ty = f["type"]
        out[f["name"]] = ty.get("name") or (ty.get("ofType") or {}).get("name")
    return out


def metadata_for(service: str, title: str) -> dict | None:
    """Builds e.g. {"tiktok": {"title": …, "isAiGenerated": true}} using the live schema."""
    try:
        if "root" not in _META:
            _META["root"] = _input_fields("PostInputMetaData")
        root = _META["root"]
        key_ = next((k for k in root if k.lower() in (service.lower(), "x" if service == "twitter" else service)), None)
        if not key_:
            return None
        sub = _META.setdefault(key_, _input_fields(root[key_]))
        m = {}
        if "title" in sub:
            m["title"] = title[:90]
        if "isAiGenerated" in sub:
            m["isAiGenerated"] = True
        return {key_: m} if m else None
    except Exception as e:
        print("  buffer metadata skipped:", e)
        return None


def post_video_everywhere(video, tag: str, tiktok_text: str, x_text: str, title: str,
                          due_at_iso: str | None, draft: bool = False) -> dict:
    url = host_video(video, tag)
    print(f"  media URL: {url}")
    out = {}
    for c in channels():
        svc = c["service"].lower()
        if svc not in ("tiktok", "twitter", "x"):
            continue
        text = tiktok_text if svc == "tiktok" else x_text
        meta = metadata_for(svc, title)
        try:
            pid = create_video_post(c["id"], text, url, due_at_iso, meta, draft)
        except RuntimeError as e:
            if meta:   # retry without metadata if the schema rejected it
                print(f"  {svc}: retry without metadata ({e})")
                pid = create_video_post(c["id"], text, url, due_at_iso, None, draft)
            else:
                raise
        out[svc] = pid
        print(f"  Buffer {svc} ✓ post {pid} ({'draft' if draft else 'scheduled' if due_at_iso else 'now'})")
    return out



def delete_post(post_id: str) -> str:
    """Deletes a Buffer post (uses the live schema for the exact argument shape)."""
    m = gql('query { __type(name: "Mutation") { fields { name args { name type { name kind ofType { name } } } } } }')
    f = next(x for x in m["__type"]["fields"] if x["name"] == "deletePost")
    arg = f["args"][0]
    tname = arg["type"].get("name") or (arg["type"].get("ofType") or {}).get("name")
    if arg["name"] == "input":
        q = f"mutation($v: {tname}!) {{ deletePost(input: $v) {{ __typename }} }}"
        var = {"v": {"id": post_id}}
    else:
        q = f"mutation($v: {tname}!) {{ deletePost({arg['name']}: $v) {{ __typename }} }}"
        var = {"v": post_id}
    return gql(q, var)["deletePost"]["__typename"]
