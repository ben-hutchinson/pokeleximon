from __future__ import annotations

from datetime import datetime, timedelta
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core import config
from app.core.observability import capture_exception
from app.data import repo
from app.services.alerting import notify_external_alert
from app.services.pokeapi_refresh import run_pokeapi_refresh_command
from app.services.reserve_generator import generate_draft_for_date, generate_puzzle_for_date, top_up_reserve

_scheduler: BackgroundScheduler | None = None
logger = logging.getLogger(__name__)


def _reserve_game_types() -> list[str]:
    return ["connections"] if config.FEATURE_CONNECTIONS_ENABLED else []


def _publish_daily() -> None:
    tz = ZoneInfo(config.TIMEZONE)
    today_date = datetime.now(tz).date()
    today = today_date.isoformat()
    for game_type in _reserve_game_types():
        result = repo.publish_next_from_reserve(
            date_value=today,
            game_type=game_type,
            timezone=tz.key,
            reserve_threshold=config.RESERVE_MIN_COUNT,
        )
        if result["status"] == "reserve_empty" and config.GENERATOR_ENABLED:
            logger.info("publish_daily: no reserve for %s on %s, generating daily puzzle", game_type, today)
            generate_puzzle_for_date(
                game_type=game_type,
                target_date=today_date,
                timezone=tz.key,
                force=False,
            )
            result = repo.publish_next_from_reserve(
                date_value=today,
                game_type=game_type,
                timezone=tz.key,
                reserve_threshold=config.RESERVE_MIN_COUNT,
            )
        logger.info(
            "publish_daily: game_type=%s date=%s status=%s reserve=%s threshold=%s",
            game_type,
            today,
            result["status"],
            result["reserveCount"],
            result["reserveThreshold"],
        )


def _top_up_reserve() -> None:
    if not config.GENERATOR_ENABLED:
        return
    for game_type in _reserve_game_types():
        try:
            result = top_up_reserve(
                game_type=game_type,
                target_count=config.RESERVE_TARGET_COUNT,
                timezone=config.TIMEZONE,
            )
            logger.info(
                "reserve_topup: game_type=%s job_id=%s inserted=%s before=%s after=%s target=%s",
                game_type,
                result["jobId"],
                result["inserted"],
                result["reserveCountBefore"],
                result["reserveCountAfter"],
                result["targetCount"],
            )
        except Exception as exc:
            logger.exception("reserve_topup failed for game_type=%s", game_type)
            capture_exception(exc)


def _build_draft_generation_trigger(tz: ZoneInfo) -> CronTrigger:
    try:
        return CronTrigger.from_crontab(config.DRAFT_GENERATION_CRON, timezone=tz)
    except ValueError:
        logger.warning(
            "invalid DRAFT_GENERATION_CRON value '%s'; falling back to 0 9 * * *",
            config.DRAFT_GENERATION_CRON,
        )
        return CronTrigger.from_crontab("0 9 * * *", timezone=tz)


def _generate_daily_drafts() -> None:
    if not config.DRAFT_GENERATION_ENABLED:
        return
    tz = ZoneInfo(config.TIMEZONE)
    target_date = datetime.now(tz).date() + timedelta(days=1)
    for game_type in ("crossword", "cryptic"):
        try:
            if repo.get_puzzle_by_date(game_type, target_date.isoformat(), timezone=tz.key) is not None:
                logger.info("draft_generation: skipping %s for %s because it is already published", game_type, target_date)
                continue
            if repo.get_draft_by_date(game_type=game_type, date_value=target_date) is not None:
                logger.info("draft_generation: skipping %s for %s because a draft already exists", game_type, target_date)
                continue
            result = generate_draft_for_date(
                game_type=game_type,
                target_date=target_date,
                timezone=tz.key,
            )
            logger.info(
                "draft_generation: game_type=%s date=%s status=%s puzzle_id=%s",
                game_type,
                target_date.isoformat(),
                result["status"],
                result["puzzleId"],
            )
        except Exception as exc:
            logger.exception("draft_generation failed for game_type=%s date=%s", game_type, target_date.isoformat())
            capture_exception(exc)

    try:
        repo.maybe_emit_draft_ready_notification(
            date_value=target_date,
            timezone=tz.key,
        )
    except Exception as exc:
        logger.exception("draft_ready notification failed for date=%s", target_date.isoformat())
        capture_exception(exc)


def _build_refresh_trigger(tz: ZoneInfo) -> CronTrigger:
    try:
        return CronTrigger.from_crontab(config.POKEAPI_REFRESH_CRON, timezone=tz)
    except ValueError:
        logger.warning(
            "invalid POKEAPI_REFRESH_CRON value '%s'; falling back to 15 2 * * *",
            config.POKEAPI_REFRESH_CRON,
        )
        return CronTrigger.from_crontab("15 2 * * *", timezone=tz)


def _refresh_pokeapi_artifacts() -> None:
    if not config.POKEAPI_REFRESH_ENABLED:
        return

    try:
        result = run_pokeapi_refresh_command()
        logger.info("pokeapi_refresh: status=%s details=%s", result.get("status"), result)
    except Exception as exc:
        logger.exception("pokeapi_refresh failed")
        capture_exception(exc)
        notify_external_alert(
            event_type="pokeapi_refresh_failed",
            severity="high",
            message=f"PokeAPI refresh pipeline failed: {type(exc).__name__}: {exc}",
            details={"cron": config.POKEAPI_REFRESH_CRON},
        )


def start_scheduler() -> None:
    global _scheduler
    if not config.SCHEDULER_ENABLED:
        return
    if _scheduler is not None:
        return

    if config.PUBLISH_ON_STARTUP:
        try:
            _publish_daily()
        except Exception as exc:
            logger.exception("publish_daily startup run failed")
            capture_exception(exc)
    if config.POKEAPI_REFRESH_ENABLED and config.POKEAPI_REFRESH_ON_STARTUP:
        try:
            _refresh_pokeapi_artifacts()
        except Exception as exc:
            logger.exception("pokeapi_refresh startup run failed")
            capture_exception(exc)

    tz = ZoneInfo(config.TIMEZONE)
    scheduler = BackgroundScheduler(timezone=tz)
    trigger = CronTrigger(hour=0, minute=0, timezone=tz)
    scheduler.add_job(
        _publish_daily,
        trigger,
        id="publish_daily",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _top_up_reserve,
        IntervalTrigger(minutes=max(5, config.RESERVE_TOPUP_INTERVAL_MINUTES), timezone=tz),
        id="reserve_topup",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    if config.DRAFT_GENERATION_ENABLED:
        scheduler.add_job(
            _generate_daily_drafts,
            _build_draft_generation_trigger(tz),
            id="draft_generation",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=600,
        )
    if config.POKEAPI_REFRESH_ENABLED:
        scheduler.add_job(
            _refresh_pokeapi_artifacts,
            _build_refresh_trigger(tz),
            id="pokeapi_refresh",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=600,
        )
    scheduler.start()
    _scheduler = scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
