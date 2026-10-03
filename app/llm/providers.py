"""Pick an LLM provider from config. The eval harness swaps providers by name."""

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.local_gguf import LocalGGUFProvider, resolve_gguf_path
from app.llm.openrouter import OpenRouterProvider


def create_teacher(settings: Settings, model: str | None = None) -> LLMProvider:
    """The teacher LLM (labels data, and is the student's fallback)."""
    if settings.teacher_provider == "vertex":
        raise NotImplementedError("TEACHER_PROVIDER=vertex is not implemented; use openrouter")
    return OpenRouterProvider(
        api_key=settings.openrouter_api_key.get_secret_value(),
        model=model or settings.teacher_model,
        base_url=settings.openrouter_base_url,
        max_output_tokens=settings.teacher_max_output_tokens,
        structured=settings.teacher_structured_output,
        reasoning_effort=settings.teacher_reasoning_effort or None,
    )


def create_student(settings: Settings) -> LLMProvider:
    """The extraction model configured by STUDENT_PROVIDER."""
    if settings.student_provider == "local_gguf":
        return LocalGGUFProvider(
            resolve_gguf_path(settings),
            model_name=settings.student_gguf_repo or None,
            n_threads=settings.student_n_threads,
            constrained=settings.student_constrained_json,
        )
    if settings.student_provider == "vertex":
        return create_teacher(settings)  # the teacher stands in for the student
    raise NotImplementedError("STUDENT_PROVIDER=base_hf runs only in notebooks/02_eval_student")
