"""Use the LLM to suggest impact-led rewrites for graph node bullets."""

from __future__ import annotations

from difflib import ndiff
from typing import Any

from jobctl.llm.base import LLMProvider, Message

__all__ = ["propose_rephrase", "compute_diff_lines"]


_SYSTEM_PROMPT = (
    "You are an expert resume coach. Rewrite the given snippet as a single "
    "impact-oriented bullet that:\n"
    "- Starts with a strong past-tense verb\n"
    "- Quantifies outcomes when any numbers are present\n"
    "- Removes filler, hedging, and passive voice\n"
    "- Stays under 200 characters\n"
    "Return only the rewritten bullet, no preamble or commentary."
)


def propose_rephrase(node: dict[str, Any], provider: LLMProvider) -> str:
    original = (node.get("text_representation") or "").strip()
    if not original:
        return ""
    messages: list[Message] = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(role="user", content=original),
    ]
    try:
        response = provider.chat(messages)
    except Exception:
        return original
    text = (response.get("content") or "").strip()
    return text or original


def compute_diff_lines(original: str, proposed: str) -> tuple[str, str]:
    """Return Rich-markup diff strings for original vs proposed text.

    Removed words in ``original`` are rendered in red; added words in
    ``proposed`` are rendered in green. Unchanged words pass through.
    """

    orig_tokens = original.split()
    prop_tokens = proposed.split()
    diff = list(ndiff(orig_tokens, prop_tokens))

    removed: list[str] = []
    added: list[str] = []
    for line in diff:
        if not line:
            continue
        marker, _, word = line[0], line[1], line[2:]
        if marker == "-":
            removed.append(f"[red]{word}[/red]")
        elif marker == "+":
            added.append(f"[green]{word}[/green]")
        elif marker == " ":
            removed.append(word)
            added.append(word)

    return " ".join(removed), " ".join(added)
