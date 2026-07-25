# ClauVDA NVDA Add-on - Constants and Model Definitions
# -*- coding: utf-8 -*-

import os
import struct
import sys
import globalVars
from logHandler import log

# Directory paths
ADDON_DIR = os.path.dirname(__file__)
PLUGIN_DIR = os.path.dirname(ADDON_DIR)
ADDON_ROOT = os.path.dirname(PLUGIN_DIR)
DATA_DIR = os.path.join(globalVars.appArgs.configPath, "ClauVDA")
_arch = "lib64" if struct.calcsize("P") == 8 else "lib32"
LIBS_DIR = os.path.join(ADDON_ROOT, _arch)

# ABI tag CPython expects on this interpreter, e.g. ".cp313-win_amd64.pyd".
EXPECTED_PYD_SUFFIX = (
    f".cp{sys.version_info.major}{sys.version_info.minor}"
    f"-{'win_amd64' if struct.calcsize('P') == 8 else 'win32'}.pyd"
)


def _diagnose_libs() -> str | None:
    """Return why LIBS_DIR is unusable, or None if it matches this interpreter.

    NVDA's bundled Python moved from 3.11/32-bit (2024.1-2025.x) to 3.13/64-bit
    (2026.1+). C extensions carry that ABI tag in their filename and CPython
    silently skips any that don't match, so a stale build fails as a bare
    "No module named 'pydantic_core._pydantic_core'" with nothing pointing at
    the real cause. Check up front so the log says what actually went wrong.
    """
    if not os.path.isdir(LIBS_DIR):
        return f"bundled dependency directory is missing: {LIBS_DIR}"
    probe_dir = os.path.join(LIBS_DIR, "pydantic_core")
    try:
        found = [name for name in os.listdir(probe_dir) if name.endswith(".pyd")]
    except OSError:
        return f"bundled dependencies are incomplete: {probe_dir} is missing"
    if not found:
        return f"no compiled extension modules found in {probe_dir}"
    if any(name.endswith(EXPECTED_PYD_SUFFIX) for name in found):
        return None
    return (
        f"bundled dependencies in {_arch} were built for a different Python: found "
        f"{', '.join(sorted(found))} but this NVDA runs Python "
        f"{sys.version_info.major}.{sys.version_info.minor} "
        f"{struct.calcsize('P') * 8}-bit, which needs *{EXPECTED_PYD_SUFFIX}. "
        "Install an add-on build that matches this NVDA version."
    )


# None when the vendored libraries match the running interpreter.
LIBS_PROBLEM = _diagnose_libs()
if LIBS_PROBLEM:
    log.error(f"ClauVDA dependencies unusable: {LIBS_PROBLEM}")

# Create data directory if it doesn't exist
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# Sound files
SOUNDS_DIR = os.path.join(ADDON_DIR, "sounds")
SND_CHAT_REQUEST_SENT = os.path.join(SOUNDS_DIR, "chatRequestSent.wav")
SND_CHAT_RESPONSE_PENDING = os.path.join(SOUNDS_DIR, "chatResponsePending.wav")
SND_CHAT_RESPONSE_RECEIVED = os.path.join(SOUNDS_DIR, "chatResponseReceived.wav")
SND_PROGRESS = os.path.join(SOUNDS_DIR, "progress.wav")

# Default system prompt for accessibility
DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant integrated with NVDA, a screen reader for blind and visually impaired users.

When describing visual content:
- Be thorough and descriptive, as users cannot see the content
- Describe layout, colors, text, and important visual elements
- For images, describe what you see in detail
- For UI elements, explain their purpose and current state

When providing information:
- Be concise but complete
- Use clear, accessible language
- Avoid unnecessary visual references like "as you can see"
- Structure information logically for audio consumption

For code and technical content:
- Explain code structure and logic clearly
- Mention indentation and nesting levels when relevant
- Describe error messages and their likely causes
"""


class Model:
    """Represents a Claude model with its capabilities."""

    def __init__(
        self,
        id: str,
        name: str,
        bedrock_id: str | None = None,
        context_window: int = 200000,
        max_output_tokens: int = 8192,
        max_temperature: float = 1.0,
        vision: bool = False,
        preview: bool = False,
        thinking: bool = False,
        sampling: bool = True,
    ):
        self.id = id
        self.name = name
        self.bedrock_id = bedrock_id or id
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens
        self.max_temperature = max_temperature
        self.vision = vision
        self.preview = preview
        self.thinking = thinking
        # False when the model rejects sampling parameters (temperature, top_p,
        # top_k). Opus 5 and Sonnet 5 return HTTP 400 if temperature is sent.
        self.sampling = sampling

    def resolve_id(self, provider: str) -> str:
        """Return the right model identifier for the given provider.

        For Bedrock, any per-model override saved in the NVDA config takes
        precedence over ``bedrock_id``. Lazy-imports configspec to avoid a
        circular import at module load.
        """
        if provider == "bedrock":
            try:
                from .configspec import get_safe_conf
                override = get_safe_conf()["bedrockModelOverrides"][self.id]
                if isinstance(override, str) and override.strip():
                    return override.strip()
            except Exception:
                pass
            return self.bedrock_id
        return self.id

    def __repr__(self):
        return f"Model({self.id}, vision={self.vision})"


# Available Claude models (as of July 2026)
# Bedrock IDs use the "global." inference profile prefix.
CLAUDE_MODELS = [
    Model(
        id="claude-opus-5",
        name="Claude Opus 5",
        bedrock_id="global.anthropic.claude-opus-5-v1",
        context_window=1000000,
        max_output_tokens=128000,
        vision=True,
        thinking=True,
        sampling=False,
    ),
    Model(
        id="claude-sonnet-5",
        name="Claude Sonnet 5",
        bedrock_id="global.anthropic.claude-sonnet-5-v1",
        context_window=1000000,
        max_output_tokens=128000,
        vision=True,
        thinking=True,
        sampling=False,
    ),
    Model(
        id="claude-haiku-4-5",
        name="Claude Haiku 4.5",
        bedrock_id="global.anthropic.claude-haiku-4-5-v1",
        context_window=200000,
        max_output_tokens=64000,
        vision=True,
        thinking=True,
    ),
]

# Default model
DEFAULT_MODEL = "claude-opus-5"
DEFAULT_VISION_MODEL = "claude-opus-5"

# Model IDs from earlier add-on versions, mapped onto their replacements so a
# saved setting keeps working after an upgrade. Anything unknown falls back to
# DEFAULT_MODEL.
LEGACY_MODEL_IDS = {
    "claude-opus-4-7": "claude-opus-5",
    "claude-opus-4-6": "claude-opus-5",
    "claude-opus-4-5": "claude-opus-5",
    "claude-sonnet-4-6": "claude-sonnet-5",
    "claude-sonnet-4-5": "claude-sonnet-5",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
}


# Model lookup helpers
def get_model_by_id(model_id: str) -> Model | None:
    """Get a model by its ID."""
    for model in CLAUDE_MODELS:
        if model.id == model_id:
            return model
    return None


def normalize_model_id(model_id: str) -> str:
    """Map a saved model ID onto one this version actually offers."""
    if get_model_by_id(model_id):
        return model_id
    return LEGACY_MODEL_IDS.get(model_id, DEFAULT_MODEL)


def get_model_choices() -> list[tuple[str, str]]:
    """Get list of (id, name) tuples for UI choices."""
    return [(m.id, m.name) for m in CLAUDE_MODELS]


def get_vision_models() -> list[Model]:
    """Get models with vision capability."""
    return [m for m in CLAUDE_MODELS if m.vision]


# Default prompts for image descriptions
DEFAULT_SCREENSHOT_PROMPT = "Describe this screenshot in detail. What application or content is shown? What are the main elements visible on screen?"

DEFAULT_OBJECT_PROMPT = "Describe this UI element or object in detail. What is it? What does it show or do?"

# Error messages
NO_API_KEY_MSG = "No Anthropic API key configured. Please add your API key in the settings."
API_ERROR_MSG = "Error communicating with Anthropic API: {error}"
