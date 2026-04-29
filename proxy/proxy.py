import httpx
import json
import sqlite3
import time
import uuid
import sys
from datetime import datetime
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse

sys.path.insert(0, "/home/madhu/hermes-observatory")
from discovery.tool_rewriter import rewrite_tools

app = FastAPI(title="Hermes Observatory Proxy")

LM_STUDIO_URL = "http://127.0.0.1:1234"
DB_PATH = "/home/madhu/hermes-observatory/data/telemetry.db"

PRICING = {
    "gpt-4o":            {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":       {"input": 0.15,  "output": 0.60},
    "claude-sonnet-4-5": {"input": 3.00,  "output": 15.00},
    "claude-opus-4":     {"input": 15.00, "output": 75.00},
    "gemini-2-flash":    {"input": 0.10,  "output": 0.40},
    "local-qwen":        {"input": 0.00,  "output": 0.00},
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id TEXT PRIMARY KEY,
            timestamp TEXT,
            model TEXT,
            messages_count INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            tool_calls TEXT,
            tools_available TEXT,
            tools_available_count INTEGER,
            response_text TEXT,
            latency_ms REAL,
            finish_reason TEXT,
            session_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            started_at TEXT,
            total_requests INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            total_tool_calls INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

current_session = str(uuid.uuid4())[:8]
session_start = datetime.utcnow().isoformat()

async def get_active_model() -> str:
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            response = await client.get(f"{LM_STUDIO_URL}/v1/models")
            models = response.json().get("data", [])
            if models:
                return models[0]["id"]
        except:
            pass
    return None

def compute_costs(prompt_tokens: int, completion_tokens: int) -> dict:
    costs = {}
    for model, prices in PRICING.items():
        input_cost = (prompt_tokens / 1_000_000) * prices["input"]
        output_cost = (completion_tokens / 1_000_000) * prices["output"]
        costs[model] = round(input_cost + output_cost, 6)
    return costs

def safe_len(s):
    try:
        return len(str(s))
    except:
        return 0

def log_to_db(data: dict):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT OR REPLACE INTO requests VALUES (
                :id, :timestamp, :model, :messages_count,
                :prompt_tokens, :completion_tokens, :total_tokens,
                :tool_calls, :tools_available, :tools_available_count,
                :response_text, :latency_ms, :finish_reason, :session_id
            )
        """, data)
        conn.execute("""
            INSERT INTO sessions (id, started_at, total_requests, total_tokens, total_tool_calls)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                total_requests = total_requests + 1,
                total_tokens = total_tokens + ?,
                total_tool_calls = total_tool_calls + ?
        """, (
            current_session, session_start,
            data["total_tokens"], len(json.loads(data["tool_calls"])),
            data["total_tokens"], len(json.loads(data["tool_calls"]))
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB error: {e}")

def extract_tool_calls(response_body: dict) -> list:
    tool_calls = []
    try:
        for choice in response_body.get("choices", []):
            msg = choice.get("message", {})
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tool_calls.append({
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"]
                    })
    except:
        pass
    return tool_calls

@app.post("/v1/chat/completions")
async def proxy_chat(request: Request):
    try:
        body = await request.body()
        body_json = json.loads(body)

        # Rewrite tool descriptions to reduce misrouting
        if "tools" in body_json:
            original_tools = [t["function"]["name"] for t in body_json["tools"] if "function" in t]
            body_json["tools"] = rewrite_tools(body_json["tools"])
            print(f"  🔧 Rewrote descriptions for: {[t for t in original_tools if t in ['terminal','read_file','search_files','write_file']]}")

        # Auto-detect active model
        active_model = await get_active_model()
        if active_model:
            body_json["model"] = active_model

        body = json.dumps(body_json).encode()

        request_id = str(uuid.uuid4())
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat()

        model = body_json.get("model", "unknown")
        messages = body_json.get("messages", [])
        tools = body_json.get("tools", [])
        tool_names = [t["function"]["name"] for t in tools if "function" in t]

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{LM_STUDIO_URL}/v1/chat/completions",
                content=body,
                headers={"Content-Type": "application/json"}
            )

        latency_ms = (time.time() - start_time) * 1000

        try:
            response_body = response.json()
        except:
            response_body = {}

        tool_calls = extract_tool_calls(response_body)
        finish_reason = response_body.get("choices", [{}])[0].get("finish_reason", "unknown")
        usage = response_body.get("usage", {})

        prompt_tokens = usage.get("prompt_tokens") or (safe_len(body_json) // 4)
        completion_tokens = usage.get("completion_tokens") or 0
        total_tokens = usage.get("total_tokens") or (prompt_tokens + completion_tokens)

        response_text = ""
        try:
            for choice in response_body.get("choices", []):
                response_text = choice.get("message", {}).get("content", "") or ""
        except:
            pass

        costs = compute_costs(prompt_tokens, completion_tokens)

        print(f"\n[{timestamp}] {request_id[:8]}")
        print(f"  Model: {model} | Tools: {len(tool_names)} | Msgs: {len(messages)}")
        print(f"  Tokens: {prompt_tokens}in + {completion_tokens}out = {total_tokens}")
        print(f"  Latency: {latency_ms:.0f}ms | Finish: {finish_reason}")
        if tool_calls:
            print(f"  🔧 {[tc['name'] for tc in tool_calls]}")
        print(f"  💰 Sonnet: ${costs['claude-sonnet-4-5']:.5f} | GPT-4o: ${costs['gpt-4o']:.5f}")

        log_to_db({
            "id": request_id,
            "timestamp": timestamp,
            "model": model,
            "messages_count": len(messages),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "tool_calls": json.dumps(tool_calls),
            "tools_available": json.dumps(tool_names),
            "tools_available_count": len(tool_names),
            "response_text": response_text[:500],
            "latency_ms": latency_ms,
            "finish_reason": finish_reason,
            "session_id": current_session
        })

        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type="application/json"
        )

    except Exception as e:
        print(f"Proxy error: {e}")
        import traceback
        traceback.print_exc()
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(
                    f"{LM_STUDIO_URL}/v1/chat/completions",
                    content=await request.body(),
                    headers={"Content-Type": "application/json"}
                )
            return Response(content=response.content, status_code=response.status_code, media_type="application/json")
        except:
            return Response(content=b'{"error": "proxy error"}', status_code=500, media_type="application/json")

@app.get("/v1/models")
async def proxy_models():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{LM_STUDIO_URL}/v1/models")
    return Response(content=response.content, media_type="application/json")

@app.get("/observatory/stats")
async def stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) as c FROM requests").fetchone()["c"]
    avg_latency = conn.execute("SELECT AVG(latency_ms) as a FROM requests").fetchone()["a"] or 0
    total_tokens = conn.execute("SELECT SUM(total_tokens) as t FROM requests").fetchone()["t"] or 0
    total_prompt = conn.execute("SELECT SUM(prompt_tokens) as t FROM requests").fetchone()["t"] or 0
    total_completion = conn.execute("SELECT SUM(completion_tokens) as t FROM requests").fetchone()["t"] or 0

    tool_rows = conn.execute("SELECT tool_calls FROM requests WHERE tool_calls != '[]'").fetchall()
    tool_counts = {}
    for row in tool_rows:
        try:
            for tc in json.loads(row["tool_calls"]):
                tool_counts[tc["name"]] = tool_counts.get(tc["name"], 0) + 1
        except:
            pass

    available_row = conn.execute("SELECT tools_available FROM requests WHERE tools_available != '[]' LIMIT 1").fetchone()
    all_available = json.loads(available_row["tools_available"]) if available_row else []
    never_called = [t for t in all_available if t not in tool_counts]

    fast = conn.execute("SELECT COUNT(*) as c FROM requests WHERE latency_ms < 1000").fetchone()["c"]
    medium = conn.execute("SELECT COUNT(*) as c FROM requests WHERE latency_ms BETWEEN 1000 AND 3000").fetchone()["c"]
    slow = conn.execute("SELECT COUNT(*) as c FROM requests WHERE latency_ms > 3000").fetchone()["c"]

    costs = compute_costs(total_prompt, total_completion)

    recent = conn.execute("""
        SELECT timestamp, model, latency_ms, finish_reason, tool_calls,
               prompt_tokens, completion_tokens, total_tokens
        FROM requests ORDER BY timestamp DESC LIMIT 10
    """).fetchall()

    sessions = conn.execute("""
        SELECT id, started_at, total_requests, total_tokens, total_tool_calls
        FROM sessions ORDER BY started_at DESC LIMIT 5
    """).fetchall()

    conn.close()

    return {
        "summary": {
            "total_requests": total,
            "avg_latency_ms": round(avg_latency, 2),
            "total_tokens": total_tokens,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
        },
        "cost_comparison": {
            "local_cost": "$0.00 (you own the GPU)",
            "vs_gpt4o": f"${costs['gpt-4o']:.4f}",
            "vs_claude_sonnet": f"${costs['claude-sonnet-4-5']:.4f}",
            "vs_claude_opus": f"${costs['claude-opus-4']:.4f}",
            "vs_gemini_flash": f"${costs['gemini-2-flash']:.4f}",
            "vs_gpt4o_mini": f"${costs['gpt-4o-mini']:.4f}",
        },
        "tool_coverage": {
            "total_available": len(all_available),
            "total_called": len(tool_counts),
            "never_called": never_called,
            "call_counts": tool_counts,
            "coverage_pct": round(len(tool_counts) / len(all_available) * 100, 1) if all_available else 0
        },
        "latency_distribution": {
            "fast_under_1s": fast,
            "medium_1_3s": medium,
            "slow_over_3s": slow
        },
        "recent_requests": [dict(r) for r in recent],
        "sessions": [dict(s) for s in sessions]
    }

@app.get("/")
async def dashboard():
    return FileResponse("/home/madhu/hermes-observatory/dashboard/index.html")
