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
    if hasattr(obj, "model_dump"):  # Pydantic v2
        return serialize_model(obj.model_dump())
    if hasattr(obj, "dict"):  # Pydantic v1
        return serialize_model(obj.dict())
    if hasattr(obj, "__dict__"):
        return {
            k: serialize_model(v)
            for k, v in obj.__dict__.items()
            if not k.startswith("_")
        }
    return str(obj)
