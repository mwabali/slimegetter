import json
import os
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class LeviReview(BaseModel):
    model_config = ConfigDict(frozen=True)
    summary: str = Field(min_length=1)
    experiments: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    execution_permission: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LeviService:
    """AI reviewer isolated from strategy configuration and execution."""
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key

    def review(self, journal_context: str) -> LeviReview:
        api_key = self._api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the openai package to enable Levi") from exc
        response = OpenAI(api_key=api_key, timeout=15.0, max_retries=0).responses.create(model=self._model, input=("Review this trading journal. Return strict JSON with summary, experiments, citations. Never recommend execution or direct strategy changes.\n" + journal_context))
        return LeviReview(**json.loads(response.output_text), execution_permission=False)
