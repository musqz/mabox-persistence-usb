import pytest

from mabox_persistence_usb import persist_luks


def test_build_luks_format_command_uses_luks2_and_stdin_keyfile():
    cmd = persist_luks.build_luks_format_command("/dev/sdb3")
    assert "--type" in cmd and "luks2" in cmd
    assert "--key-file=-" in cmd
    assert cmd[-1] == "/dev/sdb3"


def test_build_luks_format_command_is_batch_mode():
    assert "-q" in persist_luks.build_luks_format_command("/dev/sdb3")


def test_build_luks_open_command_uses_stdin_keyfile():
    cmd = persist_luks.build_luks_open_command("/dev/sdb3", "mabox_persist")
    assert "--key-file=-" in cmd
    assert cmd[-2:] == ["/dev/sdb3", "mabox_persist"]


def test_build_luks_close_command():
    assert persist_luks.build_luks_close_command("mabox_persist") == ["cryptsetup", "close", "mabox_persist"]


def test_prompt_for_passphrase_returns_when_entries_match(monkeypatch):
    monkeypatch.setattr(persist_luks.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(persist_luks.getpass, "getpass", lambda _: "correct horse")
    assert persist_luks.prompt_for_passphrase() == "correct horse"


def test_prompt_for_passphrase_retries_on_mismatch_then_succeeds(monkeypatch):
    monkeypatch.setattr(persist_luks.sys.stdin, "isatty", lambda: True)
    answers = iter(["first", "second", "match", "match"])
    monkeypatch.setattr(persist_luks.getpass, "getpass", lambda _: next(answers))
    assert persist_luks.prompt_for_passphrase() == "match"


def test_prompt_for_passphrase_rejects_empty_then_succeeds(monkeypatch):
    monkeypatch.setattr(persist_luks.sys.stdin, "isatty", lambda: True)
    answers = iter(["", "ok", "ok"])
    monkeypatch.setattr(persist_luks.getpass, "getpass", lambda _: next(answers))
    assert persist_luks.prompt_for_passphrase() == "ok"


def test_prompt_for_passphrase_raises_when_not_interactive(monkeypatch):
    monkeypatch.setattr(persist_luks.sys.stdin, "isatty", lambda: False)
    with pytest.raises(RuntimeError, match="--encrypt-persist"):
        persist_luks.prompt_for_passphrase()


def test_format_persist_encrypted_closes_mapper_even_on_mkfs_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(persist_luks, "format_container", lambda p, pw: calls.append(("format", p)))
    monkeypatch.setattr(persist_luks, "open_container", lambda p, m, pw: calls.append(("open", p, m)))
    monkeypatch.setattr(persist_luks, "close_container", lambda m: calls.append(("close", m)))
    monkeypatch.setattr(
        persist_luks.partition, "format_persist_plain",
        lambda p: (_ for _ in ()).throw(RuntimeError("mkfs failed")),
    )

    with pytest.raises(RuntimeError, match="mkfs failed"):
        persist_luks.format_persist_encrypted("/dev/sdb3", "secret", mapper_name="mabox_persist")

    assert ("close", "mabox_persist") in calls


def test_format_persist_encrypted_does_not_close_if_open_never_succeeded(monkeypatch):
    calls = []
    monkeypatch.setattr(
        persist_luks, "format_container",
        lambda p, pw: (_ for _ in ()).throw(RuntimeError("luksFormat failed")),
    )
    monkeypatch.setattr(persist_luks, "open_container", lambda p, m, pw: calls.append(("open", p, m)))
    monkeypatch.setattr(persist_luks, "close_container", lambda m: calls.append(("close", m)))

    with pytest.raises(RuntimeError, match="luksFormat failed"):
        persist_luks.format_persist_encrypted("/dev/sdb3", "secret", mapper_name="mabox_persist")

    assert calls == []


def test_format_persist_encrypted_uses_mapper_device_path_for_mkfs(monkeypatch):
    mkfs_calls = []
    monkeypatch.setattr(persist_luks, "format_container", lambda p, pw: None)
    monkeypatch.setattr(persist_luks, "open_container", lambda p, m, pw: None)
    monkeypatch.setattr(persist_luks, "close_container", lambda m: None)
    monkeypatch.setattr(persist_luks.partition, "format_persist_plain", mkfs_calls.append)

    persist_luks.format_persist_encrypted("/dev/sdb3", "secret", mapper_name="mabox_persist")

    assert mkfs_calls == ["/dev/mapper/mabox_persist"]
