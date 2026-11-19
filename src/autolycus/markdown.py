"""Portable Markdown text; the webhook sends the source unchanged."""
import re


def table_count(text):
    """Count the separator rows emitted by our Markdown table renderer."""
    return sum(bool(re.fullmatch(r"\|(?:\s*:?-{3,}:?\s*\|)+\s*", line))
               for line in text.splitlines())


def escape(value):
    text = " ".join(str(value).split())
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for char in "\\`*_{}[]()#+-.!|~":
        text = text.replace(char, "\\" + char)
    return text


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)
