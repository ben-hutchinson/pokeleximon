from __future__ import annotations

import logging
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from app.core import config


logger = logging.getLogger(__name__)


def run_pokeapi_refresh_command() -> dict[str, Any]:
    command = config.POKEAPI_REFRESH_COMMAND.strip()
    if not command:
        return {"status": "skipped", "reason": "command_missing"}

    args = shlex.split(command)
    if not args:
        return {"status": "skipped", "reason": "command_missing"}

    cwd_raw = config.POKEAPI_REFRESH_WORKDIR.strip()
    cwd = Path(cwd_raw) if cwd_raw else None

    started = time.monotonic()
    completed = subprocess.run(  # noqa: S603
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=max(60, config.POKEAPI_REFRESH_TIMEOUT_SECONDS),
        check=False,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        raise RuntimeError(
            f"refresh_command_failed rc={completed.returncode} stderr={stderr[:500]} stdout={stdout[:500]}"
        )

    logger.info(
        "pokeapi refresh command succeeded: rc=%s duration_ms=%s stdout_preview=%s",
        completed.returncode,
        duration_ms,
        stdout[:200],
    )
    return {
        "status": "ok",
        "returnCode": completed.returncode,
        "durationMs": duration_ms,
        "stdoutPreview": stdout[:500],
        "stderrPreview": stderr[:500],
        "command": args,
        "cwd": str(cwd) if cwd else None,
    }
