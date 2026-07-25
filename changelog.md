## 1.2.0

- Updated the model line-up to Claude Opus 5, Sonnet 5, and Haiku 4.5
- Opus 5 is now the default model (was Sonnet 4.6)
- Opus 5 and Sonnet 5 carry a 1M token context window and a 128K output ceiling
- Temperature is no longer sent for Opus 5 and Sonnet 5, which reject sampling
  parameters; it still applies to Haiku 4.5
- Model IDs saved by earlier versions are migrated on startup (Opus 4.7/4.6/4.5
  to Opus 5, Sonnet 4.6/4.5 to Sonnet 5, dated Haiku 4.5 to its alias)
- The output token limit is now clamped to the selected model's ceiling for
  video analysis and summarization, not just chat

## 1.1.3 and earlier

- Initial release: Claude AI integration replacing Gemini
- Support Claude Opus 4.7, Sonnet 4.6, and Haiku 4.5 via the Messages API
- Two auth providers: Anthropic direct and Amazon Bedrock (bearer token)
- Bedrock key and Anthropic key stored separately, each DPAPI-encrypted
- Video analysis now samples frames (Claude has no native video ingest)
- Configurable video / summarize / summarize-speech prompts retained from GemVDA
