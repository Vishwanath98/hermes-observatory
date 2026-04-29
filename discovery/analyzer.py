import sqlite3
import json
from collections import defaultdict

DB_PATH = "/home/madhu/hermes-observatory/data/telemetry.db"

def analyze_tool_routing():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    rows = conn.execute("""
        SELECT timestamp, tool_calls, messages_count, prompt_tokens
        FROM requests 
        WHERE tool_calls != '[]'
        ORDER BY timestamp
    """).fetchall()
    
    # Tool transition analysis - what tool follows what
    tool_sequence = []
    for row in rows:
        calls = json.loads(row["tool_calls"])
        for call in calls:
            tool_sequence.append(call["name"])
    
    # Transition matrix
    transitions = defaultdict(lambda: defaultdict(int))
    for i in range(len(tool_sequence) - 1):
        transitions[tool_sequence[i]][tool_sequence[i+1]] += 1
    
    # Command pattern analysis for terminal
    terminal_commands = []
    for row in rows:
        calls = json.loads(row["tool_calls"])
        for call in calls:
            if call["name"] == "terminal":
                try:
                    args = json.loads(call["arguments"])
                    cmd = args.get("command", "")
                    # Classify what the terminal command is actually doing
                    if any(x in cmd for x in ["cat ", "head ", "tail "]):
                        terminal_commands.append(("READ_FILE", cmd, "should_use: read_file"))
                    elif any(x in cmd for x in ["ls ", "ls\n", "find "]):
                        terminal_commands.append(("LIST_FILES", cmd, "should_use: search_files"))
                    elif any(x in cmd for x in ["echo ", "> ", "tee "]):
                        terminal_commands.append(("WRITE_FILE", cmd, "should_use: write_file"))
                    elif any(x in cmd for x in ["grep ", "rg "]):
                        terminal_commands.append(("SEARCH", cmd, "should_use: search_files"))
                    else:
                        terminal_commands.append(("EXECUTE", cmd, "terminal_correct"))
                except:
                    pass
    
    conn.close()
    
    return {
        "tool_sequence": tool_sequence,
        "transitions": {k: dict(v) for k, v in transitions.items()},
        "terminal_misrouting": [
            {"operation": op, "command": cmd[:80], "suggestion": sug}
            for op, cmd, sug in terminal_commands
            if sug != "terminal_correct"
        ],
        "terminal_correct_usage": [
            {"command": cmd[:80]}
            for op, cmd, sug in terminal_commands
            if sug == "terminal_correct"
        ],
        "misrouting_rate": round(
            len([x for x in terminal_commands if x[2] != "terminal_correct"]) / 
            max(len(terminal_commands), 1) * 100, 1
        )
    }

if __name__ == "__main__":
    result = analyze_tool_routing()
    print("\n=== TOOL ROUTING ANALYSIS ===")
    print(f"\nTool sequence: {result['tool_sequence']}")
    print(f"\nTransitions: {json.dumps(result['transitions'], indent=2)}")
    print(f"\nMisrouting rate: {result['misrouting_rate']}%")
    print(f"\nTerminal used instead of specialized tools:")
    for m in result["terminal_misrouting"]:
        print(f"  [{m['operation']}] {m['command']}")
        print(f"    → {m['suggestion']}")
    print(f"\nCorrect terminal usage:")
    for c in result["terminal_correct_usage"]:
        print(f"  {c['command']}")
