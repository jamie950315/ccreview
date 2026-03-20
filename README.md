# ccreview

Cross-model code review skill for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Sends your code changes to GPT-5.3-Codex (via [OpenRouter](https://openrouter.ai)) for review, then Claude triages the suggestions, applies fixes, and sends a follow-up round for verification.

## Features

- **Two-round review**: Initial review -> triage -> fix -> follow-up verification
- **Cross-model perspective**: GPT-5.3-Codex reviews, Claude triages and applies fixes
- **Sensitive file protection**: Auto-excludes `.env`, `*.pem`, `*.key`, credentials, etc.
- **Secret redaction**: Regex-based redaction of API keys, tokens, JWTs before sending to API
- **Rejection history**: Per-project rejection tracking (`.ccreview-rejections.md`) so the reviewer doesn't repeat them

## Installation

1. Copy the skill to your Claude Code skills directory:

```bash
cp -r ccreview ~/.claude/skills/ccreview
```

2. Set your OpenRouter API key in your shell profile:

```bash
echo 'export OPENROUTER_API_KEY=sk-or-v1-your-key-here' >> ~/.zshrc
source ~/.zshrc
```

3. That's it. Use `/ccreview` or say "code review" in Claude Code.

## How It Works

```
You finish coding
        |
        v
  [Step 1] Gather git diff
        |
        v
  [Step 2] GPT-5.3-Codex reviews the diff (Round 1)
        |
        v
  [Step 3] Claude triages: accept or reject each suggestion
        |
        v
  [Step 4] Claude applies accepted fixes
        |
        v
  [Step 5] GPT-5.3-Codex verifies fixes & evaluates rejections (Round 2)
        |
        v
  [Step 6] Final result + update rejection history
```

## File Structure

```
ccreview/
  SKILL.md          # Skill definition and workflow instructions
  scripts/
    review.py       # Python script — calls OpenRouter API

# In each project directory (auto-created by the skill):
.ccreview-rejections.md   # Per-project rejection history
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Model | `openai/gpt-5.3-codex` | Override with `--model` flag |
| Max tokens | 16384 | Response token limit |
| Temperature | 0.3 | Lower = more focused review |
| Rejection cap | 12000 chars | Max rejection history in prompt |

## Requirements

- Python 3.8+
- OpenRouter API key (`OPENROUTER_API_KEY` env var)
- Claude Code

## License

MIT
