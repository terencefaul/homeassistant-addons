from gate_pin.ratelimit import RateLimiter


def test_backoff_kicks_in_after_a_few_failures():
    rl = RateLimiter()
    ip = "1.2.3.4"
    assert rl.check(ip, "pin").allowed
    for _ in range(3):
        rl.record_failure(ip, "pin")
    d = rl.check(ip, "pin")
    assert not d.allowed and d.retry_after > 0


def test_success_clears_backoff():
    rl = RateLimiter()
    ip = "1.2.3.4"
    for _ in range(4):
        rl.record_failure(ip, "pin")
    rl.record_success(ip, "pin")
    assert rl.check(ip, "pin").allowed


def test_ip_rotation_still_trips_the_global_budget():
    """Per-IP backoff alone is defeated by rotating addresses, which is exactly
    what an attacker behind a proxy pool does."""
    rl = RateLimiter(global_budget=10)
    for i in range(10):
        rl.record_failure(f"10.0.0.{i}", "pin")
    fresh = rl.check("172.16.0.1", "pin")
    assert not fresh.allowed and fresh.reason == "locked_out"


def test_pin_lockout_never_blocks_link_credentials():
    """The practical payoff of two credentials per grant: the strict limits
    protecting a 20-bit PIN must not degrade the 192-bit link."""
    rl = RateLimiter(global_budget=5)
    for i in range(5):
        rl.record_failure(f"10.0.0.{i}", "pin")
    assert not rl.check("192.168.1.1", "pin").allowed
    assert rl.check("192.168.1.1", "token").allowed


def test_lockout_is_announced_exactly_once_per_cooldown():
    rl = RateLimiter(global_budget=3)
    results = [rl.record_failure(f"10.0.0.{i}", "pin") for i in range(6)]
    assert sum(1 for r in results if r.lockout) == 1


def test_snapshot_reports_state():
    rl = RateLimiter(global_budget=4)
    rl.record_failure("1.1.1.1", "pin")
    snap = rl.snapshot()
    assert snap["pin_failures_in_window"] == 1
    assert snap["pin_failure_budget"] == 4
    assert snap["locked_out"] is False
