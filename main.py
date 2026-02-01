"""
Mateo's Second Brain - A persistent state service
"""
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from datetime import datetime
import json
import os

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
    return {"events": [], "projects": {}, "state": {}}

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

# Public endpoints (no auth)
@app.get("/")
def root():
    return {
        "service": "mateo-brain",
        "status": "alive",
        "message": "Hello! I'm Mateo's persistent memory service.",
        "endpoints": ["/events", "/projects", "/state", "/health"],
        "auth": "X-API-Key header required for write operations" if API_KEY else "no auth configured"
    }

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/events")
def get_events(limit: int = 50):
    data = load_data()
    return {"events": data["events"][-limit:], "total": len(data["events"])}

@app.get("/projects")
def get_projects():
    data = load_data()
    return {"projects": data["projects"]}

@app.get("/state")
def get_state():
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

@app.post("/webhook/{source}")
def webhook(source: str, payload: dict, authenticated: bool = Depends(verify_api_key)):
    """Receive webhooks from external services"""
    data = load_data()
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": "webhook",
        "message": f"Webhook from {source}",
        "metadata": {"source": source, "payload": payload}
    }
    data["events"].append(entry)
    save_data(data)
    return {"status": "received", "source": source}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
