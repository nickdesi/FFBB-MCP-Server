from typing import Any


def serialize_model(obj: Any) -> Any:
    """Convertit un objet FFBB en dict JSON-serializable de manière récursive."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: serialize_model(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize_model(item) for item in obj]
    if hasattr(obj, "__dict__"):
        return {
            k: serialize_model(v)
            for k, v in obj.__dict__.items()
            if not k.startswith("_")
        }
    return str(obj)
