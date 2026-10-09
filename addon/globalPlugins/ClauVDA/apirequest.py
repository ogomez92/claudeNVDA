# ClauVDA NVDA Add-on - Shared Messages API request helpers
# -*- coding: utf-8 -*-

"""Build and read Messages API requests the same way for every feature.

Every request names the model ID for the active provider and an explicit
effort level. On the Anthropic API, models that support it also get
server-side refusal fallbacks. Responses are read by block type, because the
current models can start a reply with thinking blocks.
"""

import base64
import datetime
import os

import addonHandler
from logHandler import log

addonHandler.initTranslation()

# A request may be at most 32 MB, and base64 grows a file by a third.
MAX_PDF_BYTES = 20 * 1024 * 1024

# Retries a request that the model's safety classifiers decline on the model
# Anthropic recommends for that refusal category. Claude API only.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# How many times a turn paused by the server (stop_reason "pause_turn", e.g.
# during a long web search) is resumed before giving up.
MAX_CONTINUATIONS = 5

# Searches Claude may run for one reply.
WEB_SEARCH_MAX_USES = 5

# Sent to the model, so deliberately not translated.
_SEARCH_GUIDANCE = (
    "Your training data ends well before today's date. Records, office holders, prices, "
    "versions, rules and anything \"latest\" may have changed since then, so search for "
    "those before you answer, even when you feel sure. Facts that can't change need no "
    "search. When the answer depends on where the user is, put the user's country or "
    "region in the search query."
)


def build_request(
    model,
    provider: str,
    messages: list,
    *,
    max_tokens: int,
    effort: str,
    system: str | None = None,
    tools: list | None = None,
    cache: bool = False,
) -> tuple[dict, list[str]]:
    """Return (kwargs, betas) for :func:`create` or :func:`stream`."""
    kwargs = {
        "model": model.resolve_id(provider),
        "max_tokens": max_tokens,
        "messages": messages,
        "output_config": {"effort": effort},
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if cache:
        # Marks the end of the request as a cache breakpoint, so the next turn
        # of the conversation (images and PDFs included) is read from cache.
        kwargs["cache_control"] = {"type": "ephemeral"}
    betas = []
    if provider == "anthropic" and model.server_fallback:
        betas.append(FALLBACK_BETA)
        # Sent as extra_body because the 32-bit SDK build predates the parameter.
        kwargs["extra_body"] = {"fallbacks": "default"}
    return kwargs, betas


def create(client, kwargs: dict, betas: list[str]):
    """Send a non-streaming request, through the beta endpoint when needed."""
    if betas:
        return client.beta.messages.create(betas=betas, **kwargs)
    return client.messages.create(**kwargs)


def stream(client, kwargs: dict, betas: list[str]):
    """Open a streaming request, through the beta endpoint when needed."""
    if betas:
        return client.beta.messages.stream(betas=betas, **kwargs)
    return client.messages.stream(**kwargs)


def pdf_block(path: str) -> dict | None:
    """Read a PDF and return a document content block, or None on failure."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        log.error(f"Error reading PDF {path}: {e}")
        return None
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
        "title": os.path.basename(path),
    }


def pdf_too_large_message(path: str) -> str:
    # Translators: Error when a PDF is too large to send. {name} is the file name
    return _("{name} is too large to send. PDFs can be up to 20 MB.").format(name=os.path.basename(path))


def web_search_tool(model) -> dict:
    """The web search tool definition for ``model``."""
    return {"type": model.web_search_tool, "name": "web_search", "max_uses": WEB_SEARCH_MAX_USES}


def web_search_system_note() -> str:
    """System prompt text that keeps searches grounded in today's date."""
    return f"The current date is {datetime.date.today().isoformat()}. {_SEARCH_GUIDANCE}"


def is_refusal(response) -> bool:
    """True when Claude's safety classifiers declined the request.

    A refusal is an HTTP 200 with stop_reason "refusal", not an exception.
    """
    return getattr(response, "stop_reason", None) == "refusal"


def refusal_message() -> str:
    # Translators: Spoken when Claude's safety checks decline a request
    return _("Claude declined this request. Try rephrasing it, or choose a different model.")


def response_text(response) -> str:
    """Join the text blocks of a response, skipping thinking and tool blocks."""
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def one_shot_reply(response) -> str:
    """Text to announce for a one-shot request, or why there is none."""
    if is_refusal(response):
        return refusal_message()
    return response_text(response) or _("No response from AI")


def cited_sources(response) -> list[tuple[str, str]]:
    """(title, url) of every web page cited in a response, without repeats."""
    seen = set()
    sources = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) != "text":
            continue
        for citation in getattr(block, "citations", None) or []:
            url = getattr(citation, "url", None)
            if url and url not in seen:
                seen.add(url)
                sources.append((getattr(citation, "title", None) or url, url))
    return sources


def format_sources(sources: list[tuple[str, str]]) -> str:
    """A numbered list of sources to show under a reply, or an empty string."""
    if not sources:
        return ""
    lines = [
        # Translators: Heading above the web pages Claude cited in a reply
        _("Sources:")
    ]
    for number, (title, url) in enumerate(sources, start=1):
        lines.append(f"{number}. {title} - {url}")
    return "\n".join(lines)
