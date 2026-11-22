"""Shared helpers for governance scripts. Python stdlib only; GitHub access via the gh CLI."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

GOV_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ".governance/profile.yml"


# --------------------------------------------------------------------------- config


def load_config() -> dict:
    with open(GOV_ROOT / "config" / "governance.json", encoding="utf-8") as fh:
        return json.load(fh)


def load_profile(repo_dir: str | Path = ".") -> dict:
    path = Path(repo_dir) / PROFILE_PATH
    if not path.exists():
        return {}
    return yaml_load(path.read_text(encoding="utf-8")) or {}


def dig(data: Any, dotted: str, default: Any = None) -> Any:
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


# --------------------------------------------------------------------------- YAML subset
# Supports what governance files use: block mappings and sequences, mapping items in
# sequences, plain/quoted scalars, flow sequences of scalars, empty {} / [], literal and
# folded block scalars, comments. Anchors, tags and multi-documents are not supported.

_KEY_RE = re.compile(r"""^(?P<key>"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s'"#\[\]{},&*!|>%@`-][^#]*?|-[^\s#][^#]*?)\s*:(?:\s+|$)(?P<rest>.*)$""")
_INT_RE = re.compile(r"^[-+]?[0-9]+$")
_FLOAT_RE = re.compile(r"^[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?$")


class YamlError(ValueError):
    pass


def _strip_comment(text: str) -> str:
    quote = None
    for idx, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            if idx == 0 or text[idx - 1] in " \t[,{:":
                quote = ch
        elif ch == "#" and (idx == 0 or text[idx - 1] in " \t"):
            return text[:idx].rstrip()
    return text.rstrip()


def _split_flow(text: str) -> list[str]:
    parts, buf, quote, depth = [], [], None, 0
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _unquote_key(key: str) -> str:
    if key.startswith('"'):
        return json.loads(key)
    if key.startswith("'"):
        return key[1:-1].replace("''", "'")
    return key


def _scalar(text: str) -> Any:
    text = text.strip()
    if text == "":
        return None
    if text.startswith('"'):
        if not text.endswith('"') or len(text) < 2:
            raise YamlError(f"unterminated string: {text}")
        return json.loads(text)
    if text.startswith("'"):
        if not text.endswith("'") or len(text) < 2:
            raise YamlError(f"unterminated string: {text}")
        return text[1:-1].replace("''", "'")
    if text.startswith("["):
        if not text.endswith("]"):
            raise YamlError(f"unterminated flow sequence: {text}")
        return [_scalar(p) for p in _split_flow(text[1:-1])]
    if text.startswith("{"):
        if not text.endswith("}"):
            raise YamlError(f"unterminated flow mapping: {text}")
        out = {}
        for part in _split_flow(text[1:-1]):
            m = _KEY_RE.match(part)
            if not m:
                raise YamlError(f"bad flow mapping entry: {part}")
            out[_unquote_key(m.group("key"))] = _scalar(m.group("rest"))
        return out
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~"):
        return None
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    return text


def _is_seq_item(content: str) -> bool:
    return content == "-" or content.startswith("- ")


class _Parser:
    def __init__(self, text: str):
        self.lines = text.replace("\t", "    ").splitlines()
        self.i = 0

    def _skip(self) -> None:
        while self.i < len(self.lines):
            stripped = self.lines[self.i].strip()
            if stripped == "" or stripped.startswith("#") or stripped in ("---", "..."):
                self.i += 1
                continue
            break

    def _peek(self) -> tuple[int, str] | None:
        self._skip()
        if self.i >= len(self.lines):
            return None
        line = self.lines[self.i]
        return len(line) - len(line.lstrip(" ")), line.strip()

    def parse(self) -> Any:
        head = self._peek()
        if head is None:
            return None
        if not _is_seq_item(head[1]) and not _KEY_RE.match(head[1]):
            self.i += 1
            return _scalar(_strip_comment(head[1]))
        value = self._block(head[0])
        if self._peek() is not None:
            raise YamlError(f"unexpected content at line {self.i + 1}: {self.lines[self.i]!r}")
        return value

    def _block(self, indent: int) -> Any:
        head = self._peek()
        assert head is not None
        return self._seq(indent) if _is_seq_item(head[1]) else self._map(indent)

    def _map(self, indent: int) -> dict:
        out: dict = {}
        while True:
            head = self._peek()
            if head is None or head[0] < indent:
                return out
            if head[0] > indent:
                raise YamlError(f"bad indentation at line {self.i + 1}: {self.lines[self.i]!r}")
            if _is_seq_item(head[1]):
                return out
            m = _KEY_RE.match(head[1])
            if not m:
                raise YamlError(f"expected 'key: value' at line {self.i + 1}: {self.lines[self.i]!r}")
            key = _unquote_key(m.group("key"))
            self.i += 1
            out[key] = self._value(m.group("rest"), indent, allow_same_indent_seq=True)

    def _value(self, rest: str, indent: int, allow_same_indent_seq: bool) -> Any:
        rest = _strip_comment(rest)
        if rest == "":
            head = self._peek()
            if head is None:
                return None
            if head[0] > indent:
                return self._block(head[0])
            if allow_same_indent_seq and head[0] == indent and _is_seq_item(head[1]):
                return self._seq(indent)
            return None
        if rest[0] in "|>":
            return self._block_scalar(rest, indent)
        return _scalar(rest)

    def _seq(self, indent: int) -> list:
        out: list = []
        while True:
            head = self._peek()
            if head is None or head[0] != indent or not _is_seq_item(head[1]):
                return out
            content = head[1][1:].lstrip(" ")
            if content == "" or content.startswith("#"):
                self.i += 1
                nxt = self._peek()
                out.append(self._block(nxt[0]) if nxt and nxt[0] > indent else None)
            elif _KEY_RE.match(content):
                item_indent = indent + (len(head[1]) - len(content))
                self.lines[self.i] = " " * item_indent + content
                out.append(self._map(item_indent))
            else:
                self.i += 1
                if content[0] in "|>":
                    out.append(self._block_scalar(content, indent))
                else:
                    out.append(_scalar(_strip_comment(content)))

    def _block_scalar(self, header: str, indent: int) -> str:
        style, chomp = header[0], header[1:].strip()
        body: list[str] = []
        block_indent = None
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.strip() == "":
                body.append("")
                self.i += 1
                continue
            cur = len(line) - len(line.lstrip(" "))
            if cur <= indent:
                break
            if block_indent is None:
                block_indent = cur
            if cur < block_indent:
                break
            body.append(line[block_indent:])
            self.i += 1
        while body and body[-1] == "":
            body.pop()
        if style == "|":
            text = "\n".join(body)
        else:
            text = " ".join(part for part in body if part != "")
        return text if chomp.startswith("-") else text + "\n"


def yaml_load(text: str) -> Any:
    return _Parser(text).parse()


_PLAIN_SAFE = re.compile(r"^[A-Za-z0-9_./${}()=+~^%@-][A-Za-z0-9_ ./${}()=+~^%@,:<>*\[\]'\"-]*$")


def _fmt_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    needs_quotes = (
        text == ""
        or text != text.strip()
        or "\n" in text
        or ": " in text
        or " #" in text
        or text.endswith(":")
        or not _PLAIN_SAFE.match(text)
        or text[0] in "-?:,[]{}#&*!|>'\"%@`"
        and not (text[0] == "-" and len(text) > 1 and text[1] not in " ")
        or _scalar(text) != text
    )
    return json.dumps(text, ensure_ascii=False) if needs_quotes else text


def yaml_dump(data: Any, indent: int = 0) -> str:
    pad = " " * indent
    lines: list[str] = []
    if isinstance(data, dict):
        if not data and indent == 0:
            return "{}\n"
        for key, value in data.items():
            key_text = _fmt_scalar(key)
            if isinstance(value, dict) and value:
                lines.append(f"{pad}{key_text}:")
                lines.append(yaml_dump(value, indent + 2).rstrip("\n"))
            elif isinstance(value, list) and value:
                lines.append(f"{pad}{key_text}:")
                lines.append(yaml_dump(value, indent + 2).rstrip("\n"))
            elif isinstance(value, dict):
                lines.append(f"{pad}{key_text}: {{}}")
            elif isinstance(value, list):
                lines.append(f"{pad}{key_text}: []")
            else:
                lines.append(f"{pad}{key_text}: {_fmt_scalar(value)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item:
                nested = yaml_dump(item, indent + 2).rstrip("\n").split("\n")
                lines.append(f"{pad}- {nested[0].lstrip()}")
                lines.extend(nested[1:])
            elif isinstance(item, list) and item:
                lines.append(f"{pad}-")
                lines.append(yaml_dump(item, indent + 2).rstrip("\n"))
            elif isinstance(item, dict):
                lines.append(f"{pad}- {{}}")
            elif isinstance(item, list):
                lines.append(f"{pad}- []")
            else:
                lines.append(f"{pad}- {_fmt_scalar(item)}")
    else:
        lines.append(f"{pad}{_fmt_scalar(data)}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- Conventional Commits

CC_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^()\s]+)\))?(?P<bang>!)?: (?P<desc>\S.*)$")


def parse_cc(title: str) -> dict | None:
    m = CC_RE.match(title.strip())
    if not m:
        return None
    return {"type": m.group("type"), "scope": m.group("scope"), "breaking": bool(m.group("bang")), "description": m.group("desc")}


def is_feat(title: str) -> bool:
    parsed = parse_cc(title)
    return bool(parsed and parsed["type"] == "feat")


# --------------------------------------------------------------------------- gh CLI


class GhError(RuntimeError):
    pass


def gh(*args: str, input_text: str | None = None, check: bool = True) -> str:
    try:
        proc = subprocess.run(["gh", *args], input=input_text, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise GhError("gh CLI not found") from exc
    if check and proc.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def gh_api(path: str, method: str = "GET", fields: dict | None = None, paginate: bool = False, body: Any = None) -> Any:
    args = ["api", path, "-X", method, "-H", "Accept: application/vnd.github+json"]
    if paginate:
        args += ["--paginate", "--slurp"]
    for key, value in (fields or {}).items():
        args += ["-F" if isinstance(value, (bool, int)) else "-f", f"{key}={json.dumps(value) if isinstance(value, bool) else value}"]
    input_text = None
    if body is not None:
        args += ["--input", "-"]
        input_text = json.dumps(body)
    out = gh(*args, input_text=input_text)
    if not out.strip():
        return None
    data = json.loads(out)
    if paginate and isinstance(data, list):
        flat: list = []
        for page in data:
            if isinstance(page, list):
                flat.extend(page)
            elif isinstance(page, dict):
                items = next((v for v in page.values() if isinstance(v, list)), None)
                flat.extend(items if items is not None else [page])
        return flat
    return data


def gh_graphql(query: str, **variables: Any) -> Any:
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    return json.loads(gh(*args))


def gh_authenticated() -> bool:
    try:
        proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    return proc.returncode == 0


# --------------------------------------------------------------------------- git / process


def run(cmd: str | list[str], cwd: str | Path | None = None, check: bool = False, env: dict | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
    shell = isinstance(cmd, str)
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True, check=check, env=full_env, timeout=timeout)


def git(*args: str, cwd: str | Path = ".") -> str:
    proc = run(["git", *args], cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


# --------------------------------------------------------------------------- GitHub Actions I/O


def set_output(name: str, value: Any) -> None:
    text = value if isinstance(value, str) else json.dumps(value)
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        print(f"[output] {name}={text}")
        return
    delim = f"EOF_{uuid.uuid4().hex}"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{name}<<{delim}\n{text}\n{delim}\n")


def summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")
    print(text)


def event_payload() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fail(message: str, code: int = 1) -> int:
    print(f"::error::{message}", file=sys.stderr)
    summary(f"❌ {message}")
    return code
