"""Fail-closed production composition for the MAGI API."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
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
    DecisionOperationExecutor,
    OperationStore,
    OperationWorker,
)
from magi.audit import AuditLedger, DecisionAuditService
from magi.domain import AgentName
from magi.evaluation import (
    DecisionEvaluationService,
    EvaluationStore,
    ModelPricing,
)
from magi.infrastructure import (
    EvidenceGatewayPolicy,
    HttpEvidenceGateway,
    PostgresPersistenceRuntime,
)
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
    openai_base_url: str | None = None
    postgres_min_size: int = 1
    postgres_max_size: int = 10
    model_max_attempts: int = 2
    evidence_allowed_hosts: frozenset[str] = frozenset()
    evidence_timeout_seconds: float = 8.0
    evidence_max_response_bytes: int = 20_000
    model_input_microusd_per_million_tokens: int | None = None
    model_output_microusd_per_million_tokens: int | None = None

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
        if self.openai_base_url is not None:
            _validate_model_base_url(self.openai_base_url)
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
        prices = (
            self.model_input_microusd_per_million_tokens,
            self.model_output_microusd_per_million_tokens,
        )
        if (prices[0] is None) != (prices[1] is None):
            raise ProductionConfigurationError(
                "model input and output evaluation prices must be configured together"
            )
        if any(value is not None and value < 0 for value in prices):
            raise ProductionConfigurationError(
                "model evaluation prices must be nonnegative"
            )
        try:
            EvidenceGatewayPolicy(
                allowed_hosts=self.evidence_allowed_hosts,
                timeout_seconds=self.evidence_timeout_seconds,
                max_response_bytes=self.evidence_max_response_bytes,
            )
        except ValueError as exc:
            raise ProductionConfigurationError(
                "invalid evidence gateway policy"
            ) from exc

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
            openai_base_url=_optional(values, "MAGI_OPENAI_BASE_URL"),
            skills_dir=Path(_required(values, "MAGI_SKILLS_DIR")),
            auth_policy_file=Path(_required(values, "MAGI_AUTH_POLICY_FILE")),
            postgres_min_size=_integer(values, "MAGI_POSTGRES_MIN_SIZE", 1),
            postgres_max_size=_integer(values, "MAGI_POSTGRES_MAX_SIZE", 10),
            model_max_attempts=_integer(values, "MAGI_MODEL_MAX_ATTEMPTS", 2),
            evidence_allowed_hosts=_hosts(values, "MAGI_EVIDENCE_ALLOWED_HOSTS"),
            evidence_timeout_seconds=_float(
                values, "MAGI_EVIDENCE_TIMEOUT_SECONDS", 8.0
            ),
            evidence_max_response_bytes=_integer(
                values, "MAGI_EVIDENCE_MAX_RESPONSE_BYTES", 20_000
            ),
            model_input_microusd_per_million_tokens=_optional_integer(
                values, "MAGI_MODEL_INPUT_MICROUSD_PER_MILLION_TOKENS"
            ),
            model_output_microusd_per_million_tokens=_optional_integer(
                values, "MAGI_MODEL_OUTPUT_MICROUSD_PER_MILLION_TOKENS"
            ),
        )


class ProductionPersistence(Protocol):
    invocation_ledger: InvocationLedger
    command_idempotency_store: CommandIdempotencyStore
    operation_store: OperationStore
    audit_ledger: AuditLedger
    evaluation_store: EvaluationStore

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
    operation_store = getattr(runtime, "operation_store", None)
    evaluation_store = runtime.evaluation_store
    audit_service = DecisionAuditService(runtime.audit_ledger)
    pricing = _evaluation_pricing(selected_settings)
    evaluation_service = DecisionEvaluationService(
        audit_service,
        runtime.invocation_ledger,
        evaluation_store,
        pricing=pricing,
    )
    deferred_service = _DeferredDecisionService()
    readiness_probe = _ProductionReadinessProbe(runtime, deferred_service)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.open(setup=True)
        worker_task: asyncio.Task[None] | None = None
        try:
            runner = selected_runner_factory(
                selected_settings,
                runtime.invocation_ledger,
            )
            graph = selected_graph_factory(runner, runtime.checkpointer)
            coordinator = selected_coordinator_factory(selected_settings)
            evidence_gateway = HttpEvidenceGateway(
                EvidenceGatewayPolicy(
                    allowed_hosts=selected_settings.evidence_allowed_hosts,
                    timeout_seconds=selected_settings.evidence_timeout_seconds,
                    max_response_bytes=selected_settings.evidence_max_response_bytes,
                )
            )
            application_service = DecisionApplicationService(
                graph,
                normalizer=coordinator,
                evidence_gateway=evidence_gateway,
                auditor=audit_service,
            )
            deferred_service.bind(application_service)
            if operation_store is not None:
                worker = OperationWorker(
                    operation_store,
                    DecisionOperationExecutor(application_service),
                    worker_id=f"api-{os.getpid()}",
                )
                worker_task = asyncio.create_task(
                    worker.run_forever(), name="magi-operation-worker"
                )
            app.state.magi_runtime = runtime
            app.state.magi_model = selected_settings.openai_model
            yield
        finally:
            if worker_task is not None:
                worker_task.cancel()
                await asyncio.gather(worker_task, return_exceptions=True)
            deferred_service.unbind()
            await runtime.close()

    return create_app(
        deferred_service,
        selected_authorizer,
        idempotency_store=runtime.command_idempotency_store,
        operation_store=operation_store,
        audit_service=audit_service,
        evaluation_service=evaluation_service,
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
        base_url=settings.openai_base_url,
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
        base_url=settings.openai_base_url,
    )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise ProductionConfigurationError(f"{name} is not configured")
    return value


def _optional(values: Mapping[str, str], name: str) -> str | None:
    value = values.get(name, "").strip()
    return value or None


def _validate_model_base_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProductionConfigurationError(
            "MAGI_OPENAI_BASE_URL must be an HTTP endpoint without credentials"
        )


def _integer(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ProductionConfigurationError(f"{name} must be an integer") from exc


def _float(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ProductionConfigurationError(f"{name} must be a number") from exc


def _optional_integer(values: Mapping[str, str], name: str) -> int | None:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ProductionConfigurationError(f"{name} must be an integer") from exc


def _evaluation_pricing(settings: ProductionSettings) -> tuple[ModelPricing, ...]:
    input_price = settings.model_input_microusd_per_million_tokens
    output_price = settings.model_output_microusd_per_million_tokens
    if input_price is None or output_price is None:
        return ()
    return (
        ModelPricing(
            model_name=settings.openai_model,
            input_microusd_per_million_tokens=input_price,
            output_microusd_per_million_tokens=output_price,
        ),
    )


def _hosts(values: Mapping[str, str], name: str) -> frozenset[str]:
    raw = values.get(name, "")
    return frozenset(host.strip() for host in raw.split(",") if host.strip())
