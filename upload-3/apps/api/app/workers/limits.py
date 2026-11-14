"""Resource limits for the process that runs one job (specification section 8.1).

Each job runs in its own child process. Before it loads any customer data, the child
caps its own address space, so a dataset that would exhaust the machine's memory
fails that one job instead of taking the server (and every other customer's work)
down with it. The supervising worker enforces the wall-clock limit from outside.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def apply_resource_limits(max_memory_mb: int) -> bool:
    """Cap this process's memory. Returns False where the platform cannot do so (Windows)."""
    # One numeric thread per job keeps CPU use predictable when several jobs share a machine.
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(variable, "1")
    if max_memory_mb <= 0:
        return False
    try:
        import resource
    except ImportError:
        logger.warning("memory limits are not available on this platform; relying on the job timeout only")
        return False
    limit = max_memory_mb * 1024 * 1024
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    return True
