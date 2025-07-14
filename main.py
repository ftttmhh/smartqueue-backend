from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from redis_client import redis_client
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Remove in-memory lists
def get_queue():
    # Returns list of dicts
    return [json.loads(item) for item in redis_client.lrange('queue', 0, -1)]
def set_queue(queue):
    redis_client.delete('queue')
    if queue:
        redis_client.rpush('queue', *[json.dumps(item) for item in queue])
def add_served(entry):
    redis_client.rpush('served_tokens', json.dumps(entry))
def get_served():
    return [json.loads(item) for item in redis_client.lrange('served_tokens', 0, -1)]
def add_skipped_token(token):
    redis_client.sadd('skipped_tokens', token)
def get_skipped_tokens():
    return set(redis_client.smembers('skipped_tokens'))
def remove_skipped_token(token):
    redis_client.srem('skipped_tokens', token)

class JoinRequest(BaseModel):
    name: str
    phone: str
    service_type: str

class JoinResponse(BaseModel):
    token: str
    position: int
    eta: int  # in minutes

class StatusResponse(BaseModel):
    token: str
    position: int
    eta: int
    status: str

class TokenRequest(BaseModel):
    token: str

@app.post("/queue/join", response_model=JoinResponse)
def join_queue(req: JoinRequest):
    queue = get_queue()
    token = f"T{len(queue)+1}"
    entry = {"token": token, "name": req.name, "phone": req.phone, "service_type": req.service_type}
    queue.append(entry)
    set_queue(queue)
    position = len(queue)
    eta = position * 2
    return JoinResponse(token=token, position=position, eta=eta)

@app.get("/queue/status/{token}", response_model=StatusResponse)
def queue_status(token: str):
    queue = get_queue()
    for idx, entry in enumerate(queue):
        if entry["token"] == token:
            position = idx + 1
            eta = position * 2
            status = entry.get("status", "waiting")
            return StatusResponse(token=token, position=position, eta=eta, status=status)
    raise HTTPException(status_code=404, detail="Token not found")

@app.get("/queue/list")
def queue_list():
    queue = get_queue()
    skipped_set = get_skipped_tokens()
    active = []
    for entry in queue:
        status = entry.get("status", "waiting")
        if entry["token"] in skipped_set:
            status = "skipped"
        active.append({**entry, "status": status})
    served = get_served()
    return JSONResponse(active + served)

@app.delete("/queue/leave/{token}")
def leave_queue(token: str):
    queue = get_queue()
    queue = [entry for entry in queue if entry["token"] != token]
    remove_skipped_token(token)
    set_queue(queue)
    return {"detail": "Left the queue"}

@app.post("/queue/serve")
def serve_token(req: TokenRequest):
    token = req.token
    queue = get_queue()
    for i, entry in enumerate(queue):
        if entry["token"] == token:
            entry["status"] = "served"
            add_served(entry)
            queue.pop(i)
            set_queue(queue)
            return {"success": True}
    return {"success": False, "error": "Token not found"}

@app.post("/queue/skip")
def skip_token(req: TokenRequest):
    token = req.token
    queue = get_queue()
    for entry in queue:
        if entry["token"] == token:
            entry["status"] = "skipped"
            add_skipped_token(token)
            set_queue(queue)
            return {"success": True}
    return {"success": False, "error": "Token not found"}

@app.post("/queue/resume")
def resume_token(req: TokenRequest):
    token = req.token
    queue = get_queue()
    for entry in queue:
        if entry["token"] == token and entry.get("status") == "skipped":
            entry["status"] = "waiting"
            remove_skipped_token(token)
            set_queue(queue)
            return {"success": True}
    return {"success": False, "error": "Token not found or not skipped"}