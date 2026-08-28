"""Structured per-query trace logging — terminal + SQLite."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.audit.db import connect, init_audit_db

_current_tracer: ContextVar[Optional["QueryTracer"]] = ContextVar(
    "query_tracer", default=None
)

trace_logger = logging.getLogger("ampcus.trace")
_handler_installed = False


class TraceFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        agent = getattr(record, "agent", "SYSTEM")
        qid = getattr(record, "query_id", "—")
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:12]
        lvl = record.levelname[:4]
        return f"[{ts}] {lvl} [{agent:<16}] [{qid[:8]}] {record.getMessage()}"


def _ensure_trace_handler() -> None:
    global _handler_installed
    if _handler_installed:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(TraceFormatter())
    trace_logger.addHandler(handler)
    trace_logger.setLevel(logging.DEBUG)
    trace_logger.propagate = False
    _handler_installed = True


def set_tracer(tracer: Optional["QueryTracer"]) -> None:
    _current_tracer.set(tracer)


def get_tracer() -> Optional["QueryTracer"]:
    return _current_tracer.get()


def tracer_from_state(state: Optional[Dict[str, Any]]) -> Optional["QueryTracer"]:
    if state:
        t = state.get("tracer")
        if isinstance(t, QueryTracer):
            return t
    return get_tracer()


class QueryTracer:
    def __init__(
        self,
        *,
        user_id: str | None,
        user_email: str,
        query: str,
        session_id: str | None = None,
    ):
        _ensure_trace_handler()
        self.query_id = str(uuid.uuid4())
        self.user_id = user_id
        self.user_email = user_email
        self.query = query
        self.session_id = session_id
        self.start_time = time.time()
        self.steps: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}

    def _log(self, level: str, agent: str, message: str, **meta: Any) -> Dict[str, Any]:
        step = {
            "query_id": self.query_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round((time.time() - self.start_time) * 1000),
            "level": level,
            "agent": agent,
            "message": message,
            **meta,
        }
        self.steps.append(step)
        log_fn = getattr(trace_logger, level.lower(), trace_logger.info)
        log_fn(message, extra={"agent": agent, "query_id": self.query_id})
        return step

    def received(self, role: str, session_id: str | None = None) -> None:
        sid = session_id or self.session_id or ""
        self._log(
            "INFO",
            "SUPERVISOR",
            f"Query received from {self.user_email} (role={role})",
            event="query_received",
            role=role,
            session_id=sid,
        )

    def supervisor_classified(self, intent: str, confidence: str, reason: str) -> None:
        self._log(
            "INFO",
            "SUPERVISOR",
            f"Intent classified: {intent} (confidence={confidence})",
            event="supervisor_classified",
            intent=intent,
            confidence=confidence,
            reason=reason,
        )

    def supervisor_routed(self, target_node: str) -> None:
        label = target_node.upper().replace("_", " ")
        self._log(
            "INFO",
            "SUPERVISOR",
            f"Routing → {label}",
            event="supervisor_routed",
            target_node=target_node,
        )

    def cache_checked(self, hit: bool, similarity: Optional[float] = None) -> None:
        if hit:
            sim = f"{similarity:.3f}" if similarity is not None else "n/a"
            self._log(
                "INFO",
                "CACHE",
                f"Cache HIT (similarity={sim}) — skipping pipeline",
                event="cache_hit",
                similarity=similarity,
            )
        else:
            sim = f"{similarity:.3f}" if similarity is not None else "n/a"
            self._log(
                "INFO",
                "CACHE",
                f"Cache MISS (best={sim}) — running pipeline",
                event="cache_miss",
                similarity=similarity,
            )

    def agent_started(self, agent: str, action: str, **meta: Any) -> None:
        self._log(
            "INFO",
            agent.upper(),
            f"Started: {action}",
            event="agent_started",
            action=action,
            **meta,
        )

    def agent_step(self, agent: str, message: str, **meta: Any) -> None:
        self._log(
            "DEBUG",
            agent.upper(),
            message,
            event="agent_step",
            **meta,
        )

    def agent_tool_call(self, agent: str, tool: str, params: dict) -> None:
        param_str = ", ".join(f"{k}={v}" for k, v in params.items())
        self._log(
            "DEBUG",
            agent.upper(),
            f"Tool call: {tool}({param_str})",
            event="tool_call",
            tool=tool,
            params=params,
        )

    def agent_tool_result(self, agent: str, tool: str, result_summary: str) -> None:
        self._log(
            "DEBUG",
            agent.upper(),
            f"Tool result [{tool}]: {result_summary}",
            event="tool_result",
            tool=tool,
            result_summary=result_summary,
        )

    def kb_retrieved(self, dept: str, chunks: int, top_score: float) -> None:
        self._log(
            "INFO",
            "RETRIEVER",
            f"Retrieved {chunks} chunks from {dept.upper()} KB (top_score={top_score:.3f})",
            event="kb_retrieved",
            dept=dept,
            chunks=chunks,
            top_score=top_score,
        )

    def severity_scored(self, severity: str, model: str, reason: str) -> None:
        self._log(
            "INFO",
            "SEVERITY",
            f"Severity={severity.upper()} model={model} — {reason}",
            event="severity_scored",
            severity=severity,
            model=model,
            reason=reason,
        )

    def escalated(self, ticket_id: str | None, notified: list) -> None:
        tid = ticket_id or "pending"
        names = ", ".join(notified) if notified else "none"
        self._log(
            "WARNING",
            "ESCALATION",
            f"Ticket {tid} — notified: {names}",
            event="escalated",
            ticket_id=ticket_id,
            notified=notified,
        )

    def llm_called(self, agent: str, model: str, prompt_tokens: int) -> None:
        self._log(
            "DEBUG",
            agent.upper(),
            f"LLM call: model={model} prompt_tokens={prompt_tokens}",
            event="llm_called",
            model=model,
            prompt_tokens=prompt_tokens,
        )

    def llm_responded(
        self, agent: str, model: str, completion_tokens: int, cost_usd: float
    ) -> None:
        self._log(
            "DEBUG",
            agent.upper(),
            f"LLM response: tokens={completion_tokens} cost=${cost_usd:.5f}",
            event="llm_responded",
            model=model,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )

    def agent_done(self, agent: str, outcome: str, **meta: Any) -> None:
        self._log(
            "INFO",
            agent.upper(),
            f"Done: {outcome}",
            event="agent_done",
            outcome=outcome,
            **meta,
        )

    def complete(self, model_used: str, node: str, intent: str) -> None:
        duration = round((time.time() - self.start_time) * 1000)
        self.summary = {
            "intent": intent,
            "target_node": node,
            "model_used": model_used,
            "duration_ms": duration,
        }
        self._log(
            "INFO",
            "COMPLETE",
            f"intent={intent} node={node} model={model_used} "
            f"duration={duration}ms steps={len(self.steps)}",
            event="complete",
            model_used=model_used,
            node=node,
            intent=intent,
            duration_ms=duration,
        )

    def error(self, agent: str, message: str, exc: Exception | None = None) -> None:
        detail = f" — {type(exc).__name__}: {exc}" if exc else ""
        self._log(
            "ERROR",
            agent.upper(),
            f"Error: {message}{detail}",
            event="error",
            error_message=message,
        )

    def save(self) -> None:
        from app.audit.store import save_query_trace

        save_query_trace(self)
