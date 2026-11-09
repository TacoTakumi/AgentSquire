"""The public release-check surface and the no-startup-request rule.

Three things are pinned here. The five release names are exported from the
package. The source of the package opens a URL in one place only, and only
check_for_update reaches that place. An import of the package and the two
startup hooks (check_stale, notify_update) make no network request.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

import agentsquire
import agentsquire._pypi
import agentsquire._release_cache
import agentsquire.cli
import agentsquire.release
import agentsquire.staleness
from agentsquire._release_cache import write_cache
from agentsquire.harnesses import CLAUDE_CODE
from agentsquire.sources import DirectorySource
from agentsquire.verbs import install

SRC = Path(__file__).parent.parent / "src"
PACKAGE_DIR = SRC / "agentsquire"

# The modules that make up the release check.
RELEASE_MODULES = ("release.py", "_pypi.py", "_release_cache.py", "_install.py")

# A distribution name that is not installed.
DIST = "fixture-consumer"

HOME_MODULES = {
    "check_for_update": agentsquire.release,
    "ReleaseCheck": agentsquire.release,
    "ReleaseStatus": agentsquire.release,
    "notify_update": agentsquire.staleness,
    "check_update_command": agentsquire.cli,
}


# --- the exports ------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(HOME_MODULES))
def test_name_is_exported_and_is_the_home_object(name):
    assert name in agentsquire.__all__
    assert getattr(agentsquire, name) is getattr(HOME_MODULES[name], name)


def test_all_has_no_duplicate_and_each_name_resolves():
    assert len(agentsquire.__all__) == len(set(agentsquire.__all__))
    for name in agentsquire.__all__:
        assert hasattr(agentsquire, name), name


def test_star_import_gives_the_five_names():
    namespace = {}
    exec("from agentsquire import *", namespace)
    for name, home in HOME_MODULES.items():
        assert namespace[name] is getattr(home, name)


def test_unknown_attribute_still_raises_attribute_error():
    with pytest.raises(AttributeError):
        agentsquire.no_such_name


# --- the source scan --------------------------------------------------------


def source_files():
    files = sorted(PACKAGE_DIR.glob("*.py"))
    assert files, "no source file found"
    return files


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def scoped_nodes(tree):
    """Yield (node, scope) for each node of the tree.

    scope is the tuple of the names of the enclosing functions, outermost
    first. It is empty for module-level code. A class is not a scope here.
    """

    def walk(node, scope):
        for child in ast.iter_child_nodes(node):
            yield child, scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from walk(child, scope + (child.name,))
            else:
                yield from walk(child, scope)

    yield from walk(tree, ())


def mentions(node, name):
    """True when the node refers to ``name`` as a name, attribute or import."""
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute):
        return node.attr == name
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return any(
            name in alias.name.split(".") or alias.asname == name
            for alias in node.names
        )
    return False


def references(name):
    """Each (file name, scope) in the package source that refers to ``name``."""
    found = []
    for path in source_files():
        for node, scope in scoped_nodes(parse(path)):
            if mentions(node, name):
                found.append((path.name, scope))
    return found


def imported_modules(tree):
    """Each (dotted module name, scope) that the tree imports."""
    found = []
    for node, scope in scoped_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, scope))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            found.append((base, scope))
            for alias in node.names:
                found.append((f"{base}.{alias.name}".strip("."), scope))
    return found


def docstrings(tree):
    """The docstring nodes of the tree."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                found.add(body[0].value)
    return found


def test_urlopen_is_used_in_the_pypi_open_step_only():
    assert references("urlopen") == [("_pypi.py", ("_open",))]

    calls = []
    for path in source_files():
        for node, scope in scoped_nodes(parse(path)):
            if isinstance(node, ast.Call) and mentions(node.func, "urlopen"):
                calls.append((path.name, scope))
    assert calls == [("_pypi.py", ("_open",))]


def test_the_open_step_is_used_by_fetch_only():
    assert references("_open") == [("_pypi.py", ("fetch",))]


def test_no_other_way_to_open_a_connection_is_imported():
    # urllib.request lives in _pypi.py only, and no other network client is
    # imported anywhere in the package.
    network_roots = {
        "socket",
        "http",
        "ftplib",
        "smtplib",
        "asyncio",
        "xmlrpc",
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
    }
    for path in source_files():
        for module, _scope in imported_modules(parse(path)):
            parts = module.split(".")
            assert parts[0] not in network_roots, (path.name, module)
            if parts[:2] == ["urllib", "request"]:
                assert path.name == "_pypi.py", (path.name, module)
    for name in ("urlretrieve", "build_opener", "OpenerDirector", "create_connection"):
        assert references(name) == [], name


def test_pypi_is_imported_by_the_release_module_only():
    importers = []
    for path in source_files():
        tree = parse(path)
        for module, scope in imported_modules(tree):
            if "_pypi" in module.split("."):
                importers.append((path.name, scope))
        if path.name in ("release.py", "_pypi.py"):
            continue
        # No import of the module by its name in a string either.
        skip = docstrings(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node not in skip
            ):
                assert "_pypi" not in node.value, path.name
    # One import, inside the function that makes the fetch: an import of the
    # release module does not load the HTTP client.
    assert set(importers) == {("release.py", ("_fetch_body",))}
    assert [
        (name, scope) for name, scope in references("_pypi") if name != "release.py"
    ] == []


def release_functions():
    """Map each module-level function of release.py to the names it uses."""
    tree = parse(PACKAGE_DIR / "release.py")
    uses = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = set()
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name):
                    names.add(inner.id)
                elif isinstance(inner, ast.Attribute):
                    names.add(inner.attr)
            uses[node.name] = names
    return tree, uses


def test_the_fetch_is_reached_from_check_for_update_only():
    # The fetch attribute of _pypi is read in release.py only.
    readers = []
    for path in source_files():
        for node, scope in scoped_nodes(parse(path)):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "fetch"
                and mentions(node.value, "_pypi")
            ):
                readers.append((path.name, scope[:1]))
    assert readers, "the _pypi.fetch reference was not found"
    assert {name for name, _scope in readers} == {"release.py"}
    assert all(scope for _name, scope in readers), "module-level code reads the fetch"

    tree, uses = release_functions()
    reaching = {scope[0] for _name, scope in readers}
    assert reaching <= set(uses)

    # Follow the callers inside release.py up to the entry points.
    changed = True
    while changed:
        changed = False
        for function, names in uses.items():
            if function not in reaching and names & reaching:
                reaching.add(function)
                changed = True
    entry_points = {
        function
        for function in reaching
        if not any(function in uses[other] for other in reaching if other != function)
    }
    assert entry_points == {"check_for_update"}

    # No module-level code and no class body of release.py runs the fetch.
    for node, scope in scoped_nodes(tree):
        if not scope and isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            assert name not in reaching, name

    # No other module uses the private steps between the entry point and
    # the fetch.
    for private in reaching - {"check_for_update"}:
        assert {name for name, _scope in references(private)} == {"release.py"}, private


def test_check_for_update_is_called_by_the_check_update_command_only():
    callers = []
    for path in source_files():
        if path.name == "release.py":
            continue
        for node, scope in scoped_nodes(parse(path)):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and path.name == "__init__.py":
                # The package export. It binds the name and calls nothing.
                continue
            if mentions(node, "check_for_update"):
                callers.append((path.name, scope[:1]))
    assert callers, "the check_for_update call was not found"
    assert set(callers) == {("cli.py", ("check_update_command",))}

    # The package __init__ holds imports and assignments only: it calls
    # nothing at import time.
    init = parse(PACKAGE_DIR / "__init__.py")
    for node, scope in scoped_nodes(init):
        if not scope:
            assert not isinstance(node, ast.Call), ast.dump(node)


# --- no subprocess ----------------------------------------------------------

PROCESS_NAMES = {
    "subprocess",
    "Popen",
    "popen",
    "system",
    "check_call",
    "check_output",
    "posix_spawn",
    "posix_spawnp",
    "fork",
    "forkpty",
}


def starts_a_process(node):
    """The name by which the node could start a process, or None."""
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.Attribute):
        name = node.attr
    else:
        return None
    if name in PROCESS_NAMES or name.startswith(("exec", "spawn")):
        # The built-in exec is not a process start, but it has no place in
        # this code either.
        return name
    return None


@pytest.mark.parametrize("filename", RELEASE_MODULES)
def test_release_module_uses_no_subprocess(filename):
    tree = parse(PACKAGE_DIR / filename)
    for module, _scope in imported_modules(tree):
        parts = module.split(".")
        assert "subprocess" not in parts, module
        assert parts[0] not in ("multiprocessing", "pty", "shlex"), module
    for node in ast.walk(tree):
        assert starts_a_process(node) is None, (filename, starts_a_process(node))


def test_check_update_command_uses_no_subprocess():
    tree = parse(PACKAGE_DIR / "cli.py")
    for module, _scope in imported_modules(tree):
        assert "subprocess" not in module.split("."), module
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "check_update_command"
    ]
    assert len(functions) == 1
    for node in ast.walk(functions[0]):
        assert starts_a_process(node) is None, starts_a_process(node)
        assert not isinstance(node, (ast.Import, ast.ImportFrom)) or all(
            module.split(".")[0] == "agentsquire"
            for module, _scope in imported_modules(ast.Module(body=[node], type_ignores=[]))
        )


# --- no request at startup --------------------------------------------------


def write_skill(root: Path, name: str) -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A fixture skill.\n---\n\nbody\n"
    )
    (skill / "reference.md").write_text(f"reference for {name}\n")


def make_stale_env(root: Path) -> None:
    """One installed skill whose bundled copy changed after the install."""
    for sub in ("home", "project", "bundle"):
        (root / sub).mkdir()
    write_skill(root / "bundle", "awiki-search")
    install(
        DirectorySource(root / "bundle"),
        CLAUDE_CODE,
        scope="user",
        home=root / "home",
        project=root / "project",
        source_package=DIST,
        source_version="1.2.3",
    )
    (root / "bundle" / "awiki-search" / "reference.md").write_text("v2\n")


SKILLS_LINE_START = "awiki: "
RELEASE_LINE = "fixture: a new release is available: 1.0.0 -> 2.0.0\n"


def test_startup_hooks_make_no_fetch_call(
    tmp_path, monkeypatch, capsys, block_socket_connections
):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTSQUIRE_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(agentsquire._release_cache, "_is_windows", lambda: False)
    prefix = tmp_path / "plain-venv"
    prefix.mkdir()
    monkeypatch.setattr(sys, "prefix", str(prefix))

    calls = []

    def no_fetch(*args, **kwargs):
        calls.append(args)
        pytest.fail("a startup path called the fetch step")

    def no_open(*args, **kwargs):
        calls.append(args)
        pytest.fail("a startup path opened a URL")

    monkeypatch.setattr(agentsquire._pypi, "fetch", no_fetch)
    monkeypatch.setattr(agentsquire._pypi, "_open", no_open)

    make_stale_env(tmp_path)
    # A cache that gives a notice: the hook has a reason to do its work.
    write_cache(DIST, "2.0.0")
    capsys.readouterr()

    import agentsquire as sq

    assert sq.check_stale(
        sq.DirectorySource(tmp_path / "bundle"),
        sq.CLAUDE_CODE,
        scope="user",
        home=tmp_path / "home",
        project=tmp_path / "project",
        prog_name="awiki",
        update_command="awiki skills update",
    ) is None
    skills = capsys.readouterr()
    assert skills.out == ""
    assert skills.err.startswith(SKILLS_LINE_START)
    assert "awiki skills update" in skills.err

    assert sq.notify_update(DIST, "1.0.0", prog_name="fixture") is None
    release = capsys.readouterr()
    assert (release.out, release.err) == ("", RELEASE_LINE)

    assert calls == []
    assert block_socket_connections.attempts == []


def test_import_does_not_load_the_http_client():
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, agentsquire; assert 'agentsquire._pypi' not in sys.modules",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )
    assert done.returncode == 0, done.stderr.decode()


STARTUP_SCRIPT = """\
import socket
import sys
from pathlib import Path

attempts = []


def blocked(*args, **kwargs):
    attempts.append(args[-1:])
    raise RuntimeError("network access is blocked")


socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.create_connection = blocked
socket.getaddrinfo = blocked

import agentsquire as sq

root = Path(sys.argv[1])
sq.check_stale(
    sq.DirectorySource(root / "bundle"),
    sq.CLAUDE_CODE,
    scope="user",
    home=root / "home",
    project=root / "project",
    prog_name="awiki",
    update_command="awiki skills update",
)
sq.notify_update("fixture-consumer", "1.0.0", prog_name="fixture")

assert attempts == [], attempts
assert "agentsquire._pypi" not in sys.modules
assert "urllib.request" not in sys.modules
print("DONE")
"""


def test_fresh_process_startup_makes_no_request(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(agentsquire._release_cache, "_is_windows", lambda: False)
    make_stale_env(tmp_path)
    write_cache(DIST, "2.0.0")
    script = tmp_path / "startup.py"
    script.write_text(STARTUP_SCRIPT)

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("CI", "AGENTSQUIRE_NO_UPDATE_CHECK")
    }
    env["PYTHONPATH"] = str(SRC)
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["HOME"] = str(tmp_path / "home")

    done = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
        env=env,
    )

    stderr = done.stderr.decode()
    assert done.returncode == 0, stderr
    assert done.stdout.decode().splitlines() == ["DONE"]
    lines = stderr.splitlines()
    # Both hooks had a notice to print, so both did their work.
    assert len(lines) == 2, stderr
    assert lines[0].startswith("awiki: ")
    assert lines[1].startswith("fixture: a new release is available: 1.0.0 -> 2.0.0")
