# STREAMIOV-native gift catalogue

The current catalogue is `data/game_actions/gift_catalog.json`. Its `streamiov_points` are STREAMIOV-native points, not TikTok coins and not a cash value. TikTok-native gift IDs must remain separate and are rejected by the native catalogue loader.

`ai.runtime.gift_catalog.GiftCatalog` validates IDs, point ranges, asset paths, duplicate entries, release states and asset-root containment. When an asset root is supplied, a gift is considered released only when its status is explicitly `released` and the referenced local asset exists. Symlinked assets and path traversal are rejected.

The loader is read-only. It does not send gifts, run game actions, create checkouts, charge money, record payouts or enable real-money transactions. The current repository catalogue is a mixture of legacy entries without explicit release state and custom entries marked `local_preview_only`; absent production assets are not treated as releases. The runtime snapshot keeps checkout and payout disabled.

## Validation

Run the repository test suite:

```bash
python -m unittest tests.test_gift_catalog -v
```

Before any gift can be released, the project still needs a production-ready original asset bundle, real runtime preview/rendering, event-bus integration, security review and (for paid gifts) a verified independent payment and payout provider. The creator proceeds target remains 100% before separately itemized provider fees, refunds/chargebacks and legally required withholding; STREAMIOV and TikTok commission remain 0% for STREAMIOV-native gifts.
