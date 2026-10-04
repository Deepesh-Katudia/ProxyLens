"""Background analysis of an uploaded notice (SPEC 9: FastAPI BackgroundTasks).

One job runs at a time: the local GGUF model holds a single llama.cpp context,
and a 4 vCPU Cloud Run instance has no spare cores for a second job. Queued jobs
wait on the lock with status `queued`.

Moving off BackgroundTasks (not built, SPEC 9): POST /documents would write the
PDF to GCS and enqueue a Cloud Tasks task (or publish to Pub/Sub) carrying the
job id; a worker service runs `JobRunner.run` and updates the same `jobs`
document, so the API and frontend stay unchanged and jobs survive restarts.
"""

import asyncio
import logging
from collections.abc import Callable

from app.parsing.company import guess_company
from app.parsing.notice import segment_notice
from app.parsing.pdf_text import extract_pages
from app.pipeline.graph import build_graph
from app.pipeline.nodes import PipelineDeps, Progress
from app.pipeline.state import PipelineState
from app.reports.models import JobStatus
from app.reports.store import ReportStore
from app.rules.models import CompanyFacts

logger = logging.getLogger(__name__)

DepsFactory = Callable[[Progress], PipelineDeps]
MAX_ERROR_CHARS = 500


class NoAgendaItemsError(ValueError):
    """The PDF parsed, but no agenda items were found (not a notice, or scanned)."""


class JobRunner:
    def __init__(self, store: ReportStore, deps_factory: DepsFactory) -> None:
        self.store = store
        self.deps_factory = deps_factory
        self._lock = asyncio.Lock()

    async def run(self, job_id: str, document_id: str, pdf: bytes, company: CompanyFacts) -> None:
        async with self._lock:
            try:
                await self._run(job_id, document_id, pdf, company)
            except Exception as exc:  # recorded on the job for the UI; never re-raised
                logger.exception("job %s failed", job_id)
                # ValueErrors carry parser messages meant for the user; others get the type.
                text = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"
                message = text[:MAX_ERROR_CHARS]
                await self.store.update_job(job_id, status=JobStatus.FAILED, error=message)

    async def _run(self, job_id: str, document_id: str, pdf: bytes, company: CompanyFacts) -> None:
        await self.store.update_job(job_id, status=JobStatus.PARSING)
        pages = await asyncio.to_thread(extract_pages, pdf)
        notice = await asyncio.to_thread(segment_notice, pages)
        await self.store.update_document(
            document_id,
            company=guess_company(pages) or None,
            meeting_type=notice.meeting_type,
            pages=notice.page_count,
            item_count=len(notice.items),
        )
        if not notice.items:
            raise NoAgendaItemsError("no agenda items found; is this a text-based AGM/EGM notice?")

        async def progress(stage: str, done: int, total: int) -> None:
            await self.store.update_job(job_id, status=JobStatus(stage), done=done, total=total)

        graph = build_graph(self.deps_factory(progress))
        final = await graph.ainvoke(PipelineState(notice=notice, company=company))
        await self.store.save_results(document_id, notice, list(final["analyses"]))
        total = len(notice.items)
        await self.store.update_job(job_id, status=JobStatus.DONE, done=total, total=total)
