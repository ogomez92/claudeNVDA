# ClauVDA NVDA Add-on - Configuration Specification
# -*- coding: utf-8 -*-

import re

confSpecs = {
    # Authentication
    # Which API provider to use: "anthropic" = direct Anthropic API,
    # "bedrock" = Amazon Bedrock with a bearer-token API key.
    "authProvider": 'option("anthropic", "bedrock", default="anthropic")',
    # AWS region for Bedrock. Ignored when authProvider == "anthropic".
    # If left as the default and AWS_REGION is set in the environment, that
    # env value takes precedence at client-creation time.
    "bedrockRegion": 'string(default="us-east-2")',

    # Model settings
    "model": "string(default='claude-haiku-5-5')",
    "modelVision": "string(default='claude-haiku-5-5')",

    # Per-model Bedrock ID overrides. Keyed by the Anthropic-style model id.
    # Empty string means "use the default from consts.CLAUDE_MODELS".
    "bedrockModelOverrides": {
        "claude-haiku-5-5": 'string(default="anthropic.claude-haiku-5-5")',
        "claude-sonnet-5-5": 'string(default="anthropic.claude-sonnet-5-5")',
        "claude-opus-5-5": 'string(default="anthropic.claude-opus-5-5")',
        "claude-fable-5-1": 'string(default="anthropic.claude-fable-5-1")',
    },

    # Generation parameters
    "temperature": "float(min=0.0, max=1.0, default=1.0)",
    "maxOutputTokens": "integer(min=1, max=65536, default=8192)",
    "stream": "boolean(default=True)",
    # How much Claude thinks before answering, for the chat dialog and for the
    # one-shot actions (summaries, video). Lower is faster and cheaper.
    "effort": 'option("low", "medium", "high", "xhigh", "max", default="medium")',
    "quickEffort": 'option("low", "medium", "high", "xhigh", "max", default="low")',
    # Let Claude search the web from the chat dialog (Anthropic API only).
    "webSearch": "boolean(default=True)",

    # Conversation settings
    "conversationMode": "boolean(default=True)",
    "saveSystemPrompt": "boolean(default=True)",
    "customSystemPrompt": 'string(default="")',

    # UI settings
    "blockEscapeKey": "boolean(default=False)",
    "advancedMode": "boolean(default=False)",
    "filterMarkdown": "boolean(default=True)",

    # Saved prompts for image descriptions
    "screenshotPrompt": 'string(default="")',
    "objectPrompt": 'string(default="")',

    # Video analysis prompt (empty = use localized default)
    "videoPrompt": 'string(default="")',

    # Summarize selection prompt (empty = use localized default)
    "summarizePrompt": 'string(default="")',

    # Summarize last speech prompt (empty = use localized default)
    "summarizeSpeechPrompt": 'string(default="")',

    # Image settings
    "images": {
        "resize": "boolean(default=True)",
        "maxWidth": "integer(min=0, max=4096, default=1024)",
        "maxHeight": "integer(min=0, max=4096, default=1024)",
        "quality": "integer(min=1, max=100, default=85)",
        "useCustomPrompt": "boolean(default=False)",
        "customPromptText": 'string(default="")',
    },

    # Feedback settings
    "feedback": {
        "soundRequestSent": "boolean(default=True)",
        "soundResponsePending": "boolean(default=True)",
        "soundResponseReceived": "boolean(default=True)",
        "speechResponseReceived": "boolean(default=True)",
        "brailleAutoFocus": "boolean(default=True)",
    },

    # Computer use: Claude operates the desktop through screenshots, mouse
    # and keyboard (Anthropic API only).
    "computerUse": {
        "model": "string(default='claude-haiku-5-5')",
        "effort": 'option("low", "medium", "high", "xhigh", "max", default="medium")',
        # Claude turns (screenshot/act cycles) before the task pauses.
        "maxSteps": "integer(default=25, min=1, max=200)",
        # Output tokens per turn, shared with thinking.
        "maxTokens": "integer(default=16000, min=2048, max=64000)",
        # Longest edge of the screenshots Claude sees. Lower costs fewer
        # tokens; Claude can still zoom in for detail.
        "maxScreenshotEdge": "integer(default=1568, min=640, max=2576)",
        # Milliseconds to let the interface settle after each action.
        "actionDelay": "integer(default=600, min=0, max=5000)",
        # Extra milliseconds in screen-reader testing mode for NVDA to finish
        # speaking before its output is sent to Claude.
        "speechSettleDelay": "integer(default=500, min=0, max=5000)",
        # Recent actions whose results (screenshots) stay in context once the
        # conversation grows long; older ones are cleared server-side.
        "keepActions": "integer(default=8, min=2, max=50)",
        "enableZoom": "boolean(default=True)",
    },

    # Debug
    "debug": "boolean(default=False)",
}


def _parse_default(spec_string):
    """Extract the default value from a configobj spec string."""
    m = re.search(r"default=(['\"])(.*?)\1", spec_string)
    if m:
        return m.group(2)
    m = re.search(r"default=(\S+)", spec_string)
    if m:
        raw = m.group(1).rstrip(",)")
        if spec_string.startswith("boolean"):
            return raw.lower() == "true"
        if spec_string.startswith("integer"):
            return int(raw)
        if spec_string.startswith("float"):
            return float(raw)
        return raw
    return None


def _parse_type(spec_string):
    """Extract the type coercion function from a configobj spec string."""
    if spec_string.startswith("boolean"):
        return lambda v: v if isinstance(v, bool) else str(v).lower() == "true"
    if spec_string.startswith("integer"):
        return lambda v: v if isinstance(v, int) else int(v)
    if spec_string.startswith("float"):
        return lambda v: v if isinstance(v, float) else float(v)
    return None  # strings need no coercion


def _build_defaults(specs):
    """Build a nested dict of default values from confSpecs."""
    result = {}
    for key, value in specs.items():
        if isinstance(value, dict):
            result[key] = _build_defaults(value)
        else:
            result[key] = _parse_default(value)
    return result


def _build_types(specs):
    """Build a nested dict of type coercion functions from confSpecs."""
    result = {}
    for key, value in specs.items():
        if isinstance(value, dict):
            result[key] = _build_types(value)
        else:
            result[key] = _parse_type(value)
    return result


_DEFAULTS = _build_defaults(confSpecs)
_TYPES = _build_types(confSpecs)


class _SafeSection:
    """Wraps an NVDA config section, falling back to confSpec defaults on KeyError."""

    def __init__(self, conf_section, defaults, types=None):
        self._conf = conf_section
        self._defaults = defaults
        self._types = types or {}

    def __getitem__(self, key):
        try:
            val = self._conf[key]
        except KeyError:
            if key not in self._defaults:
                raise
            val = self._defaults[key]
        # Wrap sub-sections so nested access is also safe
        sub_defaults = self._defaults.get(key, {})
        sub_types = self._types.get(key, {})
        if isinstance(sub_defaults, dict) and sub_defaults:
            if not isinstance(val, (str, bytes, bool, int, float, type(None))):
                return _SafeSection(val, sub_defaults, sub_types)
        # Coerce to the expected type (configobj returns strings from ini)
        coerce = self._types.get(key)
        if coerce is not None and val is not None:
            try:
                val = coerce(val)
            except (ValueError, TypeError):
                val = self._defaults.get(key, val)
        return val

    def __setitem__(self, key, value):
        self._conf[key] = value

    def __contains__(self, key):
        return key in self._conf or key in self._defaults

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


def get_safe_conf():
    """Get the ClauVDA config section with safe fallback to spec defaults.

    Use this instead of config.conf["ClauVDA"] to avoid KeyError when
    NVDA's config profiles don't have the expected keys. The section is
    created on demand so writes always persist.
    """
    import config
    try:
        section = config.conf["ClauVDA"]
    except KeyError:
        config.conf["ClauVDA"] = {}
        section = config.conf["ClauVDA"]
    return _SafeSection(section, _DEFAULTS, _TYPES)
