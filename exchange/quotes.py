"""Typed application terms. These are not core A2A contracts."""
from datetime import datetime, timezone, timedelta
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exchange.common import digest, uid
from exchange.failures import ExchangeFailure


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["leo.quote.v1"] = "leo.quote.v1"
    quote_id: str
    provider: str
    principal: str
    input_digest: str
    service: str
    deliverable: str = "source-grounded result.json"
    mode: Literal["free", "simulator"]
    amount: StrictInt = Field(ge=0, le=1000000)
    asset: Literal["CREDIT"] = "CREDIT"
    network: Literal["leo:local"] = "leo:local"
    payee: str
    expires_at: str
    deadline_at: str
    verification_policy: Literal["deterministic-evidence-v1"] = "deterministic-evidence-v1"
    cancellation_terms: Literal["release-before-settlement; no-refund-after-admission"] = "release-before-settlement; no-refund-after-admission"
    round: StrictInt = Field(ge=1, le=3)

    def valid(self, *, provider=None, principal=None, task=None, at=None):
        current = at or datetime.now(timezone.utc)
        expiry, deadline = (datetime.fromisoformat(v.replace("Z", "+00:00")) for v in (self.expires_at, self.deadline_at))
        if expiry.tzinfo is None or deadline.tzinfo is None or expiry <= current or deadline < expiry:
            raise ExchangeFailure("payment", "expired or invalid quote deadline")
        if self.payee != self.provider or (provider and self.provider != provider) or (principal and self.principal != principal):
            raise ExchangeFailure("payment", "quote identity mismatch")
        if task and (self.input_digest != digest(task) or self.service != task.get("service")):
            raise ExchangeFailure("payment", "quote task mismatch")
        if self.mode == "free" and self.amount != 0:
            raise ExchangeFailure("policy", "free quote must have zero price")
        return self


def offer(provider, principal, task, mode, amount=5, round=1):
    current = datetime.now(timezone.utc)
    return Quote(quote_id=uid(), provider=provider, principal=principal, input_digest=digest(task),
                 service=task["service"], mode=mode, amount=amount if mode == "simulator" else 0,
                 payee=provider, expires_at=(current + timedelta(minutes=10)).isoformat(),
                 deadline_at=(current + timedelta(minutes=15)).isoformat(), round=round)
