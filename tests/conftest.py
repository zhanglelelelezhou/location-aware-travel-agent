import os

# Unit tests must remain deterministic and must never call a paid provider from .env.
os.environ["AGENT_PLANNER"] = "rule"
os.environ["AGENT_PROVIDER"] = "mock"
