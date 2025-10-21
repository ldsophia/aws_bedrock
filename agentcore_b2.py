# -*- coding: utf-8 -*-
# 文件名：lambda_function.py
import os
import json
import time
import boto3
import base64
from contextlib import contextmanager

# Playwright（Python）
from playwright.sync_api import sync_playwright

s3 = boto3.client("s3")

# AgentCore Browser：既可直接用 boto3 数据面 API，也可用 BrowserClient 辅助类（见官方文档）
# 这里采用 BrowserClient（推荐），它会帮你生成 WebSocket/CDP 连接所需的 url 与 headers
from bedrock_agentcore.tools.browser_client import BrowserClient  # 官方文档示例中提供的类  :contentReference[oaicite:2]{index=2}

BUCKET = os.environ["BUCKET"]
BROWSER_ID = os.environ.get("BROWSER_IDENTIFIER", "aws.browser.v1")

def _payload_to_text(event: dict) -> str:
    """把输入里的 payloadText 或 payload 转成要粘贴的字符串"""
    if event.get("payloadText"):
        return str(event["payloadText"])
    p = event.get("payload", [])
    if isinstance(p, list) and all(isinstance(x, dict) for x in p):
        names = [str(x.get("name", "")) for x in p if "name" in x]
        # 例如：["jack", "name"] -> "jack, name"
        s = ", ".join([n for n in names if n])
        return s if s else json.dumps(p, ensure_ascii=False)
    return json.dumps(p, ensure_ascii=False)

@contextmanager
def _browser_session(region: str = None, timeout_sec: int = 300):
    """
    使用 BrowserClient 启动 AgentCore 浏览器会话，生成 CDP 连接信息，并在 finally 中停止会话。
    参考官方“Starting a browser session / BrowserClient”示例。  :contentReference[oaicite:3]{index=3}
    """
    client = BrowserClient(region=region)
    # 启动会话（会在你的 Browser Tool 上创建一个托管 Chrome 会话）
    client.start(browser_identifier=BROWSER_ID, session_timeout_seconds=timeout_sec)
    try:
        # 生成用于 connect_over_cdp 的 WS 地址和 headers
        ws_url, ws_headers = client.generate_ws_headers()
        yield client, ws_url, ws_headers
    finally:
        # 结束会话
        client.stop()

def _safe_locator(page, selector: str):
    """
    工具：获取页面元素，容错处理（convertcase 页面主要控件是动态渲染，优先用通用定位）
    """
    try:
        return page.locator(selector).first
    except Exception:
        return None

def _perform_convertcase(page, text_to_paste: str):
    """
    在 convertcase.net：
    - 找到主 textarea 并粘贴文本
    - 点击 "UPPER CASE"
    - 返回当前页面文本（可选）与截图字节
    """
    # 页面加载
    page.goto("https://convertcase.net/", wait_until="domcontentloaded", timeout=60000)

    # 页面是 JS 驱动的，通用策略：
    # 1) 先找 'textarea'（通常只会有一个主文本框）
    # 2) 若找不到，再尝试 contenteditable 或其它兜底方案
    textarea = _safe_locator(page, "textarea")
    if textarea is None or textarea.count() == 0:
        # 部分场景 textarea 可能在 shadow DOM 或延迟生成；尝试通配
        page.wait_for_timeout(1500)
        textarea = _safe_locator(page, "textarea")

    if textarea is None or textarea.count() == 0:
        # 兜底：尝试 body 点击+键入（不理想，但保证流程不中断）
        page.click("body")
        page.keyboard.type(text_to_paste)
    else:
        textarea.click()
        # 先全选清空，避免残留
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.press("Backspace")
        textarea.fill(text_to_paste)

    # 点击 “UPPER CASE”
    # 这个按钮可能是 tab/链接/按钮，使用文本近似匹配更稳妥
    # 优先用 get_by_text；若失败，再尝试 role=link/button 的名称匹配
    try:
        page.get_by_text("UPPER CASE", exact=False).first.click(timeout=10000)
    except Exception:
        try:
            page.get_by_role("link", name="UPPER CASE").click(timeout=10000)
        except Exception:
            # 再兜底用包含文本的任意元素
            page.locator("text=UPPER CASE").first.click(timeout=10000)

    # 等待转换完成（页面会把 textarea 内容改成大写）
    page.wait_for_timeout(1200)

    # 读取转换后的文本（如果找得到 textarea）
    result_text = None
    try:
        if textarea and textarea.count() > 0:
            result_text = textarea.input_value(timeout=2000)
    except Exception:
        pass

    # 截图（全屏）
    bytes_png = page.screenshot(full_page=True)

    return result_text, bytes_png

def handler(event, context):
    """
    期望输入示例：
    {
      "instruction": "Open https://convertcase.net/, paste payload.text into the main textarea, then take a screenshot.",
      "payload": [
        {"client_id": "1", "name": "jack"},
        {"client_id": "2", "name": "name"}
      ],
      "payloadText": "jack, name"
    }
    """
    region = os.getenv("AWS_REGION", "us-west-2")
    text_to_paste = _payload_to_text(event)
    now_ts = int(time.time())

    with _browser_session(region=region, timeout_sec=300) as (client, ws_url, ws_headers):
        # 通过 Playwright 连接到 **托管浏览器**（CDP）
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(ws_url, headers=ws_headers)
            try:
                # 复用默认 context；若无则新建
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()

                result_text, bytes_png = _perform_convertcase(page, text_to_paste)

                # 上传截图到 S3
                key = f"digital-worker/screens/{now_ts}.png"
                s3.put_object(
                    Bucket=BUCKET,
                    Key=key,
                    Body=bytes_png,
                    ContentType="image/png"
                )

                return {
                    "status": "SUCCESS",
                    "finalUrl": page.url,
                    "screenshotS3": f"s3://{BUCKET}/{key}",
                    "extracted": result_text
                }
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
