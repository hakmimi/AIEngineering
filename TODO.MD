https://www.seangoedecke.com/how-i-use-llms-in-2026/?utm_source=tldrnewsletter


https://www.bing.com/search?q=codex+cli+windows&qs=SS&pq=codex+cli+&sc=12-10&cvid=E561B2811A7D4FCAA89A3789959C34EF&FORM=QBRE&sp=1&ghc=1&lq=0

https://github.blog/changelog/2026-05-14-github-copilot-app-is-now-available-in-technical-preview/

https://huggingface.co/datasets/GloriaaaM/LLM-Agent-Harness-Survey

https://arxiv.org/pdf/2602.12670
Tier 1 — MUST READ

These are foundational for modern agent engineering.

1. ReAct: Synergizing Reasoning and Acting in Language Models

This is probably the single most important agent paper to understand first.

Why it matters:

introduced the “reason + act” loop
foundation of tool-calling agents
influenced LangChain, LangGraph, Claude Code, Cursor, etc.

Core idea:

Thought → Action → Observation → Thought → ...

Without understanding ReAct, modern agents feel magical/random.

After reading it, many systems suddenly become understandable.

For you specifically:
this connects directly to:

routing
tool calling
iterative workflows
repair loops
execution reasoning

which you are already learning.

2. Reflexion: Language Agents with Verbal Reinforcement Learning

This paper introduced:

self-reflection
memory
retry improvement loops
verbal feedback

This is foundational for:

self-correcting agents
retry systems
execution improvement
memory-aware workflows

VERY important for understanding:

why agents retry
why trajectories matter
why logging matters
why evaluations matter

This paper is closer to:

“How do we make agents improve while running?”

rather than just reasoning once.

3. Voyager

This is probably the most directly connected paper to “skills.”

Voyager introduced:

skill libraries
reusable procedural memory
accumulating capabilities over time

Core insight:
agents become more capable when they:

store successful procedures
retrieve them later
compose them

This is VERY aligned with the SkillsBench conclusions.

Tier 2 — Important After Tier 1
4. Anthropic MCP (Model Context Protocol)

Referenced in the paper:

“Introducing the model context protocol.”

This is extremely important practically.

Read:

Model Context Protocol (MCP)

This is becoming:

the “USB-C” of AI tools
standardization for agent tooling

VERY relevant to your path.

This connects to:

tools
context injection
external systems
terminal agents
IDE integration
5. Anthropic — “Equipping Agents for the Real World with Agent Skills”

This is likely one of the conceptual inspirations for SkillsBench itself.

Read:

Agent Skills

This is more engineering-oriented than academic.

Probably the most directly practical article for:

understanding modern coding agents
procedural memory
operational workflows
skill systems
Tier 3 — Useful Later

These are valuable but not first-priority for your current stage.

6. WebArena

Referenced in SkillsBench.

Important for:

browser agents
web interaction
benchmarking autonomous agents

Useful later when you move into:

browser automation
computer-use agents
7. BigCodeBench

Important for:

code-generation evaluation
benchmarking coding agents

But less foundational conceptually.