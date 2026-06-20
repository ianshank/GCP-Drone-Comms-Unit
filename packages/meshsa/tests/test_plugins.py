"""Entry-point plugin discovery (logic tested via an injected entry_points fn)."""

from meshsa.plugins import TRANSPORT_GROUP, load_plugins


class _FakeEP:
    def __init__(self, name, loader):
        self.name = name
        self._loader = loader

    def load(self):
        return self._loader()


def test_load_plugins_loads_and_returns_names():
    ran = []

    def eps(group):
        return [_FakeEP("halow", lambda: ran.append(group))] if group == TRANSPORT_GROUP else []

    loaded = load_plugins(groups=[TRANSPORT_GROUP], entry_points=eps)
    assert loaded == ["halow"]
    assert ran == [TRANSPORT_GROUP]  # the entry point was actually loaded (imported)


def test_load_plugins_skips_failing_plugin():
    def boom():
        raise ImportError("broken driver")

    def eps(group):
        return [_FakeEP("bad", boom), _FakeEP("ok", lambda: None)]

    loaded = load_plugins(groups=["meshsa.transports"], entry_points=eps)
    assert loaded == ["ok"]  # broken plugin skipped, others still load
