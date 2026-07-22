"""Setup wizard helpers: sample OHLCV feeds + NL → instantiate_mission routing."""

from __future__ import annotations

from atlas.planner.planner import Intent, Planner
from atlas.trading.sample_feed import bars_to_json_bytes, register_market_feed, sample_bars


class _MemAssets:
    def __init__(self):
        self.calls = []
        self.by_name = {}

    def register(self, kind, name, data, *, source_uri=None, content_type=None, metadata=None):
        self.calls.append((kind, name, data, content_type, metadata))
        row = {
            "id": f"a-{len(self.calls)}",
            "kind": kind,
            "name": name,
            "current_version": 1,
            "metadata": metadata or {},
        }
        self.by_name[(kind, name)] = row
        return {"asset": row, "version": {"version": 1, "asset_id": row["id"]}}


def test_sample_bars_shape():
    bars = sample_bars(n=10, start=50.0)
    assert len(bars) == 10
    assert bars[0]["close"] > 0
    assert set(bars[0]) >= {"t", "open", "high", "low", "close", "volume"}
    assert bars_to_json_bytes(bars).startswith(b"[")


def test_register_market_feed_generates_sample():
    assets = _MemAssets()
    info = register_market_feed(assets, name="demo-feed", symbol="DEMO", generate_sample=True)
    assert info["name"] == "demo-feed"
    assert info["generated_sample"] is True
    kind, name, data, ctype, meta = assets.calls[0]
    assert kind == "market_data" and name == "demo-feed"
    assert meta["filename"].endswith(".json")
    assert meta["symbol"] == "DEMO"
    assert data.startswith(b"[")
    assert ctype == "application/json"


def test_planner_routes_start_paper_trading():
    plan = Planner().plan("start paper trading with 10000 on AAA")
    assert plan.intent == Intent.INSTANTIATE_MISSION
    args = plan.steps[0].args
    assert args["template"] == "paper_trading"
    assert args["config_overrides"]["starting_cash"] == 10000.0
    assert args["config_overrides"]["_auto_sample_feed"] is True
    assert args["config_overrides"]["instruments"][0]["symbol"] == "AAA"


def test_planner_routes_register_market_data():
    plan = Planner().plan("register sample market data for symbol MSFT")
    assert plan.intent == Intent.REGISTER_MARKET_DATA
    assert plan.steps[0].args["symbol"] == "MSFT"
    assert plan.steps[0].args["generate_sample"] is True


def test_assistant_instantiate_mission_auto_registers_feed():
    from types import SimpleNamespace

    from atlas.services.assistant_service import AssistantService
    from atlas.planner.planner import Planner
    from atlas.execution.executor import ToolExecutor
    from atlas.kernel.tools import ToolRegistry

    class FakeTemplatesSvc:
        def __init__(self):
            self.calls = []

        def instantiate(self, template, **kwargs):
            self.calls.append((template, kwargs))
            return {
                "mission": SimpleNamespace(id="m-1", title=kwargs.get("title") or template),
                "config": {},
                "workers": [],
            }

    class FakeConv:
        def ensure_session(self, sid=None):
            return SimpleNamespace(id="s1")

        def add_user_message(self, *a, **k):
            return None

        def add_assistant_message(self, *a, **k):
            return None

        def build_context(self, *a, **k):
            return None

    class FakeLLM:
        def for_role(self, role):
            return self

        def chat(self, messages, **options):
            return SimpleNamespace(text="ok")

    templates = FakeTemplatesSvc()
    assets = _MemAssets()
    svc = AssistantService(
        FakeConv(),
        Planner(),
        ToolExecutor(ToolRegistry(), retry_base=0.0),
        llm=FakeLLM(),
        templates=templates,
        assets=assets,
    )
    outcome = svc.run_step(
        Intent.INSTANTIATE_MISSION,
        {
            "template": "paper_trading",
            "title": "Learn",
            "config_overrides": {
                "starting_cash": 10000,
                "instruments": [{"symbol": "AAA", "asset": ""}],
                "_auto_sample_feed": True,
            },
        },
    )
    assert not outcome.blocked
    assert "m-1" in outcome.answer
    assert templates.calls[0][0] == "paper_trading"
    overrides = templates.calls[0][1]["config_overrides"]
    assert overrides["instruments"][0]["asset"] == "aaa-feed"
    assert assets.calls[0][1] == "aaa-feed"
