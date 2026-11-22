from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_load_profile_valid():
    from jobpilot.config import load_profile

    profile = load_profile(FIXTURE_DIR / "profile_fixture.yaml")
    assert profile.name == "Test User"
    assert profile.email == "test@example.com"


def test_load_profile_missing_email():
    from jobpilot.config import load_profile

    with open(FIXTURE_DIR / "profile_fixture.yaml") as f:
        data = yaml.safe_load(f)
    del data["email"]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        yaml.dump(data, tmp)
        tmp_path = tmp.name

    with pytest.raises(ValueError):
        load_profile(tmp_path)


def test_load_profile_bad_email():
    from jobpilot.config import load_profile

    with open(FIXTURE_DIR / "profile_fixture.yaml") as f:
        data = yaml.safe_load(f)
    data["email"] = "notanemail"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        yaml.dump(data, tmp)
        tmp_path = tmp.name

    with pytest.raises(ValueError):
        load_profile(tmp_path)


def test_load_app_config_valid():
    from jobpilot.config import load_app_config

    cfg = load_app_config(FIXTURE_DIR / "config_fixture.yaml")
    assert cfg.llm.scoring_model == "claude-haiku-5-5"
