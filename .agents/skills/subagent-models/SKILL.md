---
name: subagent-models
description: Model and reasoning effort for a subagent. Use before spawning any subagent (Agent tool, workflow agent, another CLI's subagent), and when a vendor releases a model or a ranking row needs re-checking.
---

Every subagent gets a tier, and the tier gives its model and its effort. Name the model on every spawn: a spawn without one inherits the session's model.

## Tier

Pick the lowest tier the task clearly fits; when in doubt, go one tier up.

- **Trivial.** One known target, no interpretation: read a named file or symbol and return it, run a given command and report its output, or apply an edit you have already written out exactly.
- **Simple.** No judgment calls, but some breadth: codebase searches and exploration, doc lookups, summarising what existing code does, or mechanical edits that follow a spec you have already written.
- **Judgment.** Planning, design, debugging, writing new logic, and any task you can't confidently call simple.
- **High-stakes.** Judgment where a mistake is costly or hard to spot: code review, verifying another agent's work, hard debugging, migrations.

## Model

Use your own family's row, whatever model you are running as. Claude runs trivial tasks on `claude-haiku-5-5`, simple ones on `claude-sonnet-5-5`, and judgment and high-stakes ones on `claude-fable-5-2`. Every other family runs all four tiers on its one pick: rank alone decides, never cost. Then hold the pick to your ceiling (below).

| Family | Ranking (best → worst) | Subagent model | Checked |
|---|---|---|---|
| Claude (Anthropic) | Fable 5.2 > Opus 5.5 > Sonnet 5.5 > Haiku 5.5 | `claude-fable-5-2`, `claude-sonnet-5-5`, `claude-haiku-5-5` by tier | 2026-11-09 |
| OpenAI | GPT-6 Astra > GPT-6.1 Sol > GPT-6.1 Terra > GPT-6 Sol > GPT-5.6 Sol > GPT-5.6 Terra > GPT-5.5 > GPT-6 Luna / GPT-5.6 Luna | `gpt-6-astra` | 2026-11-09 |
| Gemini (Google) | 4 Carbon > 4 Argon > 3.8 Flash > 3.7 Flash > 3.1 Pro (preview) > 3.6 Flash > 3.5 Flash > 3.5 Flash-Lite | `gemini-4-argon`, until Carbon has an API model ID (Gemini CLI subagents default to `inherit`) | 2026-11-09 |
| Grok (xAI) | Grok 4.7 > 4.6 > 4.5 > Grok Build 0.1 > 4.3 > 4.20 | `grok-4.7` | 2026-11-09 |
| Qwen (Alibaba) | Qwen3.8-Max > Qwen3.7-Max > Qwen3.8-27B > Qwen3.8-Flash > Qwen3.6 / 3.5 open models | `qwen3.8-max` (serves the 0902 snapshot). Qwen4 is announced without a model ID: re-check when it has one | 2026-11-09 |
| DeepSeek | V4.1-Flash > V4-Pro (retired; routes to V4.1-Flash) | `deepseek-flash` | 2026-11-09 |
| Kimi (Moonshot) | K3.1 Pro > K3 > K2.7 Code > K2.6 > K2 Thinking | `kimi-k3.1-pro` | 2026-11-09 |
| GLM (Z.ai) | GLM-5.3 > GLM-5.3-Flash / FlashX > GLM-5.2 > GLM-5 | `glm-5.3` | 2026-11-09 |
| Mistral | Mistral Large 4 > Mistral Medium 3.5 (deprecated) > Devstral 2 (deprecated) > Devstral Small 2 > Mistral Small 4 / Large 3 | `mistral-large-4` (`mistral-large-4-0` is the same model) | 2026-11-09 |
| Meta | Muse Wonder Full > Muse Wonder > Muse Spark 1.3 > Muse Glimmer 30B > Llama 4 | `muse-wonder-1.0` (preview). Wonder Full runs only inside Muse Code and has no API | 2026-11-09 |
| MiniMax | MiniMax-M3.1-Flash > MiniMax-M3 > M2.7 > M2.5 | `MiniMax-M3.1-Flash` | 2026-11-09 |

### Ceiling

Your own model is the ceiling: a subagent runs on a model ranked at or below yours. Rank comes from your family's Ranking column, where models sharing a rung (`/`) count as equal, and a model the row doesn't list yet, such as a newer version or a snapshot, ranks where its vendor's announcement places it. When the tier's pick ranks above you, run the subagent on your own model, at the tier's effort.

So for Claude, a Fable 5.2 session takes the picks as they stand; an Opus 5.5 session runs judgment and high-stakes on `claude-opus-5-5`; a Sonnet 5.5 session runs everything but trivial on `claude-sonnet-5-5`; a Haiku 5.5 session runs everything on `claude-haiku-5-5`. In a one-pick family, a session ranked below the pick, such as GPT-6.1 Sol under `gpt-6-astra`, runs every subagent on its own model. A model from another family counts as above you.

Only the user raises the ceiling, by naming a higher model for that spawn or for the session.

## Effort

An effort the user set, for the session or for one task, goes to every subagent unchanged. When the session's effort is auto, the tier sets it. `max` is the user's to ask for, except where the table shows it as a vendor's own step above `high`.

| Family | Parameter | Trivial | Simple | Judgment | High-stakes |
|---|---|---|---|---|---|
| Claude | `effort` | `low` | `medium` | `high` | `xhigh` |
| OpenAI | `reasoning_effort` | `low` | `medium` | `high` | `xhigh` |
| Gemini | `thinking_level` | `low` | `medium` | `high` | `high` |
| Grok | `reasoning_effort` | `low` | `medium` | `high` | `xhigh` |
| Qwen | `reasoning_effort` | `low` | `medium` | `xhigh` | `xhigh` |
| DeepSeek | `reasoning_effort`, thinking enabled | `low` | `high` | `high` | `max` |
| Kimi | `reasoning_effort` | `low` | `high` | `high` | `max` |
| GLM | `reasoning_effort`, thinking enabled | `low` | `high` | `high` | `max` |
| Mistral | `reasoning_effort` | `low` | `medium` | `high` | `high` |
| Meta | `reasoning_effort` | `low` | `medium` | `high` | `xhigh` |
| MiniMax | `reasoning_effort` | `low` | `medium` | `high` | `xhigh` |

Each cell is the vendor's level of the same name as Claude's, or the next level up where the vendor has none. Kimi, GLM, Meta and MiniMax default to `max` when the parameter is omitted, so send it on every call.

## Re-checking a row

Re-check a row when its vendor releases, deprecates or retires a model. The row is done when all four hold:

1. **Ranking** follows agentic coding and long-horizon agent results, from the vendor's announcement and at least one independent board that carries the models being compared (Vals AI Terminal-Bench, Artificial Analysis). Where they disagree, the independent board decides.
2. **Subagent model** is the highest-ranked model with a published API model ID, copied from the vendor's own model page.
3. **Effort row** lists only levels the vendor's reasoning docs accept for that model.
4. **Checked** carries today's date.
