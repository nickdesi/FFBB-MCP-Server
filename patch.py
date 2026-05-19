filepath = "src/ffbb_mcp/services.py"

with open(filepath) as f:
    content = f.read()


search_block = """def _parse_dt(raw: str | None) -> datetime | None:
    \"\"\"Parse une date FFBB en datetime avec la timezone spécifiée.\"\"\"
    if not raw:
        return None
    tz = _PARIS_TZ

    try:
        # Fast path for Python 3.11+: fromisoformat natively supports spaces.
        # This replaces the costly fallback loop and string replace.
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except ValueError:
        pass

    # Fallback pour Python <= 3.10 : fromisoformat ne supporte pas
    # toujours l'espace comme séparateur. On le remplace par 'T' via
    # concatenation (plus rapide que str.replace) si la date fait 19 chars.
    if type(raw) is str and len(raw) == 19 and raw[10] == " ":
        try:
            dt = datetime.fromisoformat(raw[:10] + "T" + raw[11:])
            if dt.tzinfo is None:
                return dt.replace(tzinfo=tz)
            return dt.astimezone(tz)
        except ValueError:
            pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=tz)
            return dt.astimezone(tz)
        except ValueError:
            pass

    return None"""

replace_block = """def _parse_dt(raw: str | None) -> datetime | None:
    \"\"\"Parse une date FFBB en datetime avec la timezone spécifiée.\"\"\"
    if raw is None:
        return None
    tz = _PARIS_TZ
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except ValueError:
        pass
    return None"""

if search_block in content:
    print("Found block, replacing...")
    new_content = content.replace(search_block, replace_block)
    with open(filepath, "w") as f:
        f.write(new_content)
else:
    print("Could not find block")
