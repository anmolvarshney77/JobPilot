from __future__ import annotations

from typing import Annotated

import typer

app = typer.Typer(
    name="jobpilot",
    help="Job application automation for software engineers targeting international markets.",
    no_args_is_help=True,
)

DryRun = Annotated[bool, typer.Option("--dry-run", help="Preview actions without making changes.")]


def _load_configs() -> tuple:
    from jobpilot.config import load_app_config, load_profile

    profile = load_profile("profile.yaml")
    cfg = load_app_config("config.yaml")
    return profile, cfg


@app.command()
def fetch(dry_run: DryRun = False) -> None:
    """Scrape job listings from configured sources."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("fetch: not yet implemented")


@app.command()
def score(dry_run: DryRun = False) -> None:
    """Score and filter fetched jobs against your profile."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("score: not yet implemented")


@app.command()
def prepare(dry_run: DryRun = False) -> None:
    """Tailor resume and draft cover letter for shortlisted jobs."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("prepare: not yet implemented")


@app.command()
def apply(dry_run: DryRun = False) -> None:
    """Submit applications via browser automation."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("apply: not yet implemented")


@app.command()
def outreach(dry_run: DryRun = False) -> None:
    """Draft recruiter/referral outreach messages."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("outreach: not yet implemented")


@app.command()
def dashboard(dry_run: DryRun = False) -> None:
    """Start the local web dashboard."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("dashboard: not yet implemented (will start uvicorn on http://localhost:8000)")


@app.command()
def daily(dry_run: DryRun = False) -> None:
    """Run fetch → score → prepare in sequence."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("daily: running fetch → score → prepare (not yet implemented)")


@app.command()
def stats(dry_run: DryRun = False) -> None:
    """Show run history and LLM usage/cost summary."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return

    import os

    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.orm import sessionmaker

    from jobpilot.db import LLMUsage, RunLog

    db_url = os.environ.get("DATABASE_URL", "sqlite:///./jobpilot.db")
    eng = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=eng)

    with Session() as session:
        run_rows = session.execute(
            select(RunLog.command, RunLog.status, RunLog.started_at).order_by(RunLog.started_at.desc()).limit(10)
        ).fetchall()

        llm_rows = session.execute(
            select(
                LLMUsage.model,
                func.count().label("calls"),
                func.sum(LLMUsage.input_tokens).label("in_tok"),
                func.sum(LLMUsage.output_tokens).label("out_tok"),
                func.sum(LLMUsage.cost_usd).label("cost"),
            ).group_by(LLMUsage.model)
        ).fetchall()

    typer.echo("\n=== Recent Runs ===")
    if run_rows:
        for r in run_rows:
            typer.echo(f"  {r.started_at}  {r.command:<12}  {r.status}")
    else:
        typer.echo("  (no runs yet)")

    typer.echo("\n=== LLM Usage (this database) ===")
    if llm_rows:
        typer.echo(f"  {'Model':<25} {'Calls':>6} {'In tok':>10} {'Out tok':>10} {'Cost USD':>10}")
        total_cost = 0.0
        for r in llm_rows:
            typer.echo(f"  {r.model:<25} {r.calls:>6} {r.in_tok:>10} {r.out_tok:>10} {r.cost:>10.4f}")
            total_cost += r.cost
        typer.echo(f"\n  Total cost: ${total_cost:.4f}")
    else:
        typer.echo("  (no LLM usage yet)")
