"""Accounting rules for STREAMIOV-native gifts.

This module calculates an auditable statement only. It does not charge cards,
create payouts, calculate a creator's taxes, or handle TikTok-native gifts.
All monetary amounts are integer minor units (for example, cents).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


FeePayer = Literal["STREAMER", "SENDER", "PLATFORM"]


@dataclass(frozen=True)
class NativeGiftAccounting:
    transaction_id: str
    gift_id: str
    currency: str
    gross_minor: int
    refund_minor: int
    provider_fee_minor: int
    provider_fee_payer: FeePayer
    statutory_withholding_minor: int
    streamer_tax_responsibility: str
    streamer_tax_calculation: str
    streamiov_commission_minor: int
    tiktok_commission_minor: int
    creator_net_minor: int
    source: str = "STREAMIOV_NATIVE"


def _non_negative_minor(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer in minor units")
    return value


def calculate_native_gift_accounting(
    *,
    transaction_id: str,
    gift_id: str,
    currency: str,
    gross_minor: int,
    provider_fee_minor: int = 0,
    provider_fee_payer: FeePayer = "STREAMER",
    refund_minor: int = 0,
    statutory_withholding_minor: int = 0,
    source: str = "STREAMIOV_NATIVE",
) -> NativeGiftAccounting:
    """Calculate creator proceeds without treating taxes as platform fees.

    The streamer is responsible for declaring and paying their own taxes and
    personal/business levies. STREAMIOV does not estimate or deduct those
    liabilities. A separately supplied statutory withholding is represented
    only when a verified legal obligation requires it.

    Payment-provider fees are itemized separately. Their allocation must be
    explicitly selected by the verified payment contract; this function
    defaults to STREAMER and never silently changes the selected payer.
    """
    if source != "STREAMIOV_NATIVE":
        raise ValueError("Only STREAMIOV_NATIVE transactions belong in this ledger")
    if not isinstance(transaction_id, str) or not transaction_id.strip():
        raise ValueError("transaction_id is required")
    if not isinstance(gift_id, str) or not gift_id.strip():
        raise ValueError("gift_id is required")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a three-letter ISO currency code")
    currency = currency.upper()
    if provider_fee_payer not in ("STREAMER", "SENDER", "PLATFORM"):
        raise ValueError("provider_fee_payer must be STREAMER, SENDER or PLATFORM")

    gross = _non_negative_minor("gross_minor", gross_minor)
    fee = _non_negative_minor("provider_fee_minor", provider_fee_minor)
    refund = _non_negative_minor("refund_minor", refund_minor)
    withholding = _non_negative_minor(
        "statutory_withholding_minor", statutory_withholding_minor
    )
    if refund > gross:
        raise ValueError("refund_minor cannot exceed gross_minor")

    fee_charged_to_creator = fee if provider_fee_payer == "STREAMER" else 0
    available = gross - refund - fee_charged_to_creator
    if withholding > available:
        raise ValueError("statutory withholding exceeds remaining creator proceeds")

    return NativeGiftAccounting(
        transaction_id=transaction_id.strip(),
        gift_id=gift_id.strip(),
        currency=currency,
        gross_minor=gross,
        refund_minor=refund,
        provider_fee_minor=fee,
        provider_fee_payer=provider_fee_payer,
        statutory_withholding_minor=withholding,
        streamer_tax_responsibility="STREAMER",
        streamer_tax_calculation="NOT_CALCULATED_BY_STREAMIOV",
        streamiov_commission_minor=0,
        tiktok_commission_minor=0,
        creator_net_minor=available - withholding,
    )


def accounting_record_dict(entry: NativeGiftAccounting) -> dict:
    """Return a JSON-ready immutable accounting snapshot."""
    return asdict(entry)
