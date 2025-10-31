import logging
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import py
import pytest

logging.basicConfig(level=logging.DEBUG)

pytest_plugins = ("conda.testing.fixtures",)

os.environ["PYTEST_IN_USE"] = "1"


@pytest.fixture()
def delete_files():
    paths = []
    yield paths
    for path in paths:
        path = Path(path)
        # If the list contains duplicates, a path may already have been deleted.
        if not path.exists():
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except IOError:
            logging.warning("Could not delete %s", path, exc_info=True)


@pytest.fixture(scope="function")
def tmpdir(tmpdir, request):
    Path(str(tmpdir)).mkdir(parents=True, exist_ok=True)
    tmpdir = TemporaryDirectory(dir=str(tmpdir))
    request.addfinalizer(tmpdir.cleanup)
    return py.path.local(tmpdir.name)


@pytest.fixture(autouse=True)
def mock_locations(monkeypatch, tmp_path):
    from menuinst.platforms.linux import LinuxMenu
    from menuinst.platforms.osx import MacOSMenuItem

    if os.name == "nt":
        from menuinst.platforms.win_utils import knownfolders

        def windows_locations(preferred_mode, check_other_mode, key):
            return tmp_path / key

        monkeypatch.setattr(knownfolders, "folder_path", windows_locations)

    def osx_base_location(self):
        return tmp_path

    if not os.environ.get("CI"):
        monkeypatch.setattr(MacOSMenuItem, "_base_location", osx_base_location)

    # For Linux
    if not os.environ.get("CI"):
        monkeypatch.setattr(LinuxMenu, "_system_config_directory", tmp_path / "config")
        monkeypatch.setattr(LinuxMenu, "_system_data_directory", tmp_path / "data")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))


@pytest.fixture()
def run_as_user(monkeypatch):
    from menuinst import utils as menuinst_utils

    monkeypatch.setattr(menuinst_utils, "user_is_admin", lambda: False)
