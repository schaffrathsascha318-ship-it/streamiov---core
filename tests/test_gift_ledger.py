import unittest

from ai.runtime.gift_ledger import (
    accounting_record_dict,
    calculate_native_gift_accounting,
)


class NativeGiftAccountingTests(unittest.TestCase):
    def test_zero_platform_and_tiktok_commission_and_streamer_tax_duty(self):
        entry = calculate_native_gift_accounting(
            transaction_id="tx-001",
            gift_id="streamiov_neonherz",
            currency="eur",
            gross_minor=1000,
        )
        self.assertEqual(entry.streamiov_commission_minor, 0)
        self.assertEqual(entry.tiktok_commission_minor, 0)
        self.assertEqual(entry.creator_net_minor, 1000)
        self.assertEqual(entry.streamer_tax_responsibility, "STREAMER")
        self.assertEqual(entry.streamer_tax_calculation, "NOT_CALCULATED_BY_STREAMIOV")

    def test_streamer_pays_provider_fee_when_contract_says_so(self):
        entry = calculate_native_gift_accounting(
            transaction_id="tx-002",
            gift_id="rose",
            currency="EUR",
            gross_minor=1000,
            provider_fee_minor=35,
            provider_fee_payer="STREAMER",
        )
        self.assertEqual(entry.provider_fee_minor, 35)
        self.assertEqual(entry.creator_net_minor, 965)

    def test_sender_or_platform_fee_does_not_reduce_creator_proceeds(self):
        for payer in ("SENDER", "PLATFORM"):
            with self.subTest(payer=payer):
                entry = calculate_native_gift_accounting(
                    transaction_id="tx-003",
                    gift_id="rose",
                    currency="EUR",
                    gross_minor=1000,
                    provider_fee_minor=35,
                    provider_fee_payer=payer,
                )
                self.assertEqual(entry.creator_net_minor, 1000)

    def test_refund_and_verified_statutory_withholding_are_separate(self):
        entry = calculate_native_gift_accounting(
            transaction_id="tx-004",
            gift_id="galaxy",
            currency="EUR",
            gross_minor=1000,
            refund_minor=100,
            statutory_withholding_minor=50,
        )
        self.assertEqual(entry.refund_minor, 100)
        self.assertEqual(entry.statutory_withholding_minor, 50)
        self.assertEqual(entry.creator_net_minor, 850)

    def test_tiktok_native_events_are_rejected_from_native_ledger(self):
        with self.assertRaisesRegex(ValueError, "Only STREAMIOV_NATIVE"):
            calculate_native_gift_accounting(
                transaction_id="tx-005",
                gift_id="tiktok_gift_1",
                currency="EUR",
                gross_minor=1000,
                source="TIKTOK_NATIVE_EVENT",
            )

    def test_invalid_money_and_over_refund_are_rejected(self):
        for amount in (-1, 1.5, True):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                calculate_native_gift_accounting(
                    transaction_id="tx-006",
                    gift_id="rose",
                    currency="EUR",
                    gross_minor=amount,
                )
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            calculate_native_gift_accounting(
                transaction_id="tx-007",
                gift_id="rose",
                currency="EUR",
                gross_minor=100,
                refund_minor=101,
            )

    def test_statutory_withholding_cannot_exceed_available_proceeds(self):
        with self.assertRaisesRegex(ValueError, "exceeds remaining"):
            calculate_native_gift_accounting(
                transaction_id="tx-008",
                gift_id="rose",
                currency="EUR",
                gross_minor=100,
                provider_fee_minor=20,
                provider_fee_payer="STREAMER",
                statutory_withholding_minor=81,
            )

    def test_record_is_json_ready_and_keeps_separate_categories(self):
        record = accounting_record_dict(calculate_native_gift_accounting(
            transaction_id="tx-009",
            gift_id="rose",
            currency="EUR",
            gross_minor=250,
        ))
        self.assertEqual(record["source"], "STREAMIOV_NATIVE")
        self.assertEqual(record["streamiov_commission_minor"], 0)
        self.assertEqual(record["tiktok_commission_minor"], 0)
        self.assertEqual(record["streamer_tax_responsibility"], "STREAMER")


if __name__ == "__main__":
    unittest.main()
