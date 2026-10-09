# ClauVDA - Anthropic Claude AI for NVDA

## Summary

ClauVDA integrates Anthropic's Claude AI directly into NVDA, providing blind and visually impaired users with powerful AI assistance. The add-on supports the current Claude line-up — Haiku 5.5, Sonnet 5.5, Opus 5.5, and Fable 5.1 — for chat, image description, screen-recording analysis, and more. Both the direct Anthropic API and Amazon Bedrock (via bearer-token API keys) are supported as authentication providers.

## Features

* **AI Chat**: Have conversations with Claude directly from NVDA
* **Screen Description**: Capture and describe the entire screen
* **Object Description**: Describe the current navigator object
* **Video Analysis**: Record a short screen clip; Claude analyzes sampled frames
* **Attach Images**: Attach images from files for AI description
* **Conversation History**: Maintain context across multiple messages
* **Multiple Models**: Choose between Haiku, Sonnet, Opus, and Fable
* **Two Auth Providers**: Anthropic API direct, or Amazon Bedrock bearer token
* **Summarize Selection**: Select text and have Claude summarize the key points
* **PDF Summary and OCR**: Summarize a PDF, or read all its text with AI, including scanned pages
* **Web Search**: Claude can look up current information and lists the pages it used
* **Computer Use**: Claude operates the current window for you, or tests it with NVDA's speech
* **Customizable Settings**: Reasoning effort, max tokens, streaming, and more

## Requirements

* NVDA 2024.1 or later
* One of:
  * An Anthropic API key, or
  * An Amazon Bedrock API key (bearer token) with access to Claude models
* Internet connection

## Setup

### Option 1 — Anthropic API (direct)

1. Visit [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
2. Create an API key
3. In NVDA: Preferences > Settings > Claude AI
4. Leave "API provider" as **Anthropic (direct)**
5. Click **Configure Anthropic API Key...** and paste your key

### Option 2 — Amazon Bedrock (bearer token)

1. Ensure your AWS account has model access for the Claude models you plan to use
2. Create a Bedrock API key at the AWS console: [Bedrock API keys](https://console.aws.amazon.com/bedrock/home#/api-keys)
3. In NVDA: Preferences > Settings > Claude AI
4. Change "API provider" to **Amazon Bedrock**
5. Set the AWS region (defaults to `us-east-1`)
6. Click **Configure Bedrock API Key...** and paste your bearer token

Keys for each provider are stored separately, encrypted at rest with Windows DPAPI. You can also supply them via environment variable (`ANTHROPIC_API_KEY` or `AWS_BEARER_TOKEN_BEDROCK`).

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| NVDA+G | Open Claude AI dialog |
| NVDA+Shift+E | Describe the entire screen |
| NVDA+Shift+O | Describe the navigator object |
| NVDA+V | Start/stop video recording for analysis |
| NVDA+Shift+U | Summarize selected text |
| NVDA+Shift+H | Summarize the last spoken text |
| NVDA+Shift+P | Summarize a PDF |
| NVDA+Alt+P | Read all the text of a PDF with AI (OCR) |
| NVDA+Alt+Shift+C | Open computer use for the current window |
| NVDA+Alt+X | Pause a running computer use task to guide Claude |

## Using the Claude Dialog

When you open the Claude dialog with NVDA+G:

1. **Model**: Select which Claude model to use
2. **Let Claude search the web**: Allow web searches for current information (Anthropic API only).
   Cited pages are listed under the reply in the history; they are not read aloud.
3. **System Prompt**: Optional instructions on how Claude should respond
4. **History**: View the conversation history
5. **Message**: Type your message or question
6. **Send**: Send your message to Claude
7. **Attach Image**: Add an image file for Claude to analyze
8. **Attach Video**: Add a video; frames are sampled and sent as images
9. **Attach PDF**: Add PDF documents (up to 20 MB each) to ask questions about them
10. **Clear**: Clear the conversation history
11. **Copy Response**: Copy the last response to the clipboard

### Dialog Tips

* Press Ctrl+Enter in the message field to quickly send
* Use Tab to navigate between controls
* Alt+1..9,0 reads the Nth most recent message; double-press to copy

## Settings

Access settings via NVDA menu > Preferences > Settings > Claude AI:

* **API provider**: Anthropic direct or Amazon Bedrock
* **AWS region**: Bedrock region (ignored when using the Anthropic API directly)
* **Default Model**: Claude model to use by default
* **Maximum Output Tokens**: Maximum length of responses
* **Reasoning effort for chat**: How much Claude thinks before answering in the dialog.
  Lower is faster and cheaper; Medium is the default
* **Reasoning effort for quick actions**: The same for summaries, PDF actions and video
  analysis; Low (fastest) is the default
* **Let Claude search the web in chat**: The default for the dialog's web search checkbox
* **Stream Responses**: Display responses as they arrive, speaking each sentence once it is complete
* **Conversation Mode**: Include chat history for context
* **Remember System Prompt**: Save your custom system prompt
* **Block Escape Key**: Prevent accidental dialog closure
* **Filter Markdown**: Remove markdown formatting from responses

### Audio Feedback

* **Play sound when sending request**
* **Play sound while waiting**
* **Play sound when response received**

## Available Models

* **Claude Haiku 5.5** (default) — Fastest and cheapest, 1M token context
* **Claude Sonnet 5.5** — Balanced for everyday use, 1M token context
* **Claude Opus 5.5** — For harder reasoning and long tasks, 1M token context
* **Claude Fable 5.1** — Most capable and most expensive, 1M token context

All four support image input and think before answering when a request needs it.
Models chosen in an earlier version are moved to their successor on startup
(Opus 5 to Opus 5.5, Sonnet 5 to Sonnet 5.5, Haiku 4.5 to Haiku 5.5).

## Image and Video Features

### Screen Description (NVDA+Shift+E)

Captures your entire screen and sends it to Claude for a detailed description.

### Object Description (NVDA+Shift+O)

Captures only the current navigator object.

### Video Analysis (NVDA+V)

1. Press NVDA+V to start recording
2. Perform the actions you want to analyze
3. Press NVDA+V again to stop
4. Frames are sampled from the recording and sent to Claude as images

Claude doesn't accept video files directly, so the add-on samples a handful of frames (default: 12) uniformly across the clip.

### Summarize Selection (NVDA+Shift+U)

Select text in any application and have Claude summarize the key points.

## PDF Features

Select a PDF in File Explorer and press NVDA+Shift+P to summarize it, or NVDA+Alt+P to
read all of its text with AI. Reading with AI also works on scanned pages and images
of text, and keeps headings, lists and tables. If File Explorer isn't focused on a PDF,
you are asked to choose one. The result opens in a window you can read with the
arrow keys and copy. Both actions are also in the NVDA menu under Claude.

## Computer Use

Press NVDA+Alt+Shift+C in any window and type what you want done. Claude looks at
screenshots of the screen and acts with the mouse and keyboard through NVDA, while
you hear what it is doing. Computer use needs NVDA 2026.1 or later and the Anthropic
API provider.

* **Assistant mode**: Claude does a task for you, such as ticking a checkbox you can't
  reach, then checks the result.
* **Screen-reader testing mode**: Claude navigates with the keyboard and also hears what
  NVDA announced after each action, then writes an accessibility report.

Press NVDA+Alt+X to pause a running task. Type new guidance in the dialog and press
Resume. When a task finishes, type a follow-up request and press Continue to keep the
same context, or press New task to start over.

Settings > Claude AI > Computer use sets the model, the reasoning effort, the maximum
steps per task, the screenshot size, the delays after each action, and how many recent
actions keep their screenshots once the task gets long.

Claude can click and type anywhere on your screen. It is told not to delete data, send
messages, buy things or change settings unless you asked, but watch what it does and
press NVDA+Alt+X or Stop if it goes wrong.

This replaces the separate Claude Computer Use add-on: uninstall that one, since both
use NVDA+Alt+X.

## Troubleshooting

### "Anthropic SDK failed to load"

The bundled libraries may be missing or corrupted. Reinstall the add-on.

### "No Anthropic API key configured"

Configure your API key in Settings > Claude AI for the provider you've selected.

### Responses are too short or cut off

Increase the "Maximum Output Tokens" setting.

### Responses are too random

Current Claude models do not accept a temperature setting. Ask for the tone you
want in the prompt or the system prompt instead.

## Privacy Notice

* Your messages, images, PDFs, and video frames are sent to the selected provider (Anthropic or AWS Bedrock)
* During computer use, screenshots of your whole screen are sent to Anthropic
* API keys are stored locally, encrypted with Windows DPAPI
* No data is shared with the add-on developer
* Review the [Anthropic usage policies](https://www.anthropic.com/legal/aup) and/or your AWS Bedrock agreement for details

## Support

* Report issues: [GitHub Issues](https://github.com/ogomez92/claudeNVDA/issues)
* Source code: [GitHub Repository](https://github.com/ogomez92/claudeNVDA)

## License

This add-on is released under the GNU General Public License v2.

## Author

Oriol Gomez Sentis
