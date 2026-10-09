## 1.3.0

- Updated the model line-up to Claude Haiku 5.5, Sonnet 5.5, Opus 5.5, and
  Fable 5.1
- Haiku 5.5 is now the default model (was Opus 5)
- Model IDs saved by earlier versions are migrated on startup (Opus 5/4.x to
  Opus 5.5, Sonnet 5/4.x to Sonnet 5.5, Haiku 4.5 to Haiku 5.5)
- Amazon Bedrock now goes through Bedrock's Messages API endpoint (Mantle), with
  model IDs of the form `anthropic.claude-haiku-5-5`
- When Claude declines a request for safety reasons, the add-on now says so
  instead of reporting an empty response
- Removed the Temperature setting: none of the current models accept it
- Computer use, merged from the separate Claude Computer Use add-on: Claude operates
  the current window through screenshots, mouse and keyboard (NVDA+Alt+Shift+C), or
  tests it with NVDA's speech; NVDA+Alt+X pauses it. Fixed along the way:
  - Uses the computer toolset the 5.5 models require (the old tool is rejected)
  - Runs a batch of actions in order and stops at the first failure
  - Old screenshots are cleared on the server instead of being edited out of the
    history, which the new models reject; the prompt cache keeps working
  - Screenshots respect the models' total size limit, not just the long edge, so
    4:3 and multi-monitor desktops are no longer rejected
  - Clicks, scrolls and mouse presses without a coordinate act at the pointer
  - Claude's notes between actions are spoken again on Opus, Sonnet and Fable 5.5/5.1
  - A cut-off reply or an API error pauses the task so it can be resumed
  - The open gesture no longer hides Word's and Excel's NVDA+Alt+C comment command
  - Uses the add-on's encrypted API key instead of a plain-text copy
- Summarize a PDF (NVDA+Shift+P) or read all its text with AI, scanned pages included
  (NVDA+Alt+P); results open in a window you can read and copy
- Attach PDFs in the chat dialog
- Web search in the chat dialog, with the cited pages listed under the reply
- Reasoning effort settings for chat and for quick actions
- Multi-turn conversations are prompt-cached, so follow-ups about the same images or
  PDFs are faster and cheaper
- Streaming speech now waits for the end of each sentence instead of speaking every
  fragment with a pause after it

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
