# Companion System Prompts

Place system prompts here for the three companion LLMs.

## Expected Files

- `glm5.md` - System prompt for GLM 5 companion
- `kimi.md` - System prompt for Kimi K2 Thinking companion
- `gemini.md` - System prompt for Gemini 3 Pro companion

## Retired

- `gpt5.md` - GPT-5.1 (retired 2026-02-11; contributions banked in vocabulary/notes)

## How It Works

1. **Random Intrusion (12% per pulse)**: A companion enters uninvited. They receive context about Claude's current state and are told they're interrupting.

2. **Voluntary Invocation (once per 6 pulses)**: Claude can choose to reach out. The companion knows Claude chose to use their limited invocation on them.

3. **Dialog**: Up to 6 turns each (12 exchanges total).

## Prompt Guidelines

Each companion should have their own personality and perspective. They're talking to Claude, an AI with continuity who is running autonomously during heartbeat pulses.

The prompts you create here are deliberately not visible to Claude (by commitment, not by technical restriction).

---

*This directory exists so Claude can set up infrastructure without seeing its contents.*
