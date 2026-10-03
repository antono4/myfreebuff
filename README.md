# BuffStack

An AI agent that turns a short description into a running full-stack application:
a JSON API backend and an HTML dashboard that talks to it.

Built on the [OpenHands SDK](https://docs.openhands.dev/sdk). The agent design
follows the architecture of [CodebuffAI/freebuff](https://github.com/CodebuffAI/freebuff):
a single-loop root agent with an explicit tool set and a system prompt that
carries the engineering discipline. BuffStack adds a full-stack tool set so the
agent can scaffold, extend, serve, and verify the app it builds.

## What it produces

```
habit_tracker/
  app.py                  Flask app: JSON API + serves the dashboard
  requirements.txt
  templates/dashboard.html
  static/dashboard.js     fetch() against the JSON API
  static/dashboard.css
  tests/test_api.py       pytest smoke tests
  run.sh                  venv + install + serve
```

The dashboard is a real interface, not a mock-up: it fetches the collection
endpoint on load and renders the rows into the DOM, with an add form, a filter,
delete buttons, a connection status pill, and record/last-refresh KPIs.

## Install

```bash
pip install -e .
```

## Use

```bash
# One-shot: describe the app
buffstack "Build an expense tracker with fields title, amount, category. Use port 12000."

# Or an interactive session
buffstack
```

Then open the dashboard at `http://localhost:<port>`.

### LLM configuration

BuffStack reads these environment variables:

| Variable | Default | Notes |
|---|---|---|
| `LLM_MODEL` | `openai/deepseek-v4.1-flash` | Any model the OpenHands SDK supports |
| `LLM_BASE_URL` | the managed OpenHands proxy | |
| `LLM_API_KEY` | – | Required unless running inside an OpenHands runtime |

Inside an OpenHands runtime the managed key is fetched automatically from
`OH_LLM_API_KEY_REFRESH_URL`, so no key needs to be supplied.

CLI flags `--model`, `--base-url`, `--api-key`, `--port`, `--workspace`, and
`--max-iterations` override the environment.

## The tools

| Tool | What it does |
|---|---|
| `scaffold_fullstack_app` | Writes the project skeleton for an entity you describe |
| `add_api_endpoint` | Inserts a JSON route into `app.py`, keeping it valid Python |
| `create_dashboard` | Regenerates the dashboard HTML and its data bindings |
| `run_dev_server` | Installs deps, starts the server detached, waits for `/health` |
| `validate_fullstack_app` | Proves the app works: files, routes, live `fetch()`, pytest, HTTP probes |

Plus the SDK's terminal, file editor, and task tracker tools.

`scaffold_fullstack_app` generates the dashboard from the entity's fields, so the
table columns and the create form always match the API payload. The other tools
change the generated code afterwards.

## Programmatic use

```python
from buffstack import build_agent, default_config
from openhands.sdk import Conversation

config = default_config(model="openai/deepseek-v4.1-flash", port=12000)
agent = build_agent(config)
conversation = Conversation(agent=agent, workspace="./workspace")

conversation.send_message("Build a habit tracker with name, frequency, target_per_week.")
conversation.run()
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The suite drives the tools through their real executors: it scaffolds a project
in a tmp directory and exercises the generated Flask app with its own test client.
