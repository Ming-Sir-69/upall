"""Read-only MCP discovery and npx cache/registry checks.

Discovery is structural: find configs that *contain* MCP server maps
(mcpServers / mcp_servers / mcp), under a shallow home scan — not a fixed
path allow-list. Only entries that are actually present/installed are kept.
Duplicates (same command/url fingerprint across hosts) collapse to one row.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
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
_NPX_BARE_FLAGS = {
    "-y", "--yes", "-q", "--quiet", "--prefer-offline", "--offline", "--no-install",
    "--ignore-existing", "-pw", "--package-worker",
}
_PKG_SPEC = re.compile(
    r"^(?P<name>(?:@[A-Za-z0-9~^*!().'_-]+/)?[A-Za-z0-9~^*!().'_-]+)(?:@(?P<tag>.+))?$"
)
_RUNNERS = {"npx", "npx.cmd", "npx.exe", "uvx", "bunx", "pnpm", "pnpx", "yarn", "dlx"}
_CONFIG_NAMES = {
    "mcp.json", "mcp_config.json", "claude_desktop_config.json",
    ".claude.json", "opencode.json", "config.toml",
}
# settings.json is ubiquitous; only consider it under agent-ish parents.
_SETTINGS_PARENT_MARKERS = frozenset({
    "claude", ".claude", "cursor", ".cursor", "codex", ".codex",
    "kimi-code", ".kimi-code", "hermes", ".hermes", "opencode", ".opencode",
    "gemini", ".gemini", "minimax", ".minimax", "pi", ".pi", "windsurf",
})
_SKIP_DIR_NAMES = {
    "node_modules", ".git", "Cache", "Caches", "logs", "Log", "tmp", "temp",
    "__pycache__", ".npm", ".cache", "DerivedData", "iCloud Drives",
}

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
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _is_config_candidate(path: Path) -> bool:
    name = path.name
    if name in _CONFIG_NAMES or name.endswith("mcp.json"):
        return True
    if name == "settings.json":
        return any(part.lower() in _SETTINGS_PARENT_MARKERS for part in path.parts)
    return False


def _public_server_view(raw: dict) -> dict[str, Any]:
    """Copy only non-secret structural fields needed for checks."""
    view: dict[str, Any] = {}
    for key in ("command", "args", "type", "url", "transport", "disabled", "enabled"):
        if key not in raw:
            continue
        value = raw[key]
        if key == "args" and isinstance(value, list):
            view[key] = [str(item) for item in value]
        elif key in ("command", "type", "url", "transport") and isinstance(value, str):
            view[key] = value
        elif key in ("disabled", "enabled") and isinstance(value, bool):
            view[key] = value
    return view


def _iter_server_maps(data: Any) -> Iterable[tuple[str, dict]]:
    """Yield (scope, servers-dict) from common MCP config shapes."""
    if not isinstance(data, dict):
        return
    for key in ("mcpServers", "mcp_servers", "mcp"):
        servers = data.get(key)
        if isinstance(servers, dict):
            cleaned = {
                name: raw for name, raw in servers.items()
                if isinstance(name, str) and isinstance(raw, dict)
            }
            if cleaned:
                yield "", cleaned
    projects = data.get("projects")
    if isinstance(projects, dict):
        for project_key, project in projects.items():
            if not isinstance(project, dict):
                continue
            nested = project.get("mcpServers")
            if isinstance(nested, dict):
                label = Path(str(project_key)).name or "project"
                yield label, nested


def _read_toml_mcp_servers(path: Path) -> Optional[dict]:
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    servers = data.get("mcp_servers")
    return servers if isinstance(servers, dict) else None


def _looks_like_mcp_file(path: Path) -> bool:
    """Structural gate: file must expose an MCP server map."""
    if path.suffix.lower() == ".toml":
        return _read_toml_mcp_servers(path) is not None
    data = _read_json(path)
    if data is None:
        return False
    return any(True for _ in _iter_server_maps(data))


def host_label_from_path(path: Path, home: Path) -> str:
    """Derive a short host label from where the config lives (no fixed map)."""
    if path.name == ".claude.json":
        return "claude-code"
    try:
        rel = path.resolve().relative_to(home.resolve())
        parts = list(rel.parts)
    except ValueError:
        parts = list(path.parts)
    if "Application Support" in parts:
        idx = parts.index("Application Support")
        if idx + 1 < len(parts):
            app = parts[idx + 1].lower().replace(" ", "-")
            if app == "claude":
                return "claude-desktop"
            if app == "code":
                return "vscode"
            return app
    for part in parts:
        if part.startswith(".") and part not in {".config", ".local", ".cache", ".Trash"}:
            return part.lstrip(".") or "mcp"
        if part.lower() in {"opencode", "gemini", "minimax", "hermes", "pi", "windsurf"}:
            return part.lower()
    parent = path.parent.name.lstrip(".")
    return parent or "mcp"


def find_mcp_config_files(home: Optional[Path | str] = None) -> list[Path]:
    """Shallow structural scan for MCP-shaped config files under the user home."""
    root = _home(home)
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path):
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen or not path.is_file():
            return
        try:
            if not _looks_like_mcp_file(path):
                return
        except Exception:
            return
        seen.add(key)
        found.append(path)

    # Home-level structural names (e.g. ~/.claude.json)
    try:
        for child in root.iterdir():
            if child.is_file() and _is_config_candidate(child):
                add(child)
            if not child.is_dir():
                continue
            name = child.name
            # Tool dots (.kimi-code, .cursor, …) and .config / Application Support
            if not (name.startswith(".") or name in {"Library", ".config"}):
                continue
            if name in _SKIP_DIR_NAMES:
                continue
            _scan_tree(child, depth=0, max_depth=3 if name in {"Library", ".config"} else 2, add=add)
    except OSError:
        pass
    return found


def _scan_tree(base: Path, *, depth: int, max_depth: int, add):
    if depth > max_depth:
        return
    try:
        children = list(base.iterdir())
    except OSError:
        return
    for child in children:
        if child.is_file():
            if _is_config_candidate(child):
                add(child)
            continue
        if not child.is_dir():
            continue
        if child.name in _SKIP_DIR_NAMES:
            continue
        # Descend into tool/config dirs; skip huge unrelated trees
        if child.name.startswith(".") and depth > 0 and child.name not in {
            ".cursor", ".codex", ".kimi-code", ".claude", ".hermes", ".agents",
            ".gemini", ".opencode", ".pi", ".minimax", ".codeium", ".config",
        }:
            # still allow nested agent/ under .pi etc. one level
            if depth >= 1:
                continue
        _scan_tree(child, depth=depth + 1, max_depth=max_depth, add=add)


def mcp_entry_fingerprint(config: dict[str, Any]) -> str:
    """Stable identity for dedup: URL or command+args (no secrets)."""
    url = str(config.get("url") or "").strip()
    if url:
        return "url:" + url
    command = str(config.get("command") or "").strip()
    args = [str(a) for a in (config.get("args") or [])]
    return "cmd:" + command + "\0" + "\0".join(args)


def is_mcp_installed(config: dict[str, Any]) -> bool:
    """True when the entry refers to something present on this machine / configured runner."""
    if config.get("disabled") is True or config.get("enabled") is False:
        return False
    if str(config.get("url") or "").strip():
        return True
    kind = str(config.get("type") or "").lower()
    if kind in {"http", "sse", "streamable-http", "websocket", "ws"}:
        return True
    command = str(config.get("command") or "").strip()
    if not command:
        return False
    base = Path(command).name.lower()
    if base in _RUNNERS:
        return True
    path = Path(command).expanduser()
    if path.is_absolute():
        return path.exists()
    return shutil.which(command) is not None


def discover_mcp_entries(home: Optional[Path | str] = None) -> list[dict[str, Any]]:
    """Discover installed MCP servers by structure; dedupe identical fingerprints."""
    root = _home(home)
    # fingerprint → merged entry
    merged: dict[str, dict[str, Any]] = {}
    for path in find_mcp_config_files(root):
        host = host_label_from_path(path, root)
        if path.suffix.lower() == ".toml":
            servers = _read_toml_mcp_servers(path) or {}
            scopes: list[tuple[str, dict]] = [("", servers)] if servers else []
        else:
            data = _read_json(path)
            if data is None:
                continue
            scopes = list(_iter_server_maps(data))
        for scope, servers in scopes:
            for server_id, raw in servers.items():
                if not isinstance(server_id, str) or not isinstance(raw, dict):
                    continue
                if not any(key in raw for key in ("command", "url", "type", "args", "transport")):
                    continue
                config = _public_server_view(raw)
                if not is_mcp_installed(config):
                    continue
                entry_id = f"{scope}/{server_id}" if scope else server_id
                fp = mcp_entry_fingerprint(config)
                if fp in merged:
                    existing = merged[fp]
                    hosts = list(existing.get("hosts") or [existing["host"]])
                    if host not in hosts:
                        hosts.append(host)
                    existing["hosts"] = hosts
                    paths = list(existing.get("paths") or [existing.get("path") or ""])
                    path_text = str(path)
                    if path_text and path_text not in paths:
                        paths.append(path_text)
                    existing["paths"] = paths
                    # Prefer a stable primary id without project scope when available
                    if not scope:
                        existing["id"] = entry_id
                        existing["host"] = host
                        existing["path"] = path_text
                    continue
                merged[fp] = {
                    "id": entry_id,
                    "host": host,
                    "hosts": [host],
                    "path": str(path),
                    "paths": [str(path)],
                    "config": config,
                    "fingerprint": fp,
                }
    return sorted(merged.values(), key=lambda item: (item["id"].lower(), item["host"]))


# Back-compat alias used by older tests / docs
def mcp_config_candidates(home: Optional[Path | str] = None) -> list[tuple[str, Path]]:
    root = _home(home)
    return [(host_label_from_path(path, root), path) for path in find_mcp_config_files(root)]


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
    home_path = _home(home)
    for spec in list(specs or []) + [package_name, f"{package_name}@latest"]:
        cache = npx_cache_dir(spec, home_path)
        if not cache.is_dir():
            continue
        version = _package_json_version(_node_module_package_json(cache, package_name))
        if version:
            return version
        meta = _read_json(cache / "package.json")
        if isinstance(meta, dict):
            deps = meta.get("dependencies")
            if isinstance(deps, dict) and package_name in deps:
                version = _package_json_version(_node_module_package_json(cache, package_name))
                if version:
                    return version
    npx_root = home_path / ".npm" / "_npx"
    if not npx_root.is_dir():
        return None
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
        deps = meta.get("dependencies")
        if not isinstance(deps, dict) or package_name not in deps:
            continue
        version = _package_json_version(_node_module_package_json(child, package_name))
        if version:
            return version
    return None


def fetch_npm_latest(package_name: str, timeout: float = 8.0) -> Optional[str]:
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
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
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
    server_id = str(entry.get("id") or "unknown")
    hosts = entry.get("hosts") or [entry.get("host") or "unknown"]
    host = ",".join(str(h) for h in hosts)
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
