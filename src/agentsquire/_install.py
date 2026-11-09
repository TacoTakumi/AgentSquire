"""Install detection: the installed version and the upgrade command.

Two lookups about the running environment, both local and both safe to call
from a startup hook: neither touches the network and neither raises.

The upgrade command is known for two install methods. A uv tool environment
holds a uv-receipt.toml file in its root, and a pipx environment is a
directory named pipx/venvs/<name>. For every other environment, and for an
editable checkout in any environment, there is no command to give.
"""

from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path


def installed_version(distribution: str) -> str | None:
    """Version of the distribution from the install metadata, else None.

    None when the distribution is not installed or the lookup fails.
    """
    try:
        return importlib.metadata.version(distribution)
    except Exception:
        return None


def _is_editable(distribution: str) -> bool:
    """True when the distribution is installed as an editable checkout.

    An editable install records dir_info.editable in its direct_url.json
    metadata file. A distribution that is not installed, or one with no such
    file or an unreadable one, is not editable.
    """
    try:
        text = importlib.metadata.distribution(distribution).read_text("direct_url.json")
        if not text:
            return False
        return json.loads(text)["dir_info"]["editable"] is True
    except Exception:
        return False


def upgrade_command(distribution: str) -> str | None:
    """Command that upgrades the distribution in the running environment.

    The distribution name is used exactly as passed. None when the install
    method is not known or the distribution is an editable checkout, which an
    upgrade command would replace with a released version.
    """
    try:
        if _is_editable(distribution):
            return None
        # Read at call time: the running environment is whatever sys.prefix
        # names now.
        prefix = Path(sys.prefix)
        if (prefix / "uv-receipt.toml").is_file():
            return f"uv tool upgrade {distribution}"
        if prefix.parts[-3:-1] == ("pipx", "venvs"):
            return f"pipx upgrade {distribution}"
        return None
    except Exception:
        return None
