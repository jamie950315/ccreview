---
name: ccreview
description: "Cross-model code review using GPT-5.3-Codex via OpenRouter. After completing code changes, sends the diff to GPT-5.3-Codex for review. Claude then examines each suggestion, accepts or rejects with reasoning, applies fixes, and sends a follow-up round so GPT-5.3-Codex can verify the fixes and evaluate rejections. Trigger on: 'code review', 'ccreview', 'review my code', 'get a second opinion', 'cross-model review'."
---

# Code Review Skill (GPT-5.3-Codex via OpenRouter)

## Overview

Two-round cross-model code review workflow:

1. **Round 1**: Send code changes to GPT-5.3-Codex for review
2. **Triage**: Claude examines each suggestion — accept or reject with reasoning
3. **Fix**: Claude applies accepted fixes
4. **Round 2**: Send updated code + triage summary back to GPT-5.3-Codex for final verdict

## Prerequisites

- **OpenRouter API Key** as `export OPENROUTER_API_KEY=...` in `~/.zshrc` or `~/.bashrc`
- Python 3.8+
- The default model is `openai/gpt-5.3-codex` — override with `--model` if needed

## Workflow (Step-by-Step)

### Step 1 — Gather the diff

Collect the code changes to review. Prefer `git diff` for the current working tree:

```bash
# Unstaged changes
git diff > /tmp/cr_diff.txt

# Staged changes
git diff --cached > /tmp/cr_diff.txt

# All changes (staged + unstaged)
git diff HEAD > /tmp/cr_diff.txt

# Specific files
git diff HEAD -- path/to/file1 path/to/file2 > /tmp/cr_diff.txt
```

If not in a git repo, concatenate the relevant source files instead. **Do NOT include sensitive files** (`.env`, credentials, private keys, etc.).

**Important**: If the diff is empty, tell the user there are no changes to review and stop.

**Sensitive file protection**: The review script automatically:
- Strips diff hunks / file sections matching sensitive patterns (`.env`, `*.pem`, `*.key`, `credentials*`, etc.)
- Redacts values that look like API keys, tokens, or secrets (OpenAI, OpenRouter, GitHub, AWS, Slack, Google, JWTs)
- Reports excluded files to stderr

### Step 2 — Round 1: Initial review

Run the review script:

```bash
python3 ~/.claude/skills/ccreview/scripts/review.py \
  --code /tmp/cr_diff.txt \
  --output /tmp/cr_review_round1.txt
```

Optional flags:
- `--context "migrating auth from JWT to session tokens"` — helps the reviewer understand intent
- `--model openai/gpt-5.3-codex` — override model if needed

Read the output file and present the review to the user.

### Step 3 — Triage: Accept or reject each suggestion

Go through each suggestion from the review:

1. **Read the suggestion carefully**
2. **Read the relevant source code** to understand the full context
3. **Decide**: Accept or Reject
   - **Accept** if the suggestion fixes a real bug, security issue, or meaningful improvement
   - **Reject** if the suggestion is incorrect, doesn't apply to the codebase context, conflicts with project conventions, or is too trivial/opinionated
4. **Record your decision** with clear reasoning

Present the triage to the user in this format:

```
## Triage Results

### Accepted
- [CRITICAL] <issue title> — <brief reason for accepting>
- [WARNING] <issue title> — <brief reason>

### Rejected
- [SUGGESTION] <issue title> — <reason for rejecting>
- [NITPICK] <issue title> — <reason for rejecting>
```

Ask the user if they agree with the triage before proceeding. The user may override your decisions.

### Step 4 — Apply accepted fixes

Apply all accepted fixes to the codebase. After fixing:

1. Write a summary of what was fixed and what was rejected to a temp file:

```bash
# Write the fixes summary to a temp file
cat > /tmp/cr_fixes_summary.txt << 'FIXES_EOF'
## Accepted & Fixed

1. [CRITICAL] <issue> — Fixed by <what you did>
2. [WARNING] <issue> — Fixed by <what you did>

## Rejected (with reasoning)

1. [SUGGESTION] <issue> — Rejected because <reason>
2. [NITPICK] <issue> — Rejected because <reason>
FIXES_EOF
```

2. Gather the updated code:

```bash
git diff HEAD > /tmp/cr_updated_code.txt
```

### Step 5 — Round 2: Follow-up review

Send everything back for verification:

```bash
python3 ~/.claude/skills/ccreview/scripts/review.py \
  --mode follow-up \
  --code /tmp/cr_updated_code.txt \
  --original-review /tmp/cr_review_round1.txt \
  --fixes-summary /tmp/cr_fixes_summary.txt \
  --output /tmp/cr_review_round2.txt
```

Read and present the follow-up review to the user. This tells GPT-5.3-Codex:
- What was fixed (so it can verify correctness)
- What was rejected and why (so it can evaluate the reasoning)

### Step 6 — Final resolution and update rejection history

If the follow-up review raises new concerns:
- Address any valid new issues
- Explain to the user if you disagree with the follow-up

Present the final status to the user.

**Update rejection history**: After the review is complete, append any **newly rejected** suggestions to `.ccreview-rejections.md` in the **project root directory** (the current working directory). Use this format:

```markdown
## <Short issue title>
- **Suggestion**: <what was suggested>
- **Rejection reason**: <why it was rejected>
- **Rejected**: 1 time.
```

If a suggestion was already in `.ccreview-rejections.md` and was rejected again, increment its count instead of adding a duplicate. The script automatically includes this file in the system prompt to prevent GPT-5.3-Codex from repeating previously rejected suggestions.

**Remove stale rejections**: If a previously rejected suggestion is **accepted** in a new review (e.g., because the codebase changed), remove it from `.ccreview-rejections.md`.

## Cleanup

After the review is complete, clean up temp files:

```bash
rm -f /tmp/cr_diff.txt /tmp/cr_review_round1.txt /tmp/cr_fixes_summary.txt /tmp/cr_updated_code.txt /tmp/cr_review_round2.txt
```

## Script Reference

```
python3 ~/.claude/skills/ccreview/scripts/review.py [OPTIONS]

Options:
  --mode {review,follow-up}   review (default) or follow-up
  --code PATH                 File with code/diff (or pipe via stdin)
  --context TEXT              Additional context for the reviewer
  --original-review PATH      Original review file (follow-up mode)
  --fixes-summary PATH        Fixes summary file (follow-up mode)
  --model MODEL               OpenRouter model ID (default: openai/gpt-5.3-codex)
  --rejections PATH            Path to rejections file (default: .ccreview-rejections.md in CWD)
  --output PATH               Save output to file (default: stdout)
```

## Important Notes

- **Always present the triage to the user** before applying fixes — don't auto-apply without confirmation
- **Be honest about rejections** — if you reject a suggestion, give a real technical reason, not a dismissive one
- **Don't blindly accept everything** — the reviewer model may suggest changes that conflict with project conventions, are over-engineered, or are simply wrong in context
- **Don't blindly reject everything either** — take CRITICAL and WARNING severity items seriously
- If the diff is very large (>50KB), consider splitting by file/module and running multiple reviews
- Temp files use `/tmp/cr_*` prefix for easy identification and cleanup
