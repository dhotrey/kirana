import asyncio

from ingestion.rate_limit import GeminiRateLimiter, retry_backoff_seconds


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_first_wait_does_not_sleep():
    fake = FakeClock()
    limiter = GeminiRateLimiter(12.0, clock=fake.clock, sleep=fake.sleep)
    limiter.wait()
    assert fake.sleeps == []


def test_second_wait_sleeps_remaining_interval():
    fake = FakeClock()
    limiter = GeminiRateLimiter(12.0, clock=fake.clock, sleep=fake.sleep)
    limiter.wait()
    fake.now += 5
    limiter.wait()
    assert fake.sleeps == [7.0]


def test_wait_after_interval_does_not_sleep():
    fake = FakeClock()
    limiter = GeminiRateLimiter(12.0, clock=fake.clock, sleep=fake.sleep)
    limiter.wait()
    fake.now += 12
    limiter.wait()
    assert fake.sleeps == []


def test_async_wait_sleeps_remaining_interval():
    async def run_test() -> None:
        fake = FakeClock()

        async def fake_async_sleep(seconds: float) -> None:
            fake.sleep(seconds)

        limiter = GeminiRateLimiter(
            12.0,
            clock=fake.clock,
            sleep=fake.sleep,
            async_sleep=fake_async_sleep,
        )
        await limiter.wait_async()
        fake.now += 5
        await limiter.wait_async()
        assert fake.sleeps == [7.0]

    asyncio.run(run_test())


def test_async_wait_yields_control_while_sleeping():
    async def run_test() -> None:
        fake = FakeClock()
        sleep_started = asyncio.Event()
        release_sleep = asyncio.Event()

        async def fake_async_sleep(seconds: float) -> None:
            fake.sleeps.append(seconds)
            sleep_started.set()
            await release_sleep.wait()
            fake.now += seconds

        limiter = GeminiRateLimiter(
            12.0,
            clock=fake.clock,
            sleep=fake.sleep,
            async_sleep=fake_async_sleep,
        )
        await limiter.wait_async()

        waiting_task = asyncio.create_task(limiter.wait_async())
        await asyncio.wait_for(sleep_started.wait(), timeout=1)

        probe_ran = False

        async def probe() -> None:
            nonlocal probe_ran
            await asyncio.sleep(0)
            probe_ran = True

        await asyncio.wait_for(probe(), timeout=1)
        assert probe_ran

        release_sleep.set()
        await waiting_task
        assert fake.sleeps == [12.0]

    asyncio.run(run_test())


def test_retry_backoff_strategies():
    assert retry_backoff_seconds(
        3, strategy="constant", base_seconds=1, max_seconds=30
    ) == 1
    assert retry_backoff_seconds(
        3, strategy="linear", base_seconds=1, max_seconds=30
    ) == 3
    assert retry_backoff_seconds(
        3, strategy="exponential", base_seconds=1, max_seconds=30
    ) == 4
    assert retry_backoff_seconds(
        10, strategy="exponential", base_seconds=10, max_seconds=30
    ) == 30
