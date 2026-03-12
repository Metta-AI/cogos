from cogos.capabilities import BUILTIN_CAPABILITIES

for cap in BUILTIN_CAPABILITIES:
    add_capability(
        cap["name"],
        handler=cap["handler"],
        description=cap.get("description", ""),
        instructions=cap.get("instructions", ""),
        schema=cap.get("schema"),
    )
