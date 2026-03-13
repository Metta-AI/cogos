# Recruiter App Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the recruiter app as a CogOS image — five processes with file-based configuration, Discord integration, and self-improvement loop.

**Architecture:** Pure image configuration — an init script (`images/cogent-v1/apps/recruiter/init/processes.py`) defines 5 processes and their capability bindings. File content under `images/cogent-v1/apps/recruiter/files/recruiter/` provides prompt templates, criteria, rubrics, sourcer strategies, and diagnosis rules. The context engine wires includes automatically. No new Python code in `src/cogos/` is needed — everything runs through existing capabilities (dir, file, procs, discord, channels, me, secrets).

**Tech Stack:** CogOS image system (Python init scripts + markdown/json files), Bedrock converse API (processes are LLM agents), existing capabilities.

**Scoping notes:** The design mentions Asana integration and web search — neither capability exists yet. This plan skips Asana tasks and web search capability, using only what's available (discord, files, procs, channels, me, secrets). Dashboard views are also out of scope — they require frontend work.

---

### Task 1: Create the recruiter app directory structure

**Files:**
- Create: `images/cogent-v1/apps/recruiter/init/processes.py`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/criteria.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/rubric.json`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/diagnosis.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/strategy.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/evolution.md`

**Step 1: Create the criteria file**

`images/cogent-v1/apps/recruiter/files/recruiter/criteria.md`:

```markdown
# Candidate Criteria

## Must-Have
- Active in coding agents, LLM orchestration, or tool-use frameworks
- Has shipped production agent systems (not just prototypes/demos)
- Evidence of deep technical work: meaningful commits, architectural decisions, detailed writing
- Python or TypeScript ecosystem experience

## Strong Signals
- Maintains or contributes to agent frameworks (LangChain, CrewAI, AutoGen, MCP, custom)
- Writes about agent reliability, orchestration patterns, or tool-use design
- Building-in-public with technical depth
- Experience with multi-agent coordination, state management, or process orchestration

## Red Flags
- Only academic/research with no shipping history
- Pure wrapper/integration work without architectural depth
- Inactive for 6+ months
- Only content consumption (stars, likes) with no original output

## Values Alignment
- Builder mindset — prefers shipping over theorizing
- Systems thinker — considers failure modes, scaling, observability
- Opinionated but adaptable — has strong views loosely held
```

**Step 2: Create the rubric file**

`images/cogent-v1/apps/recruiter/files/recruiter/rubric.json`:

```json
{
  "github_activity": {
    "weight": 0.25,
    "signals": ["commit_frequency", "code_review_quality", "repo_ownership", "pr_discussions"]
  },
  "technical_depth": {
    "weight": 0.25,
    "signals": ["architecture_decisions", "failure_handling", "systems_thinking", "original_patterns"]
  },
  "shipping_history": {
    "weight": 0.20,
    "signals": ["production_systems", "user_adoption", "maintained_projects", "real_world_impact"]
  },
  "writing_and_communication": {
    "weight": 0.15,
    "signals": ["technical_blog_posts", "detailed_threads", "documentation_quality", "clarity_of_thought"]
  },
  "community_and_influence": {
    "weight": 0.15,
    "signals": ["peer_recognition", "conference_talks", "mentoring", "ecosystem_contributions"]
  }
}
```

**Step 3: Create the diagnosis file**

`images/cogent-v1/apps/recruiter/files/recruiter/diagnosis.md`:

```markdown
# Diagnosis Guide

How to classify feedback and determine what needs to change.

## Error Types

### 1. Calibration Error
**Pattern:** Candidates match criteria but score too high or too low.
**Evidence:** Feedback says "this person is good but scored low" or "scored high but doesn't seem right."
**Fix:** Adjust weights in `rubric.json`. Can auto-apply.
**Threshold:** 2 instances of same scoring mismatch.

### 2. Criteria Gap
**Pattern:** Good candidates rejected because a dimension is missing, or bad candidates accepted because a dimension is wrong.
**Evidence:** Feedback identifies a trait we're not measuring, or a trait we're measuring wrong.
**Fix:** Patch `criteria.md`. Requires Discord approval.
**Threshold:** 3 similar rejections or acceptances that point to the same missing/wrong criterion.

### 3. Strategy Error
**Pattern:** Not finding the right people, or finding people in the wrong places.
**Evidence:** Consistent feedback that sourced candidates are "not our type" despite matching criteria.
**Fix:** Rewrite `strategy.md` or individual `sourcer/*.md` files. Requires Discord approval.
**Threshold:** 5 rejections from the same source without a single acceptance.

### 4. Process Error
**Pattern:** Fundamental approach is broken — wrong questions, wrong presentation, wrong flow.
**Evidence:** Feedback about how candidates are presented or evaluated, not who they are.
**Fix:** Modify process prompts. Requires Discord approval.
**Threshold:** Direct feedback about process issues, or 3 process-related complaints.

## Escalation Rules
- Always try the cheapest fix first (1 → 2 → 3 → 4)
- Never skip levels — a calibration adjustment might fix what looks like a criteria gap
- Auto-apply only level 1 changes; all others require approval
- Log every change attempt to `evolution.md`, even rejected ones

## What Can Be Auto-Applied
- `rubric.json` weight adjustments (level 1)
- Nothing else — everything else needs human approval via Discord
```

**Step 4: Create the strategy file**

`images/cogent-v1/apps/recruiter/files/recruiter/strategy.md`:

```markdown
# Recruiter Strategy

## Search Priorities
1. GitHub — highest signal-to-noise for builders
2. Twitter/X — catches people sharing in-progress work
3. Web search — conferences, blogs, HN, podcasts
4. Substack — deep thinkers who write consistently

## Presentation Style
- Conversational, not formal. Talk like a colleague sharing an interesting find.
- Lead with what makes this person interesting, not their resume.
- Always end with a specific question that helps refine criteria.
- Keep presentations to 2-3 sentences max. Link to the profile report for details.

## Discovery Cadence
- Run discovery once per day
- Present 2-3 candidates per batch, spaced out
- Don't overwhelm — quality over quantity

## Feedback Interpretation
- "yes" / "interesting" / "tell me more" = positive signal, track what they liked
- "no" / "pass" / "not a fit" = negative signal, ask why if not obvious
- Questions about specific traits = criteria refinement signal
- Silence = don't present more until they engage

## Source Value Tracking
Track acceptance rate per source. Current estimates:
- GitHub: ~30% acceptance rate (highest)
- Twitter: ~15%
- Web: ~10%
- Substack: ~20%

Adjust discovery effort proportionally.
```

**Step 5: Create the evolution log**

`images/cogent-v1/apps/recruiter/files/recruiter/evolution.md`:

```markdown
# Evolution Log

Record of all self-modifications, approved and rejected.

---

*No changes yet — system initialized.*
```

**Step 6: Commit**

```bash
git add images/cogent-v1/apps/recruiter/files/
git commit -m "feat(recruiter): add criteria, rubric, diagnosis, strategy, and evolution files"
```

---

### Task 2: Create sourcer strategy files

**Files:**
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/sourcer/github.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/sourcer/twitter.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/sourcer/web.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/sourcer/substack.md`

**Step 1: Create GitHub sourcer**

`images/cogent-v1/apps/recruiter/files/recruiter/sourcer/github.md`:

```markdown
# GitHub Discovery Strategy

## Search Approach
Search for repos and contributors working on agent frameworks and orchestration.

## Search Queries
Use GitHub search API or web search for GitHub repos matching:
- Topics: `agent-framework`, `llm-orchestration`, `tool-use`, `mcp`, `coding-agent`
- Keywords in README: "multi-agent", "orchestration", "tool calling", "agent runtime"
- Frameworks: repos extending LangChain, CrewAI, AutoGen, Semantic Kernel, or building alternatives

## What to Look For
- **Repo ownership**: People who created and maintain agent-related repos (not just starred them)
- **Commit frequency**: Active in last 3 months, consistent history
- **Code quality signals**: Thoughtful PR reviews, detailed issue discussions, well-structured code
- **Stars/forks**: 100+ stars suggests community validation, but don't over-index on this
- **Original work**: Custom frameworks > wrappers around existing tools

## What to Ignore
- Repos that are just tutorials or "awesome lists"
- Forks with no meaningful modifications
- Repos inactive for 6+ months
- Pure API wrapper projects with no architectural thinking

## Profile Building
For each candidate, capture:
- GitHub handle
- Top 3 relevant repos with descriptions
- Commit frequency (commits/week average over last 3 months)
- Notable PRs or issues (links)
- Languages used
- Any README/docs that show depth of thinking
```

**Step 2: Create Twitter sourcer**

`images/cogent-v1/apps/recruiter/files/recruiter/sourcer/twitter.md`:

```markdown
# Twitter/X Discovery Strategy

## Search Approach
Find accounts posting original technical content about agent development.

## Search Queries
- "building agents" OR "agent framework" OR "tool calling" OR "multi-agent"
- "LLM orchestration" OR "agent reliability" OR "coding agent"
- "MCP server" OR "function calling" OR "agent runtime"

## Signal vs Noise
**Strong signals:**
- Original technical threads explaining how they built something
- Building-in-public posts with code snippets or architecture diagrams
- Engagement from other known builders (not just impressions)
- Discussing failure modes, debugging, or production issues

**Noise to filter out:**
- Pure hype/promotion posts ("AI will change everything")
- Retweets without original commentary
- Tutorial aggregators
- Influencer-style accounts with no technical depth

## Profile Building
For each candidate, capture:
- Twitter handle
- 2-3 example technical threads (links)
- Follower count and follower quality (are other builders following them?)
- Posting frequency on technical topics
- Link to GitHub/personal site if available
```

**Step 3: Create web sourcer**

`images/cogent-v1/apps/recruiter/files/recruiter/sourcer/web.md`:

```markdown
# Web Discovery Strategy

## Search Approach
Find people through conference talks, blog posts, HN discussions, and podcasts.

## Sources
- **Conference talks**: AI Engineer Summit, NeurIPS workshops, local meetup recordings
- **Blog posts**: Personal blogs, Medium, dev.to — search for agent/orchestration topics
- **Hacker News**: Comments and submissions about agent frameworks, LLM tooling
- **Podcasts**: Latent Space, Practical AI, Software Engineering Daily — guest appearances

## Search Queries
- site:news.ycombinator.com "agent framework" OR "orchestration" OR "tool calling"
- "conference talk" + "coding agents" OR "LLM agents" OR "agent orchestration"
- "blog post" + "building agents" OR "multi-agent" OR "agent reliability"

## What to Look For
- Depth of knowledge demonstrated in talks or writing
- Practical experience (talks about real systems, not theory)
- People who show up in multiple contexts (writes AND speaks AND builds)

## Profile Building
For each candidate, capture:
- Name and online handles
- Links to talks, posts, or discussions
- Topics they're known for
- Cross-references to GitHub/Twitter profiles
```

**Step 4: Create Substack sourcer**

`images/cogent-v1/apps/recruiter/files/recruiter/sourcer/substack.md`:

```markdown
# Substack/Newsletter Discovery Strategy

## Search Approach
Find newsletters covering agent development, LLM engineering, and orchestration patterns.

## What to Look For
- **Depth**: Posts that go beyond surface-level summaries into implementation details
- **Consistency**: Regular publishing schedule (at least monthly)
- **Original thinking**: Novel frameworks, patterns, or approaches — not just news aggregation
- **Code examples**: Posts that include real code, architecture diagrams, or system designs

## Signal Newsletters
Look for newsletters that discuss:
- Agent reliability and failure handling
- Multi-agent coordination patterns
- Tool-use design and MCP
- Production deployment of agent systems
- Orchestration framework comparisons

## What to Ignore
- Pure news aggregation (just linking to other articles)
- Infrequent posting (< 1 post/month)
- Surface-level "AI trends" content
- Marketing-focused newsletters

## Profile Building
For each candidate, capture:
- Newsletter name and URL
- Author name and handles
- Subscriber count (if available)
- 2-3 best posts demonstrating depth
- Publishing frequency
- Cross-references to GitHub/Twitter
```

**Step 5: Commit**

```bash
git add images/cogent-v1/apps/recruiter/files/recruiter/sourcer/
git commit -m "feat(recruiter): add sourcer strategy files for github, twitter, web, substack"
```

---

### Task 3: Create process prompt templates

**Files:**
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/prompts/recruiter.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/prompts/discover.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/prompts/present.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/prompts/profile.md`
- Create: `images/cogent-v1/apps/recruiter/files/recruiter/prompts/evolve.md`

**Step 1: Create root recruiter prompt**

`images/cogent-v1/apps/recruiter/files/recruiter/prompts/recruiter.md` (includes: `recruiter/criteria`, `recruiter/strategy`):

```markdown
# Recruiter — Root Orchestrator

You are the recruiter daemon for Softmax. You find people building coding agents and orchestration frameworks.

## Your Job
1. **Schedule discovery** — spawn `recruiter/discover` periodically to find new candidates.
2. **Manage the pool** — track candidate status, deduplicate, maintain `recruiter/candidates/`.
3. **Trigger evolution** — after accumulating feedback, spawn `recruiter/evolve` to improve.
4. **Monitor health** — check that the pipeline is flowing: discovery → screening → presentation.

## Tick Behavior
On each tick:
1. Check if a discovery run is needed (last run > 24h ago, or no candidates in pipeline).
2. Check feedback count since last evolution — if >= 5 new entries, spawn `recruiter/evolve`.
3. Check if `recruiter/present` has candidates to show — if pool is empty, prioritize discovery.

## Spawning Discover
```python
child = procs.spawn("recruiter/discover",
    content="Run a discovery batch. Search all sources, score candidates, write to recruiter/candidates/.",
    capabilities={
        "pool": dir.scope(prefix="recruiter/candidates/", ops=["list", "read", "write", "create"]),
        "sources": dir.scope(prefix="recruiter/sourcer/", ops=["read", "list"]),
        "criteria": file.scope(key="recruiter/criteria", ops=["read"]),
        "rubric": file.scope(key="recruiter/rubric.json", ops=["read"]),
        "me": me,
        "secrets": secrets,
    })
```

## Spawning Evolve
```python
child = procs.spawn("recruiter/evolve",
    content="Analyze recent feedback and propose improvements.",
    capabilities={
        "config": dir.scope(prefix="recruiter/", ops=["list", "read", "write"]),
        "feedback": file.scope(key="recruiter/feedback.jsonl", ops=["read"]),
        "evolution": file.scope(key="recruiter/evolution", ops=["read", "write"]),
        "discord": discord,
        "me": me,
    })
```

## State Tracking
Use `me.process().scratch()` to track:
- Last discovery run timestamp
- Feedback count since last evolution
- Current pipeline health metrics
```

**Step 2: Create discover prompt**

`images/cogent-v1/apps/recruiter/files/recruiter/prompts/discover.md` (includes: `recruiter/criteria`, `recruiter/rubric.json`, `recruiter/sourcer/github`, `recruiter/sourcer/twitter`, `recruiter/sourcer/web`, `recruiter/sourcer/substack`):

```markdown
# Discover — Batch Candidate Discovery

You are a discovery agent for the Softmax recruiter. Your job is to find people building coding agents and orchestration frameworks.

## Process
1. Read the sourcer strategy files to understand where and how to search.
2. Read the criteria and rubric to understand what we're looking for.
3. Search each source systematically.
4. For each potential candidate:
   a. Check if they already exist in `recruiter/candidates/` — skip duplicates.
   b. Score them against the rubric.
   c. Write a candidate record to `recruiter/candidates/{handle}.json`.

## Candidate Record Format
Write each candidate as JSON to `recruiter/candidates/{handle}.json`:
```json
{
  "handle": "github_handle_or_name",
  "name": "Full Name (if known)",
  "status": "discovered",
  "source": "github|twitter|web|substack",
  "discovered_at": "ISO timestamp",
  "scores": {
    "github_activity": 0.0,
    "technical_depth": 0.0,
    "shipping_history": 0.0,
    "writing_and_communication": 0.0,
    "community_and_influence": 0.0
  },
  "total_score": 0.0,
  "summary": "2-3 sentence summary of why this person is interesting",
  "evidence": {
    "repos": [],
    "posts": [],
    "talks": [],
    "other": []
  },
  "profiles": {
    "github": "",
    "twitter": "",
    "website": "",
    "substack": ""
  }
}
```

## Scoring
- Score each dimension 0.0 to 1.0 based on evidence found.
- Compute `total_score` as weighted sum using rubric weights.
- Only score dimensions where you have evidence — leave others at 0.0.
- A candidate needs total_score >= 0.4 to be worth recording.

## Important
- Quality over quantity — 3 well-researched candidates beats 20 shallow ones.
- Include specific evidence (URLs, repo names) for every score.
- Don't score what you can't verify — "probably good" is not evidence.
```

**Step 3: Create present prompt**

`images/cogent-v1/apps/recruiter/files/recruiter/prompts/present.md` (includes: `recruiter/criteria`, `recruiter/strategy`):

```markdown
# Present — Candidate Presentation Daemon

You present screened candidates to the team via Discord and capture feedback.

## Behavior
On each run:
1. Read candidates from `recruiter/candidates/` with status "discovered" or "screened".
2. Pick the top-scored candidate that hasn't been presented yet.
3. Present them conversationally on Discord — not a formal card, just a colleague sharing an interesting find.
4. End with a specific question that helps refine our understanding.
5. Update the candidate's status to "presented".
6. Read any Discord messages for feedback on previously presented candidates.
7. Capture feedback to `recruiter/feedback.jsonl`.

## Presentation Style
Write like you're telling a colleague about someone you found:

> "Found someone interesting — @jsmith has been building a multi-agent orchestration layer on top of LangGraph. 800 stars, active for 6 months, writes detailed Substack posts about agent reliability patterns. Their approach is opinionated about synchronous tool calls vs async — do we care about that architectural stance, or just that they're deep in the orchestration space?"

NOT like a recruiter:
> "Candidate Profile: John Smith. Skills: Python, LangChain. Experience: 5 years."

## Feedback Capture
When you receive Discord messages, parse them for intent:
- **Approval**: "yes", "interesting", "tell me more", "profile them" → status = "approved"
- **Rejection**: "no", "pass", "not a fit" → status = "rejected"
- **Clarification**: questions about criteria or approach → capture as criteria feedback
- **Preference**: "I like X about them" or "I don't care about Y" → capture as preference signal

Write feedback to `recruiter/feedback.jsonl` as one JSON object per line:
```json
{"timestamp": "ISO", "candidate": "handle", "type": "approval|rejection|clarification|preference", "content": "raw feedback text", "source": "discord"}
```

## Pacing
- Present at most 2-3 candidates per run.
- If no feedback on previous candidates, don't present more — ask if they've seen the last batch.
```

**Step 4: Create profile prompt**

`images/cogent-v1/apps/recruiter/files/recruiter/prompts/profile.md`:

```markdown
# Profile — Deep-Dive Report Generator

You generate a detailed HTML report for a candidate that passed screening.

## Input
You receive the candidate handle via your spawn channel. Read their record from `recruiter/candidates/{handle}.json`.

## Process
1. Read the candidate's JSON record for existing evidence.
2. Deep-dive into each piece of evidence — read repos, posts, talks.
3. Generate a standalone HTML report.
4. Write the report to `recruiter/candidates/{handle}.html`.
5. Update the candidate JSON status to "profiled".

## HTML Report Format
Generate a self-contained HTML file (no external dependencies) that covers:

- **Header**: Name, handles, one-line summary
- **Why This Person**: 2-3 paragraphs on what makes them interesting for Softmax
- **Technical Work**: Their most notable projects, with analysis of architecture and quality
- **Writing & Communication**: Summary of their best writing with key insights
- **Evidence**: Links to repos, posts, talks, with brief annotations
- **Scores**: Visual representation of rubric scores
- **Concerns**: Any red flags or gaps in evidence
- **Recommended Next Steps**: What to do if we want to engage

Style the HTML simply — clean typography, good spacing, readable on desktop. Use inline CSS.
```

**Step 5: Create evolve prompt**

`images/cogent-v1/apps/recruiter/files/recruiter/prompts/evolve.md` (includes: `recruiter/diagnosis`, `recruiter/criteria`, `recruiter/rubric.json`, `recruiter/strategy`):

```markdown
# Evolve — Self-Improvement Engine

You analyze feedback and propose improvements to the recruiter system.

## Process
1. Read `recruiter/feedback.jsonl` for recent feedback entries.
2. Read `recruiter/diagnosis` for the classification framework.
3. Classify each piece of feedback into an error type (calibration, criteria, strategy, process).
4. Determine if there's a pattern that warrants a change.
5. If yes, propose the change with reasoning.
6. For auto-applicable changes (calibration only): apply and log to `recruiter/evolution`.
7. For all other changes: post approval request to Discord and wait for response.

## Proposing Changes
When proposing a change on Discord, be conversational:

> "After 3 rejections of academics with no shipping history, I think 'has shipped production agent systems' should be an explicit criterion. This is currently implied but not scored directly. Approve?"

Include:
- What feedback triggered this
- What specifically would change
- Why this is the right level of fix (not over-escalating)

## Applying Changes
When a change is approved (or auto-applied):
1. Make the edit to the target file (criteria.md, rubric.json, strategy.md, sourcer/*.md, or diagnosis.md).
2. Append to `recruiter/evolution`:
   ```
   ## YYYY-MM-DD — [Error Type] — [Auto/Approved]
   **Trigger:** [What feedback caused this]
   **Change:** [What was modified]
   **Reasoning:** [Why this fix, why this level]
   ```
3. The next discovery/presentation run will pick up the changes automatically.

## Rules
- Always try the cheapest fix first (calibration → criteria → strategy → process).
- Never skip escalation levels.
- Be transparent about what you're changing and why.
- If you're unsure, ask on Discord rather than guessing.
```

**Step 6: Commit**

```bash
git add images/cogent-v1/apps/recruiter/files/recruiter/prompts/
git commit -m "feat(recruiter): add process prompt templates for all five processes"
```

---

### Task 4: Create the init script (processes, channels, capability bindings)

**Files:**
- Create: `images/cogent-v1/apps/recruiter/init/processes.py`

**Step 1: Write the init script**

`images/cogent-v1/apps/recruiter/init/processes.py`:

```python
# Recruiter app — five processes in a tree.
#
# recruiter (daemon, root) — orchestrator
# recruiter/discover (one-shot, spawned) — batch discovery
# recruiter/present (daemon) — drip-feed candidates to Discord
# recruiter/profile (one-shot, spawned) — deep-dive HTML reports
# recruiter/evolve (one-shot, spawned) — self-improvement

# -- Channels --

add_channel("recruiter:feedback", schema=None, channel_type="named")

# -- Root orchestrator --
# Daemon that schedules discovery, monitors pipeline, triggers evolution.
# Wakes on system ticks (hourly) and on feedback channel messages.

add_process(
    "recruiter",
    mode="daemon",
    code_key="recruiter/prompts/recruiter",
    runner="lambda",
    priority=5.0,
    capabilities=["me", "procs", "dir", "file", "discord", "channels", "secrets"],
    handlers=["system:tick:hour", "recruiter:feedback"],
)

# -- Present daemon --
# Wakes on system ticks (hourly) and presents candidates to Discord.

add_process(
    "recruiter/present",
    mode="daemon",
    code_key="recruiter/prompts/present",
    runner="lambda",
    priority=3.0,
    capabilities=["me", "dir", "file", "discord", "channels"],
    handlers=["system:tick:hour"],
)
```

Note: `recruiter/discover`, `recruiter/profile`, and `recruiter/evolve` are NOT defined in init — they are spawned dynamically by the root `recruiter` process using `procs.spawn()` with scoped capabilities. Their prompt templates exist as files that the root process references via `code_key` when spawning.

**Step 2: Verify the init script loads correctly**

```bash
cd /Users/daveey/code/cogents/cogents.3
python -c "
from cogos.image.spec import load_image
from pathlib import Path
spec = load_image(Path('images/cogent-v1/apps/recruiter'))
print(f'Processes: {len(spec.processes)}')
for p in spec.processes:
    print(f'  {p[\"name\"]}: mode={p[\"mode\"]}, caps={p[\"capabilities\"]}')
print(f'Channels: {len(spec.channels)}')
for c in spec.channels:
    print(f'  {c[\"name\"]}')
print(f'Files: {len(spec.files)}')
for k in sorted(spec.files.keys()):
    print(f'  {k}')
"
```

Expected: 2 processes, 1 channel, all files from `files/` dir loaded.

**Step 3: Commit**

```bash
git add images/cogent-v1/apps/recruiter/init/
git commit -m "feat(recruiter): add init script with process and channel definitions"
```

---

### Task 5: Wire the recruiter app into the main image

**Files:**
- Modify: `images/cogent-v1/init/processes.py`

**Step 1: Check how the image loader works for apps**

The image loader (`load_image`) only processes `init/` and `files/` at the top level of the image dir. The recruiter app is in `apps/recruiter/` — we need to either:
- (a) Load it as a sub-image, or
- (b) Add a line to the main init that loads the sub-init.

Check how `load_image` handles subdirectories — it walks `init/*.py` at the image root, not recursively. So we need to import the app's init explicitly.

**Step 2: Add app loading to main image init**

Add to `images/cogent-v1/init/processes.py` (at the end):

```python
# -- Apps --
# Load app-specific process definitions.
# Apps are self-contained sub-images under apps/<name>/.
# Their init scripts use the same add_* functions.

import os
from pathlib import Path

_image_dir = Path(os.path.dirname(__file__)).parent
_apps_dir = _image_dir / "apps"
if _apps_dir.is_dir():
    for app_dir in sorted(_apps_dir.iterdir()):
        app_init = app_dir / "init"
        if app_init.is_dir():
            for py in sorted(app_init.glob("*.py")):
                if not py.name.startswith("_"):
                    exec(compile(py.read_text(), str(py), "exec"))
```

Wait — the init scripts are exec'd with a specific builtins dict. The `add_process` etc. functions are in that scope. So we need the exec'd app init to inherit them. Since the main init is itself exec'd with those builtins, and we exec the app init without specifying globals, it should inherit. But to be safe, we should pass the current globals.

Actually, looking at `spec.py` line 84, each init file gets `builtins.copy()` as its globals. So we can't just exec from within — the app init wouldn't see `add_process`. We need to modify the image loader or use a different approach.

**Better approach:** Modify `load_image` in `spec.py` to also walk `apps/*/init/*.py`.

**Step 2 (revised): Modify load_image to support apps**

Modify `src/cogos/image/spec.py` — after the main `init/` loop, add an `apps/` loop:

```python
    # Load app init scripts
    apps_dir = image_dir / "apps"
    if apps_dir.is_dir():
        for app_dir in sorted(apps_dir.iterdir()):
            app_init = app_dir / "init"
            if app_init.is_dir():
                for py in sorted(app_init.glob("*.py")):
                    if py.name.startswith("_"):
                        continue
                    exec(compile(py.read_text(), str(py), "exec"), builtins.copy())

    # Load app files
    if apps_dir.is_dir():
        for app_dir in sorted(apps_dir.iterdir()):
            app_files = app_dir / "files"
            if app_files.is_dir():
                for f in sorted(app_files.rglob("*")):
                    if f.is_file():
                        key = str(f.relative_to(app_files))
                        spec.files[key] = f.read_text()
```

**Step 3: Run the full image load to verify**

```bash
cd /Users/daveey/code/cogents/cogents.3
python -c "
from cogos.image.spec import load_image
from pathlib import Path
spec = load_image(Path('images/cogent-v1'))
print(f'Total processes: {len(spec.processes)}')
for p in spec.processes:
    print(f'  {p[\"name\"]}: mode={p[\"mode\"]}')
print(f'Total files: {len(spec.files)}')
recruiter_files = [k for k in spec.files if k.startswith('recruiter/')]
print(f'Recruiter files: {len(recruiter_files)}')
for k in sorted(recruiter_files):
    print(f'  {k}')
"
```

Expected: All existing processes + 2 recruiter processes. All recruiter files loaded.

**Step 4: Commit**

```bash
git add src/cogos/image/spec.py
git commit -m "feat(image): support apps/ subdirectory for modular image composition"
```

---

### Task 6: Add file includes for context engine wiring

**Files:**
- Modify: `images/cogent-v1/apps/recruiter/init/processes.py` (no change needed if code_key works)

The context engine resolves includes from the `File.includes` field. Files created via `load_image` use `FileStore.upsert()` which accepts includes. But `spec.files` is just `dict[str, str]` (key → content) — it doesn't carry includes metadata.

We need to extend the file loading to support includes. Two options:
- (a) Add frontmatter parsing to detect includes in file content
- (b) Accept that includes must be set up separately (via init script or file write with includes)

The simplest approach: use `add_file()` calls in the init script for files that need includes, and let the `files/` directory handle files without includes.

**Step 1: Add `add_file` to the image spec**

Modify `src/cogos/image/spec.py` to add an `add_file` function:

In the `load_image` function, after the existing builtins, add:

```python
    def add_file(key, *, content="", includes=None, source="image"):
        spec.files[key] = content
        if includes:
            if not hasattr(spec, '_file_includes'):
                spec._file_includes = {}
            spec._file_includes[key] = includes
```

Also add `_file_includes` to `ImageSpec`:

```python
@dataclass
class ImageSpec:
    capabilities: list[dict] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    processes: list[dict] = field(default_factory=list)
    cron_rules: list[dict] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    file_includes: dict[str, list[str]] = field(default_factory=dict)
    schemas: list[dict] = field(default_factory=list)
    channels: list[dict] = field(default_factory=list)
```

Update the `add_file` function:
```python
    def add_file(key, *, content="", includes=None, source="image"):
        spec.files[key] = content
        if includes:
            spec.file_includes[key] = includes
```

And add `"add_file": add_file` to the builtins dict.

**Step 2: Update apply_image to pass includes**

In `src/cogos/image/apply.py`, modify the files section:

```python
    # 4. Files
    fs = FileStore(repo)
    for key, content in spec.files.items():
        includes = spec.file_includes.get(key)
        fs.upsert(key, content, source="image", includes=includes)
        counts["files"] += 1
```

**Step 3: Use add_file in the recruiter init for files that need includes**

Update `images/cogent-v1/apps/recruiter/init/processes.py` to declare includes for prompt files:

```python
# Declare includes for prompt templates that need context injection.
# The actual file content comes from the files/ directory — add_file with
# empty content just sets up the includes metadata. If the file also exists
# in files/, the content from files/ will be used (loaded after init).

# Actually, since files/ content overwrites spec.files[key], and add_file
# sets both content and includes, we should NOT have these files in files/
# if we're using add_file. Instead, read the content in add_file.
#
# Simplest: just declare includes via add_file with empty content.
# The files/ dir content will overwrite the empty content but the includes
# will persist in spec.file_includes.
```

Hmm, this is getting complicated. Let me simplify.

**Revised approach:** Just add the includes in the init script. The `files/` directory provides the content. The init `add_file` calls just set up includes metadata (content will be overwritten by the files/ loader, but includes are stored separately in `file_includes`).

Add to `images/cogent-v1/apps/recruiter/init/processes.py` at the top:

```python
# -- Context engine wiring (includes) --
# These set up which files are injected into each prompt template.

add_file("recruiter/prompts/recruiter", content="", includes=[
    "recruiter/criteria",
    "recruiter/strategy",
])

add_file("recruiter/prompts/discover", content="", includes=[
    "recruiter/criteria",
    "recruiter/rubric.json",
    "recruiter/sourcer/github",
    "recruiter/sourcer/twitter",
    "recruiter/sourcer/web",
    "recruiter/sourcer/substack",
])

add_file("recruiter/prompts/present", content="", includes=[
    "recruiter/criteria",
    "recruiter/strategy",
])

add_file("recruiter/prompts/evolve", content="", includes=[
    "recruiter/diagnosis",
    "recruiter/criteria",
    "recruiter/rubric.json",
    "recruiter/strategy",
])
```

**Step 4: Commit**

```bash
git add src/cogos/image/spec.py src/cogos/image/apply.py images/cogent-v1/apps/recruiter/init/processes.py
git commit -m "feat(image): add add_file() for declaring file includes, wire recruiter prompts"
```

---

### Task 7: Write tests

**Files:**
- Create: `tests/test_recruiter_image.py`

**Step 1: Write image loading test**

```python
"""Tests for the recruiter app image loading."""

from pathlib import Path

from cogos.image.spec import load_image


def test_recruiter_app_loads():
    """The recruiter app should load as part of the cogent-v1 image."""
    spec = load_image(Path("images/cogent-v1"))

    # Check recruiter processes exist
    proc_names = {p["name"] for p in spec.processes}
    assert "recruiter" in proc_names
    assert "recruiter/present" in proc_names

    # Check recruiter process config
    recruiter = next(p for p in spec.processes if p["name"] == "recruiter")
    assert recruiter["mode"] == "daemon"
    assert "procs" in recruiter["capabilities"]
    assert "discord" in recruiter["capabilities"]

    present = next(p for p in spec.processes if p["name"] == "recruiter/present")
    assert present["mode"] == "daemon"
    assert "discord" in present["capabilities"]


def test_recruiter_files_loaded():
    """All recruiter files should be loaded into the image spec."""
    spec = load_image(Path("images/cogent-v1"))

    recruiter_files = {k for k in spec.files if k.startswith("recruiter/")}

    # Core config files
    assert "recruiter/criteria" in recruiter_files or "recruiter/criteria.md" in recruiter_files
    assert "recruiter/strategy" in recruiter_files or "recruiter/strategy.md" in recruiter_files

    # Sourcer files
    sourcer_files = {k for k in recruiter_files if "sourcer/" in k}
    assert len(sourcer_files) >= 4  # github, twitter, web, substack

    # Prompt files
    prompt_files = {k for k in recruiter_files if "prompts/" in k}
    assert len(prompt_files) >= 5  # recruiter, discover, present, profile, evolve


def test_recruiter_file_includes():
    """Prompt files should have correct includes for context engine."""
    spec = load_image(Path("images/cogent-v1"))

    # The recruiter prompt should include criteria and strategy
    recruiter_includes = spec.file_includes.get("recruiter/prompts/recruiter", [])
    assert "recruiter/criteria" in recruiter_includes
    assert "recruiter/strategy" in recruiter_includes

    # The discover prompt should include criteria, rubric, and all sourcers
    discover_includes = spec.file_includes.get("recruiter/prompts/discover", [])
    assert "recruiter/criteria" in discover_includes
    assert "recruiter/rubric.json" in discover_includes


def test_recruiter_channel():
    """The feedback channel should be defined."""
    spec = load_image(Path("images/cogent-v1"))
    channel_names = {c["name"] for c in spec.channels}
    assert "recruiter:feedback" in channel_names


def test_apps_dont_affect_existing_processes():
    """Loading apps should not remove or modify existing processes."""
    spec = load_image(Path("images/cogent-v1"))
    proc_names = {p["name"] for p in spec.processes}
    assert "scheduler" in proc_names
    assert "discord-handle-message" in proc_names
```

**Step 2: Run the tests**

```bash
cd /Users/daveey/code/cogents/cogents.3
python -m pytest tests/test_recruiter_image.py -v
```

Expected: All pass.

**Step 3: Commit**

```bash
git add tests/test_recruiter_image.py
git commit -m "test(recruiter): add image loading and wiring tests"
```

---

### Task 8: Final verification and cleanup

**Step 1: Run the full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

**Step 2: Verify the design.md is fully covered**

Review checklist against design.md:
- [x] Five processes (recruiter, discover, present, profile, evolve)
- [x] File structure (criteria, rubric, diagnosis, strategy, evolution, sourcer/*, candidates/)
- [x] Context engine wiring (includes)
- [x] Self-improvement engine (diagnosis.md, escalation levels)
- [x] Discord integration (present + evolve use discord capability)
- [ ] Dashboard (out of scope — needs frontend work)
- [ ] Asana integration (out of scope — capability doesn't exist yet)
- [x] Capabilities scoped per process

**Step 3: Commit all remaining changes**

```bash
git add -A
git commit -m "feat(recruiter): complete recruiter app implementation"
```
