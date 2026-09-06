"""
Rate limits.

The costs worth bounding here aren't uniform, so the limits aren't
either. Three kinds of endpoint need protecting for three different
reasons:

  - anything that calls an LLM spends real money or GPU time per request
  - extraction and PDF rendering burn CPU for seconds at a time, so a
    handful of concurrent requests is enough to stall the server
  - joining a course guesses a 6-character code, which is the one place
    an outsider can brute-force their way into somewhere they shouldn't be

Everything else is an ordinary database read and is left alone; a limit
that never fires is just a way to lock a teacher out during a demo.
"""

import hashlib

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _client_key(request: Request) -> str:
    """
    Identify the caller by their token where there is one, IP otherwise.

    Limiting purely by IP is wrong in both directions here: a whole
    university behind one NAT would share a single allowance, while
    anyone who cares can rotate addresses to escape it. The bearer token
    is per-user and can't be shed by changing network.

    It's hashed rather than used directly so credentials never reach a
    log line or an in-memory limiter key. This deliberately doesn't
    validate the token — an invalid one still gets rate limited, which is
    what you want from something standing in front of authentication.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return "user:" + hashlib.sha256(token.encode()).hexdigest()[:32]

    return "ip:" + (get_remote_address(request) or "unknown")


limiter = Limiter(key_func=_client_key)

# Per answer box, one model call — a paper with several parts is several
# calls, and a bulk run multiplies that by the class size.
LLM_LIMIT = "40/hour"

# Bulk marking fans out across every submission on a paper, so it's
# bounded far more tightly than a single run.
BULK_LLM_LIMIT = "10/hour"

# Extraction is OpenCV over a full-resolution photo; finalizing runs a
# headless browser. Both are seconds of CPU, not milliseconds.
HEAVY_CPU_LIMIT = "30/minute"

# The only endpoint where guessing gets you something: a wrong code is
# cheap to try, so make trying repeatedly expensive.
JOIN_LIMIT = "10/minute"
