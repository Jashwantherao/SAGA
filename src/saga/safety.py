"""Safety policy for model-generated GDScript.

Generated gameplay code needs scene APIs, input, animation, and ``res://``
asset loading. It never needs host filesystem access, process execution, or
networking. Reject those capabilities before Godot parses or runs the script.

This is defense in depth, not a replacement for running Godot with minimal OS
permissions. A denylist cannot prove arbitrary code safe, but it closes the
direct host-access paths that are unnecessary for SAGA's generated levels.
"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SafetyFinding:
    rule: str
    line: int
    excerpt: str

    def message(self) -> str:
        return f"Generated-code safety: {self.rule} at line {self.line}: {self.excerpt}"


class UnsafeGeneratedCodeError(ValueError):
    def __init__(self, findings: list[SafetyFinding]):
        self.findings = findings
        super().__init__("; ".join(finding.message() for finding in findings))


FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "host filesystem APIs are forbidden",
        re.compile(
            r"\b(?:FileAccess|DirAccess|ResourceLoader|ResourceSaver|ResourceUID|"
            r"PCKPacker|ZIPReader|ZIPPacker)\b"
        ),
    ),
    (
        "process and shell APIs are forbidden",
        re.compile(
            r"\bOS\s*\.\s*(?:execute|create_process|create_instance|shell_open|"
            r"set_environment|get_environment|kill|move_to_trash)\b"
        ),
    ),
    (
        "host-path conversion is forbidden",
        re.compile(r"\bProjectSettings\s*\.\s*globalize_path\b"),
    ),
    (
        "network APIs are forbidden",
        re.compile(
            r"\b(?:HTTPRequest|HTTPClient|TCPServer|StreamPeerTCP|PacketPeerUDP|"
            r"WebSocketPeer|WebSocketMultiplayerPeer|ENetMultiplayerPeer|"
            r"MultiplayerAPI|UPNP)\b"
        ),
    ),
    (
        "native-extension and platform bridges are forbidden",
        re.compile(r"\b(?:GDExtension|JavaScriptBridge|EngineDebugger|Expression)\b"),
    ),
)

RESOURCE_CALL = re.compile(r"\b(?:load|preload)\s*\(\s*(['\"])(.*?)\1")
EXTERNAL_URI = re.compile(r"(?:user|file|https?)://", re.IGNORECASE)


def _without_comment(line: str) -> str:
    """Strip a GDScript comment while preserving # characters in strings."""
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote:
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "#":
            return line[:index]
    return line


def scan_generated_gdscript(script: str) -> list[SafetyFinding]:
    findings = []
    seen: set[tuple[str, int]] = set()
    for line_number, raw_line in enumerate(script.splitlines(), start=1):
        line = _without_comment(raw_line)
        if not line.strip():
            continue
        for rule, pattern in FORBIDDEN_PATTERNS:
            if pattern.search(line) and (rule, line_number) not in seen:
                findings.append(SafetyFinding(rule, line_number, line.strip()[:180]))
                seen.add((rule, line_number))

        for match in RESOURCE_CALL.finditer(line):
            path = match.group(2)
            if not path.startswith("res://assets/"):
                rule = "generated scripts may load only res://assets/* resources"
                if (rule, line_number) not in seen:
                    findings.append(SafetyFinding(rule, line_number, line.strip()[:180]))
                    seen.add((rule, line_number))

        if EXTERNAL_URI.search(line):
            rule = "external and user:// URIs are forbidden"
            if (rule, line_number) not in seen:
                findings.append(SafetyFinding(rule, line_number, line.strip()[:180]))
                seen.add((rule, line_number))
    return findings


def assert_safe_gdscript(script: str) -> None:
    findings = scan_generated_gdscript(script)
    if findings:
        raise UnsafeGeneratedCodeError(findings)
