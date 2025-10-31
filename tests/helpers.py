import json
import os
from pathlib import Path
from subprocess import check_output

from menuinst.platforms.base import platform_key

DATA = Path(__file__).parent / "data"
LEGACY = Path(__file__).parent / "_legacy"
PLATFORM = platform_key()

def base_prefix():
    prefix = os.environ.get("CONDA_ROOT", os.environ.get("MAMBA_ROOT_PREFIX"))
    if not prefix:
        prefix = json.loads(check_output(["conda", "info", "--json"]))["root_prefix"]
    return prefix


BASE_PREFIX = base_prefix()
