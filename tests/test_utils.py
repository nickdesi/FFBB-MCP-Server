from ffbb_mcp.utils import serialize_model


def test_serialize_simple_types():
    assert serialize_model(1) == 1
    assert serialize_model("test") == "test"
    assert serialize_model(True) is True
    assert serialize_model(None) is None


def test_serialize_dict():
    data = {"a": 1, "b": "test"}
    assert serialize_model(data) == data


def test_serialize_list():
    data = [1, "test", {"a": 1}]
    assert serialize_model(data) == data


class DemoObject:
    def __init__(self):
        self.a = 1
        self._private = 2

    def method(self):
        pass


def test_serialize_object():
    obj = DemoObject()
    serialized = serialize_model(obj)
    assert serialized == {"a": 1}
    assert "_private" not in serialized
