"""Explicitly configured Base Sepolia x402 client. No mainnet or wallet import path."""
from pathlib import Path
import json
import os
import ipaddress
import fcntl
from urllib.parse import urlsplit

from eth_account import Account
from pydantic import BaseModel, ConfigDict, StrictInt, Field
from typing import Literal
from x402.schemas import PaymentPayload
from x402.mechanisms.evm.exact.client import ExactEvmScheme
from x402.http.utils import decode_payment_required_header, encode_payment_signature_header, decode_payment_response_header
from x402.extensions.payment_identifier import append_payment_identifier_to_extensions

from exchange.common import DATA, ROOT, canonical, digest, now, uid, write_json
from exchange.security import NetworkPolicy
from exchange.failures import ExchangeFailure


class TestnetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["leo.testnet.v1"]
    operator_approved: Literal[True]
    test_assets_only: Literal[True]
    network: Literal["eip155:84532"]
    resource_url: str
    asset: str
    payee: str
    max_amount: StrictInt = Field(gt=0, le=100)
    operation_id: str = Field(min_length=16, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")

    def policy(self):
        p = urlsplit(self.resource_url)
        # Exact literal public IP + TLS hostname/IP certificate validation; DNS not supported.
        origin = f"{p.scheme}://{p.netloc}"
        policy = NetworkPolicy([origin], local=False)
        policy.check(self.resource_url)
        from eth_utils import is_address
        if not is_address(self.asset) or not is_address(self.payee):
            raise ValueError("asset and payee must be EVM addresses")
        return policy


def create_test_account():
    path = DATA / "testnet" / "test-only-key.json"
    if path.exists():
        value = json.loads(path.read_text())
        return {"address": value["address"], "network": "eip155:84532", "funding": "operator only; never automatic"}
    account = Account.create()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical({"address": account.address, "key": account.key.hex(), "created_at": now(), "test_only": True}))
    return {"address": account.address, "network": "eip155:84532", "funding": "operator only; never automatic"}


async def run_testnet(path):
    directory = DATA / "testnet"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "operation.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ExchangeFailure("policy", "another testnet operation is active") from None
        return await _run_testnet(path)


async def _run_testnet(path):
    if path is None:
        raise ExchangeFailure("policy", "explicit repository-local testnet configuration required")
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ExchangeFailure("policy", "configuration must be inside this repository")
    settings = TestnetConfig.model_validate_json(path.read_text())
    net = settings.policy()
    key_path = DATA / "testnet/test-only-key.json"
    if not key_path.exists():
        raise ExchangeFailure("policy", "run testnet-init for a fresh test-only account; wallet import is unsupported")
    key = json.loads(key_path.read_text())
    if key.get("test_only") is not True:
        raise ExchangeFailure("policy", "test-only account required")
    operation = DATA / "testnet" / (settings.operation_id + ".json")
    if operation.exists():
        saved = json.loads(operation.read_text())
        if saved["config_digest"] != digest(settings.model_dump()):
            raise ExchangeFailure("policy", "operation changed-content reuse")
        if saved["status"] == "settled-response":
            return saved
        # An ambiguous remote response cannot be retried without a documented reconciliation endpoint.
        raise ExchangeFailure("payment", "outcome unknown; inspect remote receipt/chain before any new operation")
    response = await net.request("GET", settings.resource_url)
    if response.status_code != 402:
        raise ExchangeFailure("payment", "expected x402 challenge")
    required = decode_payment_required_header(response.headers["PAYMENT-REQUIRED"])
    if required.x402_version != 2 or len(required.accepts) != 1:
        raise ExchangeFailure("payment", "expected exactly one x402 v2 offer")
    terms = required.accepts[0]
    if terms.scheme != "exact" or terms.network != settings.network or terms.asset.lower() != settings.asset.lower() or terms.pay_to.lower() != settings.payee.lower() or not terms.amount.isdecimal() or not 0 < int(terms.amount) <= settings.max_amount or terms.extra.get("assetTransferMethod") == "permit2":
        raise ExchangeFailure("payment", "challenge outside approved testnet terms")
    prior = [json.loads(p.read_text()) for p in (DATA / "testnet").glob("*.json")]
    p = urlsplit(settings.resource_url)
    origin = f"{p.scheme}://{p.netloc}"
    amount = int(terms.amount)
    # Test-asset units have their own caps, separate from simulator CREDIT balances.
    if amount > 25 or sum(v.get("amount", 0) for v in prior) + amount > 100 or sum(v.get("amount", 0) for v in prior if v.get("provider_origin") == origin) + amount > 50:
        raise ExchangeFailure("policy", "test-asset per-task/run, peer or global cap exceeded (25/25, 50, 100)")
    account = Account.from_key(key["key"])
    payload = PaymentPayload(accepted=terms, resource=required.resource,
        extensions=append_payment_identifier_to_extensions(required.extensions or {}, settings.operation_id),
        payload=ExactEvmScheme(account).create_payment_payload(terms))
    saved = {"mode": "public-testnet", "network": settings.network, "config_digest": digest(settings.model_dump()),
             "operation_id": settings.operation_id, "status": "outcome-unknown", "payload": payload.model_dump(by_alias=True),
             "created_at": now(), "settlement_independently_verified": False, "amount": amount, "provider_origin": origin}
    # Durable signed payload before send. There is no automatic retry or new nonce on uncertainty.
    write_json(operation, saved)
    response = await net.request("GET", settings.resource_url, headers={"PAYMENT-SIGNATURE": encode_payment_signature_header(payload)})
    response.raise_for_status()
    settled = decode_payment_response_header(response.headers["PAYMENT-RESPONSE"])
    if not settled.success or settled.network != settings.network or (settled.payer and settled.payer.lower() != account.address.lower()):
        raise ExchangeFailure("payment", "invalid testnet settlement response")
    saved.update(status="settled-response", receipt=settled.model_dump(by_alias=True), resource_sha256=digest(response.content),
                 settlement_evidence="resource server receipt only; independent chain confirmation remains required")
    write_json(operation, saved)
    return saved
