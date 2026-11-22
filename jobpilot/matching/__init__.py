from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from jobpilot.config import AppConfig, ProfileConfig
from jobpilot.db import Job
from jobpilot.matching.hard_filters import filter_job
from jobpilot.matching.keyword_filter import keyword_score
from jobpilot.matching.llm_scorer import ScoringResponse, score_job
from jobpilot.matching.post_processor import compute_final_score, should_drop_post_llm


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class PipelineResult:
    total_processed: int = 0
    hard_filtered: dict[str, int] = field(default_factory=dict)
    keyword_filtered: int = 0
    llm_scored: int = 0
    post_filtered: dict[str, int] = field(default_factory=dict)
    shortlisted: int = 0
    llm_cost_usd: float = 0.0
    injection_flagged: int = 0


def run_pipeline(
    jobs: list[Job],
    profile: ProfileConfig,
    app_config: AppConfig,
    session: object,
    llm_client: object,
    dry_run: bool = False,
) -> PipelineResult:
    result = PipelineResult(total_processed=len(jobs))
    now = _now()

    min_keyword = getattr(app_config.scoring, "min_keyword_score", 0.1)
    shortlist_threshold = app_config.scoring.min_match_score * 100

    # Stage 1: hard filters
    surviving: list[Job] = []
    for job in jobs:
        reason = filter_job(job, profile, session, now)
        if reason:
            result.hard_filtered[reason] = result.hard_filtered.get(reason, 0) + 1
            if not dry_run:
                job.status = "filtered_out"
                job.filter_reason = reason
        else:
            surviving.append(job)

    # Stage 2: keyword prefilter
    scored_pairs: list[tuple[float, Job]] = []
    for job in surviving:
        kscore = keyword_score(
            job.description or "",
            profile.core_skills,
            profile.nice_to_have_skills,
        )
        if kscore < min_keyword:
            result.keyword_filtered += 1
            if not dry_run:
                job.status = "filtered_out"
                job.filter_reason = "keyword_no_match"
        else:
            scored_pairs.append((kscore, job))

    # Sort by keyword score descending; take top max(50, 50% of remaining)
    scored_pairs.sort(key=lambda x: x[0], reverse=True)
    cap = max(50, len(scored_pairs) // 2)
    llm_candidates = [j for _, j in scored_pairs[:cap]]
    # Drop the rest as keyword_no_match
    for _, j in scored_pairs[cap:]:
        result.keyword_filtered += 1
        if not dry_run:
            j.status = "filtered_out"
            j.filter_reason = "keyword_no_match"

    # Stage 3: LLM scoring
    # Track LLM spend before run to compute delta
    from sqlalchemy import func, select
    from jobpilot.db import LLMUsage
    from datetime import timedelta

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spend_before_row = session.execute(
        select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(
            LLMUsage.called_at >= month_start
        )
    ).scalar()
    spend_before = float(spend_before_row or 0.0)

    for job in llm_candidates:
        # Cache check
        desc_hash = (
            hashlib.md5(job.description.encode()).hexdigest()
            if job.description
            else None
        )
        if job.description_hash == desc_hash and job.match_score is not None:
            # Cached: just re-shortlist based on existing score
            if job.match_score >= shortlist_threshold:
                result.shortlisted += 1
                if not dry_run:
                    job.status = "shortlisted"
            continue

        try:
            llm_resp: ScoringResponse = score_job(job, profile, app_config, llm_client)
        except Exception:
            # Budget exceeded or parse error — skip this job, don't crash
            continue

        result.llm_scored += 1

        # Post-processing drop check
        drop_reason = should_drop_post_llm(llm_resp, profile)

        # Compute final score
        job_countries = job.countries if isinstance(job.countries, list) else []
        final_score = compute_final_score(
            llm_score=llm_resp.score,
            sponsorship_assessment=llm_resp.sponsorship_assessment,
            posted_at=job.posted_at,
            job_countries=job_countries,
            profile=profile,
            salary_meets_expectation=llm_resp.salary_meets_expectation,
            now=now,
        )

        if llm_resp.prompt_injection_detected:
            result.injection_flagged += 1

        if not dry_run:
            # Update job fields
            job.description_hash = desc_hash
            job.match_score = float(final_score)
            match_details = llm_resp.model_dump()
            if llm_resp.prompt_injection_detected:
                match_details["prompt_injection"] = True
            job.match_details = match_details
            job.required_years = llm_resp.required_years
            job.required_languages = llm_resp.required_languages
            # Update sponsorship signal
            assessment_to_signal = {
                "explicit_yes": "yes",
                "likely": "yes",
                "unknown": "unknown",
                "unlikely": "unknown",
                "explicit_no": "no",
            }
            job.sponsorship_signal = assessment_to_signal.get(
                llm_resp.sponsorship_assessment, "unknown"
            )
            if llm_resp.remote_allowed_countries is not None:
                job.remote_allowed_countries = llm_resp.remote_allowed_countries

            if drop_reason:
                result.post_filtered[drop_reason] = (
                    result.post_filtered.get(drop_reason, 0) + 1
                )
                job.status = "filtered_out"
                job.filter_reason = drop_reason
            elif final_score >= shortlist_threshold:
                job.status = "shortlisted"
                result.shortlisted += 1
            else:
                job.status = "filtered_out"
                job.filter_reason = "low_score"
        else:
            if drop_reason:
                result.post_filtered[drop_reason] = (
                    result.post_filtered.get(drop_reason, 0) + 1
                )
            elif final_score >= shortlist_threshold:
                result.shortlisted += 1

    if not dry_run:
        session.commit()

    # Compute LLM cost for this run
    spend_after_row = session.execute(
        select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(
            LLMUsage.called_at >= month_start
        )
    ).scalar()
    spend_after = float(spend_after_row or 0.0)
    result.llm_cost_usd = max(0.0, spend_after - spend_before)

    return result
