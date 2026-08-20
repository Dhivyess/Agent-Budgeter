from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
import httpx
import json
import os
import time
import uuid

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
LITELLM_URL = os.getenv("LITELLM_URL", "http://localhost:4000")
PROXY_API_KEY = os.getenv("PROXY_API_KEY")

SESSION_LIMIT_MICRO = 2_000_000     # $2.00
AGENT_LIMIT_MICRO = 50_000_000      # $50.00
TEAM_LIMIT_MICRO = 500_000_000      # $500.00

resources = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=False)
    resources["redis"] = redis_client

    base_dir = os.path.dirname(os.path.abspath(__file__))
    lua_path = os.path.join(base_dir, "..", "scripts", "budget_reservation.lua")
    with open(lua_path, "r") as f:
        lua_script = f.read()
    resources["reserve_budget"] = redis_client.register_script(lua_script)
    resources["http_client"] = httpx.AsyncClient(timeout=60.0)
    yield
    await resources["http_client"].aclose()
    await resources["redis"].close()

app = FastAPI(title="Agent Budget Controller Proxy", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def log_audit_trail(redis_client, session_id, agent_id, original, routed, intent, est_cost, act_cost, status, reason=""):
    audit_record = {
        "timestamp": time.time(),
        "session_id": session_id,
        "agent_id": agent_id,
        "original_model": original,
        "routed_model": routed,
        "intent_detected": intent,
        "estimated_cost_usd": est_cost / 1_000_000,
        "actual_cost_usd": act_cost / 1_000_000,
        "status_code": status,
        "reason": reason
    }
    await redis_client.lpush(f"audit:session:{session_id}", json.dumps(audit_record))
    await redis_client.ltrim(f"audit:session:{session_id}", 0, 49)

@app.post("/v1/chat/completions")
async def proxy_completions(request: Request):
    redis_client = resources["redis"]
    http_client = resources["http_client"]
    reserve_budget = resources["reserve_budget"]

    if PROXY_API_KEY:
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized. Missing or invalid Authorization header.")
        provided_key = auth_header.split(" ")[1]
        if provided_key != PROXY_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized. Invalid API key.")

    headers = dict(request.headers)
    team_id = headers.get("team_id")
    agent_id = headers.get("agent_id")
    session_id = headers.get("x-session-id")

    if not all([team_id, agent_id, session_id]):
        raise HTTPException(status_code=400, detail="Missing required team, agent, or session headers.")

    if await redis_client.sismember("paused_agents", agent_id):
        raise HTTPException(status_code=403, detail="Agent is currently paused due to velocity/budget limits.")

    if await redis_client.get(f"session_closed:{session_id}"):
        raise HTTPException(status_code=403, detail="Session closed due to budget exhaustion.")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    messages = body.get("messages", [])
    user_prompt = next((msg.get("content", "") for msg in reversed(messages) if msg.get("role") == "user"), "")

    prompt_length = len(user_prompt) if user_prompt else 100
    estimated_tokens = max(prompt_length // 4, 10)

    original_model = body.get("model", "gemini/gemini-3.6-flash")
    selected_model = original_model
    intent_detected = "static_route"

    if user_prompt:
        lower_prompt = user_prompt.lower()
        complex_keywords = ["code", "python", "script", "refactor", "algorithm", "math", "derive", "solve", "function"]
        is_complex = any(kw in lower_prompt for kw in complex_keywords)

        if is_complex:
            intent_detected = "complex_reasoning_or_code"
            agent_spend_raw = await redis_client.get(f"budget:agent:{agent_id}")
            current_agent_spend = int(agent_spend_raw) if agent_spend_raw else 0

            if (AGENT_LIMIT_MICRO - current_agent_spend) > (AGENT_LIMIT_MICRO * 0.10):
                selected_model = "gemini/gemini-3.7-flash"
            else:
                selected_model = "gemini/gemini-3.6-flash"
                intent_detected = "complex_but_budget_constrained"
        else:
            intent_detected = "simple_conversational"
            selected_model = "gemini/gemini-3.6-flash"

    body["model"] = selected_model

    multiplier = 15
    estimated_cost_micro = estimated_tokens * multiplier

    budget_keys = [f"budget:session:{session_id}", f"budget:agent:{agent_id}", f"budget:team:{team_id}"]
    budget_args = [estimated_cost_micro, SESSION_LIMIT_MICRO, AGENT_LIMIT_MICRO, TEAM_LIMIT_MICRO]

    result = await reserve_budget(keys=budget_keys, args=budget_args)
    allowed = result[0]

    failure_tier = result[1].decode() if isinstance(result[1], bytes) else result[1]
    current_spend = result[2]
    tier_limit = result[3]

    if not allowed:
        if failure_tier == "session":
            await redis_client.setex(f"session_closed:{session_id}", 86400, "true")

        error_payload = {
            "error": {
                "message": f"Budget Exceeded! Limit enforced at {failure_tier} tier.",
                "type": "budget_exceeded_error",
                "code": 429,
                "param": {"tier": failure_tier, "spend": current_spend / 1_000_000, "limit": tier_limit / 1_000_000}
            }
        }

        await log_audit_trail(redis_client, session_id, agent_id, original_model, selected_model, intent_detected, estimated_cost_micro, 0, 429, f"{failure_tier} limit")
        return Response(content=json.dumps(error_payload), status_code=429, media_type="application/json")

    if "host" in headers: del headers["host"]
    if "content-length" in headers: del headers["content-length"]

    actual_cost_micro = 0
    proxy_req = None

    try:
        proxy_req = await http_client.post(f"{LITELLM_URL}/v1/chat/completions", content=json.dumps(body).encode("utf-8"), headers=headers)

        if proxy_req.status_code == 200:
            try:
                response_json = proxy_req.json()
                actual_cost_usd = response_json.get("response_cost")
                actual_cost_micro = int(float(actual_cost_usd) * 1_000_000) if actual_cost_usd else estimated_cost_micro
            except Exception:
                actual_cost_micro = estimated_cost_micro

            entry_value = f"{time.time()}:{actual_cost_micro / 1_000_000}:{uuid.uuid4().hex[:6]}"
            await redis_client.zadd(f"velocity:agent:{agent_id}", {entry_value: time.time()})
        else:
            actual_cost_micro = 0
          
        adjustment = actual_cost_micro - estimated_cost_micro
        if adjustment != 0:
            pipe = redis_client.pipeline()
            for k in budget_keys: pipe.incrby(k, adjustment)
            await pipe.execute()

    except Exception as e:
        pipe = redis_client.pipeline()
        for k in budget_keys: pipe.incrby(k, -estimated_cost_micro)
        await pipe.execute()

        await log_audit_trail(redis_client, session_id, agent_id, original_model, selected_model, intent_detected, estimated_cost_micro, 0, 502, "gateway failure")
        raise HTTPException(status_code=502, detail=f"Bad Gateway: {str(e)}")

    response_headers = dict(proxy_req.headers)
    if (int(await redis_client.get(budget_keys[0]) or 0) / SESSION_LIMIT_MICRO) >= 0.8:
        response_headers["X-Budget-Warning"] = "limit_reached_80pct"
    response_headers["X-Routed-Model"] = selected_model

    for header in ["content-length", "content-encoding"]:
        if header in response_headers: del response_headers[header]

    await log_audit_trail(redis_client, session_id, agent_id, original_model, selected_model, intent_detected, estimated_cost_micro, actual_cost_micro, proxy_req.status_code)

    return Response(content=proxy_req.content, status_code=proxy_req.status_code, headers=response_headers)
