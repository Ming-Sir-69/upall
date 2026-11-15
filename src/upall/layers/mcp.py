"""Read-only MCP checks for npx-style servers (no TUI, no installs, no config writes)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
import urllib.error
import urllib.parse
import urllib.request

STATUS_OK = "ok"
STATUS_OUTDATED = "outdated"
STATUS_UNKNOWN = "unknown"
STATUS_SKIP = "skip"

_VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?")
_NPX_FLAGS_VALUE = {"-p", "--package", "-c", "--call", "--node-options", "--shell", "-r", "--require"}
_PKG_SPEC = re.compile(
    r"^(?P<name>(?:@[A-Za-z0-9~^*!().'_-]+/)?[A-Za-z0-9~^*!().'_-]+)(?:@(?P<tag>.+))?$"
)

RegistryFetcher = Callable[[str, float], Optional[str]]


def _home(home: Optional[Path | str] = None) -> Path:
    return Path(home).expanduser() if home is not None else Path.home()


def _result(
    *,
    id: str,
    host: str,
    package: Optional[str] = None,
    current: Optional[str] = None,
    latest: Optional[str] = None,
    status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "id": id,
        "host": host,
        "package": package,
        "current": current,
        "latest": latest,
        "status": status,
        "reason": reason,
    }


def _read_json(path: Path) -> Optional[Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def mcp_config_candidates(home: Optional[Path | str] = None) -> list[tuple[str, Path]]:
    """Known user-level MCP config paths (host, path). Missing files are fine."""
    root = _home(home)
    candidates: list[tuple[str, Path]] = [
        ("cursor", root / ".cursor" / "mcp.json"),
        ("claude-code", root / ".claude.json"),
        ("claude-desktop", root / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"),
        ("claude-desktop", root / ".config" / "Claude" / "claude_desktop_config.json"),
        ("vscode", root / "Library" / "Application Support" / "Code" / "User" / "mcp.json"),
        ("vscode", root / ".config" / "Code" / "User" / "mcp.json"),
        ("windsurf", root / ".codeium" / "windsurf" / "mcp_config.json"),
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(("claude-desktop", Path(appdata) / "Claude" / "claude_desktop_config.json"))
        candidates.append(("vscode", Path(appdata) / "Code" / "User" / "mcp.json"))
    return candidates


def _iter_server_maps(data: Any) -> Iterable[tuple[str, dict]]:
    """Yield (scope, mcpServers-dict) from common config shapes without leaking secrets."""
    if not isinstance(data, dict):
        return
    servers = data.get("mcpServers")
    if isinstance(servers, dict):
        yield "", servers
    # Claude Code may nest per-project servers; only take mcpServers maps.
    projects = data.get("projects")
    if isinstance(projects, dict):
        for project_key, project in projects.items():
            if not isinstance(project, dict):
                continue
            nested = project.get("mcpServers")
            if isinstance(nested, dict):
                label = Path(str(project_key)).name or "project"
                yield label, nested


def discover_mcp_entries(home: Optional[Path | str] = None) -> list[dict[str, Any]]:
    """Read-only discovery of MCP server entries from local host configs."""
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for host, path in mcp_config_candidates(home):
        data = _read_json(path)
        if data is None:
            continue
        for scope, servers in _iter_server_maps(data):
            if not isinstance(servers, dict):
                continue
            for server_id, raw in servers.items():
                if not isinstance(server_id, str) or not isinstance(raw, dict):
                    continue
                key = (host, scope, server_id)
                if key in seen:
                    continue
                seen.add(key)
                entry_id = f"{scope}/{server_id}" if scope else server_id
                entries.append({
                    "id": entry_id,
                    "host": host,
                    "path": str(path),
                    "config": _public_server_view(raw),
                })
    return entries


def _public_server_view(raw: dict) -> dict[str, Any]:
    """Copy only non-secret structural fields needed for npx checks."""
    view: dict[str, Any] = {}
    for key in ("command", "args", "type", "url", "disabled", "enabled"):
        if key not in raw:
            continue
        value = raw[key]
        if key == "args" and isinstance(value, list):
            view[key] = [str(item) for item in value]
        elif key in ("command", "type", "url") and isinstance(value, str):
            view[key] = value
        elif key in ("disabled", "enabled") and isinstance(value, bool):
            view[key] = value
    return view


def _is_disabled(config: dict) -> bool:
    if config.get("disabled") is True:
        return True
    if config.get("enabled") is False:
        return True
    return False


def _is_remote(config: dict) -> bool:
    kind = str(config.get("type") or "").lower()
    if kind in {"http", "sse", "streamable-http", "websocket", "ws"}:
        return True
    if isinstance(config.get("url"), str) and config["url"].strip():
        return True
    return False


def _command_is_npx(command: Optional[str]) -> bool:
    if not command or not isinstance(command, str):
        return False
    base = Path(command).name.lower()
    return base in {"npx", "npx.cmd", "npx.exe"}


def parse_npx_package(command: Optional[str], args: Optional[list] = None) -> Optional[dict[str, str]]:
    """Extract package name / requested tag from an npx-style MCP command."""
    if not _command_is_npx(command):
        return None
    argv = [str(a) for a in (args or [])]
    i = 0
    package_spec = None
    while i < len(argv):
        token = argv[i]
        if token in {"-p", "--package"} and i + 1 < len(argv):
            package_spec = argv[i + 1]
            break
        if token.startswith("--package="):
            package_spec = token.split("=", 1)[1]
            break
        if token in _NPX_FLAGS_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        package_spec = token
        break
    if not package_spec:
        return None
    match = _PKG_SPEC.match(package_spec)
    if not match:
        return None
    name = match.group("name")
    tag = match.group("tag") or "latest"
    if not name or name.startswith("-"):
        return None
    return {"name": name, "tag": tag, "spec": package_spec}


def npx_cache_dir(package_spec: str, home: Optional[Path | str] = None) -> Path:
    """npm npx cache folder name: sha512(spec).hexdigest()[:16] under ~/.npm/_npx."""
    digest = hashlib.sha512(package_spec.encode("utf-8")).hexdigest()[:16]
    return _home(home) / ".npm" / "_npx" / digest


def _package_json_version(path: Path) -> Optional[str]:
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if isinstance(version, str) and _VERSION.fullmatch(version):
        return version
    return None


def _node_module_package_json(cache_root: Path, package_name: str) -> Path:
    return cache_root / "node_modules" / Path(*package_name.split("/")) / "package.json"


def read_npx_cached_version(
    package_name: str,
    *,
    home: Optional[Path | str] = None,
    specs: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Read installed version from npm npx cache metadata (no subprocess)."""
    root = _home(home)
    tried: list[str] = []
    for spec in list(specs or []) + [package_name, f"{package_name}@latest"]:
        if spec in tried:
            continue
        tried.append(spec)
        cache = npx_cache_dir(spec, root)
        version = _package_json_version(_node_module_package_json(cache, package_name))
        if version:
            return version
        # Some caches only record the requested dependency range in the root package.json.
        meta = _read_json(cache / "package.json")
        if isinstance(meta, dict):
            deps = meta.get("dependencies") or {}
            if isinstance(deps, dict) and package_name in deps:
                version = _package_json_version(_node_module_package_json(cache, package_name))
                if version:
                    return version

    # Fallback: scan _npx roots for a matching dependency (bounded, read-only).
    npx_root = root / ".npm" / "_npx"
    try:
        children = list(npx_root.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_dir():
            continue
        meta = _read_json(child / "package.json")
        if not isinstance(meta, dict):
            continue
        deps = meta.get("dependencies") or {}
        if not isinstance(deps, dict) or package_name not in deps:
            continue
        version = _package_json_version(_node_module_package_json(child, package_name))
        if version:
            return version
    return None


def fetch_npm_latest(package_name: str, timeout: float = 8.0) -> Optional[str]:
    """HTTPS GET registry.npmjs.org/<pkg>/latest; returns version or None on failure."""
    if not package_name or "://" in package_name or ".." in package_name:
        return None
    encoded = "/".join(urllib.parse.quote(part, safe="@") for part in package_name.split("/"))
    url = f"https://registry.npmjs.org/{encoded}/latest"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "upall-mcp-check"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — fixed npm registry host
            raw = response.read(1_000_000)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if isinstance(version, str) and _VERSION.fullmatch(version):
        return version
    return None


def _version_tuple(version: str) -> Optional[tuple[int, ...]]:
    core = version.lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    if not re.fullmatch(r"\d+(?:\.\d+)*", core):
        return None
    try:
        return tuple(int(part) for part in core.split("."))
    except ValueError:
        return None


def compare_versions(current: str, latest: str) -> str:
    """Return ok / outdated / unknown for two version strings."""
    left, right = _version_tuple(current), _version_tuple(latest)
    if left is None or right is None:
        return STATUS_UNKNOWN
    if left < right:
        return STATUS_OUTDATED
    return STATUS_OK


def check_npx_package(
    name: str,
    *,
    home: Optional[Path | str] = None,
    fetch_latest: bool = True,
    timeout: float = 8.0,
    registry: Optional[RegistryFetcher] = None,
    specs: Optional[Iterable[str]] = None,
    id: str = "package",
    host: str = "npx",
) -> dict[str, Any]:
    """Check one npm package against local npx cache and registry latest."""
    raw = name.strip() if isinstance(name, str) else ""
    parsed = _PKG_SPEC.match(raw) if raw else None
    if not parsed:
        return _result(id=id, host=host, package=None, status=STATUS_SKIP, reason="invalid package name")
    package = parsed.group("name")
    candidate_specs = list(specs or [])
    candidate_specs.append(raw)
    if parsed.group("tag"):
        candidate_specs.append(f"{package}@{parsed.group('tag')}")
    candidate_specs.append(package)

    current = read_npx_cached_version(package, home=home, specs=candidate_specs)
    latest = None
    if fetch_latest:
        fetcher = registry or (lambda pkg, t: fetch_npm_latest(pkg, timeout=t))
        latest = fetcher(package, timeout)

    if current is None and latest is None:
        return _result(
            id=id, host=host, package=package, current=None, latest=None,
            status=STATUS_UNKNOWN, reason="no npx cache and registry unavailable",
        )
    if current is None:
        return _result(
            id=id, host=host, package=package, current=None, latest=latest,
            status=STATUS_UNKNOWN, reason="npx cache miss",
        )
    if latest is None:
        return _result(
            id=id, host=host, package=package, current=current, latest=None,
            status=STATUS_UNKNOWN, reason="registry unavailable",
        )
    status = compare_versions(current, latest)
    reason = {
        STATUS_OK: "cache matches registry latest",
        STATUS_OUTDATED: "cache behind registry latest",
        STATUS_UNKNOWN: "version compare failed",
    }.get(status, status)
    return _result(
        id=id, host=host, package=package, current=current, latest=latest,
        status=status, reason=reason,
    )


def check_mcp_entry(
    entry: dict[str, Any],
    *,
    home: Optional[Path | str] = None,
    fetch_latest: bool = True,
    timeout: float = 8.0,
    registry: Optional[RegistryFetcher] = None,
) -> dict[str, Any]:
    """Classify one discovered MCP entry into a structured check result."""
    server_id = str(entry.get("id") or "unknown")
    host = str(entry.get("host") or "unknown")
    config = entry.get("config") if isinstance(entry.get("config"), dict) else {}

    if _is_disabled(config):
        return _result(id=server_id, host=host, status=STATUS_SKIP, reason="disabled")
    if _is_remote(config):
        return _result(id=server_id, host=host, status=STATUS_SKIP, reason="remote-only server")

    command = config.get("command")
    args = config.get("args") if isinstance(config.get("args"), list) else []
    if not _command_is_npx(command if isinstance(command, str) else None):
        return _result(id=server_id, host=host, status=STATUS_SKIP, reason="not npx-style command")

    parsed = parse_npx_package(command, args)
    if not parsed:
        return _result(id=server_id, host=host, status=STATUS_SKIP, reason="npx package not found in args")

    return check_npx_package(
        parsed["name"],
        home=home,
        fetch_latest=fetch_latest,
        timeout=timeout,
        registry=registry,
        specs=[parsed["spec"], f"{parsed['name']}@{parsed['tag']}", parsed["name"]],
        id=server_id,
        host=host,
    )


def iter_mcp_checks(
    home: Optional[Path | str] = None,
    *,
    fetch_latest: bool = True,
    timeout: float = 8.0,
    registry: Optional[RegistryFetcher] = None,
) -> list[dict[str, Any]]:
    """Discover local MCP configs and return structured npx check results for Lead/engine."""
    results = []
    for entry in discover_mcp_entries(home):
        results.append(
            check_mcp_entry(
                entry,
                home=home,
                fetch_latest=fetch_latest,
                timeout=timeout,
                registry=registry,
            )
        )
    return results
