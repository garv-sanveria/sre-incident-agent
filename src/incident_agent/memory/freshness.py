from datetime import datetime, timezone

def is_usable(memory, now=None):
    if "status:deprecated" in memory.get("tags",[]):
        return False
    expiry=memory.get("metadata",{}).get("valid_until")
    if not expiry:
        return False
    try:
        value=datetime.fromisoformat(expiry.replace("Z","+00:00"))
        return value.tzinfo is not None and value > (now or datetime.now(timezone.utc))
    except (ValueError, TypeError):
        return False
