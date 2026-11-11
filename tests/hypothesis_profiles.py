"""Hypothesis settings for the property checks.

HYPOTHESIS_PROFILE picks one:
  thorough  the default: every check runs all its examples (local runs and the nightly workflow)
  ci        the required CI jobs: a check that starts a process per example runs a quarter of them

Both draw new examples on every run. A failure prints the falsifying example and the @reproduce_failure line that
replays it; the explicit @example cases run in both.
"""
import os

PROFILE = os.environ.get("HYPOTHESIS_PROFILE") or "thorough"

try:
    from hypothesis import HealthCheck, settings
except ImportError:
    pass
else:
    # Hypothesis loads its own "ci" profile by itself when CI is set, and that one is derandomized: every CI run would
    # draw the same examples. Both profiles here replace it.
    common = dict(deadline=None, print_blob=True, derandomize=False, suppress_health_check=[HealthCheck.too_slow])
    settings.register_profile("thorough", **common)
    settings.register_profile("ci", database=None, **common)
    settings.load_profile(PROFILE)


def examples(full):
    """max_examples for a check that starts a process per example."""
    return max(5, full // 4) if PROFILE == "ci" else full
