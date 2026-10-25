"""Bounded fixture demonstration using the existing isolated test runner."""
from exchange.common import DATA, ROOT
from exchange.demo import demo
from exchange.runtime_check import restart_check


def require_isolated_runtime():
    # Never spend the demonstration wallet or crash its services during validation.
    assert DATA.parent == ROOT / 'local_data/validation-runs', 'Use exchange.evidence.check()'


async def test_free_demo_lifecycle():
    require_isolated_runtime()
    result = await demo()
    assert result['status'] == 'passed'
    assert result['clarification'] and result['cancellation'] and result['failure_and_recovery']
    assert result['buyer']['verifier']['accepted']


def test_paid_fixture_survives_owned_provider_crash():
    require_isolated_runtime()
    result = restart_check(crash=True)
    assert result['crash_injection']['signal'] == 'SIGKILL'
    assert result['provider_task_unchanged'] and result['same_cached_response']
    assert result['balances_unchanged'] and result['ledger_conserved']
