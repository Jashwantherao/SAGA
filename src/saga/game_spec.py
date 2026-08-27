"""Typed, data-only game assembly contract.

``DesignDoc`` remains SAGA's creative brief.  ``GameSpec`` is the stricter
handoff that future capability packs can consume without asking a model to
write gameplay code.  It deliberately contains only JSON-compatible data:
capability identifiers, content catalogs, a world graph, typed state, and a
small condition/effect language.

This module is intentionally independent from the live graph and capability
resolver.  The legacy translator lets every current mechanic enter the new
contract while those integrations are introduced incrementally.
"""

from __future__ import annotations

import copy
import re
from collections import deque
from typing import Any


GAME_SPEC_VERSION = 2

LEGACY_TEMPLATE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    # Classic templates remain one legacy-generated component until each is
    # promoted into stable, independently composable runtime modules.
    "collect": ("legacy.collect",),
    "survive_hazards": ("legacy.survive_hazards",),
    "ordered_switches": ("legacy.ordered_switches",),
    "depletion": ("legacy.depletion",),
    "herd_to_goal": ("legacy.herd_to_goal",),
    "capture_zones": ("legacy.capture_zones",),
    "survive_and_deplete": ("legacy.survive_and_deplete",),
    "maze_chase": ("legacy.maze_chase",),
    "dot_maze": ("legacy.dot_maze",),
    "run_and_gun": (
        "movement.side_view",
        "combat.ranged_arsenal",
        "enemy_ai.run_and_gun",
        "world.run_and_gun",
        "checkpoint.run_and_gun",
        "boss.run_and_gun",
        "progression.run_and_gun",
        "persistence.run_and_gun",
        "hud.run_and_gun",
    ),
    "action_rpg": (
        "movement.top_down",
        "combat.melee",
        "enemy_ai.action_rpg",
        "inventory.action_rpg",
        "quest.action_rpg",
        "world.action_rpg",
        "persistence.action_rpg",
        "boss.action_rpg",
        "hud.action_rpg",
    ),
}

SPATIAL_MODE_FOR_TEMPLATE = {
    template: ("side_view_2d" if template == "run_and_gun" else "top_down_2d")
    for template in LEGACY_TEMPLATE_CAPABILITIES
}

STATE_NAMESPACE_FOR_TEMPLATE = {
    **{
        template: f"legacy.{template}"
        for template in LEGACY_TEMPLATE_CAPABILITIES
        if template not in {"run_and_gun", "action_rpg"}
    },
    "run_and_gun": "world.run_and_gun",
    "action_rpg": "world.action_rpg",
}
LOSS_NAMESPACE_FOR_TEMPLATE = {
    **STATE_NAMESPACE_FOR_TEMPLATE,
    "run_and_gun": "combat.ranged_arsenal",
    "action_rpg": "combat.melee",
}

CONDITION_OPERATORS = frozenset(
    {"always", "never", "all", "any", "not", "flag", "counter_gte", "owns_item", "party_has_tag"}
)
EFFECT_OPERATORS = frozenset(
    {"set_flag", "add_counter", "grant_item", "unlock_edge"}
)
FACT_TYPES = frozenset({"bool", "int", "string"})
SPATIAL_MODELS = frozenset({"top_down_2d", "side_view_2d"})

MAX_AST_DEPTH = 12
MAX_AST_NODES = 128
MAX_BOOLEAN_CHILDREN = 32

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+){0,7}$")


_CONDITION_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "properties": {"op": {"enum": ["always", "never"]}},
            "required": ["op"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "op": {"enum": ["all", "any"]},
                "conditions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_BOOLEAN_CHILDREN,
                    "items": {"$ref": "#/$defs/condition"},
                },
            },
            "required": ["op", "conditions"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "op": {"const": "not"},
                "condition": {"$ref": "#/$defs/condition"},
            },
            "required": ["op", "condition"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "op": {"const": "flag"},
                "fact": {"type": "string"},
                "equals": {"type": "boolean"},
            },
            "required": ["op", "fact", "equals"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "op": {"const": "counter_gte"},
                "fact": {"type": "string"},
                "value": {"type": "integer"},
            },
            "required": ["op", "fact", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "op": {"const": "owns_item"},
                "item": {"type": "string"},
                "count": {"type": "integer", "minimum": 1},
            },
            "required": ["op", "item", "count"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "op": {"const": "party_has_tag"},
                "tag": {"type": "string"},
            },
            "required": ["op", "tag"],
            "additionalProperties": False,
        },
    ]
}

_EFFECT_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "op": {"const": "set_flag"},
                "fact": {"type": "string"},
                "value": {"type": "boolean"},
            },
            "required": ["op", "fact", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "op": {"const": "add_counter"},
                "fact": {"type": "string"},
                "amount": {"type": "integer", "not": {"const": 0}},
            },
            "required": ["op", "fact", "amount"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "op": {"const": "grant_item"},
                "item": {"type": "string"},
                "count": {"type": "integer", "minimum": 1},
            },
            "required": ["op", "item", "count"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "op": {"const": "unlock_edge"},
                "edge": {"type": "string"},
            },
            "required": ["op", "edge"],
            "additionalProperties": False,
        },
    ]
}

# JSON Schema is exported for structured model output and external tooling.
# Runtime code below performs the same checks without adding a jsonschema
# dependency to the pipeline.
GAME_SPEC_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://saga.local/schema/game-spec-v2.json",
    "title": "SAGA GameSpec v2",
    "type": "object",
    "properties": {
        "game_spec_version": {"const": GAME_SPEC_VERSION},
        "identity": {"$ref": "#/$defs/identity"},
        "legacy": {"$ref": "#/$defs/legacy"},
        "capabilities": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": CAPABILITY_RE.pattern},
        },
        "modes": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/mode"},
        },
        "state": {"$ref": "#/$defs/state"},
        "content": {"$ref": "#/$defs/content"},
        "world": {"$ref": "#/$defs/world"},
        "rules": {"$ref": "#/$defs/rules"},
        "presentation": {"$ref": "#/$defs/presentation"},
    },
    "required": [
        "game_spec_version",
        "identity",
        "capabilities",
        "modes",
        "state",
        "content",
        "world",
        "rules",
        "presentation",
    ],
    "additionalProperties": False,
    "$defs": {
        "condition": _CONDITION_SCHEMA,
        "effect": _EFFECT_SCHEMA,
        "identity": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "genre": {"type": "string", "minLength": 1},
                "premise": {"type": "string", "minLength": 1},
                "theme_thread": {"type": "string", "minLength": 1},
                "core_loop": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "required": ["title", "genre", "premise", "theme_thread", "core_loop"],
            "additionalProperties": False,
        },
        "legacy": {
            "type": "object",
            "properties": {
                "source_version": {"const": 1},
                "mechanic_template": {
                    "type": "string",
                    "enum": sorted(LEGACY_TEMPLATE_CAPABILITIES),
                },
            },
            "required": ["source_version", "mechanic_template"],
            "additionalProperties": False,
        },
        "mode": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "pattern": SLUG_RE.pattern},
                "spatial_model": {"enum": sorted(SPATIAL_MODELS)},
                "capabilities": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/capability_request"},
                },
            },
            "required": ["id", "spatial_model", "capabilities"],
            "additionalProperties": False,
        },
        "capability_request": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "pattern": CAPABILITY_RE.pattern},
                "version": {"type": "integer", "minimum": 1},
            },
            "required": ["id", "version"],
            "additionalProperties": False,
        },
        "fact": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "pattern": SLUG_RE.pattern},
                "namespace": {"type": "string", "pattern": CAPABILITY_RE.pattern},
                "type": {"enum": sorted(FACT_TYPES)},
                "initial": {},
                "minimum": {"type": "integer"},
                "maximum": {"type": "integer"},
                "allowed_values": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string"},
                },
            },
            "required": ["id", "namespace", "type", "initial"],
            "additionalProperties": False,
        },
        "state": {
            "type": "object",
            "properties": {
                "facts": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/fact"},
                }
            },
            "required": ["facts"],
            "additionalProperties": False,
        },
        "catalog_entry": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "pattern": SLUG_RE.pattern},
                "name": {"type": "string", "minLength": 1},
                "description": {"type": "string", "minLength": 1},
                "tags": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": SLUG_RE.pattern},
                },
            },
            "required": ["id", "name", "description", "tags"],
            "additionalProperties": False,
        },
        "content": {
            "type": "object",
            "properties": {
                "hero": {"$ref": "#/$defs/catalog_entry"},
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/catalog_entry"},
                },
                "actors": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/catalog_entry"},
                },
                "party_tags": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": SLUG_RE.pattern},
                },
            },
            "required": ["hero", "items", "actors", "party_tags"],
            "additionalProperties": False,
        },
        "zone": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "pattern": SLUG_RE.pattern},
                "name": {"type": "string", "minLength": 1},
                "description": {"type": "string", "minLength": 1},
                "intensity": {"type": "integer", "minimum": 1, "maximum": 10},
                "pacing_notes": {"type": "string", "minLength": 1},
                "outro_beat": {"type": "string", "minLength": 1},
                "on_complete": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/effect"},
                },
            },
            "required": [
                "id",
                "name",
                "description",
                "intensity",
                "pacing_notes",
                "outro_beat",
                "on_complete",
            ],
            "additionalProperties": False,
        },
        "edge": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "pattern": SLUG_RE.pattern},
                "from": {"type": "string", "pattern": SLUG_RE.pattern},
                "to": {"type": "string", "pattern": SLUG_RE.pattern},
                "bidirectional": {"type": "boolean"},
                "gate": {"$ref": "#/$defs/condition"},
            },
            "required": ["id", "from", "to", "bidirectional", "gate"],
            "additionalProperties": False,
        },
        "world": {
            "type": "object",
            "properties": {
                "start_zone": {"type": "string", "pattern": SLUG_RE.pattern},
                "zones": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/zone"},
                },
                "edges": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/edge"},
                },
            },
            "required": ["start_zone", "zones", "edges"],
            "additionalProperties": False,
        },
        "objective": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "minLength": 1},
                "when": {"$ref": "#/$defs/condition"},
            },
            "required": ["description", "when"],
            "additionalProperties": False,
        },
        "rules": {
            "type": "object",
            "properties": {
                "win": {"$ref": "#/$defs/objective"},
                "lose": {"$ref": "#/$defs/objective"},
            },
            "required": ["win", "lose"],
            "additionalProperties": False,
        },
        "presentation": {
            "type": "object",
            "properties": {
                "art_style": {"type": "string", "minLength": 1},
                "audio_mood": {"type": "string", "minLength": 1},
            },
            "required": ["art_style", "audio_mood"],
            "additionalProperties": False,
        },
    },
}


def _plain_int(value: Any) -> bool:
    return type(value) is int


def _static_condition_value(node: object) -> bool | None:
    """Evaluate only condition forms whose truth is independent of game state."""
    if not isinstance(node, dict):
        return None
    op = node.get("op")
    if op == "always":
        return True
    if op == "never":
        return False
    if op == "not":
        value = _static_condition_value(node.get("condition"))
        return None if value is None else not value
    if op in {"all", "any"}:
        values = [
            _static_condition_value(child)
            for child in (node.get("conditions") or [])
        ]
        if op == "all":
            if False in values:
                return False
            return True if values and all(value is True for value in values) else None
        if True in values:
            return True
        return False if values and all(value is False for value in values) else None
    return None


def _unexpected_keys(value: dict, allowed: set[str], path: str) -> list[str]:
    extras = sorted(set(value) - allowed)
    return [f"{path} has unsupported field {key!r}" for key in extras]


def _required_text(container: dict, key: str, path: str, problems: list[str]) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{path}.{key} must be a non-empty string")
        return ""
    return value


def _valid_slug(value: Any, path: str, problems: list[str]) -> str:
    if not isinstance(value, str) or not SLUG_RE.fullmatch(value):
        problems.append(f"{path} must be a lowercase slug")
        return ""
    return value


def _condition_problems(
    node: Any,
    *,
    path: str,
    fact_types: dict[str, str] | None,
    item_ids: set[str] | None,
    party_tags: set[str] | None,
    depth: int,
    budget: list[int],
) -> list[str]:
    problems: list[str] = []
    budget[0] -= 1
    if budget[0] < 0:
        return [f"{path} exceeds the {MAX_AST_NODES}-node AST limit"]
    if depth > MAX_AST_DEPTH:
        return [f"{path} exceeds the maximum AST depth of {MAX_AST_DEPTH}"]
    if not isinstance(node, dict):
        return [f"{path} must be a condition object"]
    op = node.get("op")
    if op not in CONDITION_OPERATORS:
        return [
            f"{path}.op must be one of {sorted(CONDITION_OPERATORS)}; "
            "arbitrary expressions or code are forbidden"
        ]

    if op in {"always", "never"}:
        return _unexpected_keys(node, {"op"}, path)

    if op in {"all", "any"}:
        problems += _unexpected_keys(node, {"op", "conditions"}, path)
        children = node.get("conditions")
        if not isinstance(children, list) or not children:
            problems.append(f"{path}.conditions must be a non-empty list")
            return problems
        if len(children) > MAX_BOOLEAN_CHILDREN:
            problems.append(
                f"{path}.conditions exceeds the {MAX_BOOLEAN_CHILDREN}-child limit"
            )
        for index, child in enumerate(children[:MAX_BOOLEAN_CHILDREN]):
            problems += _condition_problems(
                child,
                path=f"{path}.conditions[{index}]",
                fact_types=fact_types,
                item_ids=item_ids,
                party_tags=party_tags,
                depth=depth + 1,
                budget=budget,
            )
        return problems

    if op == "not":
        problems += _unexpected_keys(node, {"op", "condition"}, path)
        if "condition" not in node:
            problems.append(f"{path}.condition is required")
            return problems
        problems += _condition_problems(
            node["condition"],
            path=f"{path}.condition",
            fact_types=fact_types,
            item_ids=item_ids,
            party_tags=party_tags,
            depth=depth + 1,
            budget=budget,
        )
        return problems

    if op == "flag":
        problems += _unexpected_keys(node, {"op", "fact", "equals"}, path)
        fact = _valid_slug(node.get("fact"), f"{path}.fact", problems)
        if type(node.get("equals")) is not bool:
            problems.append(f"{path}.equals must be a boolean")
        if fact_types is not None and fact:
            if fact not in fact_types:
                problems.append(f"{path}.fact references unknown state fact {fact!r}")
            elif fact_types[fact] != "bool":
                problems.append(f"{path}.fact {fact!r} must have type 'bool'")
        return problems

    if op == "counter_gte":
        problems += _unexpected_keys(node, {"op", "fact", "value"}, path)
        fact = _valid_slug(node.get("fact"), f"{path}.fact", problems)
        if not _plain_int(node.get("value")):
            problems.append(f"{path}.value must be an integer")
        if fact_types is not None and fact:
            if fact not in fact_types:
                problems.append(f"{path}.fact references unknown state fact {fact!r}")
            elif fact_types[fact] != "int":
                problems.append(f"{path}.fact {fact!r} must have type 'int'")
        return problems

    if op == "owns_item":
        problems += _unexpected_keys(node, {"op", "item", "count"}, path)
        item = _valid_slug(node.get("item"), f"{path}.item", problems)
        count = node.get("count")
        if not _plain_int(count) or count < 1:
            problems.append(f"{path}.count must be a positive integer")
        if item_ids is not None and item and item not in item_ids:
            problems.append(f"{path}.item references unknown item {item!r}")
        return problems

    # party_has_tag
    problems += _unexpected_keys(node, {"op", "tag"}, path)
    tag = _valid_slug(node.get("tag"), f"{path}.tag", problems)
    if party_tags is not None and tag and tag not in party_tags:
        problems.append(f"{path}.tag references unknown party tag {tag!r}")
    return problems


def validate_condition_ast(
    node: Any,
    *,
    path: str = "condition",
    fact_types: dict[str, str] | None = None,
    item_ids: set[str] | None = None,
    party_tags: set[str] | None = None,
) -> list[str]:
    """Validate the safe condition language; arbitrary expressions never pass."""
    return _condition_problems(
        node,
        path=path,
        fact_types=fact_types,
        item_ids=item_ids,
        party_tags=party_tags,
        depth=0,
        budget=[MAX_AST_NODES],
    )


def validate_effect_ast(
    node: Any,
    *,
    path: str = "effect",
    fact_types: dict[str, str] | None = None,
    item_ids: set[str] | None = None,
    edge_ids: set[str] | None = None,
) -> list[str]:
    """Validate one state mutation from the restricted effect language."""
    if not isinstance(node, dict):
        return [f"{path} must be an effect object"]
    op = node.get("op")
    if op not in EFFECT_OPERATORS:
        return [
            f"{path}.op must be one of {sorted(EFFECT_OPERATORS)}; "
            "arbitrary expressions or code are forbidden"
        ]
    problems: list[str] = []
    if op == "set_flag":
        problems += _unexpected_keys(node, {"op", "fact", "value"}, path)
        fact = _valid_slug(node.get("fact"), f"{path}.fact", problems)
        if type(node.get("value")) is not bool:
            problems.append(f"{path}.value must be a boolean")
        if fact_types is not None and fact:
            if fact not in fact_types:
                problems.append(f"{path}.fact references unknown state fact {fact!r}")
            elif fact_types[fact] != "bool":
                problems.append(f"{path}.fact {fact!r} must have type 'bool'")
    elif op == "add_counter":
        problems += _unexpected_keys(node, {"op", "fact", "amount"}, path)
        fact = _valid_slug(node.get("fact"), f"{path}.fact", problems)
        amount = node.get("amount")
        if not _plain_int(amount) or amount == 0:
            problems.append(f"{path}.amount must be a non-zero integer")
        if fact_types is not None and fact:
            if fact not in fact_types:
                problems.append(f"{path}.fact references unknown state fact {fact!r}")
            elif fact_types[fact] != "int":
                problems.append(f"{path}.fact {fact!r} must have type 'int'")
    elif op == "grant_item":
        problems += _unexpected_keys(node, {"op", "item", "count"}, path)
        item = _valid_slug(node.get("item"), f"{path}.item", problems)
        count = node.get("count")
        if not _plain_int(count) or count < 1:
            problems.append(f"{path}.count must be a positive integer")
        if item_ids is not None and item and item not in item_ids:
            problems.append(f"{path}.item references unknown item {item!r}")
    else:  # unlock_edge
        problems += _unexpected_keys(node, {"op", "edge"}, path)
        edge = _valid_slug(node.get("edge"), f"{path}.edge", problems)
        if edge_ids is not None and edge and edge not in edge_ids:
            problems.append(f"{path}.edge references unknown world edge {edge!r}")
    return problems


def _validate_fact(
    fact: Any, index: int, problems: list[str]
) -> tuple[str, str, str] | None:
    path = f"state.facts[{index}]"
    if not isinstance(fact, dict):
        problems.append(f"{path} must be an object")
        return None
    problems += _unexpected_keys(
        fact,
        {"id", "namespace", "type", "initial", "minimum", "maximum", "allowed_values"},
        path,
    )
    fact_id = _valid_slug(fact.get("id"), f"{path}.id", problems)
    namespace = fact.get("namespace")
    if not isinstance(namespace, str) or not CAPABILITY_RE.fullmatch(namespace):
        problems.append(f"{path}.namespace must be a capability namespace")
        namespace = ""
    fact_type = fact.get("type")
    if fact_type not in FACT_TYPES:
        problems.append(f"{path}.type must be one of {sorted(FACT_TYPES)}")
        return (fact_id, "", namespace) if fact_id else None
    initial = fact.get("initial")
    if fact_type == "bool":
        if type(initial) is not bool:
            problems.append(f"{path}.initial must be a boolean for a bool fact")
        for forbidden in ("minimum", "maximum", "allowed_values"):
            if forbidden in fact:
                problems.append(f"{path}.{forbidden} is not valid for a bool fact")
    elif fact_type == "int":
        if not _plain_int(initial):
            problems.append(f"{path}.initial must be an integer for an int fact")
        minimum = fact.get("minimum")
        maximum = fact.get("maximum")
        if minimum is not None and not _plain_int(minimum):
            problems.append(f"{path}.minimum must be an integer")
        if maximum is not None and not _plain_int(maximum):
            problems.append(f"{path}.maximum must be an integer")
        if _plain_int(minimum) and _plain_int(maximum) and minimum > maximum:
            problems.append(f"{path}.minimum cannot exceed maximum")
        if _plain_int(initial) and _plain_int(minimum) and initial < minimum:
            problems.append(f"{path}.initial is below minimum")
        if _plain_int(initial) and _plain_int(maximum) and initial > maximum:
            problems.append(f"{path}.initial is above maximum")
        if "allowed_values" in fact:
            problems.append(f"{path}.allowed_values is not valid for an int fact")
    else:
        if not isinstance(initial, str):
            problems.append(f"{path}.initial must be a string for a string fact")
        allowed = fact.get("allowed_values")
        if allowed is not None:
            if (
                not isinstance(allowed, list)
                or not allowed
                or not all(isinstance(item, str) for item in allowed)
                or len(set(allowed)) != len(allowed)
            ):
                problems.append(
                    f"{path}.allowed_values must be a non-empty unique string list"
                )
            elif isinstance(initial, str) and initial not in allowed:
                problems.append(f"{path}.initial must occur in allowed_values")
        for forbidden in ("minimum", "maximum"):
            if forbidden in fact:
                problems.append(f"{path}.{forbidden} is not valid for a string fact")
    return (fact_id, fact_type, namespace) if fact_id else None


def _validate_catalog_entry(entry: Any, path: str, problems: list[str]) -> str:
    if not isinstance(entry, dict):
        problems.append(f"{path} must be an object")
        return ""
    problems += _unexpected_keys(entry, {"id", "name", "description", "tags"}, path)
    entry_id = _valid_slug(entry.get("id"), f"{path}.id", problems)
    _required_text(entry, "name", path, problems)
    _required_text(entry, "description", path, problems)
    tags = entry.get("tags")
    if not isinstance(tags, list):
        problems.append(f"{path}.tags must be a list")
    else:
        seen: set[str] = set()
        for index, tag in enumerate(tags):
            valid = _valid_slug(tag, f"{path}.tags[{index}]", problems)
            if valid in seen:
                problems.append(f"{path}.tags contains duplicate {valid!r}")
            seen.add(valid)
    return entry_id


def _object(value: Any, path: str, problems: list[str]) -> dict:
    if not isinstance(value, dict):
        problems.append(f"{path} must be an object")
        return {}
    return value


def _list(value: Any, path: str, problems: list[str]) -> list:
    if not isinstance(value, list):
        problems.append(f"{path} must be a list")
        return []
    return value


def validate_game_spec(spec: Any) -> list[str]:
    """Return every structural, reference, type, and world-graph problem.

    The validator intentionally does not execute conditions.  It proves they
    are made only from the safe AST and reference declared typed content.
    """
    if not isinstance(spec, dict):
        return ["GameSpec must be an object"]
    problems: list[str] = []
    top_fields = {
        "game_spec_version", "identity", "legacy", "capabilities", "modes",
        "state", "content", "world", "rules", "presentation",
    }
    problems += _unexpected_keys(spec, top_fields, "GameSpec")
    required = top_fields - {"legacy"}
    for key in sorted(required):
        if key not in spec:
            problems.append(f"GameSpec is missing required field {key!r}")
    if spec.get("game_spec_version") != GAME_SPEC_VERSION:
        problems.append(
            f"game_spec_version must be {GAME_SPEC_VERSION}, "
            f"got {spec.get('game_spec_version')!r}"
        )

    identity = _object(spec.get("identity"), "identity", problems)
    problems += _unexpected_keys(
        identity, {"title", "genre", "premise", "theme_thread", "core_loop"}, "identity"
    )
    for key in ("title", "genre", "premise", "theme_thread"):
        _required_text(identity, key, "identity", problems)
    core_loop = identity.get("core_loop")
    if (
        not isinstance(core_loop, list)
        or not core_loop
        or not all(isinstance(item, str) and item.strip() for item in core_loop)
    ):
        problems.append("identity.core_loop must be a non-empty string list")

    legacy = spec.get("legacy")
    if legacy is not None:
        legacy = _object(legacy, "legacy", problems)
        problems += _unexpected_keys(
            legacy, {"source_version", "mechanic_template"}, "legacy"
        )
        if legacy.get("source_version") != 1:
            problems.append("legacy.source_version must be 1")
        if legacy.get("mechanic_template") not in LEGACY_TEMPLATE_CAPABILITIES:
            problems.append(
                "legacy.mechanic_template must name a supported legacy template"
            )

    capabilities = _list(spec.get("capabilities"), "capabilities", problems)
    capability_set: set[str] = set()
    if not capabilities:
        problems.append("capabilities must contain at least one capability id")
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, str) or not CAPABILITY_RE.fullmatch(capability):
            problems.append(f"capabilities[{index}] is not a valid capability id")
            continue
        if capability in capability_set:
            problems.append(f"capabilities contains duplicate {capability!r}")
        capability_set.add(capability)

    modes = _list(spec.get("modes"), "modes", problems)
    if not modes:
        problems.append("modes must contain at least one game mode")
    mode_ids: set[str] = set()
    assigned_capabilities: set[str] = set()
    for index, raw_mode in enumerate(modes):
        path = f"modes[{index}]"
        mode = _object(raw_mode, path, problems)
        problems += _unexpected_keys(mode, {"id", "spatial_model", "capabilities"}, path)
        mode_id = _valid_slug(mode.get("id"), f"{path}.id", problems)
        if mode_id in mode_ids:
            problems.append(f"modes contains duplicate id {mode_id!r}")
        mode_ids.add(mode_id)
        if mode.get("spatial_model") not in SPATIAL_MODELS:
            problems.append(f"{path}.spatial_model must be one of {sorted(SPATIAL_MODELS)}")
        mode_capabilities = _list(mode.get("capabilities"), f"{path}.capabilities", problems)
        if not mode_capabilities:
            problems.append(f"{path}.capabilities must not be empty")
        seen_mode: set[str] = set()
        for cap_index, request in enumerate(mode_capabilities):
            request_path = f"{path}.capabilities[{cap_index}]"
            if not isinstance(request, dict):
                problems.append(
                    f"{request_path} must be a versioned capability request"
                )
                continue
            problems += _unexpected_keys(request, {"id", "version"}, request_path)
            capability = request.get("id")
            if not isinstance(capability, str) or not CAPABILITY_RE.fullmatch(capability):
                problems.append(f"{request_path}.id is not a valid capability id")
                continue
            version = request.get("version")
            if not _plain_int(version) or version < 1:
                problems.append(f"{request_path}.version must be a positive integer")
            if capability in seen_mode:
                problems.append(f"{path}.capabilities contains duplicate {capability!r}")
            seen_mode.add(capability)
            assigned_capabilities.add(capability)
            if capability not in capability_set:
                problems.append(
                    f"{path}.capabilities references undeclared capability {capability!r}"
                )
    unassigned = sorted(capability_set - assigned_capabilities)
    if unassigned:
        problems.append(f"capabilities are not assigned to any mode: {unassigned}")

    state = _object(spec.get("state"), "state", problems)
    problems += _unexpected_keys(state, {"facts"}, "state")
    facts = _list(state.get("facts"), "state.facts", problems)
    fact_types: dict[str, str] = {}
    for index, fact in enumerate(facts):
        parsed = _validate_fact(fact, index, problems)
        if not parsed:
            continue
        fact_id, fact_type, _namespace = parsed
        if fact_id in fact_types:
            problems.append(f"state.facts contains duplicate id {fact_id!r}")
        fact_types[fact_id] = fact_type

    content = _object(spec.get("content"), "content", problems)
    problems += _unexpected_keys(
        content, {"hero", "items", "actors", "party_tags"}, "content"
    )
    _validate_catalog_entry(content.get("hero"), "content.hero", problems)
    item_ids: set[str] = set()
    for index, item in enumerate(_list(content.get("items"), "content.items", problems)):
        item_id = _validate_catalog_entry(item, f"content.items[{index}]", problems)
        if item_id in item_ids:
            problems.append(f"content.items contains duplicate id {item_id!r}")
        item_ids.add(item_id)
    actor_ids: set[str] = set()
    for index, actor in enumerate(_list(content.get("actors"), "content.actors", problems)):
        actor_id = _validate_catalog_entry(actor, f"content.actors[{index}]", problems)
        if actor_id in actor_ids:
            problems.append(f"content.actors contains duplicate id {actor_id!r}")
        actor_ids.add(actor_id)
    party_tags: set[str] = set()
    for index, tag in enumerate(
        _list(content.get("party_tags"), "content.party_tags", problems)
    ):
        valid = _valid_slug(tag, f"content.party_tags[{index}]", problems)
        if valid in party_tags:
            problems.append(f"content.party_tags contains duplicate {valid!r}")
        party_tags.add(valid)

    world = _object(spec.get("world"), "world", problems)
    problems += _unexpected_keys(world, {"start_zone", "zones", "edges"}, "world")
    zones = _list(world.get("zones"), "world.zones", problems)
    if not zones:
        problems.append("world.zones must contain at least one zone")
    zone_ids: set[str] = set()
    zone_objects: list[tuple[str, dict, int]] = []
    for index, raw_zone in enumerate(zones):
        path = f"world.zones[{index}]"
        zone = _object(raw_zone, path, problems)
        problems += _unexpected_keys(
            zone,
            {"id", "name", "description", "intensity", "pacing_notes", "outro_beat", "on_complete"},
            path,
        )
        zone_id = _valid_slug(zone.get("id"), f"{path}.id", problems)
        if zone_id in zone_ids:
            problems.append(f"world.zones contains duplicate id {zone_id!r}")
        zone_ids.add(zone_id)
        for key in ("name", "description", "pacing_notes", "outro_beat"):
            _required_text(zone, key, path, problems)
        intensity = zone.get("intensity")
        if not _plain_int(intensity) or not 1 <= intensity <= 10:
            problems.append(f"{path}.intensity must be an integer from 1 to 10")
        zone_objects.append((zone_id, zone, index))

    edges = _list(world.get("edges"), "world.edges", problems)
    edge_ids: set[str] = set()
    edge_objects: list[tuple[str, dict, int]] = []
    for index, raw_edge in enumerate(edges):
        path = f"world.edges[{index}]"
        edge = _object(raw_edge, path, problems)
        problems += _unexpected_keys(
            edge, {"id", "from", "to", "bidirectional", "gate"}, path
        )
        edge_id = _valid_slug(edge.get("id"), f"{path}.id", problems)
        if edge_id in edge_ids:
            problems.append(f"world.edges contains duplicate id {edge_id!r}")
        edge_ids.add(edge_id)
        source = _valid_slug(edge.get("from"), f"{path}.from", problems)
        target = _valid_slug(edge.get("to"), f"{path}.to", problems)
        if source and source not in zone_ids:
            problems.append(f"{path}.from references unknown zone {source!r}")
        if target and target not in zone_ids:
            problems.append(f"{path}.to references unknown zone {target!r}")
        if source and source == target:
            problems.append(f"{path} cannot connect a zone to itself")
        if type(edge.get("bidirectional")) is not bool:
            problems.append(f"{path}.bidirectional must be a boolean")
        problems += validate_condition_ast(
            edge.get("gate"),
            path=f"{path}.gate",
            fact_types=fact_types,
            item_ids=item_ids,
            party_tags=party_tags,
        )
        edge_objects.append((edge_id, edge, index))

    start_zone = _valid_slug(world.get("start_zone"), "world.start_zone", problems)
    if start_zone and start_zone not in zone_ids:
        problems.append(f"world.start_zone references unknown zone {start_zone!r}")
    if start_zone in zone_ids:
        adjacency = {zone_id: set() for zone_id in zone_ids}
        for _, edge, _ in edge_objects:
            source = edge.get("from")
            target = edge.get("to")
            if (
                source in adjacency
                and target in adjacency
                and _static_condition_value(edge.get("gate")) is not False
            ):
                adjacency[source].add(target)
                if edge.get("bidirectional") is True:
                    adjacency[target].add(source)
        reached = {start_zone}
        queue = deque([start_zone])
        while queue:
            current = queue.popleft()
            for target in adjacency[current] - reached:
                reached.add(target)
                queue.append(target)
        unreachable = sorted(zone_ids - reached)
        if unreachable:
            problems.append(
                f"world graph has zones unreachable from {start_zone!r}: {unreachable}"
            )

    for _, zone, index in zone_objects:
        effects = _list(
            zone.get("on_complete"), f"world.zones[{index}].on_complete", problems
        )
        for effect_index, effect in enumerate(effects):
            problems += validate_effect_ast(
                effect,
                path=f"world.zones[{index}].on_complete[{effect_index}]",
                fact_types=fact_types,
                item_ids=item_ids,
                edge_ids=edge_ids,
            )

    rules = _object(spec.get("rules"), "rules", problems)
    problems += _unexpected_keys(rules, {"win", "lose"}, "rules")
    for name in ("win", "lose"):
        objective = _object(rules.get(name), f"rules.{name}", problems)
        problems += _unexpected_keys(objective, {"description", "when"}, f"rules.{name}")
        _required_text(objective, "description", f"rules.{name}", problems)
        problems += validate_condition_ast(
            objective.get("when"),
            path=f"rules.{name}.when",
            fact_types=fact_types,
            item_ids=item_ids,
            party_tags=party_tags,
        )
        if name == "win" and _static_condition_value(objective.get("when")) is False:
            problems.append("rules.win.when is statically impossible")

    presentation = _object(spec.get("presentation"), "presentation", problems)
    problems += _unexpected_keys(
        presentation, {"art_style", "audio_mood"}, "presentation"
    )
    for key in ("art_style", "audio_mood"):
        _required_text(presentation, key, "presentation", problems)

    return list(dict.fromkeys(problems))


def _slug(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = fallback
    return normalized[:48].rstrip("_") or fallback


def _catalog_entry(
    entry_id: str,
    name: str,
    description: str,
    tags: list[str],
) -> dict:
    return {
        "id": entry_id,
        "name": name,
        "description": description,
        "tags": list(dict.fromkeys(_slug(tag, "legacy") for tag in tags)),
    }


def game_spec_from_legacy_design(design_doc: dict) -> dict:
    """Translate a current DesignDoc into a valid, data-only GameSpec v2.

    Translation is deterministic and does not infer new mechanics.  The
    legacy template becomes an explicit compatibility capability profile;
    each authored level becomes a world zone connected in campaign order.
    """
    if not isinstance(design_doc, dict):
        raise ValueError("legacy design must be an object")
    source = copy.deepcopy(design_doc)
    template = source.get("mechanic_template")
    if template not in LEGACY_TEMPLATE_CAPABILITIES:
        raise ValueError(f"unsupported legacy mechanic_template {template!r}")
    levels = source.get("levels")
    if not isinstance(levels, list) or not levels:
        raise ValueError("legacy design must contain at least one level")

    required_text = {
        "title": source.get("title"),
        "genre": source.get("genre"),
        "story_premise": source.get("story_premise"),
        "theme_thread": source.get("theme_thread"),
        "win_condition": source.get("win_condition"),
        "lose_condition": source.get("lose_condition"),
        "art_style": source.get("art_style"),
        "audio_mood": source.get("audio_mood"),
        "hero_description": source.get("hero_description"),
    }
    missing = [
        name for name, value in required_text.items()
        if not isinstance(value, str) or not value.strip()
    ]
    core_loop = source.get("core_mechanics")
    if missing or not isinstance(core_loop, list) or not core_loop:
        details = ", ".join(missing + ([] if core_loop else ["core_mechanics"]))
        raise ValueError(f"legacy design is missing required content: {details}")

    capabilities = list(LEGACY_TEMPLATE_CAPABILITIES[template])
    edge_ids = [f"level_{index}_to_{index + 1}" for index in range(len(levels) - 1)]
    facts = [
        {
            "id": f"level_{index}_complete",
            "namespace": STATE_NAMESPACE_FOR_TEMPLATE[template],
            "type": "bool",
            "initial": False,
        }
        for index in range(len(levels))
    ]
    lose_description = str(source["lose_condition"])
    has_loss = lose_description.strip().lower() != "none"
    if has_loss:
        facts.append(
            {
                "id": "game_lost",
                "namespace": LOSS_NAMESPACE_FOR_TEMPLATE[template],
                "type": "bool",
                "initial": False,
            }
        )

    zones = []
    for index, raw_level in enumerate(levels):
        if not isinstance(raw_level, dict):
            raise ValueError(f"legacy levels[{index}] must be an object")
        on_complete = [
            {
                "op": "set_flag",
                "fact": f"level_{index}_complete",
                "value": True,
            }
        ]
        if index < len(edge_ids):
            on_complete.append({"op": "unlock_edge", "edge": edge_ids[index]})
        zones.append(
            {
                "id": f"level_{index}",
                "name": str(raw_level.get("name") or f"Level {index + 1}"),
                "description": str(raw_level.get("description") or "Authored level"),
                "intensity": raw_level.get("intensity", 4),
                "pacing_notes": str(
                    raw_level.get("pressure_notes") or "Use the authored template pacing."
                ),
                "outro_beat": str(
                    raw_level.get("outro_beat") or "The path onward opens."
                ),
                "on_complete": on_complete,
            }
        )

    edges = [
        {
            "id": edge_ids[index],
            "from": f"level_{index}",
            "to": f"level_{index + 1}",
            "bidirectional": False,
            "gate": {
                "op": "flag",
                "fact": f"level_{index}_complete",
                "equals": True,
            },
        }
        for index in range(len(edge_ids))
    ]

    key_item = source.get("key_item") or {}
    key_role = _slug(key_item.get("role"), "legacy_item")
    items = [
        _catalog_entry(
            "key_item",
            "Key Item",
            str(key_item.get("description") or "The authored objective item."),
            [key_role],
        )
    ]
    actors = []
    used_actor_ids: set[str] = set()
    for index, sprite in enumerate(source.get("extra_sprites") or []):
        if not isinstance(sprite, dict):
            continue
        actor_id = _slug(sprite.get("name"), f"extra_actor_{index}")
        if actor_id in used_actor_ids:
            suffix = 2
            while f"{actor_id}_{suffix}" in used_actor_ids:
                suffix += 1
            actor_id = f"{actor_id}_{suffix}"[:48]
        used_actor_ids.add(actor_id)
        actors.append(
            _catalog_entry(
                actor_id,
                actor_id.replace("_", " ").title(),
                str(sprite.get("description") or "An authored supporting actor."),
                ["legacy_extra_sprite"],
            )
        )

    spec = {
        "game_spec_version": GAME_SPEC_VERSION,
        "identity": {
            "title": source["title"],
            "genre": source["genre"],
            "premise": source["story_premise"],
            "theme_thread": source["theme_thread"],
            "core_loop": [str(item) for item in core_loop],
        },
        "legacy": {"source_version": 1, "mechanic_template": template},
        "capabilities": capabilities,
        "modes": [
            {
                "id": "main",
                "spatial_model": SPATIAL_MODE_FOR_TEMPLATE[template],
                "capabilities": [
                    {"id": capability, "version": 1}
                    for capability in capabilities
                ],
            }
        ],
        "state": {"facts": facts},
        "content": {
            "hero": _catalog_entry(
                "hero", "Hero", source["hero_description"], ["player_character"]
            ),
            "items": items,
            "actors": actors,
            "party_tags": [],
        },
        "world": {"start_zone": "level_0", "zones": zones, "edges": edges},
        "rules": {
            "win": {
                "description": source["win_condition"],
                "when": {
                    "op": "flag",
                    "fact": f"level_{len(levels) - 1}_complete",
                    "equals": True,
                },
            },
            "lose": {
                "description": lose_description,
                "when": (
                    {"op": "flag", "fact": "game_lost", "equals": True}
                    if has_loss
                    else {"op": "never"}
                ),
            },
        },
        "presentation": {
            "art_style": source["art_style"],
            "audio_mood": source["audio_mood"],
        },
    }
    problems = validate_game_spec(spec)
    if problems:  # A translator bug must fail before this contract reaches runtime.
        raise ValueError("legacy design produced invalid GameSpec: " + "; ".join(problems))
    return spec


# The explicit alias reads naturally at intake call sites and keeps the public
# API discoverable without committing the future graph to either name.
translate_legacy_design = game_spec_from_legacy_design
