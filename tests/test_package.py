import importlib.metadata

import agentsquire


def test_package_importable_and_versioned():
    assert agentsquire.__version__


def test_questionary_is_a_hard_runtime_dependency():
    """REQ-01: questionary is a plain runtime dependency, never gated behind an extra."""
    requires = importlib.metadata.requires("agentsquire") or []
    matches = [
        req
        for req in requires
        if req.split(";", 1)[0].strip().lower().startswith("questionary")
    ]
    assert matches, "questionary is not declared as a runtime dependency of agentsquire"
    for req in matches:
        assert "extra ==" not in req, f"questionary must not be gated behind an extra: {req!r}"
