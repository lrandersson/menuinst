"""Tests for distribution_name resolution and menuinst.toml tracking."""

import json
import logging
from pathlib import Path

import pytest

from menuinst.api import (
    _install_adapter,
    delete_paths,
    get_recorded_paths,
    install,
    record_shortcuts,
    remove,
    remove_shortcut_records,
    write_menuinst_toml,
)
from menuinst.platforms import Menu
from menuinst.utils import MENUINST_TOML_SCHEMA_VERSION, parse_schemaver, read_menuinst_toml

# Placeholder distribution names for tests
DIST_NAME = "Something"
DIST_NAME_ALT = "SomethingElse"


class TestGetDistributionName:
    """Tests for Menu._get_distribution_name() resolution order."""

    def test_env_var_takes_priority(self, tmp_path, monkeypatch):
        """MENUINST_DISTRIBUTION_NAME env var should be used when set."""
        monkeypatch.setenv("MENUINST_DISTRIBUTION_NAME", DIST_NAME)
        menu = Menu("test", prefix=str(tmp_path), base_prefix=str(tmp_path))
        assert menu._get_distribution_name() == DIST_NAME
        assert menu.placeholders["DISTRIBUTION_NAME"] == DIST_NAME

    def test_toml_used_when_no_env_var(self, tmp_path, monkeypatch):
        """TOML value should be used when env var is not set."""
        monkeypatch.delenv("MENUINST_DISTRIBUTION_NAME", raising=False)
        write_menuinst_toml(tmp_path, {"distribution_name": DIST_NAME})
        menu = Menu("test", prefix=str(tmp_path), base_prefix=str(tmp_path))
        assert menu._get_distribution_name() == DIST_NAME

    def test_fallback_to_base_prefix_name(self, tmp_path, monkeypatch):
        """Should fall back to base_prefix.name when no env var or TOML."""
        monkeypatch.delenv("MENUINST_DISTRIBUTION_NAME", raising=False)
        menu = Menu("test", prefix=str(tmp_path), base_prefix=str(tmp_path))
        assert menu._get_distribution_name() == tmp_path.name

    def test_env_var_overrides_toml(self, tmp_path, monkeypatch):
        """Env var should take priority over TOML value."""
        monkeypatch.setenv("MENUINST_DISTRIBUTION_NAME", DIST_NAME)
        write_menuinst_toml(tmp_path, {"distribution_name": DIST_NAME_ALT})
        menu = Menu("test", prefix=str(tmp_path), base_prefix=str(tmp_path))
        assert menu._get_distribution_name() == DIST_NAME

    def test_malformed_toml_raises(self, tmp_path, monkeypatch):
        """Malformed TOML should raise an exception."""
        monkeypatch.delenv("MENUINST_DISTRIBUTION_NAME", raising=False)
        toml_path = tmp_path / "Menu" / "menuinst.toml"
        toml_path.parent.mkdir(parents=True, exist_ok=True)
        toml_path.write_text("this is not valid toml {{{{")
        with pytest.raises(ValueError, match="Failed to read"):
            # On Linux, Menu() triggers _get_distribution_name() during __init__,
            # but on Windows/macOS it's lazy. Call it explicitly to ensure the
            # error is raised on all platforms.
            menu = Menu("test", prefix=str(tmp_path), base_prefix=str(tmp_path))
            menu._get_distribution_name()


class TestShortcutRecording:
    """Tests for shortcut recording and removal in menuinst.toml."""

    def test_install_records_to_toml(self, tmp_path, monkeypatch):
        """install() should record shortcuts to menuinst.toml."""
        monkeypatch.delenv("MENUINST_DISTRIBUTION_NAME", raising=False)
        base_prefix = tmp_path / "base"
        base_prefix.mkdir()

        # Test via record_shortcuts directly
        record_shortcuts(
            base_prefix,
            base_prefix,
            "foo.json",
            [tmp_path / "foo.lnk", tmp_path / "bar.lnk"],
            distribution_name=DIST_NAME,
        )

        data = read_menuinst_toml(base_prefix)
        assert data["distribution_name"] == DIST_NAME
        assert len(data["shortcuts"]) == 2
        assert data["shortcuts"][0]["source"] == "foo.json"

    def test_remove_cleans_toml(self, tmp_path, monkeypatch):
        """remove() should clean up TOML entries."""
        monkeypatch.delenv("MENUINST_DISTRIBUTION_NAME", raising=False)
        base_prefix = tmp_path / "base"
        base_prefix.mkdir()

        # Pre-populate TOML with shortcuts from two sources
        write_menuinst_toml(
            base_prefix,
            {
                "distribution_name": DIST_NAME,
                "shortcuts": [
                    {"source": "foo.json", "path": "/path/to/foo.lnk"},
                    {"source": "foo.json", "path": "/path/to/bar.lnk"},
                    {"source": "baz.json", "path": "/path/to/baz.lnk"},
                ],
            },
        )

        # Remove records for foo.json
        remove_shortcut_records(base_prefix, "foo.json")

        data = read_menuinst_toml(base_prefix)
        assert len(data["shortcuts"]) == 1
        assert data["shortcuts"][0]["source"] == "baz.json"
        # distribution_name should be preserved
        assert data["distribution_name"] == DIST_NAME

    def test_distribution_name_only_written_to_base_prefix(self, tmp_path):
        """distribution_name should only be written when prefix == base_prefix."""
        base_prefix = tmp_path / "base"
        env_prefix = tmp_path / "envs" / "foo"
        base_prefix.mkdir(parents=True)
        env_prefix.mkdir(parents=True)

        # Record to base prefix - should include distribution_name
        record_shortcuts(
            base_prefix,
            base_prefix,
            "foo.json",
            [tmp_path / "foo.lnk"],
            distribution_name=DIST_NAME,
        )
        data = read_menuinst_toml(base_prefix)
        assert data.get("distribution_name") == DIST_NAME

        # Record to non-base prefix - should NOT include distribution_name
        record_shortcuts(
            env_prefix,
            base_prefix,
            "bar.json",
            [tmp_path / "bar.lnk"],
            distribution_name=DIST_NAME,
        )
        data = read_menuinst_toml(env_prefix)
        assert "distribution_name" not in data
        assert len(data["shortcuts"]) == 1


class TestInstallAdapter:
    """Tests for _install_adapter recording correct source filename."""

    def test_records_actual_filename_not_menu_name(self, tmp_path, monkeypatch):
        """_install_adapter should record JSON filename, not rendered menu_name."""
        monkeypatch.delenv("MENUINST_DISTRIBUTION_NAME", raising=False)
        (tmp_path / ".nonadmin").touch()
        menu_dir = tmp_path / "Menu"
        menu_dir.mkdir()

        # Create JSON with menu_name containing placeholder
        json_file = menu_dir / "test_shortcut.json"
        json_file.write_text(
            json.dumps(
                {
                    "$schema": "https://json-schema.org/draft-07/schema",
                    "menu_name": "{{ DISTRIBUTION_NAME }} Foo Bar",
                    "menu_items": [
                        {
                            "name": "Foo Bar",
                            "command": ["echo", "test"],
                            "activate": False,
                            "platforms": {"linux": {}, "win": {}, "osx": {}},
                        }
                    ],
                }
            )
        )

        _install_adapter(str(json_file), prefix=str(tmp_path), root_prefix=str(tmp_path))

        data = read_menuinst_toml(tmp_path)
        # Source should be the filename, not "{{ DISTRIBUTION_NAME }} Foo Bar.json"
        assert data["shortcuts"][0]["source"] == "test_shortcut.json"


class TestSchemaVersion:
    """Tests for SchemaVer parsing and TOML schema version handling."""

    @pytest.mark.parametrize(
        "version,expected",
        [
            ("1-0-0", (1, 0, 0)),
            ("1-1-3", (1, 1, 3)),
            ("2-0-0", (2, 0, 0)),
            ("10-20-30", (10, 20, 30)),
        ],
    )
    def test_parse_schemaver_valid(self, version, expected):
        """Valid SchemaVer strings should parse correctly."""
        assert parse_schemaver(version) == expected

    @pytest.mark.parametrize(
        "version",
        [
            "1",
            "1-0",
            "1.0.0",
            "1-0-0-0",
            "a-b-c",
            "",
        ],
    )
    def test_parse_schemaver_invalid(self, version):
        """Invalid SchemaVer strings should raise ValueError."""
        with pytest.raises(ValueError):
            parse_schemaver(version)

    def test_toml_writes_schemaver_format(self, tmp_path):
        """write_menuinst_toml should write schema_version in SchemaVer format."""
        write_menuinst_toml(tmp_path, {"distribution_name": "Test"})
        data = read_menuinst_toml(tmp_path)
        assert data["schema_version"] == MENUINST_TOML_SCHEMA_VERSION
        # Verify it's a valid SchemaVer string
        parse_schemaver(data["schema_version"])


class TestGetRecordedPaths:
    """Tests for get_recorded_paths()."""

    def test_returns_paths_for_source(self, tmp_path):
        """Test that paths matching the given source are returned."""
        write_menuinst_toml(
            tmp_path,
            {
                "shortcuts": [
                    {"source": "foo.json", "path": "/path/to/foo.lnk"},
                    {"source": "foo.json", "path": "/path/to/bar.lnk"},
                    {"source": "baz.json", "path": "/path/to/baz.lnk"},
                ],
            },
        )
        paths = get_recorded_paths(tmp_path, "foo.json")
        assert paths == [Path("/path/to/foo.lnk"), Path("/path/to/bar.lnk")]

    def test_returns_empty_list_when_no_matches(self, tmp_path):
        """Test that empty list is returned when no shortcuts match source."""
        write_menuinst_toml(
            tmp_path,
            {"shortcuts": [{"source": "other.json", "path": "/path/to/other.lnk"}]},
        )
        paths = get_recorded_paths(tmp_path, "foo.json")
        assert paths == []

    def test_returns_empty_list_when_no_toml(self, tmp_path):
        """Test that empty list is returned when menuinst.toml doesn't exist."""
        paths = get_recorded_paths(tmp_path, "foo.json")
        assert paths == []

    def test_skips_entries_missing_path_key(self, tmp_path):
        """Test that shortcuts missing the 'path' key are skipped."""
        write_menuinst_toml(
            tmp_path,
            {
                "shortcuts": [
                    {"source": "foo.json", "path": "/valid/path.lnk"},
                    {"source": "foo.json"},  # Missing path key
                ],
            },
        )
        paths = get_recorded_paths(tmp_path, "foo.json")
        assert paths == [Path("/valid/path.lnk")]


class TestDeletePaths:
    """Tests for delete_paths()."""

    def test_deletes_existing_files(self, tmp_path):
        """Test that existing files are deleted and their paths returned."""
        file1 = tmp_path / "foo.lnk"
        file2 = tmp_path / "bar.lnk"
        file1.touch()
        file2.touch()

        deleted = delete_paths([file1, file2])

        assert not file1.exists()
        assert not file2.exists()
        assert len(deleted) == 2

    def test_deletes_directories(self, tmp_path):
        """Test that directories (e.g., .app bundles) are deleted using rmtree."""
        app_dir = tmp_path / "MyApp.app"
        app_dir.mkdir()
        (app_dir / "Contents").mkdir()
        (app_dir / "Contents" / "Info.plist").touch()

        deleted = delete_paths([app_dir])

        assert not app_dir.exists()
        assert len(deleted) == 1

    def test_warns_on_missing_path(self, tmp_path, caplog):
        """Test that a warning is logged when path doesn't exist."""
        missing = tmp_path / "nonexistent.lnk"

        with caplog.at_level(logging.WARNING):
            deleted = delete_paths([missing])

        assert len(deleted) == 0
        assert "Shortcut not found at expected location" in caplog.text
        assert str(missing) in caplog.text


class TestRemoveUsesTomlPaths:
    """Tests for TOML-based shortcut removal."""

    def test_remove_uses_recorded_paths(self, tmp_path):
        """Test that remove() deletes files at recorded TOML paths, not computed paths."""
        (tmp_path / ".nonadmin").touch()
        menu_dir = tmp_path / "Menu"
        menu_dir.mkdir()

        recorded_path = tmp_path / "recorded_location" / "MyShortcut.lnk"
        recorded_path.parent.mkdir(parents=True)
        recorded_path.touch()

        write_menuinst_toml(
            tmp_path,
            {"shortcuts": [{"source": "test.json", "path": str(recorded_path)}]},
        )

        json_file = menu_dir / "test.json"
        json_file.write_text(
            json.dumps(
                {
                    "$schema": "https://json-schema.org/draft-07/schema",
                    "menu_name": "Test Menu",
                    "menu_items": [
                        {
                            "name": "MyShortcut",
                            "command": ["echo", "test"],
                            "activate": False,
                            "platforms": {"linux": {}, "win": {}, "osx": {}},
                        }
                    ],
                }
            )
        )

        remove(str(json_file), target_prefix=str(tmp_path), base_prefix=str(tmp_path))

        assert not recorded_path.exists()

    def test_remove_falls_back_when_no_toml_entries(self, tmp_path, monkeypatch):
        """Test that remove() falls back to computed paths when no TOML entries exist."""
        monkeypatch.delenv("MENUINST_DISTRIBUTION_NAME", raising=False)
        (tmp_path / ".nonadmin").touch()
        menu_dir = tmp_path / "Menu"
        menu_dir.mkdir()

        json_file = menu_dir / "test.json"
        json_file.write_text(
            json.dumps(
                {
                    "$schema": "https://json-schema.org/draft-07/schema",
                    "menu_name": "Test Menu",
                    "menu_items": [
                        {
                            "name": "MyShortcut",
                            "command": ["echo", "test"],
                            "activate": False,
                            "platforms": {"linux": {}, "win": {}, "osx": {}},
                        }
                    ],
                }
            )
        )

        # Install shortcuts
        paths = install(str(json_file), target_prefix=str(tmp_path), base_prefix=str(tmp_path))
        shortcut_paths = [
            p for p in paths if Path(p).suffix in (".lnk", ".desktop") or Path(p).is_dir()
        ]
        assert shortcut_paths, "Expected at least one shortcut to be created"

        # Clear TOML to simulate legacy install (pre-TOML tracking)
        write_menuinst_toml(tmp_path, {})

        # Remove should use fallback computed paths
        remove(str(json_file), target_prefix=str(tmp_path), base_prefix=str(tmp_path))

        # Verify shortcuts were removed
        for p in shortcut_paths:
            assert not Path(p).exists(), f"Shortcut should have been removed: {p}"
