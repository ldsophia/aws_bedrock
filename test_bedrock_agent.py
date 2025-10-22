def import_check(event, context):
    import bedrock_agentcore
    from bedrock_agentcore.tools.browser_client import BrowserClient
    return {"ok": True, "sdk_version": getattr(bedrock_agentcore, "__version__", "unknown")}
