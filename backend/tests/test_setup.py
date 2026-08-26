import builtins

from scripts import setup


def test_setup_installs_requirements_with_the_active_python(monkeypatch) -> None:
    marker = setup.PROJECT_ROOT / "work" / ".test-requirements.sha256"
    marker.unlink(missing_ok=True)
    calls: list[list[str]] = []
    monkeypatch.setattr(setup.subprocess, "run", lambda command, **_: calls.append(command))
    monkeypatch.setattr(setup, "dependencies_are_available", lambda: False)
    monkeypatch.setattr(setup, "DEPENDENCY_MARKER_PATH", marker)

    setup.install_dependencies()

    assert calls == [[setup.sys.executable, "-m", "pip", "install", "-r", str(setup.PROJECT_ROOT / "requirements.txt")]]
    marker.unlink(missing_ok=True)


def test_setup_skips_dependency_install_when_marker_matches(monkeypatch) -> None:
    marker = setup.PROJECT_ROOT / "work" / ".test-requirements.sha256"
    marker.write_text(setup._requirements_hash() + "\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(setup.subprocess, "run", lambda command, **_: calls.append(command))
    monkeypatch.setattr(setup, "dependencies_are_available", lambda: True)
    monkeypatch.setattr(setup, "DEPENDENCY_MARKER_PATH", marker)

    setup.install_dependencies()

    assert calls == []
    marker.unlink(missing_ok=True)


def test_docker_options_show_when_docker_is_installed_but_not_running(monkeypatch) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(setup, "find_docker_command", lambda: "docker")
    monkeypatch.setattr(setup, "docker_is_ready", lambda _command=None: False)
    monkeypatch.setattr(builtins, "input", lambda prompt: prompts.append(prompt) or "4")

    storage_mode, database_url, start_container, apply_migrations, auto_start = setup.choose_storage()

    assert storage_mode == "sqlite"
    assert database_url == setup.LOCAL_SQLITE_URL
    assert start_container is False
    assert apply_migrations is False
    assert auto_start is False
    assert prompts == ["Choose 1, 2, 3, or 4 [4]: "]


def test_setup_creates_legacy_work_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path)

    setup.ensure_codex_work_permissions()

    assert (tmp_path / "work").is_dir()
