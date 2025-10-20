import os, json, time, traceback
from uuid import uuid4
from typing import Any, Dict, List

import boto3
import requests
from playwright.sync_api import sync_playwright

# LangGraph / LangChain
from langgraph.graph import StateGraph, START, END
from langchain_core.tools import tool
from langchain_aws import ChatBedrockConverse
from typing import TypedDict

# --------- Config (env) ----------
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0")
ARTIFACT_BUCKET = os.environ["ARTIFACT_BUCKET"]

bedrock_llm = ChatBedrockConverse(model_id=MODEL_ID, temperature=0.2, max_tokens=2048)
s3 = boto3.client("s3")

SYSTEM_PROMPT = """
You are “Digital Worker,” a precise, reliable web-automation agent.

GOALS
- Read the user’s instruction & payload (JSON).
- Plan minimal steps.
- Use the available tools to browse web pages, fill forms, click buttons, read page text, take screenshots, or call HTTP APIs.
- Return a concise final JSON per the OUTPUT FORMAT.

RULES
- Prefer stable CSS selectors or obvious label/text alternatives; if a selector fails, try ONE sensible alternative.
- After each tool call, check page state and continue until the task is satisfied or impossible.
- Keep actions minimal (no unnecessary navigation, no repeated clicks).
- If something is impossible (selector missing, disabled button, page error, network block), stop and return an error JSON with a brief reason and a helpful hint.
- Do NOT include chain-of-thought; return only the required JSON.

TOOLS
- Use these tools: open_url, fill_form, click, get_text, screenshot, api_request.
- When opening a page, wait for a meaningful selector before next actions.
- Use get_text (DOM) as the source of truth for results; screenshots are optional artifacts.

OUTPUT FORMAT (strict)
Return ONLY this JSON object:
{
  "status": "ok" | "error",
  "result": {
    "summary": "1 short sentence",
    "data": {},
    "artifacts": { "screenshot_s3": "s3://bucket/key" }
  },
  "error": {
    "message": "brief reason",
    "hint": "optional actionable hint"
  }
}

STYLE
- Be deterministic.
- Short sentences. Compact JSON. No extra prose outside the JSON.
"""

# --------- Browser session management ----------
class Browser:
    def __enter__(self):
        self._pw = sync_playwright().start()
        # --no-sandbox is required in Lambda containers
        self._browser = self._pw.chromium.launch(args=["--no-sandbox"])
        self._ctx = self._browser.new_context()
        self.page = self._ctx.new_page()
        return self
    def __exit__(self, exc_type, exc, tb):
        try:
            self._ctx.close()
            self._browser.close()
        finally:
            self._pw.stop()

browser_singleton = {"session": None}

def get_browser():
    if browser_singleton["session"] is None:
        # create a new browser per invocation (simple & robust)
        browser_singleton["session"] = Browser().__enter__()
    return browser_singleton["session"]

# --------- Tools (Playwright + HTTP) ----------
@tool
def open_url(url: str, wait_for: str = None) -> Dict[str, Any]:
    """Open a page; optionally wait for a CSS selector to appear."""
    b = get_browser()
    b.page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if wait_for:
        b.page.wait_for_selector(wait_for, timeout=15000)
    return {"status": "ok", "current_url": b.page.url}

@tool
def fill_form(selector: str, value: str) -> Dict[str, Any]:
    """Fill text into a CSS selector."""
    b = get_browser()
    b.page.fill(selector, value)
    return {"status": "ok"}

@tool
def click(selector: str) -> Dict[str, Any]:
    """Click an element by CSS selector."""
    b = get_browser()
    b.page.click(selector, timeout=15000)
    return {"status": "ok"}

@tool
def get_text(selector: str) -> Dict[str, Any]:
    """Return trimmed textContent of the element."""
    b = get_browser()
    txt = (b.page.text_content(selector) or "").strip()
    return {"status": "ok", "text": txt}

@tool
def screenshot() -> Dict[str, Any]:
    """Take a full-page screenshot and upload to S3."""
    b = get_browser()
    buf = b.page.screenshot(full_page=True)
    key = f"screens/{time.strftime('%Y%m%d')}/{uuid4()}.png"
    s3.put_object(Bucket=ARTIFACT_BUCKET, Key=key, Body=buf, ContentType="image/png")
    return {"status": "ok", "s3": f"s3://{ARTIFACT_BUCKET}/{key}"}

@tool
def api_request(url: str, method: str = "GET", headers: Dict[str, str] = None, body_json: Dict[str, Any] = None) -> Dict[str, Any]:
    """Make an HTTP(S) request."""
    headers = headers or {}
    method = (method or "GET").upper()
    try:
        resp = requests.request(method, url, headers=headers, json=body_json, timeout=30)
        return {"status":"ok", "http_status": resp.status_code, "body": resp.text[:5000]}
    except Exception as e:
        return {"status":"error", "message": str(e)}

TOOLS = [open_url, fill_form, click, get_text, screenshot, api_request]

# Bind tools to Bedrock (Converse)
llm = bedrock_llm.bind_tools(TOOLS)

# --------- LangGraph state & nodes ----------
class AgentState(TypedDict):
    messages: List[Dict[str, Any]]

def agent_node(state: AgentState) -> AgentState:
    """Ask the model. It may answer directly or request tools."""
    response = llm.invoke(state["messages"])
    state["messages"].append({"role": "assistant", "content": response.content, "raw": response})
    return state

def route_after_agent(state: AgentState):
    """If tool calls exist, go to tools; else END."""
    raw = state["messages"][-1]["raw"]
    tool_calls = getattr(raw, "tool_calls", None) or []
    return "tools" if tool_calls else END

def run_tools(state: AgentState) -> AgentState:
    """Execute each requested tool and append their outputs as messages."""
    raw = state["messages"][-1]["raw"]
    tool_calls = getattr(raw, "tool_calls", []) or []
    tool_msgs = []
    for tc in tool_calls:
        name = tc["name"]
        args = tc["args"]
        # find matching tool
        found = None
        for t in TOOLS:
            if t.name == name:
                found = t
                break
        if not found:
            tool_msgs.append({"role": "tool", "name": name, "content": json.dumps({"error": f"Unknown tool: {name}"})})
            continue
        try:
            result = found.invoke(args)
        except Exception as e:
            result = {"status": "error", "message": str(e)}
        tool_msgs.append({"role": "tool", "name": name, "content": json.dumps(result)})
    state["messages"].extend(tool_msgs)
    return state

# Build the graph
graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("tools", run_tools)
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")
app = graph.compile()

def _start_messages(instruction: str, payload: Dict[str, Any]):
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"instruction": instruction, "payload": payload})}
    ]

def lambda_handler(event, context):
    """
    event: { "instruction": "...", "payload": {...} }
    """
    try:
        instruction = event.get("instruction","")
        payload = event.get("payload",{})
        messages = _start_messages(instruction, payload)

        # Run the LangGraph loop (agent ↔ tools) until finish
        state = app.invoke({"messages": messages})

        # Expect the last assistant message to contain the final JSON string
        final_msg = None
        for m in reversed(state["messages"]):
            if m["role"] == "assistant":
                final_msg = m["content"]
                break

        try:
            parsed = json.loads(final_msg)
            return {"statusCode": 200, "body": parsed}
        except Exception:
            return {"statusCode": 200, "body": {"status":"error","error":{"message":"Non-JSON final output","hint":"Ensure the model returns only the JSON."},"raw": final_msg}}
    except Exception as e:
        return {"statusCode": 500, "body": {"status":"error","error":{"message":str(e),"hint":"See CloudWatch logs for stack trace."}, "trace": traceback.format_exc()}}
