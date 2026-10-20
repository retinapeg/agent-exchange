import base64
import json
from pathlib import Path

from exchange.x402_checks import conformance
from x402.schemas import PaymentRequirements, PaymentRequired
from x402.http.utils import encode_payment_required_header, decode_payment_required_header


def test_sdk_signing_and_verification():
    result = conformance()
    assert result['signature_valid'] and all(result['mutations_rejected'].values())
    assert result['settlement'] == 'not executed'


def test_golden_wire():
    path = Path(__file__).parent / 'fixtures/x402-required.json'
    expected = json.loads(path.read_text())
    value = PaymentRequired(accepts=[PaymentRequirements(scheme='exact', network='eip155:84532', asset='0x1111111111111111111111111111111111111111', amount='7', pay_to='0x2222222222222222222222222222222222222222', max_timeout_seconds=120)])
    encoded = encode_payment_required_header(value)
    assert json.loads(base64.b64decode(encoded)) == expected
    assert decode_payment_required_header(base64.b64encode(json.dumps(expected).encode()).decode()) == value


def test_mainnet_cannot_be_enabled():
    import pytest
    from pydantic import ValidationError
    from exchange.testnet import TestnetConfig
    base = dict(schema_version='leo.testnet.v1', operator_approved=True, test_assets_only=True, network='eip155:84532', resource_url='https://1.1.1.1:443/resource', asset='0x1111111111111111111111111111111111111111', payee='0x2222222222222222222222222222222222222222', max_amount=7, operation_id='test-operation-0001')
    TestnetConfig(**base).policy()
    for patch in ({'network':'eip155:1'}, {'operator_approved':False}, {'test_assets_only':False}, {'max_amount':1.5}, {'max_amount':101}, {'wallet_path':'some-existing-wallet'}):
        with pytest.raises(ValidationError):
            TestnetConfig(**{**base, **patch})
    for url in ('https://127.0.0.1:443/resource','http://1.1.1.1:80/resource','https://169.254.169.254:443/resource'):
        with pytest.raises(ValueError):
            TestnetConfig(**{**base, 'resource_url':url}).policy()


async def test_configured_testnet_client_against_wire_stub(tmp_path, monkeypatch):
    """Functional HTTP-boundary stub only; no public RPC or settlement."""
    import copy
    import httpx
    from exchange import testnet
    from exchange.common import canonical
    from exchange.failures import ExchangeFailure
    from exchange.x402_checks import ASSET, PAYEE, ChainReadFixture
    from x402.schemas import PaymentRequired, PaymentRequirements, SettleResponse
    from x402.http.utils import encode_payment_required_header, decode_payment_signature_header, encode_payment_response_header
    from x402.mechanisms.evm.exact.facilitator import ExactEvmScheme
    monkeypatch.setattr(testnet,'DATA',tmp_path)
    monkeypatch.setattr(testnet,'ROOT',tmp_path)
    testnet.create_test_account()
    settings = dict(schema_version='leo.testnet.v1',operator_approved=True,test_assets_only=True,network='eip155:84532',resource_url='https://1.1.1.1:443/resource',asset=ASSET,payee=PAYEE,max_amount=7,operation_id='testnet-stub-operation-0001')
    path = tmp_path/'config.json'; path.write_bytes(canonical(settings))
    terms = PaymentRequirements(scheme='exact',network='eip155:84532',asset=ASSET,pay_to=PAYEE,amount='7',max_timeout_seconds=120,extra={'name':'Fixture Credit','version':'1'})
    calls = []
    async def remote(self, method, url, **kw):
        calls.append(kw)
        req = httpx.Request(method,url)
        if not kw.get('headers'):
            return httpx.Response(402,request=req,headers={'PAYMENT-REQUIRED':encode_payment_required_header(PaymentRequired(accepts=[terms]))})
        payload = decode_payment_signature_header(kw['headers']['PAYMENT-SIGNATURE'])
        assert ExactEvmScheme(ChainReadFixture()).verify(payload,terms).is_valid
        return httpx.Response(200,request=req,content=b'fixture resource',headers={'PAYMENT-RESPONSE':encode_payment_response_header(SettleResponse(success=True,network='eip155:84532',transaction='stub-only'))})
    monkeypatch.setattr(testnet.NetworkPolicy,'request',remote)
    result = await testnet.run_testnet(path)
    assert result['status'] == 'settled-response' and not result['settlement_independently_verified']
    assert await testnet.run_testnet(path) == result and len(calls) == 2
    saved = tmp_path/'testnet'/('testnet-stub-operation-0001.json')
    result['status'] = 'outcome-unknown'; saved.write_bytes(canonical(result))
    with __import__('pytest').raises(ExchangeFailure,match='outcome unknown'):
        await testnet.run_testnet(path)
    assert len(calls) == 2
