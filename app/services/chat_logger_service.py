import json
from datetime import datetime
from pathlib import Path


LOG_PATH = Path("data/chat_logs.jsonl")


def log_chat(entry: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    entry["timestamp"] = datetime.now().isoformat(timespec="seconds")

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_logs(limit: int = 50):
    if not LOG_PATH.exists():
        return []

    with open(LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    logs = []

    for line in lines[-limit:]:
        try:
            logs.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return logs
