import contextvars
import logging
import os
import sys

import structlog

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")
workflow_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("workflow_id", default="-")
run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")
activity_type_var: contextvars.ContextVar[str] = contextvars.ContextVar("activity_type", default="-")
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
task_queue_var: contextvars.ContextVar[str] = contextvars.ContextVar("task_queue", default="-")

_loki_handler = None


def _add_correlation_ids(
    logger: logging.Logger, method_name: str, event_dict: dict
) -> dict:
    event_dict["trace_id"] = trace_id_var.get()
    event_dict["workflow_id"] = workflow_id_var.get()
    event_dict["run_id"] = run_id_var.get()
    event_dict["activity_type"] = activity_type_var.get()
    event_dict["request_id"] = request_id_var.get()
    event_dict["task_queue"] = task_queue_var.get()
    return event_dict


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _add_correlation_ids,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    loki_url = os.getenv("LOKI_URL")
    if loki_url:
        _setup_loki_handler(loki_url)


def _setup_loki_handler(loki_url: str) -> None:
    global _loki_handler
    try:
        import logging_loki
        from multiprocessing import Queue

        app_name = os.getenv("APP_NAME", "contract-review")
        environment = os.getenv("ENVIRONMENT", "development")
        batch_interval = float(os.getenv("LOKI_BATCH_INTERVAL", "5.0"))

        loki_handler = logging_loki.LokiBatchQueueHandler(
            Queue(-1),
            url=f"{loki_url}/loki/api/v1/push",
            tags={
                "app": app_name,
                "environment": environment,
            },
            version="2",
            flush_interval=batch_interval,
        )

        root_logger = logging.getLogger()
        root_logger.addHandler(loki_handler)
        _loki_handler = loki_handler
    except ImportError:
        pass


def get_logger(name: str = "contract_review") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def flush_loki() -> None:
    if _loki_handler is not None:
        try:
            _loki_handler.flush()
        except Exception:
            pass
