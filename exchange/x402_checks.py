"""Official SDK cryptographic/wire fixtures, explicitly without chain settlement."""
import copy
from eth_account import Account
from x402.schemas import PaymentRequirements, PaymentRequired, PaymentPayload, SettleResponse
from x402.http.utils import (encode_payment_required_header, decode_payment_required_header,
    encode_payment_signature_header, decode_payment_signature_header,
    encode_payment_response_header, decode_payment_response_header)
from x402.mechanisms.evm.exact.client import ExactEvmScheme as ClientScheme
from x402.mechanisms.evm.exact.facilitator import ExactEvmScheme as FacilitatorScheme
from x402.extensions.payment_identifier import declare_payment_identifier_extension, append_payment_identifier_to_extensions

from exchange.common import DATA, uid, write_json

ASSET = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"


class ChainReadFixture:
    """Only contract reads are mocked. EOA signature recovery is SDK cryptography."""
    def get_code(self, address):
        return b"\x60\x00" if address.lower() == ASSET.lower() else b""

    def read_contract(self, address, abi, method, *args):
        if address.lower() != ASSET.lower() or method != "transferWithAuthorization":
            raise AssertionError("unexpected fixture contract read")
        return None

    def write_contract(self, *args):
        raise AssertionError("fixture cannot submit transactions")


def conformance(save=True):
    account = Account.create()  # New unfunded account; secret never written.
    requirements = PaymentRequirements(scheme="exact", network="eip155:84532", asset=ASSET, amount="7", pay_to=PAYEE,
                                      max_timeout_seconds=120, extra={"name": "Fixture Credit", "version": "1"})
    required = PaymentRequired(accepts=[requirements], extensions={"payment-identifier": declare_payment_identifier_extension()})
    extensions = append_payment_identifier_to_extensions(copy.deepcopy(required.extensions), "fixture-payment-0001")
    payload = PaymentPayload(accepted=requirements, payload=ClientScheme(account).create_payment_payload(requirements), extensions=extensions)
    encoded = encode_payment_signature_header(payload)
    decoded = decode_payment_signature_header(encoded)
    verifier = FacilitatorScheme(ChainReadFixture())
    valid = verifier.verify(decoded, requirements)
    if not valid.is_valid:
        raise AssertionError(valid.model_dump())
    rejected = {}
    for field, value in [("to", "0x3333333333333333333333333333333333333333"), ("value", "8"), ("nonce", "0x"+"00"*32), ("validBefore", "1")]:
        changed = payload.model_copy(deep=True)
        changed.payload["authorization"][field] = value
        rejected[field] = not verifier.verify(changed, requirements).is_valid
    changed = payload.model_copy(deep=True)
    changed.accepted.network = "eip155:1"
    rejected["network"] = not verifier.verify(changed, requirements).is_valid
    assert all(rejected.values())
    assert decode_payment_required_header(encode_payment_required_header(required)) == required
    response = SettleResponse(success=True, network="eip155:84532", transaction="fixture-only", payer=account.address)
    assert decode_payment_response_header(encode_payment_response_header(response)) == response
    result = {"sdk": "x402==2.25.0", "wire_version": 2, "signature_valid": valid.is_valid,
              "mutations_rejected": rejected, "chain_reads": "explicit fixture", "settlement": "not executed",
              "headers": {"PAYMENT-REQUIRED": encode_payment_required_header(required), "PAYMENT-SIGNATURE": encoded,
                          "PAYMENT-RESPONSE": encode_payment_response_header(response)},
              "payload": payload.model_dump(by_alias=True), "actual_service_expenditure": 0}
    if save:
        write_json(DATA / "receipts" / ("x402-sdk-" + uid() + ".json"), result)
    return result
