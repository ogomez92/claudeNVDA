# ClauVDA NVDA Add-on - Markdown Filter
# -*- coding: utf-8 -*-

"""
Simple markdown filter for screen reader friendly output.
Removes common markdown formatting that AI models produce.
"""

import re


def filter_markdown(text: str) -> str:
    """
    Remove common markdown formatting from text.

    Handles:
    - Bold: **text** or __text__
    - Italic: *text* or _text_
    - Bold+Italic: ***text*** or ___text___
    - Strikethrough: ~~text~~
    - Headings: # Heading, ## Heading, etc.
    - Code blocks: ```code``` or `code`
    - Links: [text](url) -> text
    - Images: ![alt](url) -> alt
    - Blockquotes: > text -> text
    - Horizontal rules: ---, ***, ___
    - Unordered lists: - item, * item, + item
    - Ordered lists: 1. item, 2. item
    """
    if not text:
        return text

    # Code blocks (``` ... ```) - remove the markers but keep content
    text = re.sub(r'```[\w]*\n?(.*?)```', r'\1', text, flags=re.DOTALL)

    # Inline code (`code`) - remove backticks
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Images ![alt](url) -> alt
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)

    # Links [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # Reference links [text][ref] -> text
    text = re.sub(r'\[([^\]]+)\]\[[^\]]*\]', r'\1', text)

    # Bold+Italic (must be before bold and italic)
    text = re.sub(r'\*\*\*([^*]+)\*\*\*', r'\1', text)
    text = re.sub(r'___([^_]+)___', r'\1', text)

    # Bold
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)

    # Italic (be careful not to match underscores in words)
    text = re.sub(r'\*([^*\n]+)\*', r'\1', text)
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_\n]+)_(?![a-zA-Z0-9])', r'\1', text)

    # Strikethrough
    text = re.sub(r'~~([^~]+)~~', r'\1', text)

    # Headings (# Heading -> Heading)
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # Blockquotes (> text -> text)
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)

    # Horizontal rules (---, ***, ___)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # Unordered list markers (- item, * item, + item -> item)
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)

    # Ordered list markers (1. item -> item)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)

    # Clean up extra blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Clean up leading/trailing whitespace on lines
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    return text.strip()
