from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from jobpilot.db import Base, Company


EXPECTED_TABLES = {"companies", "jobs", "applications", "outreach", "llm_usage", "run_log"}


@pytest.fixture
def in_memory_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(in_memory_engine):
    Session = sessionmaker(bind=in_memory_engine)
    with Session() as s:
        yield s


def test_create_all_tables(in_memory_engine):
    inspector = inspect(in_memory_engine)
    actual_tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES == actual_tables


def test_company_insert(session):
    company = Company(
        name="Acme Corp",
        normalized_name="acme-corp",
        added_at=datetime.utcnow(),
    )
    session.add(company)
    session.commit()

    result = session.query(Company).filter_by(normalized_name="acme-corp").first()
    assert result is not None
    assert result.name == "Acme Corp"
