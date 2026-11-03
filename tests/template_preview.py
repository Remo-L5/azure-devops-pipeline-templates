"""Expand the template-expression subset used by application helpers for local tests.

This is not Azure DevOps' schema validator or a substitute for its preview API.
"""
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def arguments(text):
    parts, depth, quoted, start = [], 0, False, 0
    for index, character in enumerate(text):
        if character == "'":
            quoted = not quoted
        elif not quoted:
            depth += (character == "(") - (character == ")")
            if character == "," and depth == 0:
                parts.append(text[start:index].strip())
                start = index + 1
    return parts + [text[start:].strip()] if text else []


def evaluate(text, context):
    text = text.strip()
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    if text.isdigit():
        return int(text)
    call = re.fullmatch(r"(\w+)\((.*)\)", text)
    if call:
        values = [evaluate(arg, context) for arg in arguments(call[2])]
        functions = {
            "eq": lambda a, b: a == b,
            "ne": lambda a, b: a != b,
            "gt": lambda a, b: a > b,
            "and": lambda *args: all(args),
            "or": lambda *args: any(args),
            "length": lambda value: len(value or []),
            "coalesce": lambda *args: next(
                (value for value in args if value is not None and value != ""), ""),
            "format": lambda pattern, *args: pattern.format(*args),
        }
        if call[1] == "convertToJson":
            import json
            return json.dumps(values[0])
        return functions[call[1]](*values)
    value = context
    for key in text.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def render(node, context):
    if isinstance(node, str):
        match = EXPRESSION.fullmatch(node)
        if match:
            return evaluate(match[1], context)
        return EXPRESSION.sub(lambda match: str(evaluate(match[1], context)), node)
    if isinstance(node, list):
        result = []
        for item in node:
            value = render(item, context)
            if (isinstance(item, dict) and any(
                str(key).startswith("${{") for key in item
            )) or (isinstance(item, str) and EXPRESSION.fullmatch(item)):
                if isinstance(value, list):
                    result.extend(value)
                elif value:
                    result.append(value)
            else:
                result.append(value)
        return result
    if not isinstance(node, dict):
        return node
    result, condition = {}, False
    for key, value in node.items():
        match = EXPRESSION.fullmatch(str(key))
        directive = match[1] if match else ""
        if directive.startswith("if "):
            condition = bool(evaluate(directive[3:], context))
            if not condition:
                continue
        elif directive == "else":
            if condition:
                continue
        elif directive.startswith("each "):
            variable, source = directive[5:].split(" in ", 1)
            source = evaluate(source, context) or []
            if isinstance(source, dict):
                source = [{"key": key, "value": val} for key, val in source.items()]
            entries = [render(value, {**context, variable: item}) for item in source]
            if isinstance(value, list):
                return [item for entry in entries for item in entry]
            for entry in entries:
                result.update(entry)
            continue
        else:
            result[render(key, context)] = render(value, context)
            continue
        rendered = render(value, context)
        if isinstance(rendered, list):
            return rendered
        result.update(rendered)
    return result


def expand(path, parameters=None):
    path = Path(path)
    source = yaml.safe_load(path.read_text(encoding="utf-8"))
    declarations = {item["name"]: item for item in source.get("parameters", [])}
    supplied = parameters or {}
    unexpected = supplied.keys() - declarations.keys()
    if unexpected:
        raise AssertionError(f"Unknown parameters in {path}: {unexpected}")
    values = {}
    for name, declaration in declarations.items():
        if name not in supplied and "default" not in declaration:
            raise AssertionError(f"Missing parameter {name} in {path}")
        values[name] = supplied.get(name, declaration.get("default"))
        if "values" in declaration and values[name] not in declaration["values"]:
            raise AssertionError(f"Invalid parameter {name} in {path}")
    rendered = render({key: value for key, value in source.items()
                       if key != "parameters"}, {"parameters": values})

    def templates(node):
        if isinstance(node, list):
            output = []
            for item in node:
                if isinstance(item, dict) and "template" in item:
                    name = item["template"]
                    target = ROOT / name.lstrip("/") if name.startswith("/") else path.parent / name
                    included = expand(target, item.get("parameters"))
                    self_key = next(key for key in ("stages", "jobs", "steps") if key in included)
                    output.extend(included[self_key])
                else:
                    output.append(templates(item))
            return output
        if isinstance(node, dict):
            return {key: templates(value) for key, value in node.items()}
        return node

    return templates(rendered)
