"""Fail-closed production composition for the MAGI API."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI

from magi.agents import (
    DecisionNormalizer,
    InvocationLedger,
    LangChainCoordinator,
    LangChainPerspectiveRunner,
    PerspectiveRunner,
    PerspectiveSkillLoader,
)
from magi.application import (
    CommandIdempotencyStore,
    DecisionApplicationService,
    DecisionGraph,
    DecisionPreparationRequest,
    DecisionView,
)
from magi.domain import AgentName
from magi.infrastructure import PostgresPersistenceRuntime
from magi.orchestration import build_langgraph_workflow

from .app import DecisionApiService, create_app
from .auth import DecisionAuthorizer, HashedBearerAuthorizer


class ProductionConfigurationError(RuntimeError):
    """Raised before serving when required production configuration is invalid."""


@dataclass(frozen=True)
class ProductionSettings:
    """Explicit production settings; secrets are excluded from representations."""

    database_url: str = field(repr=False)
    openai_api_key: str = field(repr=False)
    openai_model: str
    skills_dir: Path
    auth_policy_file: Path
    postgres_min_size: int = 1
    postgres_max_size: int = 10
    model_max_attempts: int = 2

    def __post_init__(self) -> None:
        required = {
            "MAGI_DATABASE_URL": self.database_url,
            "OPENAI_API_KEY": self.openai_api_key,
            "MAGI_OPENAI_MODEL": self.openai_model,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            names = ", ".join(sorted(missing))
            raise ProductionConfigurationError(
                f"required production settings are empty: {names}"
            )
        if not self.skills_dir.is_dir():
            raise ProductionConfigurationError(
                f"MAGI_SKILLS_DIR is not a directory: {self.skills_dir}"
            )
        if not self.auth_policy_file.is_file():
            raise ProductionConfigurationError(
                f"MAGI_AUTH_POLICY_FILE is not a file: {self.auth_policy_file}"
            )
        if self.postgres_min_size < 0:
            raise ProductionConfigurationError("MAGI_POSTGRES_MIN_SIZE must be nonnegative")
        if self.postgres_max_size < 2:
            raise ProductionConfigurationError("MAGI_POSTGRES_MAX_SIZE must be at least 2")
        if self.postgres_min_size > self.postgres_max_size:
            raise ProductionConfigurationError(
                "MAGI_POSTGRES_MIN_SIZE cannot exceed MAGI_POSTGRES_MAX_SIZE"
            )
        if not 1 <= self.model_max_attempts <= 5:
            raise ProductionConfigurationError(
                "MAGI_MODEL_MAX_ATTEMPTS must be between 1 and 5"
            )

    @classmethod
    def from_environment(
        cls,
        *,
        env_file: str | Path | None = None,
    ) -> ProductionSettings:
        load_dotenv(dotenv_path=env_file)
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> ProductionSettings:
        return cls(
            database_url=_required(values, "MAGI_DATABASE_URL"),
            openai_api_key=_required(values, "OPENAI_API_KEY"),
            openai_model=_required(values, "MAGI_OPENAI_MODEL"),
            skills_dir=Path(_required(values, "MAGI_SKILLS_DIR")),
            auth_policy_file=Path(_required(values, "MAGI_AUTH_POLICY_FILE")),
            postgres_min_size=_integer(values, "MAGI_POSTGRES_MIN_SIZE", 1),
            postgres_max_size=_integer(values, "MAGI_POSTGRES_MAX_SIZE", 10),
            model_max_attempts=_integer(values, "MAGI_MODEL_MAX_ATTEMPTS", 2),
        )


class ProductionPersistence(Protocol):
    invocation_ledger: InvocationLedger
    command_idempotency_store: CommandIdempotencyStore

    @property
    def checkpointer(self) -> Any: ...

    async def open(self, *, setup: bool = True) -> None: ...

    async def close(self) -> None: ...

    async def is_ready(self, *, timeout_seconds: float = 2.0) -> bool: ...


class _DeferredDecisionService:
    """Bind the application service only after persistence startup succeeds."""

    def __init__(self) -> None:
        self._delegate: DecisionApiService | None = None

    def bind(self, delegate: DecisionApiService) -> None:
        if self._delegate is not None:
            raise RuntimeError("production decision service is already bound")
        self._delegate = delegate

    def unbind(self) -> None:
        self._delegate = None

    @property
    def ready(self) -> bool:
        return self._delegate is not None

    def _service(self) -> DecisionApiService:
        if self._delegate is None:
            raise RuntimeError("production decision service is not ready")
        return self._delegate

    async def prepare(self, request: DecisionPreparationRequest) -> DecisionView:
        return await self._service().prepare(request)

    async def get(self, decision_id: UUID, version: int) -> DecisionView:
        return await self._service().get(decision_id, version)

    async def confirm(
        self,
        decision_id: UUID,
        version: int,
        *,
        confirmed_at: datetime,
    ) -> DecisionView:
        return await self._service().confirm(
            decision_id,
            version,
            confirmed_at=confirmed_at,
        )

    async def run(self, decision_id: UUID, version: int) -> DecisionView:
        return await self._service().run(decision_id, version)

    async def cancel(
        self,
        decision_id: UUID,
        version: int,
        *,
        reason: str | None = None,
    ) -> DecisionView:
        return await self._service().cancel(decision_id, version, reason=reason)


RuntimeFactory = Callable[[ProductionSettings], ProductionPersistence]
RunnerFactory = Callable[[ProductionSettings, InvocationLedger], PerspectiveRunner]
GraphFactory = Callable[[PerspectiveRunner, Any], DecisionGraph]
CoordinatorFactory = Callable[[ProductionSettings], DecisionNormalizer]


class _ProductionReadinessProbe:
    def __init__(
        self,
        runtime: ProductionPersistence,
        service: _DeferredDecisionService,
    ) -> None:
        self._runtime = runtime
        self._service = service

    async def is_ready(self) -> bool:
        if not self._service.ready:
            return False
        return await self._runtime.is_ready(timeout_seconds=2.0)


def create_production_app(
    settings: ProductionSettings | None = None,
    *,
    authorizer: DecisionAuthorizer | None = None,
    runtime_factory: RuntimeFactory | None = None,
    runner_factory: RunnerFactory | None = None,
    graph_factory: GraphFactory | None = None,
    coordinator_factory: CoordinatorFactory | None = None,
) -> FastAPI:
    """Create the production ASGI app without insecure fallback adapters."""

    selected_settings = settings or ProductionSettings.from_environment()
    selected_authorizer = (
        authorizer if authorizer is not None else _build_authorizer(selected_settings)
    )
    selected_runtime_factory = runtime_factory or _build_runtime
    selected_runner_factory = runner_factory or _build_runner
    selected_graph_factory = graph_factory or _build_graph
    selected_coordinator_factory = coordinator_factory or _build_coordinator
    runtime = selected_runtime_factory(selected_settings)
    deferred_service = _DeferredDecisionService()
    readiness_probe = _ProductionReadinessProbe(runtime, deferred_service)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.open(setup=True)
        try:
            runner = selected_runner_factory(
                selected_settings,
                runtime.invocation_ledger,
            )
            graph = selected_graph_factory(runner, runtime.checkpointer)
            coordinator = selected_coordinator_factory(selected_settings)
            deferred_service.bind(
                DecisionApplicationService(graph, normalizer=coordinator)
            )
            app.state.magi_runtime = runtime
            app.state.magi_model = selected_settings.openai_model
            yield
        finally:
            deferred_service.unbind()
            await runtime.close()

    return create_app(
        deferred_service,
        selected_authorizer,
        idempotency_store=runtime.command_idempotency_store,
        lifespan=lifespan,
        readiness_probe=readiness_probe,
    )


def _build_authorizer(settings: ProductionSettings) -> DecisionAuthorizer:
    try:
        return HashedBearerAuthorizer.from_file(settings.auth_policy_file)
    except ValueError as exc:
        raise ProductionConfigurationError("invalid bearer authorization policy") from exc


def _build_runtime(settings: ProductionSettings) -> ProductionPersistence:
    return PostgresPersistenceRuntime(
        settings.database_url,
        min_size=settings.postgres_min_size,
        max_size=settings.postgres_max_size,
    )


def _build_runner(
    settings: ProductionSettings,
    ledger: InvocationLedger,
) -> PerspectiveRunner:
    loader = PerspectiveSkillLoader(settings.skills_dir)
    for agent in AgentName:
        loader.system_prompt(agent)
    return LangChainPerspectiveRunner.from_openai(
        model=settings.openai_model,
        skills_root=settings.skills_dir,
        api_key=settings.openai_api_key,
        max_attempts=settings.model_max_attempts,
        ledger=ledger,
    )


def _build_graph(runner: PerspectiveRunner, checkpointer: Any) -> DecisionGraph:
    return build_langgraph_workflow(runner, checkpointer=checkpointer)


def _build_coordinator(settings: ProductionSettings) -> DecisionNormalizer:
    return LangChainCoordinator.from_openai(
        model=settings.openai_model,
        skills_root=settings.skills_dir,
        api_key=settings.openai_api_key,
    )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise ProductionConfigurationError(f"{name} is not configured")
    return value


def _integer(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ProductionConfigurationError(f"{name} must be an integer") from exc
