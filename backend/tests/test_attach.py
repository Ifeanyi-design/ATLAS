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
