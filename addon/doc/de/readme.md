# ClauVDA - Anthropic Claude AI for NVDA

## Summary

ClauVDA integrates Anthropic's Claude AI directly into NVDA, providing blind and visually impaired users with powerful AI assistance. The add-on supports the current Claude line-up — Opus 4.7, Sonnet 4.6, and Haiku 4.5 — for chat, image description, screen-recording analysis, and more. Both the direct Anthropic API and Amazon Bedrock (via bearer-token API keys) are supported as authentication providers.

## Features

* **AI Chat**: Have conversations with Claude directly from NVDA
* **Screen Description**: Capture and describe the entire screen
* **Object Description**: Describe the current navigator object
* **Video Analysis**: Record a short screen clip; Claude analyzes sampled frames
* **Attach Images**: Attach images from files for AI description
* **Conversation History**: Maintain context across multiple messages
* **Multiple Models**: Choose between Opus, Sonnet, and Haiku
* **Two Auth Providers**: Anthropic API direct, or Amazon Bedrock bearer token
* **Summarize Selection**: Select text and have Claude summarize the key points
* **Customizable Settings**: Temperature, max tokens, streaming, and more

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

## Using the Claude Dialog

When you open the Claude dialog with NVDA+G:

1. **Model**: Select which Claude model to use
2. **System Prompt**: Optional instructions on how Claude should respond
3. **History**: View the conversation history
4. **Message**: Type your message or question
5. **Send**: Send your message to Claude
6. **Attach Image**: Add an image file for Claude to analyze
7. **Attach Video**: Add a video; frames are sampled and sent as images
8. **Clear**: Clear the conversation history
9. **Copy Response**: Copy the last response to the clipboard

### Dialog Tips

* Press Ctrl+Enter in the message field to quickly send
* Use Tab to navigate between controls
* Alt+1..9,0 reads the Nth most recent message; double-press to copy

## Settings

Access settings via NVDA menu > Preferences > Settings > Claude AI:

* **API provider**: Anthropic direct or Amazon Bedrock
* **AWS region**: Bedrock region (ignored when using the Anthropic API directly)
* **Default Model**: Claude model to use by default
* **Temperature (0-100)**: Response randomness (0 = focused, 100 = creative)
* **Maximum Output Tokens**: Maximum length of responses
* **Stream Responses**: Display/speak responses as they arrive
* **Conversation Mode**: Include chat history for context
* **Remember System Prompt**: Save your custom system prompt
* **Block Escape Key**: Prevent accidental dialog closure
* **Filter Markdown**: Remove markdown formatting from responses

### Audio Feedback

* **Play sound when sending request**
* **Play sound while waiting**
* **Play sound when response received**

## Available Models

* **Claude Opus 4.7** — Most capable, extended thinking
* **Claude Sonnet 4.6** — Balanced for everyday use, extended thinking
* **Claude Haiku 4.5** — Fastest, cost-efficient

All three support image input.

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

## Troubleshooting

### "Anthropic SDK failed to load"

The bundled libraries may be missing or corrupted. Reinstall the add-on.

### "No Anthropic API key configured"

Configure your API key in Settings > Claude AI for the provider you've selected.

### Responses are too short or cut off

Increase the "Maximum Output Tokens" setting.

### Responses are too random

Lower the Temperature setting.

## Privacy Notice

* Your messages, images, and video frames are sent to the selected provider (Anthropic or AWS Bedrock)
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
