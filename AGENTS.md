# AGENTS.md

## What this repo is

BuffStack: an OpenHands SDK agent that turns a short description into a running
full-stack app (Flask JSON API + HTML dashboard). Design follows the
single-loop root-agent architecture of `CodebuffAI/freebuff`.

## Layout

- `buffstack/agent.py` – builds the SDK agent (model + tool set + prompt)
- `buffstack/config.py` – env/flag config; inside an OpenHands runtime the
  managed LLM key is fetched from `OH_LLM_API_KEY_REFRESH_URL`
- `buffstack/templates.py` – the Flask app / dashboard templates the tools emit
- `buffstack/tools/` – `scaffold`, `add_endpoint`, `create_dashboard`,
  `run_server`, `validate` (custom SDK tools)
- `tests/` – drives the tools through their real executors and the generated
  Flask app through its test client

## Commands

```bash
pip install -e ".[dev]"     # openhands-sdk, openhands-tools, pytest
OPENHANDS_SUPPRESS_BANNER=1 python3 -m pytest -q
python3 -m compileall -q buffstack
```

Run the agent:

```bash
buffstack "Build an expense tracker with title, amount, category. Port 12000."
```

## Notes

- `workspace/` holds apps the agent generated; it is git-ignored.
- Generated apps use in-memory storage, so data is lost on restart.
- In this sandbox `python3` resolves to `/usr/local/bin/python3` (3.13);
  `pip3 install --user` lands in `/home/openhands/.local/lib/python3.13/site-packages`.
