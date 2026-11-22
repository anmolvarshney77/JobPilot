from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class _SimpleSchema(BaseModel):
    result: str
    prompt_injection_detected: str = ""


def _make_app_config(budget: float = 15.0):
    from jobpilot.config import load_app_config

    cfg = load_app_config(FIXTURE_DIR / "config_fixture.yaml")
    # override budget for tests
    object.__setattr__(cfg.llm, "monthly_budget_usd", budget)
    return cfg


def _make_session_factory(monthly_spend: float):
    """Return a session factory whose execute() returns the given monthly spend."""

    @contextmanager
    def factory():
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = monthly_spend
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()
        yield mock_session

    return factory


def test_budget_exceeded():
    from jobpilot.llm import BudgetExceededError, LLMClient

    cfg = _make_app_config(budget=5.0)
    session_factory = _make_session_factory(monthly_spend=10.0)  # over budget

    client = LLMClient(cfg, session_factory)

    with pytest.raises(BudgetExceededError):
        client.call(
            model="claude-haiku-5-5",
            purpose="test",
            system="You are a helpful assistant.",
            user_message="Hello",
            response_schema=_SimpleSchema,
        )


def test_job_description_wrapped():
    from jobpilot.llm import LLMClient

    cfg = _make_app_config(budget=15.0)
    session_factory = _make_session_factory(monthly_spend=0.0)

    captured_messages = []

    def mock_create(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({"result": "ok"}))]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        return mock_response

    client = LLMClient(cfg, session_factory)

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_instance = MagicMock()
        mock_instance.messages.create.side_effect = mock_create
        mock_anthropic_cls.return_value = mock_instance

        client.call(
            model="claude-haiku-5-5",
            purpose="test",
            system="You are a helpful assistant.",
            user_message="Some job description text",
            response_schema=_SimpleSchema,
            is_job_description=True,
        )

    assert len(captured_messages) == 1
    user_content = captured_messages[0][0]["content"]
    assert "<untrusted_job_posting>" in user_content


def test_injection_warning_in_system():
    from jobpilot.llm import INJECTION_GUARD, LLMClient

    cfg = _make_app_config(budget=15.0)
    session_factory = _make_session_factory(monthly_spend=0.0)

    captured_systems = []

    def mock_create(**kwargs):
        captured_systems.append(kwargs.get("system", ""))
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({"result": "ok"}))]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        return mock_response

    client = LLMClient(cfg, session_factory)

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_instance = MagicMock()
        mock_instance.messages.create.side_effect = mock_create
        mock_anthropic_cls.return_value = mock_instance

        client.call(
            model="claude-haiku-5-5",
            purpose="test",
            system="You are a helpful assistant.",
            user_message="Some job description text",
            response_schema=_SimpleSchema,
            is_job_description=True,
        )

    assert len(captured_systems) == 1
    assert "untrusted_job_posting" in captured_systems[0]
