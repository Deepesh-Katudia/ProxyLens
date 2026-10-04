"""Persistence for documents, jobs, resolutions, analyses and feedback.

`ReportStore` is the interface the API and the job runner use; `MongoReportStore`
backs it with the SPEC 5 collections, `InMemoryReportStore` with dicts (tests and
local runs without a database).
"""

from datetime import UTC, datetime
from typing import Any, Protocol

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

from app.db.client import Document
from app.db.collections import ANALYSES, DOCUMENTS, EVAL_RUNS, FEEDBACK, JOBS, RESOLUTIONS
from app.parsing.models import ParsedNotice
from app.reports.models import (
    Analysis,
    DocumentMeta,
    DocumentReport,
    Feedback,
    FeedbackIn,
    Job,
    JobStatus,
    ReportItem,
    Resolution,
)
from app.rules.models import CompanyFacts
from app.schemas.analysis import ItemAnalysis


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(ObjectId())


def build_records(
    document_id: str, notice: ParsedNotice, analyses: list[ItemAnalysis]
) -> list[tuple[Resolution, Analysis]]:
    """Split pipeline results into `resolutions` and `analyses` records."""
    by_seq = {item.seq: item for item in notice.items}
    created = now()
    records = []
    for result in analyses:
        item = by_seq[result.seq]
        resolution = Resolution(
            id=new_id(),
            document_id=document_id,
            seq=result.seq,
            item_no=result.item_no,
            raw_text=item.text,
            explanatory_statement=item.explanatory_statement,
            extracted=result.extraction,
            extractor=result.extractor,
        )
        analysis = Analysis(
            id=new_id(),
            resolution_id=resolution.id,
            document_id=document_id,
            recommendation=result.recommendation,
            confidence=result.confidence,
            rationale=result.rationale,
            rule_findings=result.rule_findings,
            citations=result.citations,
            retrieved_ids=result.retrieved_ids,
            flags=result.flags,
            adjustments=result.adjustments,
            pipeline_version=result.pipeline_version,
            created_at=created,
        )
        records.append((resolution, analysis))
    return records


class ReportStore(Protocol):
    async def create_document(
        self, filename: str, file_sha256: str, company_facts: CompanyFacts
    ) -> DocumentMeta: ...

    async def find_document_by_sha(self, file_sha256: str) -> DocumentMeta | None: ...

    async def update_document(self, document_id: str, **fields: Any) -> None: ...

    async def get_document(self, document_id: str) -> DocumentMeta | None: ...

    async def list_documents(self, limit: int) -> list[DocumentMeta]: ...

    async def create_job(self, document_id: str) -> Job: ...

    async def update_job(self, job_id: str, **fields: Any) -> None: ...

    async def get_job(self, job_id: str) -> Job | None: ...

    async def save_results(
        self, document_id: str, notice: ParsedNotice, analyses: list[ItemAnalysis]
    ) -> None: ...

    async def get_report(self, document_id: str) -> DocumentReport | None: ...

    async def get_report_item(self, resolution_id: str) -> ReportItem | None: ...

    async def get_analysis(self, analysis_id: str) -> Analysis | None: ...

    async def add_feedback(self, analysis_id: str, feedback: FeedbackIn) -> Feedback: ...

    async def latest_eval_run(self) -> dict[str, Any] | None: ...


class InMemoryReportStore:
    def __init__(self) -> None:
        self.documents: dict[str, DocumentMeta] = {}
        self.jobs: dict[str, Job] = {}
        self.resolutions: dict[str, Resolution] = {}
        self.analyses: dict[str, Analysis] = {}
        self.feedback: list[Feedback] = []
        self.eval_runs: list[dict[str, Any]] = []

    async def create_document(
        self, filename: str, file_sha256: str, company_facts: CompanyFacts
    ) -> DocumentMeta:
        doc = DocumentMeta(
            id=new_id(),
            filename=filename,
            file_sha256=file_sha256,
            company_facts=company_facts,
            uploaded_at=now(),
        )
        self.documents[doc.id] = doc
        return doc

    async def find_document_by_sha(self, file_sha256: str) -> DocumentMeta | None:
        matches = [d for d in self.documents.values() if d.file_sha256 == file_sha256]
        return max(matches, key=lambda d: d.uploaded_at) if matches else None

    async def update_document(self, document_id: str, **fields: Any) -> None:
        self.documents[document_id] = self.documents[document_id].model_copy(update=fields)

    async def get_document(self, document_id: str) -> DocumentMeta | None:
        return self.documents.get(document_id)

    async def list_documents(self, limit: int) -> list[DocumentMeta]:
        docs = sorted(self.documents.values(), key=lambda d: d.uploaded_at, reverse=True)
        return docs[:limit]

    async def create_job(self, document_id: str) -> Job:
        stamp = now()
        job = Job(
            id=new_id(),
            document_id=document_id,
            status=JobStatus.QUEUED,
            created_at=stamp,
            updated_at=stamp,
        )
        self.jobs[job.id] = job
        await self.update_document(document_id, job_id=job.id)
        return job

    async def update_job(self, job_id: str, **fields: Any) -> None:
        self.jobs[job_id] = self.jobs[job_id].model_copy(update={**fields, "updated_at": now()})

    async def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def save_results(
        self, document_id: str, notice: ParsedNotice, analyses: list[ItemAnalysis]
    ) -> None:
        stale = [r.id for r in self.resolutions.values() if r.document_id == document_id]
        for resolution_id in stale:
            del self.resolutions[resolution_id]
        self.analyses = {k: a for k, a in self.analyses.items() if a.document_id != document_id}
        for resolution, analysis in build_records(document_id, notice, analyses):
            self.resolutions[resolution.id] = resolution
            self.analyses[analysis.id] = analysis

    def _item(self, resolution: Resolution) -> ReportItem:
        analysis = next(
            (a for a in self.analyses.values() if a.resolution_id == resolution.id), None
        )
        feedback = [f for f in self.feedback if analysis and f.analysis_id == analysis.id]
        return ReportItem(resolution=resolution, analysis=analysis, feedback=feedback)

    async def get_report(self, document_id: str) -> DocumentReport | None:
        doc = self.documents.get(document_id)
        if doc is None:
            return None
        resolutions = sorted(
            (r for r in self.resolutions.values() if r.document_id == document_id),
            key=lambda r: r.seq,
        )
        job = self.jobs.get(doc.job_id) if doc.job_id else None
        return DocumentReport(document=doc, job=job, items=[self._item(r) for r in resolutions])

    async def get_report_item(self, resolution_id: str) -> ReportItem | None:
        resolution = self.resolutions.get(resolution_id)
        return self._item(resolution) if resolution else None

    async def get_analysis(self, analysis_id: str) -> Analysis | None:
        return self.analyses.get(analysis_id)

    async def add_feedback(self, analysis_id: str, feedback: FeedbackIn) -> Feedback:
        record = Feedback(
            id=new_id(), analysis_id=analysis_id, created_at=now(), **feedback.model_dump()
        )
        self.feedback.append(record)
        return record

    async def latest_eval_run(self) -> dict[str, Any] | None:
        return self.eval_runs[-1] if self.eval_runs else None


def _oid(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def _out(doc: Document, *refs: str) -> Document:
    """A Mongo document as API fields: `_id` -> `id`, ObjectId references -> str."""
    data = {k: v for k, v in doc.items() if k != "_id"}
    data["id"] = str(doc["_id"])
    for ref in refs:
        if data.get(ref) is not None:
            data[ref] = str(data[ref])
    return data


class MongoReportStore:
    def __init__(self, db: AsyncDatabase[Document]) -> None:
        self.db = db

    async def ensure_indexes(self) -> None:
        await self.db[DOCUMENTS].create_index([("file_sha256", ASCENDING)])
        await self.db[DOCUMENTS].create_index([("uploaded_at", DESCENDING)])
        await self.db[RESOLUTIONS].create_index([("document_id", ASCENDING), ("seq", ASCENDING)])
        await self.db[ANALYSES].create_index([("resolution_id", ASCENDING)])
        await self.db[ANALYSES].create_index([("document_id", ASCENDING)])
        await self.db[FEEDBACK].create_index([("analysis_id", ASCENDING)])

    async def create_document(
        self, filename: str, file_sha256: str, company_facts: CompanyFacts
    ) -> DocumentMeta:
        record = {
            "filename": filename,
            "file_sha256": file_sha256,
            "company_facts": company_facts.model_dump(),
            "uploaded_at": now(),
        }
        result = await self.db[DOCUMENTS].insert_one(record)
        return DocumentMeta.model_validate(_out({**record, "_id": result.inserted_id}))

    async def find_document_by_sha(self, file_sha256: str) -> DocumentMeta | None:
        doc = await self.db[DOCUMENTS].find_one(
            {"file_sha256": file_sha256}, sort=[("uploaded_at", DESCENDING)]
        )
        return DocumentMeta.model_validate(_out(doc, "job_id")) if doc else None

    async def update_document(self, document_id: str, **fields: Any) -> None:
        if "job_id" in fields:
            fields["job_id"] = ObjectId(fields["job_id"])
        await self.db[DOCUMENTS].update_one({"_id": ObjectId(document_id)}, {"$set": fields})

    async def get_document(self, document_id: str) -> DocumentMeta | None:
        oid = _oid(document_id)
        doc = await self.db[DOCUMENTS].find_one({"_id": oid}) if oid else None
        return DocumentMeta.model_validate(_out(doc, "job_id")) if doc else None

    async def list_documents(self, limit: int) -> list[DocumentMeta]:
        cursor = self.db[DOCUMENTS].find().sort("uploaded_at", DESCENDING).limit(limit)
        return [DocumentMeta.model_validate(_out(d, "job_id")) async for d in cursor]

    async def create_job(self, document_id: str) -> Job:
        stamp = now()
        record = {
            "document_id": ObjectId(document_id),
            "status": JobStatus.QUEUED.value,
            "done": 0,
            "total": 0,
            "error": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        result = await self.db[JOBS].insert_one(record)
        job_id = str(result.inserted_id)
        await self.update_document(document_id, job_id=job_id)
        return Job.model_validate(_out({**record, "_id": result.inserted_id}, "document_id"))

    async def update_job(self, job_id: str, **fields: Any) -> None:
        values = {k: v.value if isinstance(v, JobStatus) else v for k, v in fields.items()}
        await self.db[JOBS].update_one(
            {"_id": ObjectId(job_id)}, {"$set": {**values, "updated_at": now()}}
        )

    async def get_job(self, job_id: str) -> Job | None:
        oid = _oid(job_id)
        doc = await self.db[JOBS].find_one({"_id": oid}) if oid else None
        return Job.model_validate(_out(doc, "document_id")) if doc else None

    async def save_results(
        self, document_id: str, notice: ParsedNotice, analyses: list[ItemAnalysis]
    ) -> None:
        doc_oid = ObjectId(document_id)
        await self.db[RESOLUTIONS].delete_many({"document_id": doc_oid})
        await self.db[ANALYSES].delete_many({"document_id": doc_oid})
        records = build_records(document_id, notice, analyses)
        if not records:
            return
        await self.db[RESOLUTIONS].insert_many(
            [
                {
                    **r.model_dump(mode="json", exclude={"id", "document_id"}),
                    "_id": ObjectId(r.id),
                    "document_id": doc_oid,
                }
                for r, _ in records
            ]
        )
        await self.db[ANALYSES].insert_many(
            [
                {
                    **a.model_dump(
                        mode="json", exclude={"id", "resolution_id", "document_id", "created_at"}
                    ),
                    "_id": ObjectId(a.id),
                    "resolution_id": ObjectId(a.resolution_id),
                    "document_id": doc_oid,
                    "created_at": a.created_at,
                }
                for _, a in records
            ]
        )

    async def _item(self, resolution_doc: Document) -> ReportItem:
        analysis_doc = await self.db[ANALYSES].find_one({"resolution_id": resolution_doc["_id"]})
        analysis = (
            Analysis.model_validate(_out(analysis_doc, "resolution_id", "document_id"))
            if analysis_doc
            else None
        )
        feedback: list[Feedback] = []
        if analysis_doc:
            cursor = (
                self.db[FEEDBACK]
                .find({"analysis_id": analysis_doc["_id"]})
                .sort("created_at", ASCENDING)
            )
            feedback = [Feedback.model_validate(_out(f, "analysis_id")) async for f in cursor]
        return ReportItem(
            resolution=Resolution.model_validate(_out(resolution_doc, "document_id")),
            analysis=analysis,
            feedback=feedback,
        )

    async def get_report(self, document_id: str) -> DocumentReport | None:
        doc = await self.get_document(document_id)
        if doc is None:
            return None
        cursor = (
            self.db[RESOLUTIONS].find({"document_id": ObjectId(document_id)}).sort("seq", ASCENDING)
        )
        items = [await self._item(r) async for r in cursor]
        job = await self.get_job(doc.job_id) if doc.job_id else None
        return DocumentReport(document=doc, job=job, items=items)

    async def get_report_item(self, resolution_id: str) -> ReportItem | None:
        oid = _oid(resolution_id)
        doc = await self.db[RESOLUTIONS].find_one({"_id": oid}) if oid else None
        return await self._item(doc) if doc else None

    async def get_analysis(self, analysis_id: str) -> Analysis | None:
        oid = _oid(analysis_id)
        doc = await self.db[ANALYSES].find_one({"_id": oid}) if oid else None
        return Analysis.model_validate(_out(doc, "resolution_id", "document_id")) if doc else None

    async def add_feedback(self, analysis_id: str, feedback: FeedbackIn) -> Feedback:
        record = {
            **feedback.model_dump(mode="json"),
            "analysis_id": ObjectId(analysis_id),
            "created_at": now(),
        }
        result = await self.db[FEEDBACK].insert_one(record)
        return Feedback.model_validate(_out({**record, "_id": result.inserted_id}, "analysis_id"))

    async def latest_eval_run(self) -> dict[str, Any] | None:
        doc = await self.db[EVAL_RUNS].find_one(sort=[("created_at", DESCENDING)])
        return _out(doc) if doc else None
