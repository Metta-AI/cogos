"""Mirror executor runtime output into session artifact steps."""

from __future__ import annotations

import io
import logging
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Callable, Iterator

_FORMATTER = logging.Formatter()


class _ArtifactLoggingHandler(logging.Handler):
    def __init__(
        self,
        record_step: Callable[[str, dict], None],
        *,
        excluded_prefixes: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._record_step = record_step
        self._excluded_prefixes = excluded_prefixes

    def emit(self, record: logging.LogRecord) -> None:
        if any(record.name.startswith(prefix) for prefix in self._excluded_prefixes):
            return
        try:
            payload = {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["exception"] = _FORMATTER.formatException(record.exc_info)
            self._record_step("executor_log", payload)
        except Exception:
            self.handleError(record)


class _LineBufferedTee(io.TextIOBase):
    def __init__(self, stream, sink: Callable[[str], None]) -> None:  # noqa: ANN001
        self._stream = stream
        self._sink = sink
        self._buffer = ""

    @property
    def encoding(self) -> str:
        return getattr(self._stream, "encoding", "utf-8")

    def writable(self) -> bool:
        return True

    def write(self, data: str) -> int:
        text = str(data)
        self._stream.write(text)
        self._buffer += text
        self._flush_complete_lines()
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    def finish(self) -> None:
        if self._buffer:
            line = self._buffer.rstrip("\r\n")
            self._buffer = ""
            if line:
                self._sink(line)
        self.flush()

    def _flush_complete_lines(self) -> None:
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line:
                self._sink(line)


@contextmanager
def capture_executor_artifacts(
    record_step: Callable[[str, dict], None],
    *,
    min_log_level: int = logging.INFO,
) -> Iterator[None]:
    """Capture runtime logger/stdout/stderr output as artifact steps."""
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    if previous_level > min_log_level:
        root_logger.setLevel(min_log_level)

    log_handler = _ArtifactLoggingHandler(
        record_step,
        excluded_prefixes=("cogos.executor.log_capture", "cogos.executor.session_store"),
    )
    root_logger.addHandler(log_handler)

    stdout_tee = _LineBufferedTee(sys.stdout, lambda line: record_step("executor_stdout", {"message": line}))
    stderr_tee = _LineBufferedTee(sys.stderr, lambda line: record_step("executor_stderr", {"message": line}))

    try:
        with redirect_stdout(stdout_tee), redirect_stderr(stderr_tee):
            yield
    finally:
        stdout_tee.finish()
        stderr_tee.finish()
        root_logger.removeHandler(log_handler)
        root_logger.setLevel(previous_level)
