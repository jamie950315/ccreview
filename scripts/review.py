#!/usr/bin/env python3
"""
Code review via OpenRouter API (GPT-5.3-Codex).

Two modes:
  - review:    Initial code review — returns structured feedback
  - follow-up: Second-round review — evaluates fixes and acknowledged rejections

Usage:
    # Initial review (code from file)
    python3 review.py --code /tmp/diff.txt

    # Initial review (code from stdin)
    git diff | python3 review.py

    # Follow-up review
    python3 review.py --mode follow-up \
        --code /tmp/updated_code.txt \
        --original-review /tmp/review.txt \
        --fixes-summary /tmp/fixes.txt

Environment:
    OPENROUTER_API_KEY  - Required. Must be present in process environment (e.g. export in ~/.zshrc).
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request


# ── Sensitive file / secret filtering ────────────────────────────────────────

SENSITIVE_PATTERNS = [
    ".env", ".env.*",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
    "*.secret", "*.secrets",
    "credentials*", "*credential*",
    "*secret*",
    "id_rsa*", "id_ed25519*", "id_ecdsa*",
    ".netrc", ".npmrc", ".pypirc", ".docker/config.json",
    "*.tfvars", "terraform.tfstate*",
    "kubeconfig*", ".kube/config",
]

# Regex for values that look like secrets (API keys, tokens, passwords)
SECRET_VALUE_RE = re.compile(
    r'(?:^|(?<=[=:"\s]))'                 # start of line OR preceded by = : " or space
    r'('
    r'sk-[a-zA-Z0-9_-]{20,}'             # OpenAI-style keys
    r'|sk-or-v1-[a-zA-Z0-9]{20,}'        # OpenRouter keys
    r'|ghp_[a-zA-Z0-9]{20,}'             # GitHub PAT
    r'|ghu_[a-zA-Z0-9]{20,}'             # GitHub user token
    r'|ghs_[a-zA-Z0-9]{20,}'             # GitHub server token
    r'|glpat-[a-zA-Z0-9_-]{20,}'         # GitLab PAT
    r'|xox[bpsa]-[a-zA-Z0-9-]{20,}'      # Slack tokens
    r'|AKIA[0-9A-Z]{16}'                  # AWS access key
    r'|AIza[a-zA-Z0-9_-]{30,}'           # Google API key
    r'|[a-zA-Z0-9_-]{30,}\.[a-zA-Z0-9_-]{30,}\.[a-zA-Z0-9_-]{30,}'  # JWT
    r')',
    re.ASCII | re.MULTILINE,
)


def _is_sensitive_path(filepath):
    """Check if a file path matches any sensitive pattern."""
    basename = os.path.basename(filepath)
    for pat in SENSITIVE_PATTERNS:
        if "/" in pat:
            if fnmatch.fnmatch(filepath, pat) or filepath.endswith(pat):
                return True
        else:
            if fnmatch.fnmatch(basename, pat):
                return True
    return False


def redact_secrets(text):
    """Redact secret values from arbitrary text."""
    return SECRET_VALUE_RE.sub("[REDACTED]", text)


def sanitize_diff(text):
    """Strip diff hunks for sensitive files and redact secret values."""
    lines = text.split("\n")
    output = []
    skipping = False
    skipped_files = []

    for line in lines:
        # Detect git diff file header
        if line.startswith("diff --git "):
            # Extract b-side path: diff --git a/foo b/foo
            parts = line.split(" b/", 1)
            filepath = parts[1] if len(parts) > 1 else ""
            if _is_sensitive_path(filepath):
                skipping = True
                skipped_files.append(filepath)
                continue
            else:
                skipping = False

        # Detect concatenated file header (=== FILE: path ===)
        if line.startswith("=== FILE:") and line.endswith("==="):
            filepath = line.split("FILE:", 1)[1].rsplit("===", 1)[0].strip()
            if _is_sensitive_path(filepath):
                skipping = True
                skipped_files.append(filepath)
                continue
            else:
                skipping = False

        if skipping:
            continue

        output.append(line)

    result = "\n".join(output)

    # Redact secret values
    result = redact_secrets(result)

    if skipped_files:
        print(f"Sanitizer: excluded {len(skipped_files)} sensitive file(s): {', '.join(skipped_files)}",
              file=sys.stderr)

    return result


# ── Constants ────────────────────────────────────────────────────────────────

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-5.3-codex"
def _find_project_root():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return os.getcwd()

REJECTIONS_FILE = os.path.join(_find_project_root(), ".ccreview-rejections.md")


# ── API call ─────────────────────────────────────────────────────────────────

def call_openrouter(api_key, model, messages, temperature=0.3):
    """Send chat completion request to OpenRouter."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 16384,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://claude.code/skill/ccreview",
            "X-Title": "Claude Code - ccreview",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Error: OpenRouter API returned {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ── Rejection history ────────────────────────────────────────────────────────

def load_rejections():
    """Load previously rejected suggestions from rejections.md."""
    try:
        if os.path.exists(REJECTIONS_FILE):
            with open(REJECTIONS_FILE, encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                return content
    except (OSError, UnicodeDecodeError) as e:
        print(f"Warning: Could not read {REJECTIONS_FILE}: {e}", file=sys.stderr)
    return ""


# ── Review prompts ───────────────────────────────────────────────────────────

REVIEW_SYSTEM_BASE = """\
You are an expert code reviewer with deep knowledge across multiple languages and frameworks.
Review the provided code changes thoroughly and provide actionable feedback.

For each issue found, structure your feedback as:

### [severity] Issue Title
- **Location**: file and line reference if identifiable
- **Problem**: clear description of the issue
- **Suggestion**: specific code fix or improvement

Severity levels:
- **CRITICAL**: Bugs, security vulnerabilities, data loss risks — must fix
- **WARNING**: Performance issues, error handling gaps, potential edge cases — should fix
- **SUGGESTION**: Code quality, readability, maintainability improvements — nice to fix
- **NITPICK**: Style, naming, minor preferences — optional

Focus on:
1. Bugs and logic errors
2. Security vulnerabilities (injection, auth, data exposure)
3. Performance issues and resource leaks
4. Error handling gaps
5. Race conditions and concurrency issues
6. API contract violations
7. Code maintainability

At the end, provide a brief summary:
- Total issues by severity
- Overall assessment (ready to ship / needs fixes / needs major rework)

Be specific and actionable. Skip obvious or trivial observations.\
"""


MAX_REJECTIONS_CHARS = 12000


def build_review_system():
    """Build review system prompt, appending rejection history if present."""
    rejections = redact_secrets(load_rejections())
    if len(rejections) > MAX_REJECTIONS_CHARS:
        rejections = rejections[-MAX_REJECTIONS_CHARS:]
        rejections = "[...truncated older entries...]\n" + rejections
    if rejections:
        return (
            REVIEW_SYSTEM_BASE
            + "\n\n"
            + "IMPORTANT: The following suggestions have been previously reviewed and explicitly rejected by the developer. "
            + "Do NOT raise these issues again unless the code has materially changed in a way that invalidates the original rejection reasoning.\n\n"
            + rejections
        )
    return REVIEW_SYSTEM_BASE

FOLLOW_UP_SYSTEM = """\
You are an expert code reviewer conducting a follow-up review.
The developer has addressed some of your previous suggestions and explained their reasoning for rejecting others.

Your job:
1. **Verify fixes**: Check that accepted suggestions were implemented correctly
2. **Evaluate rejections**: Assess the developer's reasoning for rejected suggestions — acknowledge when their reasoning is valid, push back only if the rejection creates real risk
3. **New issues**: Check if the fixes introduced any new problems
4. **Final verdict**: Is the code now ready to ship?

Structure your response as:

## Fixes Verified
[For each accepted fix, confirm it looks good or note remaining concerns]

## Rejections Evaluated
[For each rejected suggestion, agree with the reasoning OR explain why you still recommend the change]

## New Issues (if any)
[Any problems introduced by the fixes]

## Final Assessment
[Ready to ship / Still needs work — with clear reasoning]

Be constructive and concise. Respect the developer's judgment where reasonable.\
"""


# ── Core functions ───────────────────────────────────────────────────────────

def review_code(api_key, model, code, context=""):
    """Run initial code review."""
    user_msg = "Please review the following code changes:\n\n"
    if context:
        user_msg = f"Context: {context}\n\n{user_msg}"
    user_msg += code

    messages = [
        {"role": "system", "content": build_review_system()},
        {"role": "user", "content": user_msg},
    ]
    return call_openrouter(api_key, model, messages)


def follow_up_review(api_key, model, original_review, fixes_summary, updated_code):
    """Run follow-up review after fixes."""
    user_msg = f"""\
## Previous Review

{original_review}

## Developer's Response

{fixes_summary}

## Updated Code

{updated_code}"""

    messages = [
        {"role": "system", "content": FOLLOW_UP_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    return call_openrouter(api_key, model, messages)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Code review via OpenRouter API")
    parser.add_argument("--mode", choices=["review", "follow-up"], default="review",
                        help="review = initial review, follow-up = second round")
    parser.add_argument("--code", type=str,
                        help="Path to file containing code/diff to review (default: stdin)")
    parser.add_argument("--context", type=str, default="",
                        help="Additional context for the review")
    parser.add_argument("--original-review", type=str,
                        help="Path to file with original review (follow-up mode)")
    parser.add_argument("--fixes-summary", type=str,
                        help="Path to file with fixes summary (follow-up mode)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        help=f"Model ID on OpenRouter (default: {DEFAULT_MODEL})")
    parser.add_argument("--rejections", type=str, default=None,
                        help="Path to rejections file (default: .ccreview-rejections.md in project root)")
    parser.add_argument("--output", "-o", type=str,
                        help="Path to save review output (default: stdout)")
    args = parser.parse_args()

    # Override rejections file path if provided
    if args.rejections:
        global REJECTIONS_FILE
        REJECTIONS_FILE = args.rejections

    # API key
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("Error: OPENROUTER_API_KEY not found in environment. Add 'export OPENROUTER_API_KEY=sk-or-...' to ~/.zshrc and restart your shell.",
              file=sys.stderr)
        sys.exit(1)

    # Read code input
    if args.code:
        try:
            with open(args.code, encoding="utf-8") as f:
                code = f.read()
        except (OSError, UnicodeDecodeError) as e:
            print(f"Error: Cannot read code file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        if sys.stdin.isatty():
            print("Error: No code provided. Use --code <file> or pipe via stdin.", file=sys.stderr)
            sys.exit(1)
        code = sys.stdin.read()

    if not code.strip():
        print("Error: Empty code input — nothing to review.", file=sys.stderr)
        sys.exit(1)

    # Sanitize sensitive content
    code = sanitize_diff(code)

    if not code.strip():
        print("Error: All content was filtered as sensitive — nothing to review.", file=sys.stderr)
        sys.exit(1)

    # Redact secrets from context
    context = redact_secrets(args.context) if args.context else ""

    # Dispatch
    if args.mode == "review":
        print(f"Sending to {args.model} for review...", file=sys.stderr)
        result = review_code(api_key, args.model, code, context)

    elif args.mode == "follow-up":
        if not args.original_review or not args.fixes_summary:
            print("Error: --original-review and --fixes-summary are required for follow-up mode.",
                  file=sys.stderr)
            sys.exit(1)
        try:
            with open(args.original_review, encoding="utf-8") as f:
                original_review = redact_secrets(f.read())
            with open(args.fixes_summary, encoding="utf-8") as f:
                fixes_summary = redact_secrets(f.read())
        except (OSError, UnicodeDecodeError) as e:
            print(f"Error: Cannot read follow-up file: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Sending follow-up to {args.model}...", file=sys.stderr)
        result = follow_up_review(api_key, args.model, original_review, fixes_summary, code)

    # Output
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(result)
            print(f"Review saved to {args.output}", file=sys.stderr)
        except OSError as e:
            print(f"Error: Cannot write output file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(result)


if __name__ == "__main__":
    main()
