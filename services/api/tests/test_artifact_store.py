from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import sys


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.append(str(API_ROOT))

if "psycopg_pool" not in sys.modules:
    psycopg_pool_module = ModuleType("psycopg_pool")
    psycopg_pool_module.ConnectionPool = object
    sys.modules["psycopg_pool"] = psycopg_pool_module

if "psycopg" not in sys.modules:
    psycopg_module = ModuleType("psycopg")
    psycopg_rows_module = ModuleType("psycopg.rows")
    psycopg_rows_module.dict_row = object()
    psycopg_module.rows = psycopg_rows_module
    sys.modules["psycopg"] = psycopg_module
    sys.modules["psycopg.rows"] = psycopg_rows_module

if "redis" not in sys.modules:
    redis_module = ModuleType("redis")
    redis_module.Redis = SimpleNamespace(from_url=lambda *args, **kwargs: None)
    sys.modules["redis"] = redis_module

import app.services.artifact_store as artifact_store  # noqa: E402


class ArtifactStoreTests(unittest.TestCase):
    def test_disabled_returns_none(self):
        with (
            patch.object(artifact_store.config, "ARTIFACT_STORAGE_ENABLED", False),
            patch.object(artifact_store.config, "ARTIFACT_STORAGE_BACKEND", "local"),
            patch.object(artifact_store.config, "ARTIFACT_STORAGE_DIR", "/tmp/ignored"),
        ):
            ref = artifact_store.write_json_artifact(
                artifact_type="puzzles",
                object_id="puz_1",
                payload={"id": "puz_1"},
            )
        self.assertIsNone(ref)

    def test_writes_local_artifact(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch.object(artifact_store.config, "ARTIFACT_STORAGE_ENABLED", True),
                patch.object(artifact_store.config, "ARTIFACT_STORAGE_BACKEND", "local"),
                patch.object(artifact_store.config, "ARTIFACT_STORAGE_DIR", tmp_dir),
                patch.object(artifact_store.config, "ARTIFACT_PUBLIC_BASE_URL", ""),
            ):
                ref = artifact_store.write_json_artifact(
                    artifact_type="puzzles",
                    object_id="puz_2",
                    payload={"id": "puz_2", "gameType": "crossword"},
                )
            self.assertIsNotNone(ref)
            assert ref is not None
            path = Path(ref)
            self.assertTrue(path.exists())
            payload = json.loads(path.read_text())
            self.assertEqual(payload["id"], "puz_2")

    def test_writes_s3_artifact_and_returns_uri(self):
        class FakeS3Client:
            def __init__(self):
                self.put_calls: list[dict] = []

            def put_object(self, **kwargs):
                self.put_calls.append(kwargs)

        fake_s3 = FakeS3Client()
        with (
            patch.object(artifact_store.config, "ARTIFACT_STORAGE_ENABLED", True),
            patch.object(artifact_store.config, "ARTIFACT_STORAGE_BACKEND", "s3"),
            patch.object(artifact_store.config, "ARTIFACT_S3_BUCKET", "pokeleximon-artifacts"),
            patch.object(artifact_store.config, "ARTIFACT_S3_PREFIX", "generated"),
            patch.object(artifact_store.config, "ARTIFACT_PUBLIC_BASE_URL", ""),
            patch.object(artifact_store.config, "ARTIFACT_S3_PRESIGN_TTL_SECONDS", 0),
            patch.object(artifact_store, "_build_s3_client", return_value=fake_s3),
        ):
            ref = artifact_store.write_json_artifact(
                artifact_type="puzzles",
                object_id="puz_3",
                payload={"id": "puz_3"},
            )

        self.assertEqual(ref, "s3://pokeleximon-artifacts/generated/puzzles/puz_3.json")
        self.assertEqual(len(fake_s3.put_calls), 1)
        self.assertEqual(fake_s3.put_calls[0]["Bucket"], "pokeleximon-artifacts")
        self.assertEqual(fake_s3.put_calls[0]["Key"], "generated/puzzles/puz_3.json")

    def test_writes_s3_artifact_and_returns_presigned_url(self):
        class FakeS3Client:
            def put_object(self, **kwargs):  # noqa: ARG002
                return None

            def generate_presigned_url(self, operation, Params, ExpiresIn):  # noqa: N803
                self.operation = operation
                self.params = Params
                self.expires = ExpiresIn
                return "https://signed.example/puz_4"

        fake_s3 = FakeS3Client()
        with (
            patch.object(artifact_store.config, "ARTIFACT_STORAGE_ENABLED", True),
            patch.object(artifact_store.config, "ARTIFACT_STORAGE_BACKEND", "s3"),
            patch.object(artifact_store.config, "ARTIFACT_S3_BUCKET", "pokeleximon-artifacts"),
            patch.object(artifact_store.config, "ARTIFACT_S3_PREFIX", "generated"),
            patch.object(artifact_store.config, "ARTIFACT_PUBLIC_BASE_URL", ""),
            patch.object(artifact_store.config, "ARTIFACT_S3_PRESIGN_TTL_SECONDS", 900),
            patch.object(artifact_store, "_build_s3_client", return_value=fake_s3),
        ):
            ref = artifact_store.write_json_artifact(
                artifact_type="puzzles",
                object_id="puz_4",
                payload={"id": "puz_4"},
            )

        self.assertEqual(ref, "https://signed.example/puz_4")
        self.assertEqual(fake_s3.operation, "get_object")
        self.assertEqual(fake_s3.params, {"Bucket": "pokeleximon-artifacts", "Key": "generated/puzzles/puz_4.json"})
        self.assertEqual(fake_s3.expires, 900)


if __name__ == "__main__":
    unittest.main()
