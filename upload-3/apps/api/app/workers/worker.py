"""The background worker: claims queued jobs and supervises the process running each one.

    python -m app.workers.worker

It can run next to the API in the same container, or as several separate processes on
several machines: the queue hands each job to exactly one of them.

For each job the worker starts a child process (``runner``) and then only watches it:
it sends heartbeats, stops the child if the customer cancels or the time limit passes,
and decides what happens if the child dies. The worker itself never loads customer
data, so it stays small and survives a job that runs out of memory.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

from ..core.config import Settings, get_settings
from ..core.logging import configure_logging
from ..models import JobStatus
from . import queue
from .runner import MEMORY_MESSAGE

logger = logging.getLogger(__name__)

STALE_CHECK_SECONDS = 15
TERMINATE_GRACE_SECONDS = 5


@dataclass
class Running:
    claim: queue.Claim
    process: subprocess.Popen
    started: float
    stopping_for: str | None = None  # "cancel" | "timeout" once the worker has asked it to stop
    stop_requested_at: float = 0.0


class Worker:
    def __init__(self, settings: Settings, worker_id: str | None = None) -> None:
        self.settings = settings
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.running: dict[uuid.UUID, Running] = {}
        self._stop = False
        self._last_heartbeat = self._last_stale_check = 0.0

    # ------------------------------------------------------------------ lifecycle
    def request_stop(self, *_: object) -> None:
        self._stop = True

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        logger.info(
            "worker started", extra={"worker_id": self.worker_id, "concurrency": self.settings.worker_concurrency}
        )
        while not self._stop:
            claimed = self.tick()
            if not claimed:
                time.sleep(self.settings.worker_poll_seconds)
        self.shutdown()

    def shutdown(self) -> None:
        """Stop children and hand their jobs back to the queue so another worker can take them."""
        for item in list(self.running.values()):
            self._terminate(item)
            item.process.wait()
            outcome = queue.retry_or_fail(item.claim.job_id, item.claim.lock_token,
                                          "The analysis was interrupted by a restart. Please try again.")  # fmt: skip
            logger.info("job released on shutdown", extra={"job_id": str(item.claim.job_id), "outcome": outcome})
        self.running.clear()
        logger.info("worker stopped", extra={"worker_id": self.worker_id})

    # ----------------------------------------------------------------------- loop
    def tick(self) -> bool:
        """One pass of the supervision loop. Returns True if a new job was claimed."""
        now = time.monotonic()
        self._reap()
        self._enforce_time_limit(now)
        if now - self._last_heartbeat >= self.settings.job_heartbeat_seconds or self._wants_fast_heartbeat():
            self._heartbeat()
            self._last_heartbeat = now
        if now - self._last_stale_check >= STALE_CHECK_SECONDS:
            for job_id, outcome in queue.recover_stale(self.settings.job_stale_after_seconds):
                logger.warning("recovered a job whose worker stopped responding",
                               extra={"job_id": str(job_id), "outcome": outcome})  # fmt: skip
            self._last_stale_check = now
        if len(self.running) < self.settings.worker_concurrency and not self._stop:
            claim = queue.claim_next(self.worker_id)
            if claim is not None:
                self._start(claim)
                return True
        return False

    def _wants_fast_heartbeat(self) -> bool:
        # Poll for cancellation every pass while jobs are running, so "Cancel" feels immediate.
        return bool(self.running)

    def _start(self, claim: queue.Claim) -> None:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.workers.runner", str(claim.job_id), str(claim.lock_token)],
            stdin=subprocess.DEVNULL,
        )
        self.running[claim.job_id] = Running(claim=claim, process=process, started=time.monotonic())
        logger.info("job claimed", extra={"job_id": str(claim.job_id), "pid": process.pid})

    def _terminate(self, item: Running, reason: str | None = None) -> None:
        if item.process.poll() is None:
            item.process.terminate()
        item.stopping_for, item.stop_requested_at = reason or item.stopping_for, time.monotonic()

    def _heartbeat(self) -> None:
        if not self.running:
            return
        states = queue.heartbeat([item.claim for item in self.running.values()])
        for job_id, state in states.items():
            item = self.running[job_id]
            if state == "cancel" and item.stopping_for is None:
                self._terminate(item, "cancel")
            elif state == "lost" and item.process.poll() is None and item.stopping_for is None:
                self._terminate(item, "lost")  # the job was reassigned; stop working on it

    def _enforce_time_limit(self, now: float) -> None:
        for item in self.running.values():
            if item.stopping_for is None and now - item.started > self.settings.job_timeout_seconds:
                self._terminate(item, "timeout")
            elif (
                item.stopping_for
                and item.process.poll() is None
                and now - item.stop_requested_at > TERMINATE_GRACE_SECONDS
            ):
                item.process.kill()

    def _reap(self) -> None:
        for job_id, item in list(self.running.items()):
            code = item.process.poll()
            if code is None:
                continue
            del self.running[job_id]
            claim, extra = item.claim, {"job_id": str(job_id), "exit_code": code}
            if item.stopping_for == "cancel":
                queue.finish(
                    claim.job_id, claim.lock_token, JobStatus.CANCELLED, error_message="Cancelled at your request."
                )
                logger.info("job cancelled", extra=extra)
            elif item.stopping_for == "timeout":
                minutes = self.settings.job_timeout_seconds // 60
                queue.finish(claim.job_id, claim.lock_token, JobStatus.FAILED,
                             error_message=f"The analysis took longer than the {minutes}-minute limit and was stopped. "
                                           "Try a smaller dataset or a narrower question.")  # fmt: skip
                logger.error("job exceeded its time limit", extra=extra)
            elif code == 0 or item.stopping_for == "lost":
                # The child records its own outcome. If it somehow exited cleanly without doing so, fail the job.
                if queue.finish(claim.job_id, claim.lock_token, JobStatus.FAILED,
                                error_message="The analysis stopped unexpectedly. Please try again."):  # fmt: skip
                    logger.error("job exited without recording an outcome", extra=extra)
            elif code < 0:
                # Killed by a signal, most often the operating system reclaiming memory. Running the
                # same data again would end the same way, so the job is failed rather than retried.
                queue.finish(claim.job_id, claim.lock_token, JobStatus.FAILED, error_message=MEMORY_MESSAGE)
                logger.error("job process was killed", extra=extra)
            else:
                # The child crashed (EXIT_RETRY) or could not start. Worth another attempt, up to the limit.
                outcome = queue.retry_or_fail(claim.job_id, claim.lock_token,
                                              "The analysis failed repeatedly with an internal error. It has been logged.")  # fmt: skip
                logger.error("job crashed", extra={**extra, "outcome": outcome})


def main() -> None:
    configure_logging()
    Worker(get_settings()).run_forever()


if __name__ == "__main__":
    main()
