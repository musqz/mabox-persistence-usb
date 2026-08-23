from mabox_persistence_usb import privilege


def test_is_root_false_for_non_root_euid(monkeypatch):
    monkeypatch.setattr(privilege.os, "geteuid", lambda: 1000)
    assert privilege.is_root() is False


def test_is_root_true_for_root_euid(monkeypatch):
    monkeypatch.setattr(privilege.os, "geteuid", lambda: 0)
    assert privilege.is_root() is True


def test_require_root_raises_when_not_root(monkeypatch):
    monkeypatch.setattr(privilege.os, "geteuid", lambda: 1000)
    try:
        privilege.require_root("write")
    except privilege.NotRootError as e:
        assert "requires root" in str(e)
    else:
        raise AssertionError("expected NotRootError")


def test_require_root_passes_when_root(monkeypatch):
    monkeypatch.setattr(privilege.os, "geteuid", lambda: 0)
    privilege.require_root("write")  # must not raise
