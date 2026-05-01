"""POST /api/ingest accepts multipart uploads and stores them in the KB."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient


class TestIngestEndpoint:
    def test_uploads_text_file(self, client: TestClient, tmp_path, monkeypatch) -> None:
        # Redirect documents_dir into the test tmpdir so we don't write
        # outside the sandbox.
        client.app.state.app_state.settings.documents_dir = str(tmp_path)

        files = [("files", ("note.txt", io.BytesIO(b"hello world"), "text/plain"))]
        r = client.post("/api/ingest", files=files)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ingested_files"] == 1
        assert body["ingested_chunks"] == 1
        assert len(body["memory_ids"]) == 1
        assert (tmp_path / "note.txt").exists()

    def test_rejects_empty_upload(self, client: TestClient) -> None:
        r = client.post("/api/ingest", files=[])
        assert r.status_code in (400, 422)

    def test_uploads_multiple_files(self, client: TestClient, tmp_path) -> None:
        client.app.state.app_state.settings.documents_dir = str(tmp_path)
        files = [
            ("files", ("a.txt", io.BytesIO(b"alpha"), "text/plain")),
            ("files", ("b.md", io.BytesIO(b"# beta"), "text/markdown")),
        ]
        r = client.post("/api/ingest", files=files)
        assert r.status_code == 200
        assert r.json()["ingested_files"] == 2
