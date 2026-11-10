"""The whole review workflow over HTTP, as the UI drives it.

upload → extract → translate (fake provider) → list/get chunks → edit →
accept a suggestion → decide a term for the whole book → glossary CRUD,
import and export → approve/unapprove → export DOCX and download → stats.
"""

from __future__ import annotations

import io
import json

import httpx
from docx import Document

from app.core.database import session_scope
from app.jobs import queue
from app.main import create_app
from app.models.verification_result import VerificationResult
from app.services import export as export_service
from app.services import extraction as extraction_service
from app.services import translation as translation_service


async def _noop(_f: float, _m: str) -> None:
    return None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t")


async def test_review_workflow_end_to_end(sample_pdf, tmp_storage, fake_provider) -> None:
    async with _client() as c:
        files = {"file": ("s.pdf", sample_pdf.read_bytes(), "application/pdf")}
        r = await c.post(
            "/api/v1/books",
            files=files,
            data={"title": "Review", "source_language": "en", "target_language": "ar"},
        )
        assert r.status_code == 201
        bid = r.json()["id"]

        # Run the queued jobs in-process (the worker would do this).
        async with session_scope() as s:
            job = await queue.claim(s, "test-worker")
            assert job is not None and job.kind.value == "extraction"
            result = await extraction_service.run_extraction(bid, fake_provider, _noop)
            await queue.complete(s, job.id, result)
        r = await c.post(f"/api/v1/books/{bid}/translate", json={"page_range": "abc"})
        assert r.status_code == 400, "an invalid page range is rejected before queueing"
        await translation_service.run_translation(bid, fake_provider, _noop)

        r = await c.get(f"/api/v1/books/{bid}")
        detail = r.json()
        assert detail["status"] == "review" and detail["percent_translated"] == 100.0

        r = await c.get(f"/api/v1/books/{bid}/chunks", params={"limit": 10})
        chunks = r.json()["chunks"]
        assert r.json()["total"] == len(chunks) >= 2
        assert all(ch["translated_text"].startswith("[fake-") for ch in chunks)
        r = await c.get(f"/api/v1/books/{bid}/chunks", params={"status": "nonsense"})
        assert r.status_code == 400

        # The «salah» term in the fixture produced a terminology flag.
        r = await c.get(f"/api/v1/books/{bid}/chunks", params={"has_pending_flags": "true"})
        flagged = r.json()["chunks"]
        assert len(flagged) == 1 and flagged[0]["pending_flags"] == 1
        idx = flagged[0]["index"]

        # Edit the translation.
        r = await c.patch(
            f"/api/v1/books/{bid}/chunks/{idx}", json={"translated_text": "نص FAIL هنا"}
        )
        assert r.status_code == 200 and r.json()["human_edited"] is True

        # Add a suggestion as the verifier would, then accept it over HTTP.
        async with session_scope() as s:
            s.add(
                VerificationResult(
                    chunk_id=flagged[0]["id"],
                    suggestions=[
                        {
                            "issue": "x",
                            "original_span": "FAIL",
                            "suggested": "PASS",
                            "severity": "high",
                            "status": "pending",
                        }
                    ],
                    score=0.4,
                    attempt=9,
                )
            )
            await s.commit()
        r = await c.post(
            f"/api/v1/books/{bid}/chunks/{idx}/suggestions/0", json={"action": "accept"}
        )
        assert r.status_code == 200, r.text
        assert "PASS" in r.json()["translated_text"]
        assert r.json()["verification"]["suggestions"][0]["status"] == "accepted"
        r = await c.post(
            f"/api/v1/books/{bid}/chunks/{idx}/suggestions/5", json={"action": "accept"}
        )
        assert r.status_code == 404

        # Decide the term for the whole book: it lands in the glossary.
        r = await c.get(f"/api/v1/books/{bid}/terminology")
        flag = r.json()["flags"][0]
        r = await c.post(
            f"/api/v1/books/{bid}/terminology/{flag['id']}/decide",
            json={"decision": "edited", "final_value": "الصلاة", "apply_to_book": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["glossary_term"]["translation"] == "الصلاة"
        assert (await c.get(f"/api/v1/books/{bid}/terminology")).json()["count"] == 0

        # Glossary: upsert, import CSV and JSON, export, delete.
        r = await c.post(
            f"/api/v1/books/{bid}/glossary",
            json={"original_term": "worship", "translation": "العبادة", "category": "religious"},
        )
        assert r.status_code == 200 and r.json()["category"] == "religious"
        csv_bytes = "original_term,translation\nfasting,الصيام\n,missing\n".encode()
        r = await c.post(
            f"/api/v1/books/{bid}/glossary/import",
            files={"file": ("g.csv", csv_bytes, "text/csv")},
        )
        assert r.json()["imported"] == 1, "rows without a term are skipped"
        r = await c.post(
            f"/api/v1/books/{bid}/glossary/import",
            files={"file": ("g.json", b'{"not": "a list"}', "application/json")},
        )
        assert r.status_code == 400
        r = await c.get(f"/api/v1/books/{bid}/glossary/export")
        exported = json.loads(r.content)
        assert {t["original_term"] for t in exported} == {"salah", "worship", "fasting"}
        terms = (await c.get(f"/api/v1/books/{bid}/glossary")).json()["terms"]
        worship = next(t for t in terms if t["original_term"] == "worship")
        assert (await c.delete(f"/api/v1/books/{bid}/glossary/{worship['id']}")).status_code == 204
        assert (await c.delete(f"/api/v1/books/{bid}/glossary/{worship['id']}")).status_code == 404

        # Approve every chunk (idempotent), unapprove one, approve it again.
        for ch in chunks:
            r = await c.post(f"/api/v1/books/{bid}/chunks/{ch['index']}/approve")
            assert r.json()["status"] == "approved"
        r = await c.post(f"/api/v1/books/{bid}/chunks/{chunks[0]['index']}/approve")
        assert r.status_code == 200
        r = await c.post(f"/api/v1/books/{bid}/chunks/{chunks[0]['index']}/unapprove")
        assert r.json()["status"] == "terminology_reviewed"
        await c.post(f"/api/v1/books/{bid}/chunks/{chunks[0]['index']}/approve")
        assert (await c.get(f"/api/v1/books/{bid}")).json()["percent_approved"] == 100.0

        # Export through the service, then download over HTTP.
        assert (await c.get(f"/api/v1/books/{bid}/export/download")).status_code == 404
        r = await c.post(f"/api/v1/books/{bid}/export", json={"format": "pdf"})
        assert r.status_code == 400
        r = await c.post(f"/api/v1/books/{bid}/export", json={"format": "docx"})
        assert r.status_code == 202
        job_id = r.json()["job"]["id"]
        r = await c.post(f"/api/v1/books/{bid}/export", json={"format": "docx"})
        assert r.status_code == 409, "one active job per book"
        result = await export_service.run_export(bid, _noop)
        async with session_scope() as s:
            from app.models.job import Job

            job = await s.get(Job, job_id)
            await queue.complete(s, job.id, result)
        r = await c.get(f"/api/v1/books/{bid}/export/download")
        assert r.status_code == 200
        doc = Document(io.BytesIO(r.content))
        text = "\n".join(p.text for p in doc.paragraphs)
        assert "PASS" in text and "Review" in text
        rtl = [
            p
            for p in doc.paragraphs
            if p._p.pPr is not None
            and p._p.pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}bidi")
            is not None
        ]
        assert rtl, "Arabic paragraphs are right-to-left"

        r = await c.get(f"/api/v1/books/{bid}/stats")
        assert r.json()["llm_calls"] > 0
        r = await c.get(f"/api/v1/books/{bid}/jobs")
        assert {j["kind"] for j in r.json()["jobs"]} >= {"extraction", "export"}
        r = await c.get(f"/api/v1/jobs/{job_id}")
        assert r.json()["status"] == "succeeded"

        # Retranslate one chunk queues a job; delete the book.
        r = await c.post(f"/api/v1/books/{bid}/chunks/99/retranslate")
        assert r.status_code == 404
        assert (await c.delete(f"/api/v1/books/{bid}")).status_code == 204
        assert (await c.get(f"/api/v1/books/{bid}")).status_code == 404
