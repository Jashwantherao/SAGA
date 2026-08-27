"""Deterministic capability composition for complex SAGA games.

Game-generation models should choose and configure stable gameplay modules;
they should not be trusted to rewrite a growing monolith.  This module is the
composition firewall between a typed GameSpec and runtime packs.  Components
declare dependencies, incompatible peers, service ports, events, owned state,
input meanings, runtime files, and the QA probes that must prove them.

The resolver is intentionally model-free.  The same GameSpec always produces
the same assembly lock, independent of request order, and an invalid assembly
fails before image generation or Godot startup consumes time.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Iterable


LOCK_VERSION = 1
MANIFEST_VERSION = 2
PACK_ROOT = Path(__file__).resolve().parent / "archetype_packs"
COMPATIBILITY_ROOT = Path(__file__).resolve().parent / "capability_packs"

ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
ACTION_RE = re.compile(r"^[a-z][a-z0-9_]*$")
MANIFEST_RE = re.compile(r"^[a-z][a-z0-9_]*$")
IMPLEMENTATIONS = {"stable_pack", "legacy_generated"}
EXTERNAL_EVENTS = frozenset({"engine.physics_tick"})

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class CompositionError(ValueError):
    """A GameSpec cannot be assembled without ambiguity or broken wiring."""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _plain_positive_int(value: object) -> bool:
    return type(value) is int and value >= 1


def canonical_game_spec(spec: dict) -> dict:
    """Normalize set-like GameSpec fields while preserving authored sequences."""
    normalized = json.loads(json.dumps(spec))
    normalized["capabilities"] = sorted(normalized.get("capabilities") or [])
    modes = normalized.get("modes") or []
    for mode in modes:
        mode["capabilities"] = sorted(
            mode.get("capabilities") or [],
            key=lambda request: (request.get("id"), request.get("version")),
        )
    normalized["modes"] = sorted(modes, key=lambda mode: mode.get("id"))
    return normalized


def _string_list(component: dict, field: str) -> list[str]:
    value = component.get(field)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise CompositionError(
            f"component {component.get('id')!r} field {field!r} must be a list of strings"
        )
    return value


def _validate_component(component: dict, manifest_id: str) -> None:
    component_id = component.get("id")
    if not isinstance(component_id, str) or not ID_RE.fullmatch(component_id):
        raise CompositionError(
            f"manifest {manifest_id!r} has invalid component id {component_id!r}"
        )
    version = component.get("version")
    if not _plain_positive_int(version):
        raise CompositionError(f"component {component_id!r} needs a positive integer version")
    if component.get("implementation") not in IMPLEMENTATIONS:
        raise CompositionError(
            f"component {component_id!r} implementation must be one of {sorted(IMPLEMENTATIONS)}"
        )

    requirements = component.get("requires")
    if not isinstance(requirements, list):
        raise CompositionError(f"component {component_id!r} requires must be a list")
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise CompositionError(f"component {component_id!r} has a malformed requirement")
        required_id = requirement.get("id")
        required_version = requirement.get("version")
        if not isinstance(required_id, str) or not ID_RE.fullmatch(required_id):
            raise CompositionError(
                f"component {component_id!r} has invalid requirement id {required_id!r}"
            )
        if not _plain_positive_int(required_version):
            raise CompositionError(
                f"component {component_id!r} requirement {required_id!r} needs a version"
            )

    for field in (
        "conflicts",
        "provides",
        "requires_ports",
        "emits",
        "consumes",
        "state_owners",
        "runtime_files",
        "required_probes",
    ):
        values = _string_list(component, field)
        token_fields = {
            "conflicts",
            "provides",
            "requires_ports",
            "emits",
            "consumes",
            "state_owners",
            "required_probes",
        }
        if field in token_fields:
            invalid = [value for value in values if not TOKEN_RE.fullmatch(value)]
            if invalid:
                raise CompositionError(
                    f"component {component_id!r} has invalid {field}: {invalid}"
                )

    if not component["provides"]:
        raise CompositionError(f"component {component_id!r} must provide at least one port")
    if not component["state_owners"]:
        raise CompositionError(f"component {component_id!r} must own a state namespace")
    if not component["required_probes"]:
        raise CompositionError(f"component {component_id!r} must declare a QA probe")
    if component["implementation"] == "stable_pack" and not component["runtime_files"]:
        raise CompositionError(f"stable component {component_id!r} must name runtime files")
    for runtime_file in component["runtime_files"]:
        normalized = runtime_file.replace("\\", "/")
        runtime_path = PurePosixPath(normalized)
        if (
            runtime_path.is_absolute()
            or ".." in runtime_path.parts
            or ":" in normalized
            or normalized.startswith("/")
        ):
            raise CompositionError(
                f"component {component_id!r} has unsafe runtime file {runtime_file!r}"
            )

    bindings = component.get("input_actions")
    if not isinstance(bindings, list):
        raise CompositionError(f"component {component_id!r} input_actions must be a list")
    for binding in bindings:
        if not isinstance(binding, dict):
            raise CompositionError(f"component {component_id!r} has a malformed input binding")
        action = binding.get("action")
        meaning = binding.get("meaning")
        if not isinstance(action, str) or not ACTION_RE.fullmatch(action):
            raise CompositionError(
                f"component {component_id!r} has invalid input action {action!r}"
            )
        if not isinstance(meaning, str) or not TOKEN_RE.fullmatch(meaning):
            raise CompositionError(
                f"component {component_id!r} has invalid input meaning {meaning!r}"
            )


@dataclass(frozen=True)
class CapabilityRegistry:
    components: dict[str, dict]
    profiles: dict[str, tuple[dict, ...]]

    def component(self, component_id: str) -> dict:
        try:
            return self.components[component_id]
        except KeyError as exc:
            raise CompositionError(f"unknown capability {component_id!r}") from exc


def registry_from_manifests(
    manifests: Iterable[dict],
    *,
    known_component_ids: Iterable[str] | None = None,
) -> CapabilityRegistry:
    components: dict[str, dict] = {}
    profiles: dict[str, tuple[dict, ...]] = {}
    for manifest in manifests:
        if not isinstance(manifest, dict):
            raise CompositionError("capability manifest must be an object")
        manifest_id = str(manifest.get("id") or "")
        if not MANIFEST_RE.fullmatch(manifest_id):
            raise CompositionError(f"invalid capability manifest id {manifest_id!r}")
        source_path = manifest.get("__source_path")
        source_root = Path(source_path).parent if source_path else None
        manifest_version = manifest.get("manifest_version")
        if type(manifest_version) is not int or manifest_version != MANIFEST_VERSION:
            raise CompositionError(
                f"manifest {manifest_id!r} version must be {MANIFEST_VERSION}"
            )
        listed = manifest.get("components")
        if not isinstance(listed, list) or not listed:
            raise CompositionError(f"manifest {manifest_id!r} declares no components")
        for raw in listed:
            if not isinstance(raw, dict):
                raise CompositionError(f"manifest {manifest_id!r} has a malformed component")
            component = json.loads(json.dumps(raw))
            _validate_component(component, manifest_id)
            component_id = component["id"]
            if component_id in components:
                raise CompositionError(f"duplicate capability id {component_id!r}")
            component["manifest_id"] = manifest_id
            component["component_digest"] = _digest(raw)
            runtime_digests = {}
            if source_root is not None:
                for runtime_file in component["runtime_files"]:
                    runtime_path = source_root / runtime_file
                    try:
                        payload = runtime_path.read_bytes()
                    except OSError as exc:
                        raise CompositionError(
                            f"component {component_id!r} runtime file is unavailable: "
                            f"{runtime_path}: {exc}"
                        ) from exc
                    runtime_digests[runtime_file] = hashlib.sha256(payload).hexdigest()
            component["runtime_digests"] = dict(sorted(runtime_digests.items()))
            components[component_id] = component

        raw_profiles = manifest.get("template_profiles") or {}
        if not isinstance(raw_profiles, dict):
            raise CompositionError(f"manifest {manifest_id!r} template_profiles must be an object")
        for template, requests in raw_profiles.items():
            if template in profiles:
                raise CompositionError(f"duplicate composition profile {template!r}")
            if not isinstance(requests, list) or not requests:
                raise CompositionError(f"composition profile {template!r} is empty")
            normalized = []
            for request in requests:
                if not isinstance(request, dict):
                    raise CompositionError(
                        f"composition profile {template!r} has a malformed request"
                    )
                request_id = request.get("id")
                request_version = request.get("version")
                if not isinstance(request_id, str) or not ID_RE.fullmatch(request_id):
                    raise CompositionError(
                        f"composition profile {template!r} has invalid capability id "
                        f"{request_id!r}"
                    )
                if not _plain_positive_int(request_version):
                    raise CompositionError(
                        f"composition profile {template!r} request {request_id!r} "
                        "needs a positive integer version"
                    )
                normalized.append({"id": request_id, "version": request_version})
            profiles[str(template)] = tuple(normalized)

    conflict_catalog = set(known_component_ids or ()) | set(components)
    for component in components.values():
        unknown_conflicts = sorted(set(component["conflicts"]) - conflict_catalog)
        if unknown_conflicts:
            raise CompositionError(
                f"component {component['id']!r} conflicts with unknown capabilities "
                f"{unknown_conflicts}"
            )

    for template, requests in profiles.items():
        for request in requests:
            component = components.get(request["id"])
            if component is None:
                raise CompositionError(
                    f"profile {template!r} requests unknown capability {request['id']!r}"
                )
            if component["version"] != request["version"]:
                raise CompositionError(
                    f"profile {template!r} requests {request['id']}@{request['version']}, "
                    f"registry has @{component['version']}"
                )
    return CapabilityRegistry(components=components, profiles=profiles)


def _manifest_paths() -> list[Path]:
    paths = sorted(PACK_ROOT.glob("*/manifest.json"))
    if COMPATIBILITY_ROOT.is_dir():
        paths.extend(sorted(COMPATIBILITY_ROOT.glob("*.json")))
    return paths


def _catalog_component_ids(paths: Iterable[Path]) -> set[str]:
    """Read only valid component identities from discoverable manifests.

    A selectively loaded pack may declare a conflict with an installed pack
    that is intentionally absent from the returned registry.  The complete
    catalog distinguishes that valid cross-pack reference from a typo without
    silently adding the other pack to the active registry.
    """
    component_ids: set[str] = set()
    for path in paths:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("manifest_version") != MANIFEST_VERSION:
            continue
        listed = manifest.get("components")
        if not isinstance(listed, list):
            continue
        for component in listed:
            component_id = component.get("id") if isinstance(component, dict) else None
            if isinstance(component_id, str) and ID_RE.fullmatch(component_id):
                component_ids.add(component_id)
    return component_ids


def load_registry(paths: Iterable[str | Path] | None = None) -> CapabilityRegistry:
    selected = [Path(path) for path in paths] if paths is not None else _manifest_paths()
    manifests = []
    for path in selected:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CompositionError(f"cannot read capability manifest {path}: {exc}") from exc
        if not isinstance(manifest, dict):
            raise CompositionError(f"capability manifest {path} must be an object")
        manifest["__source_path"] = str(path.resolve())
        manifests.append(manifest)
    if not manifests:
        raise CompositionError("no capability manifests were found")
    catalog_paths = {path.resolve() for path in [*_manifest_paths(), *selected]}
    return registry_from_manifests(
        manifests,
        known_component_ids=_catalog_component_ids(sorted(catalog_paths)),
    )


def _resolve_mode(mode: dict, registry: CapabilityRegistry) -> list[dict]:
    requested_versions: dict[str, int] = {}
    selected: dict[str, dict] = {}
    visiting: list[str] = []

    def visit(component_id: str, required_version: int) -> None:
        prior = requested_versions.get(component_id)
        if prior is not None and prior != required_version:
            raise CompositionError(
                f"capability {component_id!r} requested at incompatible versions {prior} and {required_version}"
            )
        requested_versions[component_id] = required_version
        component = registry.component(component_id)
        if component["version"] != required_version:
            raise CompositionError(
                f"capability {component_id!r} requires version {required_version}, "
                f"registry has {component['version']}"
            )
        if component_id in selected:
            return
        if component_id in visiting:
            cycle = visiting[visiting.index(component_id):] + [component_id]
            raise CompositionError(f"capability dependency cycle: {' -> '.join(cycle)}")
        visiting.append(component_id)
        for requirement in sorted(component["requires"], key=lambda item: item["id"]):
            visit(requirement["id"], requirement["version"])
        visiting.pop()
        selected[component_id] = component

    requests: list[dict] = []
    for raw_request in mode.get("capabilities") or []:
        if isinstance(raw_request, str):
            component = registry.component(raw_request)
            requests.append({"id": raw_request, "version": component["version"]})
        elif isinstance(raw_request, dict):
            requests.append(raw_request)
        else:
            raise CompositionError(
                f"mode {mode.get('id')!r} has a malformed capability request"
            )

    for request in sorted(requests, key=lambda item: item["id"]):
        visit(request["id"], request["version"])

    selected_ids = set(selected)
    for component in selected.values():
        conflicts = selected_ids & set(component["conflicts"])
        if conflicts:
            raise CompositionError(
                f"capability {component['id']!r} conflicts with {sorted(conflicts)} in mode {mode['id']!r}"
            )

    port_providers: dict[str, list[str]] = {}
    event_providers: dict[str, list[str]] = {}
    inputs: dict[str, tuple[str, str]] = {}
    for component in selected.values():
        for port in component["provides"]:
            port_providers.setdefault(port, []).append(component["id"])
        for event in component["emits"]:
            event_providers.setdefault(event, []).append(component["id"])
        for binding in component["input_actions"]:
            action = binding["action"]
            meaning = binding["meaning"]
            prior = inputs.get(action)
            if prior and prior[0] != meaning:
                raise CompositionError(
                    f"input action {action!r} means {prior[0]!r} in {prior[1]!r} "
                    f"but {meaning!r} in {component['id']!r}"
                )
            inputs[action] = (meaning, component["id"])

    for component in selected.values():
        for port in component["requires_ports"]:
            providers = port_providers.get(port) or []
            if len(providers) != 1:
                raise CompositionError(
                    f"capability {component['id']!r} requires port {port!r}; "
                    f"expected exactly one provider, got {providers}"
                )
        for event in component["consumes"]:
            if event in EXTERNAL_EVENTS:
                continue
            providers = event_providers.get(event) or []
            if not providers:
                raise CompositionError(
                    f"capability {component['id']!r} consumes event {event!r} with no provider"
                )

    return list(selected.values())


def _normalized_requests(mode: dict) -> list[dict]:
    return sorted(
        [
            {"id": request.get("id"), "version": request.get("version")}
            for request in (mode.get("capabilities") or [])
            if isinstance(request, dict)
        ],
        key=lambda request: (str(request["id"]), request["version"] or 0),
    )


def resolve_game_spec(spec: dict, registry: CapabilityRegistry | None = None) -> dict:
    """Resolve a validated GameSpec into a deterministic assembly lock."""
    from saga.game_spec import validate_game_spec

    problems = validate_game_spec(spec)
    if problems:
        raise CompositionError("invalid GameSpec: " + "; ".join(problems))
    registry = registry or load_registry()

    modes = []
    global_state: dict[str, str] = {}
    global_components: dict[tuple[str, int], dict] = {}
    ordered_modes = sorted(spec["modes"], key=lambda item: item["id"])
    legacy_template = (spec.get("legacy") or {}).get("mechanic_template")
    for mode_index, mode in enumerate(ordered_modes):
        if legacy_template:
            expected = sorted(
                profile_requests(legacy_template, registry),
                key=lambda request: (request["id"], request["version"]),
            )
            declared = _normalized_requests(mode)
            if declared != expected:
                raise CompositionError(
                    f"legacy profile {legacy_template!r} drifted: "
                    f"declared {declared}, expected {expected}"
                )
        selected = _resolve_mode(mode, registry)
        explicitly_declared = {
            (request["id"], request["version"])
            for request in _normalized_requests(mode)
        }
        locked_components = []
        for component in selected:
            key = (component["id"], component["version"])
            global_components[key] = component
            for namespace in component["state_owners"]:
                prior = global_state.get(namespace)
                if prior and prior != component["id"]:
                    raise CompositionError(
                        f"state namespace {namespace!r} is owned by both {prior!r} and {component['id']!r}"
                    )
                global_state[namespace] = component["id"]
            locked_components.append(
                {
                    "id": component["id"],
                    "version": component["version"],
                    "implementation": component["implementation"],
                    "manifest_id": component["manifest_id"],
                    "component_digest": component["component_digest"],
                    "declared": key in explicitly_declared,
                    "runtime_files": sorted(component["runtime_files"]),
                    "runtime_digests": component["runtime_digests"],
                    "required_probes": sorted(component["required_probes"]),
                }
            )
        modes.append(
            {
                "id": mode["id"],
                "perspective": mode.get("perspective") or mode.get("spatial_model"),
                "entry": bool(mode.get("entry", mode_index == 0)),
                "declared_capabilities": _normalized_requests(mode),
                "components": locked_components,
            }
        )

    state_facts = {}
    for fact in (spec.get("state") or {}).get("facts") or []:
        namespace = fact.get("namespace")
        owner = global_state.get(namespace)
        if owner is None:
            raise CompositionError(
                f"state fact {fact.get('id')!r} uses unowned namespace {namespace!r}"
            )
        state_facts[f"{namespace}.{fact['id']}"] = {
            "owner": owner,
            "type": fact.get("type"),
        }

    body = {
        "lock_version": LOCK_VERSION,
        "game_spec_version": spec["game_spec_version"],
        "game_spec_hash": _digest(canonical_game_spec(spec)),
        "title": (spec.get("identity") or {}).get("title") or spec.get("title"),
        "modes": modes,
        "state_owners": dict(sorted(global_state.items())),
        "state_facts": dict(sorted(state_facts.items())),
        "required_probes": sorted({
            probe
            for component in global_components.values()
            for probe in component["required_probes"]
        }),
    }
    body["assembly_hash"] = _digest(body)
    return body


def validate_assembly_lock(assembly_lock: object) -> list[str]:
    """Return structural and integrity problems in a persisted assembly lock."""
    if not isinstance(assembly_lock, dict):
        return ["assembly lock must be an object"]

    from saga.game_spec import FACT_TYPES, GAME_SPEC_VERSION, SPATIAL_MODELS

    problems: list[str] = []
    lock_fields = {
        "lock_version",
        "game_spec_version",
        "game_spec_hash",
        "title",
        "modes",
        "state_owners",
        "state_facts",
        "required_probes",
        "assembly_hash",
    }
    missing_fields = sorted(lock_fields - set(assembly_lock))
    unexpected_fields = sorted(set(assembly_lock) - lock_fields)
    if missing_fields:
        problems.append(f"assembly lock is missing fields: {missing_fields}")
    if unexpected_fields:
        problems.append(f"assembly lock has unexpected fields: {unexpected_fields}")

    lock_version = assembly_lock.get("lock_version")
    if type(lock_version) is not int or lock_version != LOCK_VERSION:
        problems.append(f"assembly lock version must be {LOCK_VERSION}")
    game_spec_version = assembly_lock.get("game_spec_version")
    if type(game_spec_version) is not int or game_spec_version != GAME_SPEC_VERSION:
        problems.append(f"assembly lock GameSpec version must be {GAME_SPEC_VERSION}")
    if not isinstance(assembly_lock.get("game_spec_hash"), str) or not SHA256_RE.fullmatch(
        assembly_lock["game_spec_hash"]
    ):
        problems.append("assembly lock game_spec_hash must be a lowercase SHA-256 digest")
    if not isinstance(assembly_lock.get("title"), str) or not assembly_lock["title"].strip():
        problems.append("assembly lock title must be a non-empty string")

    assembly_hash = assembly_lock.get("assembly_hash")
    if not isinstance(assembly_hash, str) or not SHA256_RE.fullmatch(assembly_hash):
        problems.append("assembly lock assembly_hash must be a lowercase SHA-256 digest")
    hash_body = {
        key: value for key, value in assembly_lock.items() if key != "assembly_hash"
    }
    try:
        expected_hash = _digest(hash_body)
    except (TypeError, ValueError):
        problems.append("assembly lock must contain only JSON-serializable values")
    else:
        if assembly_hash != expected_hash:
            problems.append("assembly lock assembly_hash does not match its contents")

    modes = assembly_lock.get("modes")
    selected_component_ids: set[str] = set()
    all_required_probes: set[str] = set()
    valid_mode_ids: set[str] = set()
    entry_count = 0
    if not isinstance(modes, list) or not modes:
        problems.append("assembly lock modes must be a non-empty list")
        modes = []
    for mode_index, mode in enumerate(modes):
        path = f"assembly lock modes[{mode_index}]"
        if not isinstance(mode, dict):
            problems.append(f"{path} must be an object")
            continue
        mode_fields = {
            "id",
            "perspective",
            "entry",
            "declared_capabilities",
            "components",
        }
        if set(mode) != mode_fields:
            missing = sorted(mode_fields - set(mode))
            unexpected = sorted(set(mode) - mode_fields)
            if missing:
                problems.append(f"{path} is missing fields: {missing}")
            if unexpected:
                problems.append(f"{path} has unexpected fields: {unexpected}")

        mode_id = mode.get("id")
        if not isinstance(mode_id, str) or not MODE_RE.fullmatch(mode_id):
            problems.append(f"{path}.id is invalid")
        elif mode_id in valid_mode_ids:
            problems.append(f"assembly lock has duplicate mode id {mode_id!r}")
        else:
            valid_mode_ids.add(mode_id)
        perspective = mode.get("perspective")
        if not isinstance(perspective, str) or perspective not in SPATIAL_MODELS:
            problems.append(f"{path}.perspective is invalid")
        if type(mode.get("entry")) is not bool:
            problems.append(f"{path}.entry must be a boolean")
        elif mode["entry"]:
            entry_count += 1

        declared = mode.get("declared_capabilities")
        declared_keys: set[tuple[str, int]] = set()
        if not isinstance(declared, list) or not declared:
            problems.append(f"{path}.declared_capabilities must be a non-empty list")
            declared = []
        for request_index, request in enumerate(declared):
            request_path = f"{path}.declared_capabilities[{request_index}]"
            if not isinstance(request, dict) or set(request) != {"id", "version"}:
                problems.append(f"{request_path} must be an id/version object")
                continue
            request_id = request.get("id")
            request_version = request.get("version")
            if not isinstance(request_id, str) or not ID_RE.fullmatch(request_id):
                problems.append(f"{request_path}.id is invalid")
                continue
            if not _plain_positive_int(request_version):
                problems.append(f"{request_path}.version must be a positive integer")
                continue
            request_key = (request_id, request_version)
            if request_key in declared_keys:
                problems.append(f"{path} has duplicate declared capability {request_key!r}")
            declared_keys.add(request_key)

        components = mode.get("components")
        component_keys: set[tuple[str, int]] = set()
        flagged_declared: set[tuple[str, int]] = set()
        if not isinstance(components, list) or not components:
            problems.append(f"{path}.components must be a non-empty list")
            components = []
        for component_index, component in enumerate(components):
            component_path = f"{path}.components[{component_index}]"
            if not isinstance(component, dict):
                problems.append(f"{component_path} must be an object")
                continue
            component_fields = {
                "id",
                "version",
                "implementation",
                "manifest_id",
                "component_digest",
                "declared",
                "runtime_files",
                "runtime_digests",
                "required_probes",
            }
            if set(component) != component_fields:
                missing = sorted(component_fields - set(component))
                unexpected = sorted(set(component) - component_fields)
                if missing:
                    problems.append(f"{component_path} is missing fields: {missing}")
                if unexpected:
                    problems.append(f"{component_path} has unexpected fields: {unexpected}")

            component_id = component.get("id")
            component_version = component.get("version")
            valid_identity = True
            if not isinstance(component_id, str) or not ID_RE.fullmatch(component_id):
                problems.append(f"{component_path}.id is invalid")
                valid_identity = False
            if not _plain_positive_int(component_version):
                problems.append(f"{component_path}.version must be a positive integer")
                valid_identity = False
            if valid_identity:
                component_key = (component_id, component_version)
                if component_key in component_keys:
                    problems.append(f"{path} has duplicate component {component_key!r}")
                component_keys.add(component_key)
                selected_component_ids.add(component_id)
                if component.get("declared") is True:
                    flagged_declared.add(component_key)

            implementation = component.get("implementation")
            if not isinstance(implementation, str) or implementation not in IMPLEMENTATIONS:
                problems.append(f"{component_path}.implementation is invalid")
            manifest_id = component.get("manifest_id")
            if not isinstance(manifest_id, str) or not MANIFEST_RE.fullmatch(manifest_id):
                problems.append(f"{component_path}.manifest_id is invalid")
            component_digest = component.get("component_digest")
            if not isinstance(component_digest, str) or not SHA256_RE.fullmatch(
                component_digest
            ):
                problems.append(f"{component_path}.component_digest must be a SHA-256 digest")
            if type(component.get("declared")) is not bool:
                problems.append(f"{component_path}.declared must be a boolean")

            runtime_files = component.get("runtime_files")
            valid_runtime_files: list[str] = []
            if not isinstance(runtime_files, list) or not all(
                isinstance(item, str) and item for item in runtime_files
            ):
                problems.append(f"{component_path}.runtime_files must be a string list")
            else:
                valid_runtime_files = runtime_files
                if len(set(runtime_files)) != len(runtime_files):
                    problems.append(f"{component_path}.runtime_files contains duplicates")
                for runtime_file in runtime_files:
                    normalized = runtime_file.replace("\\", "/")
                    runtime_path = PurePosixPath(normalized)
                    if (
                        runtime_path.is_absolute()
                        or ".." in runtime_path.parts
                        or ":" in normalized
                        or normalized.startswith("/")
                    ):
                        problems.append(
                            f"{component_path} has unsafe runtime file {runtime_file!r}"
                        )
            if implementation == "stable_pack" and not valid_runtime_files:
                problems.append(f"{component_path} stable component has no runtime files")

            runtime_digests = component.get("runtime_digests")
            if not isinstance(runtime_digests, dict):
                problems.append(f"{component_path}.runtime_digests must be an object")
            else:
                if set(runtime_digests) != set(valid_runtime_files):
                    problems.append(
                        f"{component_path}.runtime_digests must exactly cover runtime_files"
                    )
                for runtime_file, digest in runtime_digests.items():
                    if not isinstance(runtime_file, str) or not isinstance(
                        digest, str
                    ) or not SHA256_RE.fullmatch(digest):
                        problems.append(
                            f"{component_path}.runtime_digests contains an invalid SHA-256 digest"
                        )

            component_probes = component.get("required_probes")
            if not isinstance(component_probes, list) or not component_probes or not all(
                isinstance(probe, str) and TOKEN_RE.fullmatch(probe)
                for probe in component_probes
            ):
                problems.append(f"{component_path}.required_probes must be a non-empty token list")
            else:
                if len(set(component_probes)) != len(component_probes):
                    problems.append(f"{component_path}.required_probes contains duplicates")
                all_required_probes.update(component_probes)

        if declared_keys - component_keys:
            problems.append(f"{path} declares capabilities not present in components")
        if flagged_declared != declared_keys:
            problems.append(f"{path} declared component flags do not match declared_capabilities")

    if modes and entry_count != 1:
        problems.append("assembly lock must contain exactly one entry mode")

    state_owners = assembly_lock.get("state_owners")
    if not isinstance(state_owners, dict) or not state_owners:
        problems.append("assembly lock state_owners must be a non-empty object")
    else:
        for namespace, owner in state_owners.items():
            if not isinstance(namespace, str) or not TOKEN_RE.fullmatch(namespace):
                problems.append(f"assembly lock has invalid state namespace {namespace!r}")
            if not isinstance(owner, str) or owner not in selected_component_ids:
                problems.append(
                    f"assembly lock state namespace {namespace!r} has unknown owner {owner!r}"
                )

    state_facts = assembly_lock.get("state_facts")
    if not isinstance(state_facts, dict):
        problems.append("assembly lock state_facts must be an object")
    else:
        for fact_id, fact in state_facts.items():
            if not isinstance(fact_id, str) or not TOKEN_RE.fullmatch(fact_id):
                problems.append(f"assembly lock has invalid state fact id {fact_id!r}")
            if not isinstance(fact, dict) or set(fact) != {"owner", "type"}:
                problems.append(f"assembly lock state fact {fact_id!r} is malformed")
                continue
            fact_owner = fact.get("owner")
            if not isinstance(fact_owner, str) or fact_owner not in selected_component_ids:
                problems.append(f"assembly lock state fact {fact_id!r} has an unknown owner")
            fact_type = fact.get("type")
            if not isinstance(fact_type, str) or fact_type not in FACT_TYPES:
                problems.append(f"assembly lock state fact {fact_id!r} has an invalid type")

    required_probes = assembly_lock.get("required_probes")
    if not isinstance(required_probes, list) or not required_probes or not all(
        isinstance(probe, str) and TOKEN_RE.fullmatch(probe)
        for probe in required_probes
    ):
        problems.append("assembly lock required_probes must be a non-empty token list")
    elif len(set(required_probes)) != len(required_probes):
        problems.append("assembly lock required_probes contains duplicates")
    elif set(required_probes) != all_required_probes:
        problems.append("assembly lock required_probes do not match component probes")

    return list(dict.fromkeys(problems))


def profile_requests(template: str, registry: CapabilityRegistry | None = None) -> list[dict]:
    registry = registry or load_registry()
    requests = registry.profiles.get(template)
    if requests is None:
        raise CompositionError(f"no composition profile exists for template {template!r}")
    return [dict(request) for request in requests]


def verify_project_assembly(project_dir: str | Path, assembly_lock: dict) -> None:
    """Verify that QA is about to execute the exact locked stable runtime."""
    project_root = Path(project_dir).resolve()
    lock_path = project_root / "assembly.lock.json"
    try:
        project_lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompositionError(f"project assembly lock is unavailable: {exc}") from exc
    if project_lock != assembly_lock:
        raise CompositionError("project assembly lock does not match pipeline state")

    for mode in assembly_lock.get("modes") or []:
        for component in mode.get("components") or []:
            manifest_id = component.get("manifest_id")
            if not isinstance(manifest_id, str) or not MANIFEST_RE.fullmatch(manifest_id):
                raise CompositionError(
                    f"locked component has unsafe manifest id {manifest_id!r}"
                )
            for runtime_file, expected_digest in (
                component.get("runtime_digests") or {}
            ).items():
                runtime_path = (
                    project_root / "archetypes" / manifest_id / runtime_file
                ).resolve()
                if not runtime_path.is_relative_to(project_root):
                    raise CompositionError(
                        f"locked runtime path escapes the project: {runtime_file!r}"
                    )
                try:
                    actual_digest = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
                except OSError as exc:
                    raise CompositionError(
                        f"locked runtime file is unavailable: {runtime_path}: {exc}"
                    ) from exc
                if actual_digest != expected_digest:
                    raise CompositionError(
                        f"locked runtime file hash mismatch: {manifest_id}/{runtime_file}"
                    )
