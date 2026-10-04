"""Build pipeline dependencies from settings. Providers are created on the first
job, not at startup: the student may need a 1.9 GB download and a model load."""

import logging
import threading

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.local_gguf import LocalGGUFProvider
from app.llm.providers import create_student, create_teacher
from app.pipeline.nodes import PipelineDeps, Progress, Retriever
from app.rules.models import RuleSpec

logger = logging.getLogger(__name__)


class PipelineFactory:
    def __init__(self, settings: Settings, retriever: Retriever, rules: list[RuleSpec]) -> None:
        self.settings = settings
        self.retriever = retriever
        self.rules = rules
        self._lock = threading.Lock()
        self._providers: tuple[LLMProvider, LLMProvider | None] | None = None

    def _teacher(self) -> LLMProvider | None:
        try:
            return create_teacher(self.settings)
        except (ValueError, NotImplementedError) as exc:
            logger.warning("teacher unavailable (%s): no fallback, no reasoner", exc)
            return None

    def providers(self) -> tuple[LLMProvider, LLMProvider | None]:
        """(extractor, teacher); the teacher is also the reasoner."""
        with self._lock:
            if self._providers is None:
                teacher = self._teacher()
                if self.settings.pipeline_extractor == "teacher":
                    if teacher is None:
                        raise RuntimeError("PIPELINE_EXTRACTOR=teacher but no teacher configured")
                    self._providers = (teacher, teacher)
                else:
                    self._providers = (create_student(self.settings), teacher)
            return self._providers

    @property
    def student_loaded(self) -> bool:
        providers = self._providers
        if providers is None:
            return False
        extractor = providers[0]
        return extractor.loaded if isinstance(extractor, LocalGGUFProvider) else True

    def __call__(self, progress: Progress) -> PipelineDeps:
        extractor, teacher = self.providers()
        uses_student = self.settings.pipeline_extractor == "student"
        return PipelineDeps(
            student=extractor,
            teacher=teacher if uses_student else None,
            reasoner=teacher,
            retriever=self.retriever,
            rules=self.rules,
            progress=progress,
        )
