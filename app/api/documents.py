"""Notice upload, job status, reports and analyst feedback (SPEC 9)."""

import hashlib
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.api.security import require_api_key
from app.config import Settings, get_settings
from app.observability import current_request_id
from app.reports.models import (
    DocumentMeta,
    DocumentReport,
    Feedback,
    FeedbackIn,
    Job,
    JobStatus,
    ReportItem,
)
from app.reports.runner import JobRunner
from app.reports.store import ReportStore
from app.rules.models import CompanyFacts

router = APIRouter(tags=["documents"])

PDF_MAGIC = b"%PDF-"
CRORE = 10_000_000
MAX_LIST = 100


class UploadResponse(BaseModel):
    document_id: str
    job_id: str
    duplicate: bool  # True: the same PDF with the same inputs was already analysed


def get_store(request: Request) -> ReportStore:
    store: ReportStore = request.app.state.report_store
    return store


def get_runner(request: Request) -> JobRunner:
    runner: JobRunner = request.app.state.job_runner
    return runner


Store = Annotated[ReportStore, Depends(get_store)]


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"unknown {what}")


async def _read_pdf(file: UploadFile, max_bytes: int) -> bytes:
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"file exceeds {max_bytes // 1_000_000} MB"
        )
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "file is not a PDF")
    return data


def _company_facts(turnover_cr: float | None, net_profit_cr: float | None) -> CompanyFacts:
    return CompanyFacts(
        turnover_inr=turnover_cr * CRORE if turnover_cr is not None else None,
        net_profit_inr=net_profit_cr * CRORE if net_profit_cr is not None else None,
    )


@router.post(
    "/documents",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
async def upload_document(
    background: BackgroundTasks,
    store: Store,
    runner: Annotated[JobRunner, Depends(get_runner)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File(description="AGM/EGM notice (text-based PDF)")],
    turnover_cr: Annotated[float | None, Form(ge=0)] = None,
    net_profit_cr: Annotated[float | None, Form()] = None,
) -> UploadResponse:
    pdf = await _read_pdf(file, settings.max_upload_mb * 1_000_000)
    sha = hashlib.sha256(pdf).hexdigest()
    facts = _company_facts(turnover_cr, net_profit_cr)

    existing = await store.find_document_by_sha(sha)
    if existing and existing.job_id and existing.company_facts == facts:
        job = await store.get_job(existing.job_id)
        if job and job.status != JobStatus.FAILED:
            return UploadResponse(document_id=existing.id, job_id=job.id, duplicate=True)

    filename = (file.filename or "notice.pdf")[:200]
    document = await store.create_document(filename, sha, facts)
    job = await store.create_job(document.id)
    background.add_task(
        runner.run, job.id, document.id, pdf, facts, request_id=current_request_id()
    )
    return UploadResponse(document_id=document.id, job_id=job.id, duplicate=False)


@router.get("/documents", response_model=list[DocumentMeta])
async def list_documents(
    store: Store, limit: Annotated[int, Query(ge=1, le=MAX_LIST)] = 20
) -> list[DocumentMeta]:
    return await store.list_documents(limit)


@router.get("/documents/{document_id}", response_model=DocumentReport)
async def get_document(document_id: str, store: Store) -> DocumentReport:
    report = await store.get_report(document_id)
    if report is None:
        raise _not_found("document")
    return report


@router.get("/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str, store: Store) -> Job:
    job = await store.get_job(job_id)
    if job is None:
        raise _not_found("job")
    return job


@router.get("/resolutions/{resolution_id}", response_model=ReportItem)
async def get_resolution(resolution_id: str, store: Store) -> ReportItem:
    item = await store.get_report_item(resolution_id)
    if item is None:
        raise _not_found("resolution")
    return item


@router.post(
    "/analyses/{analysis_id}/feedback",
    response_model=Feedback,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
async def add_feedback(analysis_id: str, feedback: FeedbackIn, store: Store) -> Feedback:
    if await store.get_analysis(analysis_id) is None:
        raise _not_found("analysis")
    return await store.add_feedback(analysis_id, feedback)


@router.get("/eval/latest")
async def latest_eval(store: Store) -> dict[str, Any]:
    run = await store.latest_eval_run()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no eval run yet")
    return run
