from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core import config
from app.services.alerting import notify_external_alert


logger = logging.getLogger(__name__)


def _build_s3_client():
    try:
        import boto3  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError("boto3_not_installed") from exc

    client_kwargs: dict[str, Any] = {}
    if config.ARTIFACT_S3_REGION:
        client_kwargs["region_name"] = config.ARTIFACT_S3_REGION
    if config.ARTIFACT_S3_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = config.ARTIFACT_S3_ENDPOINT_URL
    if config.ARTIFACT_S3_ACCESS_KEY_ID and config.ARTIFACT_S3_SECRET_ACCESS_KEY:
        client_kwargs["aws_access_key_id"] = config.ARTIFACT_S3_ACCESS_KEY_ID
        client_kwargs["aws_secret_access_key"] = config.ARTIFACT_S3_SECRET_ACCESS_KEY
    if config.ARTIFACT_S3_SESSION_TOKEN:
        client_kwargs["aws_session_token"] = config.ARTIFACT_S3_SESSION_TOKEN

    if config.ARTIFACT_S3_ADDRESSING_STYLE:
        try:
            from botocore.config import Config as BotoConfig  # type: ignore[import-not-found]

            client_kwargs["config"] = BotoConfig(
                s3={"addressing_style": config.ARTIFACT_S3_ADDRESSING_STYLE}
            )
        except ModuleNotFoundError:
            logger.warning("botocore config unavailable; ARTIFACT_S3_ADDRESSING_STYLE ignored")

    return boto3.client("s3", **client_kwargs)


def _write_local_json_artifact(
    *,
    artifact_type: str,
    object_id: str,
    payload: dict[str, Any],
) -> str:
    base_dir = Path(config.ARTIFACT_STORAGE_DIR)
    artifact_dir = base_dir / artifact_type
    artifact_dir.mkdir(parents=True, exist_ok=True)
    file_path = artifact_dir / f"{object_id}.json"
    file_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    if config.ARTIFACT_PUBLIC_BASE_URL:
        relative = file_path.relative_to(base_dir).as_posix()
        return f"{config.ARTIFACT_PUBLIC_BASE_URL.rstrip('/')}/{relative}"
    return str(file_path)


def _write_s3_json_artifact(
    *,
    artifact_type: str,
    object_id: str,
    payload: dict[str, Any],
) -> str:
    bucket = config.ARTIFACT_S3_BUCKET.strip()
    if not bucket:
        raise RuntimeError("artifact_s3_bucket_missing")

    prefix = config.ARTIFACT_S3_PREFIX.strip("/")
    key_parts = [part for part in (prefix, artifact_type.strip("/"), f"{object_id}.json") if part]
    key = "/".join(key_parts)
    body = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8")

    s3 = _build_s3_client()
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json; charset=utf-8",
    )

    if config.ARTIFACT_PUBLIC_BASE_URL:
        return f"{config.ARTIFACT_PUBLIC_BASE_URL.rstrip('/')}/{key}"

    presign_ttl = max(0, int(config.ARTIFACT_S3_PRESIGN_TTL_SECONDS))
    if presign_ttl > 0:
        return str(
            s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=presign_ttl,
            )
        )

    return f"s3://{bucket}/{key}"


def write_json_artifact(
    *,
    artifact_type: str,
    object_id: str,
    payload: dict[str, Any],
) -> str | None:
    if not config.ARTIFACT_STORAGE_ENABLED:
        return None

    try:
        backend = config.ARTIFACT_STORAGE_BACKEND.strip().lower()
        if backend == "local":
            return _write_local_json_artifact(
                artifact_type=artifact_type,
                object_id=object_id,
                payload=payload,
            )
        if backend == "s3":
            return _write_s3_json_artifact(
                artifact_type=artifact_type,
                object_id=object_id,
                payload=payload,
            )
        raise RuntimeError(f"unsupported_artifact_backend:{backend}")
    except Exception as exc:
        logger.warning(
            "artifact write failed: backend=%s artifact_type=%s object_id=%s error=%s",
            config.ARTIFACT_STORAGE_BACKEND,
            artifact_type,
            object_id,
            exc,
        )
        notify_external_alert(
            event_type="artifact_write_failed",
            severity="warning",
            message="Artifact write failed",
            details={
                "backend": config.ARTIFACT_STORAGE_BACKEND,
                "artifactType": artifact_type,
                "objectId": object_id,
                "errorType": type(exc).__name__,
                "error": str(exc),
            },
        )
        if config.ARTIFACT_STORAGE_STRICT:
            raise
        return None
