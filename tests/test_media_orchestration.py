"""Media orchestration gate (MEDIA_ORCHESTRATION_PLAN · MO.0 / MO.1 / MO.2 / MO.4).

Acceptance:
  - Learn-from-video / bare YouTube URL → Intent.MEDIA_LEARN, description Learn from media
  - Caption-only phrasing → youtube_transcript
  - media.learn invokes MediaLearnOrchestrator (permanent MO.0 regression)
  - robots captions → automatic strategies continue (journal length > 1 family)
  - interactive recovery → blocked + suggestions; no fabricated Knowledge
"""

from __future__ import annotations

from atlas.ingestion.media_learn import MediaLearnOrchestrator
from atlas.planner import Intent, Planner
from atlas.transcripts.acquisition import (
    REASON_ROBOTS_DISALLOWED,
    STRATEGY_OFFICIAL_CAPTIONS_API,
    STRATEGY_UPLOAD_LOCAL_MEDIA,
    STRATEGY_UPLOAD_TRANSCRIPT,
)


def test_planner_learn_from_video_is_media_learn():
    plan = Planner().plan(
        "Learn from this video https://youtu.be/abcdefghijk"
    )
    assert plan.intent == Intent.MEDIA_LEARN
    assert plan.steps[0].capability == "media_learn"
    assert plan.steps[0].description == "Learn from media."
    assert "youtu.be/abcdefghijk" in plan.steps[0].args["source"]


def test_planner_bare_youtube_url_is_media_learn():
    plan = Planner().plan("https://www.youtube.com/watch?v=abcdefghijk")
    assert plan.intent == Intent.MEDIA_LEARN
    assert plan.steps[0].description == "Learn from media."


def test_planner_caption_only_stays_youtube_transcript():
    plan = Planner().plan("get the transcript of https://youtu.be/abcdefghijk")
    assert plan.intent == Intent.YOUTUBE_TRANSCRIPT
    assert plan.steps[0].description == "Fetch a YouTube video transcript."


def test_mo0_orchestrator_invoked_on_media_learn():
    """Permanent regression: media.learn path must call the orchestrator (A5)."""

    def caption_fetch(video: str):
        return {
            "outcome": "blocked",
            "reason_code": REASON_ROBOTS_DISALLOWED,
            "reason": "robots.txt disallows",
            "text": "",
            "bytes_read": 0,
            "acquisition": {
                "strategies_tried": [
                    {
                        "strategy": "youtube_watch_page",
                        "outcome": "blocked",
                        "reason_code": REASON_ROBOTS_DISALLOWED,
                        "reason": "robots",
                        "bytes_read": 0,
                    }
                ]
            },
        }

    class FakeMedia:
        def ingest_url(self, url, **kw):
            return {
                "outcome": "blocked",
                "text": "",
                "fetch": {
                    "outcome": "blocked",
                    "reason_code": "policy_requires_operator_asset",
                    "reason": "need operator asset",
                    "strategies_tried": [
                        {
                            "name": "youtube_media",
                            "outcome": "blocked",
                            "reason_code": "policy_requires_operator_asset",
                            "bytes_read": 0,
                        }
                    ],
                },
                "speech": None,
                "ingest": None,
            }

        def ingest_file(self, path, **kw):
            raise AssertionError("unexpected ingest_file")

    orch = MediaLearnOrchestrator(
        caption_fetch=caption_fetch,
        media_ingestor=FakeMedia(),
        knowledge=None,
        speech_status=lambda: "disabled",
    )
    result = orch.learn("https://youtu.be/abcdefghijk", to_knowledge=True)
    assert orch.calls, "MediaLearnOrchestrator.learn was not invoked"
    assert result["orchestrator"] == "media.learn"
    strategies = {s["strategy"] for s in result["strategies"]}
    assert "youtube_watch_page" in strategies or "youtube_caption_tracks" in strategies
    assert STRATEGY_OFFICIAL_CAPTIONS_API in strategies or any(
        "official" in s for s in strategies
    )
    assert "youtube_media" in strategies or "source_fetch" in strategies or "speech_to_text" in strategies
    assert len(result["strategies"]) >= 3
    assert result["interactive_recovery"] is True
    assert result["outcome"] == "waiting"
    assert STRATEGY_UPLOAD_TRANSCRIPT in result["suggested_next_strategies"]
    assert STRATEGY_UPLOAD_LOCAL_MEDIA in result["suggested_next_strategies"]
    assert result.get("ingest") is None
    names = {s["strategy"] for s in result["strategies"]}
    assert "speech_to_text" not in names  # MO.5: no fake speech without Asset
    assert "media_asset" in names or "youtube_media" in names


def test_mo4_assistant_media_learn_blocks_with_journal():
    """Job/Assistant path: one media.learn step journals strategies and blocks."""
    from atlas.conversation import ConversationService
    from atlas.execution import ToolExecutor
    from atlas.kernel.tools import ToolRegistry
    from atlas.services.assistant_service import AssistantService

    class FakeConvRepo:
        def __init__(self):
            self.sessions = {}
            self.messages = {}

        def create_session(self, *, title=None, metadata=None):
            import uuid
            from atlas.models import ConversationSession

            sid = str(uuid.uuid4())
            self.sessions[sid] = ConversationSession(
                id=sid, title=title, metadata=metadata or {}
            )
            self.messages[sid] = []
            return self.sessions[sid]

        def get_session(self, session_id):
            return self.sessions.get(str(session_id))

        def list_sessions(self, *, limit=50):
            return list(self.sessions.values())[:limit]

        def touch_session(self, session_id):
            pass

        def add_message(self, session_id, role, content, *, tool_calls=None):
            import uuid
            from atlas.models import ConversationMessage

            sid = str(session_id)
            msg = ConversationMessage(
                id=str(uuid.uuid4()),
                session_id=sid,
                ordinal=len(self.messages[sid]),
                role=role,
                content=content,
                tool_calls=tool_calls or [],
            )
            self.messages[sid].append(msg)
            return msg

        def history(self, session_id, *, limit=None):
            msgs = self.messages.get(str(session_id), [])
            return msgs[-limit:] if limit else list(msgs)

        def count_sessions(self):
            return len(self.sessions)

    class FakeLLM:
        def for_role(self, role):
            class _R:
                def chat(self, messages, **kw):
                    from atlas.llm.provider import LLMResponse

                    return LLMResponse(text="ok", model="fake", usage={})

            return _R()

    def caption_fetch(video: str):
        return {
            "outcome": "blocked",
            "reason_code": REASON_ROBOTS_DISALLOWED,
            "reason": "robots",
            "text": "",
            "acquisition": {
                "strategies_tried": [
                    {
                        "strategy": "youtube_caption_tracks",
                        "outcome": "blocked",
                        "reason_code": REASON_ROBOTS_DISALLOWED,
                        "bytes_read": 0,
                    }
                ]
            },
        }

    class FakeMedia:
        def ingest_url(self, url, **kw):
            return {
                "outcome": "blocked",
                "text": "",
                "fetch": {
                    "strategies_tried": [
                        {
                            "name": "youtube_media",
                            "outcome": "blocked",
                            "reason_code": "policy_requires_operator_asset",
                        }
                    ]
                },
            }

    orch = MediaLearnOrchestrator(
        caption_fetch=caption_fetch,
        media_ingestor=FakeMedia(),
        speech_status=lambda: "disabled",
    )
    tools = ToolRegistry()
    from atlas.kernel.capabilities import CapabilityRegistry
    from atlas.capabilities import CAP_MEDIA_LEARN, MediaLearnCapability

    caps = CapabilityRegistry()
    caps.register(CAP_MEDIA_LEARN, orch, contract=MediaLearnCapability)

    conv = ConversationService(FakeConvRepo())
    svc = AssistantService(
        conv,
        Planner(),
        ToolExecutor(tools),
        llm=FakeLLM(),
        tools=tools,
        capabilities=caps,
        media_learn=orch,
    )
    turn = svc.chat("Learn from this video https://youtu.be/abcdefghijk")
    assert turn.intent == Intent.MEDIA_LEARN
    assert turn.tool_calls
    assert turn.tool_calls[0]["action"] == "media.learn"
    assert turn.tool_calls[0]["orchestrator"] == "media.learn"
    strategies = turn.tool_calls[0].get("strategies") or []
    assert len(strategies) >= 3

    outcome = svc.run_step(
        Intent.MEDIA_LEARN,
        {"source": "https://youtu.be/abcdefghijk"},
        capability="media_learn",
    )
    assert outcome.blocked is True
    assert outcome.blocked_reason == "interactive_recovery_required"
    assert len(outcome.extras.get("strategies") or []) >= 3
    assert orch.calls


def test_media_learn_success_ingests_caption_text():
    ingested = []

    class FakeKnowledge:
        def ingest_text(self, source, content, **kw):
            ingested.append((source, content, kw))
            return {"document_id": "d1", "outcome": "ok"}

    orch = MediaLearnOrchestrator(
        caption_fetch=lambda v: {
            "outcome": "ok",
            "text": "Hello from captions.",
            "title": "Talk",
            "acquisition": {
                "strategies_tried": [
                    {
                        "strategy": "youtube_caption_tracks",
                        "outcome": "ok",
                        "reason_code": "ok",
                        "bytes_read": 20,
                    }
                ]
            },
        },
        media_ingestor=None,
        knowledge=FakeKnowledge(),
    )
    result = orch.learn("https://youtu.be/abcdefghijk")
    assert result["outcome"] == "ok"
    assert result["interactive_recovery"] is False
    assert ingested and "Hello from captions." in ingested[0][1]
