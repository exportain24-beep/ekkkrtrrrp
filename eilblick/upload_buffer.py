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
                      metadata: dict | None = None) -> str:
    mode = "customScheduled" if due_at_iso else "shareNow"
    inp = {"text": text, "channelId": channel_id, "schedulingType": "automatic", "mode": mode,
           "assets": [{"video": {"url": video_url, "metadata": {"thumbnailOffset": 0}}}]}
    if due_at_iso:
        inp["dueAt"] = due_at_iso
    if metadata:
        inp["metadata"] = metadata
    q = """mutation($input: CreatePostInput!) { createPost(input: $input) {
             ... on PostActionSuccess { post { id } }
             ... on MutationError { message } } }"""
    res = gql(q, {"input": inp})["createPost"]
    if "post" not in res:
        raise RuntimeError(f"Buffer createPost: {res.get('message')}")
    return res["post"]["id"]
