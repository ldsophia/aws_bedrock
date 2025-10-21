import os, json, time, boto3

s3 = boto3.client("s3")
agentcore = boto3.client("bedrock-agentcore")

BUCKET = os.environ["BUCKET"]
BROWSER_ID = os.environ.get("BROWSER_IDENTIFIER", "aws.browser.v1")

def _payload_to_text(event):
    if event.get("payloadText"):
        return str(event["payloadText"])
    p = event.get("payload", [])
    if isinstance(p, list):
        names = [str(x.get("name", "")) for x in p if isinstance(x, dict)]
        return ", ".join([n for n in names if n])
    return json.dumps(p, ensure_ascii=False)

def handler(event, context):
    instruction = event.get("instruction", "")
    text_to_paste = _payload_to_text(event)

    start = agentcore.start_browser_session(
        browserIdentifier=BROWSER_ID,
        name=f"digital-worker-{int(time.time())}",
        sessionTimeoutSeconds=300
    )
    session_id = start["sessionId"]

    try:
        # ===== 在这里对接你的 browser-use / Nova Act 适配器 =====
        # 例如：传入 session_id、instruction、text_to_paste，
        # 让代理自动：打开 convertcase.net → 粘贴文本 → 截图
        #
        # bytes_png = do_actions_and_screenshot(session_id, instruction, text_to_paste)
        #
        one_px_png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
            "/w8AAn8B9m3p5QAAAABJRU5ErkJggg=="
        )
        bytes_png = base64.b64decode(one_px_png_b64)

        key = f"digital-worker/screens/{int(time.time())}.png"
        s3.put_object(Bucket=BUCKET, Key=key, Body=bytes_png, ContentType="image/png")

        return {
            "status": "SUCCESS",
            "finalUrl": "https://convertcase.net/",
            "screenshotS3": f"s3://{BUCKET}/{key}"
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}
    finally:
        try:
            agentcore.stop_browser_session(
                browserIdentifier=BROWSER_ID,
                sessionId=session_id
            )
        except Exception:
            pass
