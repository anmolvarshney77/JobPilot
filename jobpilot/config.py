from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProfilePhone(BaseModel):
    country_code: str
    number: str


class ProfileLocation(BaseModel):
    city: str
    country: str
    timezone: str


class ProfileEducation(BaseModel):
    degree: str
    field: str
    institution: str
    graduation_year: int


class SeniorityRange(BaseModel):
    min: int
    max: int


class SalaryBand(BaseModel):
    currency: str
    min: int


class FixedAnswers(BaseModel):
    authorized_to_work_US: str
    authorized_to_work_EU: str
    authorized_to_work_UK: str
    require_sponsorship_now_or_future: str
    willing_to_relocate: str
    previously_employed_here: str
    criminal_conviction: str
    age_18_or_over: str
    gender: str
    race_ethnicity: str
    veteran_status: str
    disability_status: str
    pronouns: str
    how_did_you_hear: str


class ProfileConfig(BaseModel):
    name: str
    email: str
    phone: ProfilePhone
    current_location: ProfileLocation
    linkedin: str
    github: str
    portfolio: str
    years_experience: int
    education: list[ProfileEducation]
    languages: dict[str, str]
    target_titles: list[str]
    target_titles_local: list[str] = []
    seniority_years_range: SeniorityRange
    core_skills: list[str]
    nice_to_have_skills: list[str] = []
    target_countries: list[str]
    preferred_cities: list[str] = []
    remote_ok: bool
    needs_visa_sponsorship: bool
    open_to_relocation: bool
    earliest_start: str
    notice_period_days: int
    expected_salary: dict[str, SalaryBand]
    exclude_companies: list[str] = []
    company_cooldown_days: int = 60
    fixed_answers: FixedAnswers
    resume_master_path: str

    @field_validator("email")
    @classmethod
    def email_must_contain_at(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError(f"Invalid email address: '{v}' (must contain '@')")
        return v


class LLMConfig(BaseModel):
    scoring_model: str
    tailoring_model: str
    monthly_budget_usd: float
    max_description_chars: int


class ScoringConfig(BaseModel):
    min_match_score: float
    sponsorship_required: bool
    boost_remote: float
    min_keyword_score: float = 0.1


class RateLimitConfig(BaseModel):
    fetch_delay_seconds: float
    max_jobs_per_run: int


class AppConfig(BaseModel):
    llm: LLMConfig
    scoring: ScoringConfig
    rate_limits: RateLimitConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    database_url: str = "sqlite:///./jobpilot.db"
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""


def load_profile(path: str | Path) -> ProfileConfig:
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Profile file not found: {path}")
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse profile YAML at {path}: {e}") from e
    try:
        return ProfileConfig.model_validate(data)
    except Exception as e:
        raise ValueError(f"Profile validation failed ({path}): {e}") from e


def load_settings() -> "Settings":
    return Settings()  # type: ignore[call-arg]


def load_app_config(path: str | Path = "config.yaml") -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Config file not found: {path}")
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse config YAML at {path}: {e}") from e
    try:
        return AppConfig.model_validate(data)
    except Exception as e:
        raise ValueError(f"App config validation failed ({path}): {e}") from e
