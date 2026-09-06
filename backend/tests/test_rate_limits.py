"""
Rate limits.

These exist because the app is going to be publicly reachable and some
of its endpoints are genuinely expensive — a model call costs money or
GPU time, extraction burns seconds of CPU, and a join code is guessable.
A limit that is configured but never applied protects nothing, which is
what these assert against.
"""

import pytest

from models import Course
from ratelimit import limiter


@pytest.fixture(autouse=True)
def _reset_limits():
    """Each test starts with a fresh allowance, whatever ran before."""
    limiter.reset()
    yield
    limiter.reset()


def _join(client, user, token: str, code: str = "WRONGX"):
    return client.as_user(user).post(
        "/api/courses/join",
        json={"join_code": code},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_join_attempts_are_capped(client, make_user):
    """
    Joining is the one place guessing gets an outsider somewhere they
    shouldn't be, so repeated wrong codes have to become expensive.
    """
    student = make_user(role="student")

    # The limit is 10/minute; wrong codes 404 until it bites.
    statuses = [_join(client, student, "token-a").status_code for _ in range(12)]

    assert statuses[0] == 404, "a wrong code should just fail, not be blocked"
    assert 429 in statuses, "brute-forcing join codes was never limited"
    assert statuses.count(429) >= 2


def test_one_caller_being_limited_does_not_block_another(client, make_user):
    """
    The limit is keyed on the caller's token, not their IP. A whole
    university behind one NAT would otherwise share a single allowance,
    and anyone determined could shed an IP-based limit by changing
    network.
    """
    first = make_user(role="student")
    second = make_user(role="student")

    for _ in range(12):
        _join(client, first, "token-first")

    # Different token, untouched allowance.
    assert _join(client, second, "token-second").status_code == 404


def test_grading_is_rate_limited(client, make_user):
    """
    Marking spends real money or GPU time per answer box.

    Uses an id that doesn't exist: the limit is checked before the
    endpoint runs, so the responses turn from 404 into 429 without any
    marking being done. That it bites before the work starts is the
    point — a limit applied afterwards would still have paid for it.
    """
    teacher = make_user(role="teacher")

    statuses = []
    for _ in range(45):  # the limit is 40/hour
        res = client.as_user(teacher).post(
            "/api/submissions/does-not-exist/grade",
            json={"provider": "self_hosted"},
            headers={"Authorization": "Bearer grading-token"},
        )
        statuses.append(res.status_code)
        if res.status_code == 429:
            break

    assert statuses[0] == 404
    assert 429 in statuses, "grading could be called without limit"


def test_bulk_grading_is_limited_harder_than_single(client, make_user):
    """
    One bulk call fans out across every submission on a paper, so it
    carries a much tighter allowance than marking one script.
    """
    teacher = make_user(role="teacher")

    statuses = []
    for _ in range(14):  # the limit is 10/hour
        res = client.as_user(teacher).post(
            "/api/questions/does-not-exist/grade-all",
            json={"provider": "self_hosted"},
            headers={"Authorization": "Bearer bulk-token"},
        )
        statuses.append(res.status_code)
        if res.status_code == 429:
            break

    assert 429 in statuses
    assert statuses.index(429) <= 11, "bulk marking should bite sooner than single marking"


def test_ordinary_reads_are_not_limited(client, make_user):
    """
    A limit that fires on a plain database read is just a way to lock a
    teacher out mid-demo, so only the costly endpoints carry one.
    """
    teacher = make_user(role="teacher")
    for _ in range(60):
        res = client.as_user(teacher).get(
            "/api/courses", headers={"Authorization": "Bearer reads-token"}
        )
        assert res.status_code == 200
