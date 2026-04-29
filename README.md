# hermes-observatory

> Framework-agnostic telemetry proxy for AI agents.

A FastAPI proxy that sits between any AI agent and its LLM backend, capturing every decision invisibly — no agent code changes required.

---

## The Problem

AI agents are black boxes. You can't see which tools they pick, why they pick them, how much it costs, or which execution paths never get tested. This project makes all of that visible.

---

## Key Findings

From instrumenting a real autonomous agent (Hermes) running qwen3.5-35b locally:

- **76.9% tool misrouting** — the agent used terminal shell commands instead of purpose-built tools (read_file, search_files) for file operations
- **6.2% tool coverage** — only 2 of 32 available tools were ever called in a session
- **$0 local vs $10.58 Claude Opus** — for the same 689K token workload
- **Fixed misrouting without touching agent code** — by rewriting tool descriptions at the proxy layer

---

## How It Works
Agent (Hermes / LangGraph / any OpenAI-compatible)
↓
Observatory Proxy :1235   ← intercepts everything here
↓
LM Studio :1234           ← local inference (RTX 3090)
↓
SQLite                    ← telemetry stored per request
↓
Live Dashboard            ← visible at http://server:1235

The proxy is completely transparent — the agent never knows it's there.

---

## What Gets Captured

Per request:
- Model used, token counts (prompt + completion)
- Tool calls made and arguments
- All tools available vs tools actually called
- Latency in milliseconds
- Finish reason

Aggregated:
- Tool coverage % across all runs
- Cost comparison vs GPT-4o, Claude Sonnet, Claude Opus, Gemini
- Latency distribution (fast/medium/slow)
- Tool usage heatmap
- Never-called tools (untested surface area)

---

## The Misrouting Fix

The analyzer detected that 76.9% of terminal tool calls should have used specialized tools:
[LIST_FILES]  ls -la          → should use: search_files
[READ_FILE]   cat file.py     → should use: read_file
[WRITE_FILE]  echo "x" > f   → should use: write_file

Fix: rewrite tool descriptions in-flight at the proxy layer.
The model now receives steered descriptions without any agent code changes:

```python
"terminal": "Use ONLY for running scripts, git operations. 
             NOT for reading files (use read_file) or listing files (use search_files)."
```

---

## Stack

- **FastAPI** — proxy server
- **SQLite** — telemetry storage
- **Chart.js** — live dashboard
- **LM Studio** — local inference backend
- **Tailscale** — remote access to pop-os from anywhere

---

## Structure
hermes-observatory/
proxy/
proxy.py          Main proxy — intercepts all LLM calls
discovery/
analyzer.py       Tool routing analysis — detects misrouting
tool_rewriter.py  In-flight tool description intervention
dashboard/
index.html        Live dashboard — auto-refreshes every 3s

---

## Running

```bash
python3 -m venv venv && source venv/bin/activate
pip install fastapi uvicorn httpx sqlite-utils rich pydantic

# Start LM Studio on :1234 first
~/.lmstudio/bin/lms server start --port 1234

# Start proxy
uvicorn proxy.proxy:app --host 0.0.0.0 --port 1235 --reload

# Point your agent at :1235 instead of :1234
# Dashboard at http://localhost:1235
# Stats API at http://localhost:1235/observatory/stats
```

---

## Related

**lg-evals** — LangGraph + MCP telemetry evaluation system. Measures graph coverage, edge transitions, and tool routing across runs. Found and fixed a structural coverage gap (executor→synthesizer never triggered), reducing latency 52%.
