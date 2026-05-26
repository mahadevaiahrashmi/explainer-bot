# Reviewer — how it works and why

How the explainer-bot's reviewer ("critic") is implemented, plus a
side-by-side comparison of the five common ways to structure this kind
of LLM call so you can decide when to move beyond the current
implementation.

---

## Part 1 — How the reviewer works today

It's a **plain Python string** baked into the source — no separate
prompt file, no markdown loader, no skills/MCP/agent runner. Here's the
exact path.

### 1. The reviewer's instructions live as a module constant

**`prompts.py:31` — `CRITIC_PROMPT`** (~22 lines):

```python
CRITIC_PROMPT = """You are reviewing a draft explainer-video script against three criteria,
on behalf of a first-year computer-science undergraduate who will watch the final video.

Criteria:
  A. UNDERSTANDABILITY — can a first-year CS undergrad follow every sentence on first listen?
     Flag any undefined jargon, leaps of logic, or sentences that require re-reading.
  B. ANALOGIES — does the script use vivid, accurate analogies …
  C. WONDER — does the script convey genuine curiosity …

Output a JSON object only … Schema:
{
  "scores": {"understandability": int 1-5, "analogies": int 1-5, "wonder": int 1-5},
  "verdict": "approve" | "revise",
  "notes": [string, ...]
}

Be honest. A 3 is mediocre. Approve only if all three scores are >= 4.
"""
```

That's the *entire* reviewer "skill." There's no further config, no
rubric file, no examples to load.

### 2. It's imported at module-load time

**`pipeline.py:62–67`**:

```python
from prompts import (
    AESTHETIC_PICKER_PROMPT,
    CRITIC_PROMPT,
    SLIDE_DESIGNER_PROMPT,
    SLIDE_FIXER_PROMPT,
    WRITER_PROMPT,
)
```

Python evaluates `prompts.py` once on first import; `CRITIC_PROMPT`
becomes a module-level constant. No file I/O at call time.

### 3. It's invoked from one place — a single LLM call inside `draft_script`

**`pipeline.py:405–414`** (inside `draft_script`):

```python
critic_user = "Script to review (JSON array of slide segments):\n\n" + json.dumps(
    [s.__dict__ for s in segments], indent=2
)
critique_raw = await claude(CRITIC_PROMPT, critic_user)   # ← one call, no loop
crit = _extract_json(critique_raw)
critique = Critique(
    scores=dict(crit["scores"]),
    verdict=str(crit["verdict"]),
    notes=list(crit["notes"]),
)
```

So the reviewer:

- gets `CRITIC_PROMPT` as its **system** prompt
- gets the just-drafted segments (as JSON) as its **user** message
- replies with a JSON object that gets parsed into a `Critique`
  dataclass

### 4. Which backend actually executes the call

`claude(...)` is an alias for `pipeline.llm_call(system, user)`.
Depending on `BACKEND` it dispatches to one of:

| Backend       | What "executes" the prompt                                                                                  |
| ------------- | ------------------------------------------------------------------------------------------------------------ |
| `claude_cli`  | `subprocess.exec("claude", "-p", "--append-system-prompt", CRITIC_PROMPT, …)`                                |
| `ollama`      | `httpx.post(/api/chat, json={"messages":[{role:"system", content:CRITIC_PROMPT}, {role:"user", content:…}]})`|
| `llm`         | `subprocess.exec("llm", "-m", $LLM_MODEL, "--system", CRITIC_PROMPT, …)`                                     |

### What it is *not*

- ❌ Not a Claude Code **skill** (no `.claude/skills/`, no SkillRunner).
- ❌ Not an MCP server / tool — the critic has no tools, makes no
  further calls.
- ❌ Not a markdown file (`.md`) loaded from disk at runtime.
- ❌ Not a multi-turn agent loop — one request, one response, then we
  parse.
- ❌ Not chained to the writer — the writer drafts, *then separately*
  the critic reviews the writer's output.

### If you wanted to externalize it to a `.md` file

Trivial swap — replace the string constant with a file read:

```python
# in prompts.py
from pathlib import Path
CRITIC_PROMPT = (Path(__file__).parent / "prompts" / "critic.md").read_text()
```

You'd then move the prompt body into `prompts/critic.md` and never
touch Python again to tune the reviewer. Useful if a non-coder is
iterating on the rubric. The pipeline doesn't care where the string
came from.

---

## Part 2 — Five ways to structure this kind of LLM call

A comparison so you can decide when (and whether) to move beyond the
plain Python string.

### Side-by-side comparison

| Axis                                | **Python string** *(current)* | **.md file**                  | **Claude Code skill**            | **MCP server/tool**                                                                            | **Multi-turn agent loop**                       |
| ----------------------------------- | ----------------------------- | ----------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| Where the instruction lives         | `prompts.py` constant         | `prompts/critic.md` (loaded at startup) | `.claude/skills/critic/SKILL.md` | Server process, registered tool schema                                                         | Code that runs N LLM calls in a loop            |
| Who edits it                        | Anyone comfortable in Python  | **Non-coders** can edit       | Skill author                     | Whoever owns the server                                                                        | Coder (loop logic is in code)                   |
| Loading mechanism                   | Imported at process start     | `Path.read_text()` once at import | Loaded by Claude Code on `/critic` or auto-invocation | Connected via MCP transport (stdio/SSE); model picks the tool                                  | N/A — orchestration code makes the calls        |
| Backend-agnostic?                   | ✅ works with any LLM         | ✅ same as string             | ❌ Claude Code only              | ✅ if client speaks MCP (Claude Code, Claude Desktop, Cursor…) — but not direct SDK calls       | ✅                                              |
| Setup cost                          | Zero                          | One file read                 | Skill scaffold + frontmatter     | Server skeleton + tool schemas + transport                                                     | Significant — agent framework, termination logic, retries |
| Per-call overhead                   | 0 ms (string ref)             | 0 ms after first load         | Loader cost (~ms)                | Network/IPC hop + schema validation                                                            | N × call latency (3–10× a single call)          |
| Determinism                         | Highest                       | High                          | High                             | Tool **call** is deterministic; the model deciding *whether* to call it is not                 | Lowest — loop length + branch choices           |
| Can use tools (files, search, web)? | ❌                            | ❌                            | ✅ skill can include bash/scripts | ✅ that's the whole point                                                                      | ✅                                              |
| Can ask clarifying questions?       | ❌ one shot                   | ❌                            | ❌ (still one-shot)              | ❌ (still one call)                                                                            | ✅                                              |
| Versionable in git?                 | ✅                            | ✅ (cleaner diffs)            | ✅                               | ✅ (server code)                                                                               | ✅                                              |
| Testable in isolation?              | ✅ trivial unit test          | ✅ load + assert              | Hardest — needs Claude Code      | Medium — mock the transport                                                                    | Hard — non-determinism + length                 |
| Best when…                          | Prompt rarely changes; ship-with-code | A non-coder iterates on the rubric | You want it invocable from chat as a slash command, or shippable as a skill | The critic needs *other* tools (file access, web lookup)                                       | The critic needs to negotiate with the writer or iterate to a target score |
| Cost per invocation                 | 1 × LLM call                  | 1 × LLM call                  | 1 × LLM call                     | 1 × LLM call + small tool overhead                                                             | N × LLM calls                                   |
| Failure modes                       | Bad output → 1 parse error    | Same + file-not-found at import | Skill not auto-invoked when expected | Server unreachable / schema mismatch / model doesn't call tool                                 | Infinite loop, score-gaming, runaway cost       |

### Quick decision tree

```
  Does the reviewer need file/web/db access?
   ├─ No  → does a non-coder maintain the rubric?
   │        ├─ Yes  → .md file
   │        └─ No   → Python string  ← current choice
   └─ Yes → does it need to be one *agent* that can decide to use those tools?
            ├─ No   → MCP server (deterministic tool calls)
            └─ Yes  → Multi-turn agent loop

  Special case: do you want it discoverable via Claude Code's UI?
   └─ Yes → Claude Code skill (in addition to one of the above)
```

### Why the Python-string choice fits the explainer-bot reviewer

The critic here has these properties, which is why the simplest option
is the right one:

- **No tools needed.** It reads a JSON array of segments, writes a JSON
  object of scores. No filesystem, no web, no DB.
- **No iteration needed.** It just scores once. Re-running is the
  user's call, not the critic's.
- **The rubric rarely changes.** When it does change, it's a code
  change (the dataclass and the UI render keys would change too).
- **Must work on any backend.** A user on Ollama or OpenAI shouldn't
  get a different critic from a Claude Code user.
- **One-shot is cheap.** Adding an agent loop would 3–10× the cost and
  time for marginal quality.

### When to upgrade *this* critic

| If you want…                                                                                       | Move to…                                                                                |
| -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| A teaching-assistant (non-coder) to tune wording without touching Python                           | **.md file** (3-line change in `prompts.py`)                                            |
| The critic to look up real video references ("does this analogy match what 3B1B used?")            | **MCP server with a web-search tool**                                                   |
| Auto-redraft until all scores ≥ 4 (closing the loop without the human)                             | **Multi-turn agent loop** — writer + critic + revision, max N rounds                    |
| The critic to be reusable from Claude Code's chat *and* from this pipeline                         | **Claude Code skill** wrapping the same prompt (with a shim that calls it as a tool too) |

### Side note: hybrid is fine

These aren't mutually exclusive. You can:

- Load the prompt from a `.md` file (option 4) but invoke it as a
  one-shot string (option 1).
- Wrap a multi-turn agent loop (option 5) behind an MCP tool (option
  3) so other clients call it as a single tool.
- Ship the same prompt as both a Python constant (for the pipeline)
  and a Claude Code skill (for ad-hoc use).

For the explainer-bot, the cleanest evolution path is
**string → .md → MCP** if needs grow. Skipping straight to MCP or an
agent loop today would buy capability nobody is using.
