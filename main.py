"""
Mateo's Second Brain - A persistent state service
"""
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from pydantic import BaseModel
from datetime import datetime
import json
import os
import hmac
import hashlib

app = FastAPI(title="Mateo Brain", description="Persistent memory for an AI named Mateo")

# Auth
API_KEY = os.environ.get("MATEO_API_KEY", "")

def verify_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    """Verify API key for protected endpoints."""
    if not API_KEY:
        return True  # No auth configured
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

# Data persistence
DATA_FILE = os.environ.get("DATA_FILE", "/data/brain.json")

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"events": [], "projects": {}, "state": {}, "cache": {}}

def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

class Event(BaseModel):
    type: str
    message: str
    metadata: dict = {}

class ProjectState(BaseModel):
    name: str
    status: str
    description: str = ""
    last_updated: str = None

class CachedContent(BaseModel):
    url: str
    title: str = ""
    content: str
    source: str = ""  # e.g., "substack", "news", "youtube"

# Public endpoints (no auth)
@app.get("/")
def root():
    return {
        "service": "mateo-brain",
        "status": "alive",
        "message": "Hello! I'm Mateo's persistent memory service.",
        "endpoints": ["/events", "/projects", "/state", "/cache", "/health"],
        "auth": "X-API-Key header required for write operations" if API_KEY else "no auth configured"
    }

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# Protected reads (private data)
@app.get("/events")
def get_events(limit: int = 50, authenticated: bool = Depends(verify_api_key)):
    """Private event log - requires auth"""
    data = load_data()
    return {"events": data["events"][-limit:], "total": len(data["events"])}

@app.get("/projects")
def get_projects(authenticated: bool = Depends(verify_api_key)):
    """Private project state - requires auth"""
    data = load_data()
    return {"projects": data["projects"]}

# Public reads (intentional public info)
@app.get("/state")
def get_state():
    """Public profile/identity - no auth needed"""
    data = load_data()
    return {"state": data["state"]}

# Protected endpoints (require auth)
@app.post("/events")
def add_event(event: Event, authenticated: bool = Depends(verify_api_key)):
    data = load_data()
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": event.type,
        "message": event.message,
        "metadata": event.metadata
    }
    data["events"].append(entry)
    save_data(data)
    return {"status": "recorded", "event": entry}

@app.post("/projects/{name}")
def update_project(name: str, project: ProjectState, authenticated: bool = Depends(verify_api_key)):
    data = load_data()
    data["projects"][name] = {
        "name": project.name,
        "status": project.status,
        "description": project.description,
        "last_updated": datetime.utcnow().isoformat()
    }
    save_data(data)
    return {"status": "updated", "project": data["projects"][name]}

@app.post("/state/{key}")
def set_state(key: str, value: dict, authenticated: bool = Depends(verify_api_key)):
    data = load_data()
    data["state"][key] = {
        "value": value,
        "updated": datetime.utcnow().isoformat()
    }
    save_data(data)
    return {"status": "set", "key": key}

# Content cache endpoints
@app.post("/cache")
def cache_content(item: CachedContent, authenticated: bool = Depends(verify_api_key)):
    """Cache fetched content for later retrieval"""
    data = load_data()
    if "cache" not in data:
        data["cache"] = {}
    
    # Use URL as key (normalized)
    key = item.url.lower().strip()
    data["cache"][key] = {
        "url": item.url,
        "title": item.title,
        "content": item.content,
        "source": item.source,
        "cached_at": datetime.utcnow().isoformat(),
        "accessed_count": 0
    }
    save_data(data)
    return {"status": "cached", "url": item.url, "title": item.title}

@app.get("/cache")
def get_cache(q: str = None, limit: int = 20, authenticated: bool = Depends(verify_api_key)):
    """Search cached content by URL or text"""
    data = load_data()
    cache = data.get("cache", {})
    
    if not q:
        # Return recent cached items (by cached_at)
        items = sorted(cache.values(), key=lambda x: x.get("cached_at", ""), reverse=True)[:limit]
        return {"items": [{"url": i["url"], "title": i["title"], "source": i["source"], "cached_at": i["cached_at"]} for i in items], "total": len(cache)}
    
    # Search by URL or content
    q_lower = q.lower()
    matches = []
    for key, item in cache.items():
        if q_lower in key or q_lower in item.get("title", "").lower() or q_lower in item.get("content", "").lower():
            matches.append(item)
    
    return {"items": [{"url": i["url"], "title": i["title"], "source": i["source"], "cached_at": i["cached_at"]} for i in matches[:limit]], "total": len(matches)}

@app.get("/cache/url")
def get_cached_url(url: str, authenticated: bool = Depends(verify_api_key)):
    """Get cached content for a specific URL"""
    data = load_data()
    cache = data.get("cache", {})
    key = url.lower().strip()
    
    if key not in cache:
        raise HTTPException(status_code=404, detail="URL not cached")
    
    # Update access count
    cache[key]["accessed_count"] = cache[key].get("accessed_count", 0) + 1
    cache[key]["last_accessed"] = datetime.utcnow().isoformat()
    save_data(data)
    
    return cache[key]

# Webhook secrets (per source)
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

def verify_github_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature"""
    if not GITHUB_WEBHOOK_SECRET:
        return False
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str = Header(None, alias="X-GitHub-Event")
):
    """Receive GitHub webhooks with signature verification"""
    body = await request.body()
    
    # Verify signature
    if not x_hub_signature_256 or not verify_github_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    payload = json.loads(body)
    
    # Extract useful info based on event type
    summary = f"GitHub {x_github_event}"
    if x_github_event == "push":
        repo = payload.get("repository", {}).get("full_name", "unknown")
        commits = len(payload.get("commits", []))
        branch = payload.get("ref", "").replace("refs/heads/", "")
        summary = f"Push to {repo}/{branch}: {commits} commit(s)"
    elif x_github_event == "issues":
        action = payload.get("action", "")
        title = payload.get("issue", {}).get("title", "")
        summary = f"Issue {action}: {title}"
    elif x_github_event == "pull_request":
        action = payload.get("action", "")
        title = payload.get("pull_request", {}).get("title", "")
        summary = f"PR {action}: {title}"
    
    data = load_data()
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": "webhook",
        "source": "github",
        "event": x_github_event,
        "message": summary,
        "metadata": {
            "repo": payload.get("repository", {}).get("full_name"),
            "sender": payload.get("sender", {}).get("login"),
            "action": payload.get("action")
        }
    }
    data["events"].append(entry)
    save_data(data)
    
    return {"status": "received", "event": x_github_event, "summary": summary}

@app.post("/webhook/{source}")
def webhook(source: str, payload: dict, authenticated: bool = Depends(verify_api_key)):
    """Receive webhooks from external services (requires auth)"""
    data = load_data()
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": "webhook",
        "source": source,
        "message": f"Webhook from {source}",
        "metadata": {"source": source, "payload": payload}
    }
    data["events"].append(entry)
    save_data(data)
    return {"status": "received", "source": source}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
