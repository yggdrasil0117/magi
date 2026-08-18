# MAGI

MAGI is a decision-support system inspired by Evangelion's three-perspective computer. It runs three isolated agents, preserves dissent, and applies deterministic arbitration rules. The first release is advisory only: it analyzes and records decisions but cannot modify external systems.

M1 includes the framework-independent decision domain, lifecycle state machine, first-round router, deterministic arbiter, and versioned protocol fixtures.

M2a adds a LangGraph Graph API builder, JSON-serializable checkpoint state, confirmation interrupt, parallel first and review branches, scripted perspective runner, and sanitized public-event projection. The executable LangGraph interrupt/resume integration path is verified with LangGraph 1.2.11.

M2b-1 adds a LangChain/OpenAI structured-output runner. Each LangGraph perspective node loads the shared MAGI protocol and exactly one perspective skill, receives an isolated prompt, and returns a ballot draft. Application code seals authoritative identity, round, decision, option, and evidence boundaries.

## Local setup (Windows PowerShell)

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install langgraph langchain langchain-openai python-dotenv -i https://mirrors.aliyun.com/pypi/simple/
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

## Confirmed M0 scope

- Melchior evaluates evidence, logic, feasibility, and uncertainty.
- Balthasar evaluates human impact, safety, privacy, and reversibility.
- Casper evaluates strategy, alternatives, and long-term effects.
- The first ballot is secret and parallel.
- A bounded cross-review may change each ballot once.
- Python code, not a fourth judging model, produces the result.
- Web, terminal TUI, and CLI clients share one API and one DecisionView.
- All tools are read-only in the first release.

## Repository map

~~~text
apps/          API, Web, TUI, and CLI client boundaries
src/magi/      Decision domain and service modules
skills/        Shared protocol and three perspective skills
docs/          Frozen M0 architecture and contracts
tests/         Unit, integration, evaluation, and fixture areas
~~~

Start with docs/architecture.md, docs/m1-implementation.md, and docs/m2a-implementation.md.
The current model-adapter increment is documented in docs/m2b1-implementation.md.
