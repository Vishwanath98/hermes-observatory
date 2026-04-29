import json

# Injected descriptions that steer model toward specialized tools
TOOL_DESCRIPTION_OVERRIDES = {
    "read_file": (
        "PREFERRED tool for reading file contents. "
        "Always use this instead of 'terminal' with cat/head/tail commands. "
        "Faster, safer, and returns structured output with line numbers."
    ),
    "search_files": (
        "PREFERRED tool for listing and finding files. "
        "Always use this instead of 'terminal' with ls/find commands. "
        "More reliable and works across all environments."
    ),
    "write_file": (
        "PREFERRED tool for writing or creating files. "
        "Always use this instead of 'terminal' with echo/tee/redirect commands."
    ),
    "terminal": (
        "Use ONLY for: running scripts, installing packages, starting servers, "
        "git operations, or commands with no equivalent specialized tool. "
        "DO NOT use for reading files (use read_file), "
        "listing files (use search_files), or writing files (use write_file)."
    ),
}

def rewrite_tools(tools: list) -> list:
    """Inject better descriptions into tool definitions."""
    rewritten = []
    for tool in tools:
        if tool.get("type") == "function":
            name = tool["function"]["name"]
            if name in TOOL_DESCRIPTION_OVERRIDES:
                tool = json.loads(json.dumps(tool))  # deep copy
                tool["function"]["description"] = TOOL_DESCRIPTION_OVERRIDES[name]
        rewritten.append(tool)
    return rewritten
