from scripts import attach


def test_attach_writes_project_config_with_project_name(tmp_path) -> None:
    config_path = attach.write_project_config(tmp_path, "bizlive-dashboard")

    content = config_path.read_text(encoding="utf-8")

    assert "[mcp_servers.atlas]" in content
    assert "[mcp_servers.atlas.env]" in content
    assert 'ATLAS_PROJECT_NAME = "bizlive-dashboard"' in content


def test_attach_replaces_existing_atlas_blocks_and_preserves_other_config(tmp_path) -> None:
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[mcp_servers.other]\n"
        'command = "other"\n'
        "\n"
        "[mcp_servers.atlas]\n"
        'command = "old"\n'
        "\n"
        "[mcp_servers.atlas.env]\n"
        'ATLAS_PROJECT_NAME = "old"\n',
        encoding="utf-8",
    )

    config_path = attach.write_project_config(tmp_path, "new-project")
    content = config_path.read_text(encoding="utf-8")

    assert '[mcp_servers.other]\ncommand = "other"' in content
    assert 'command = "old"' not in content
    assert content.count("[mcp_servers.atlas]") == 1
    assert 'ATLAS_PROJECT_NAME = "new-project"' in content


def test_attach_creates_agents_guidance(tmp_path) -> None:
    agents_path = attach.upsert_agents_guidance(tmp_path)
    content = agents_path.read_text(encoding="utf-8")

    assert agents_path == tmp_path / "AGENTS.md"
    assert "Atlas Memory Workflow" in content
    assert "get_context" in content
    assert attach.ATLAS_AGENTS_START in content
    assert attach.ATLAS_AGENTS_END in content


def test_attach_preserves_existing_agents_content_and_replaces_managed_block(tmp_path) -> None:
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(
        "# Project Rules\n\n"
        "- Keep existing user guidance.\n\n"
        f"{attach.ATLAS_AGENTS_START}\n"
        "old atlas text\n"
        f"{attach.ATLAS_AGENTS_END}\n",
        encoding="utf-8",
    )

    attach.upsert_agents_guidance(tmp_path)
    content = agents_path.read_text(encoding="utf-8")

    assert "- Keep existing user guidance." in content
    assert "old atlas text" not in content
    assert content.count(attach.ATLAS_AGENTS_START) == 1
    assert content.count(attach.ATLAS_AGENTS_END) == 1


def test_attach_updates_agents_override_when_present(tmp_path) -> None:
    override_path = tmp_path / "AGENTS.override.md"
    override_path.write_text("# Override Rules\n", encoding="utf-8")

    agents_path = attach.upsert_agents_guidance(tmp_path)

    assert agents_path == override_path
    assert "Atlas Memory Workflow" in override_path.read_text(encoding="utf-8")
    assert not (tmp_path / "AGENTS.md").exists()
