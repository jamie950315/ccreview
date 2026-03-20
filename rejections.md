# Previously Rejected Suggestions

## API response schema validation / defensive parsing
- **Suggestion**: Validate `choices[0].message.content` structure before indexing; handle content as string or list-of-parts.
- **Rejection reason**: OpenRouter strictly follows the OpenAI-compatible chat completions schema. This is a single-purpose local CLI tool — the existing generic `except` block is sufficient. Over-validating adds complexity without practical benefit.
- **Rejected**: 3 times across 3 review rounds.

## sys.exit() inside helper function reduces reusability/testability
- **Suggestion**: Raise typed exceptions from `call_openrouter()` instead of calling `sys.exit()` directly; handle exits only in `main()`.
- **Rejection reason**: This is a single-purpose CLI script, not a reusable library. There are no unit tests and no plans to import this module elsewhere. Direct exit in helpers is acceptable for this use case.
- **Rejected**: 2 times across 2 review rounds.

## Import-time side effects reduce testability
- **Suggestion**: Move environment loading and process exits to `main()` instead of module top-level.
- **Rejection reason**: Same as above — single-purpose CLI script, not a shared module. Import-time initialization is a common and acceptable pattern for CLI tools.
- **Rejected**: 1 time.

## Argument validation order in follow-up mode
- **Suggestion**: Validate `--original-review` and `--fixes-summary` before reading `--code` input.
- **Rejection reason**: `--code` is required for both modes, so reading it first is logically correct. The caller is Claude Code (not a human typing manually), so missing args is not a realistic scenario.
- **Rejected**: 1 time.

## No retry/backoff for transient API failures
- **Suggestion**: Add bounded retries with exponential backoff for 429/5xx/timeout errors.
- **Rejection reason**: This script is only invoked interactively by Claude Code on a local machine. On failure the user can simply re-run. Adding retry logic is over-engineering for this use case.
- **Rejected**: 1 time.

## Quoted/escaped git diff path parsing
- **Suggestion**: Handle Git's quoted/escaped path format in `diff --git` headers for sensitive file detection.
- **Rejection reason**: Git only quotes paths containing special characters (spaces, non-ASCII). Sensitive filenames like `.env`, `*.pem`, `*.key` never contain these characters. Additionally, the regex-based `redact_secrets()` provides a second layer of protection even if file-level exclusion misses.
- **Rejected**: 2 times.

## Sensitive-file filtering is format-dependent
- **Suggestion**: Support additional patch header formats (`---`/`+++`, plain patches) and redact multiline secret blocks (e.g., PEM private keys) regardless of file path metadata.
- **Rejection reason**: `sanitize_diff` is designed for two specific formats controlled by the SKILL.md workflow (git diff and `=== FILE:` concatenation). Arbitrary patch formats are not in scope. Regex-based `redact_secrets()` serves as the second layer of protection. PEM block detection is a new feature beyond current scope.
- **Rejected**: 1 time.

## Sanitizer logging full sensitive file paths to stderr
- **Suggestion**: Log only count of excluded files by default, or basenames only; add a `--verbose` flag for full paths.
- **Rejection reason**: This CLI is only invoked locally by Claude Code; stderr is not captured by external systems. File paths like `.env` or `id_rsa` are not secrets themselves, and printing them aids debugging.
- **Rejected**: 1 time.
