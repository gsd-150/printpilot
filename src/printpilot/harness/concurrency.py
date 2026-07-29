"""Bounded parallel execution.

At roughly twenty seconds per call, a 160-case split takes about fifty minutes
serially and a five-configuration ablation takes most of a working day. That is
long enough to discourage re-running an evaluation, which is exactly the habit an
evaluation harness exists to encourage.

Threads rather than asyncio: the work is entirely I/O wait on HTTP, the OpenAI SDK's
synchronous client is thread-safe, and going async would mean rewriting the client
and every caller for no additional throughput.

Two properties the callers depend on:

* **Results come back in input order**, whatever order they complete in. Predictions
  are matched to cases positionally downstream, so out-of-order results would
  silently score the wrong case.
* **Concurrency does not change results.** Each case is an independent call at
  temperature 0; nothing is shared but counters, and those are guarded.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

DEFAULT_WORKERS = 8

#: An upper bound applied even when a caller asks for more. The relay advertises no
#: rate limit, but "no documented limit" is not "no limit", and a runaway fan-out
#: would be indistinguishable from abuse from the provider's side.
MAX_WORKERS = 32


def resolve_workers(requested: int | None) -> int:
    if requested is None:
        return DEFAULT_WORKERS
    if requested < 1:
        msg = f"workers must be at least 1, got {requested}"
        raise ValueError(msg)
    return min(requested, MAX_WORKERS)


def map_bounded[T, R](
    fn: Callable[[T], R],
    items: Sequence[T],
    *,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[R]:
    """Apply ``fn`` across ``items`` with at most ``workers`` calls in flight.

    Exceptions propagate. A genuine bug should stop the run rather than be averaged
    into the metrics; failures that are *expected* — an LLM timeout, say — are
    handled by the diagnoser, which turns them into an explicit abstention.
    """
    count = resolve_workers(workers)
    total = len(items)
    if total == 0:
        return []
    if count == 1:
        results: list[R] = []
        for index, item in enumerate(items, start=1):
            results.append(fn(item))
            if progress is not None:
                progress(index, total)
        return results

    ordered: list[R | None] = [None] * total
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures: dict[Future[R], int] = {
            pool.submit(fn, item): index for index, item in enumerate(items)
        }
        for done, future in enumerate(as_completed(futures), start=1):
            ordered[futures[future]] = future.result()
            if progress is not None:
                progress(done, total)

    # None is a legitimate R for some callers, so completion is asserted by count
    # rather than by testing for None.
    return [value for value in ordered]  # type: ignore[misc]
