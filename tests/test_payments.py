import os
import base64
import tempfile

from monatise.live.server import CryptoPaymentWatcher, PaymentGateway
from monatise.live.users import User, UserStore


def test_crypto_payment_config_exposes_usdc_networks() -> None:
    old_rails = os.environ.get("MONATISE_CRYPTO_PAYMENT_RAILS")
    os.environ.pop("MONATISE_CRYPTO_PAYMENT_RAILS", None)
    try:
        config = PaymentGateway().config()
        networks = config["rails"]["crypto"]["networks"]

        assert config["rails"]["crypto"]["configured"]
        assert networks == [
            {"network": "USDC on Solana", "address": "dJs4k4PUfH8WVWoECJ925WWP91LcUq8nbZPZcHZCWHp"},
            {"network": "USDC on Arbitrum", "address": "0xbD0B18D46B7afA6E5874A6e0eebbfD28276EA560"},
            {"network": "USDC on Polygon", "address": "0xbD0B18D46B7afA6E5874A6e0eebbfD28276EA560"},
        ]
    finally:
        _restore_env("MONATISE_CRYPTO_PAYMENT_RAILS", old_rails)


def test_crypto_checkout_returns_all_usdc_networks() -> None:
    old_rails = os.environ.get("MONATISE_CRYPTO_PAYMENT_RAILS")
    os.environ["MONATISE_CRYPTO_PAYMENT_RAILS"] = "USDC on Testnet|0xtest,USDC on Backup|0xbackup"
    try:
        checkout = PaymentGateway().checkout(User(id=7, username="trader"), {"plan": "pro", "method": "crypto"})

        assert checkout["setupRequired"] is False
        assert checkout["network"] == "USDC on Testnet"
        assert checkout["address"] == "0xtest"
        assert checkout["networks"] == [
            {"network": "USDC on Testnet", "address": "0xtest"},
            {"network": "USDC on Backup", "address": "0xbackup"},
        ]
        assert checkout["reference"].startswith("monatise-7-pro-")
    finally:
        _restore_env("MONATISE_CRYPTO_PAYMENT_RAILS", old_rails)


def test_crypto_checkout_creates_pending_invoice() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("crypto-client", "password123")
            checkout = PaymentGateway(store).checkout(user, {"plan": "pro", "method": "crypto"})
            invoice = store.crypto_invoice_for_reference(checkout["reference"])

            assert invoice is not None
            assert invoice.user_id == user.id
            assert invoice.plan == "pro"
            assert 29 < invoice.amount < 29.01
            assert invoice.currency == "USDC"
            assert invoice.status == "pending"
    finally:
        _restore_key(old_key)


def test_crypto_watcher_marks_evm_invoice_paid_and_activates_plan() -> None:
    old_key = _with_key()
    old_rails = os.environ.get("MONATISE_CRYPTO_PAYMENT_RAILS")
    os.environ["MONATISE_CRYPTO_PAYMENT_RAILS"] = "USDC on Arbitrum|0xbD0B18D46B7afA6E5874A6e0eebbfD28276EA560"
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("evm-client", "password123")
            gateway = PaymentGateway(store)
            gateway.checkout(user, {"plan": "pro", "method": "crypto"})
            required_units = int(round(store.pending_crypto_invoices()[0].amount * 1_000_000))

            class FakeWatcher(CryptoPaymentWatcher):
                def _rpc_json(self, url: str, method: str, params: list) -> object:
                    if method == "eth_blockNumber":
                        return "0x100"
                    if method == "eth_getLogs":
                        return [{"data": hex(required_units), "transactionHash": "0xpaid"}]
                    raise AssertionError(f"unexpected method {method}")

            confirmed = FakeWatcher(store, gateway).check_once()
            invoice = store.pending_crypto_invoices()

            assert confirmed == 1
            assert invoice == []
            assert store.settings_for_user(user.id).subscription_plan == "pro"
    finally:
        _restore_env("MONATISE_CRYPTO_PAYMENT_RAILS", old_rails)
        _restore_key(old_key)


def test_crypto_watcher_marks_solana_invoice_paid_and_activates_plan() -> None:
    old_key = _with_key()
    old_rails = os.environ.get("MONATISE_CRYPTO_PAYMENT_RAILS")
    os.environ["MONATISE_CRYPTO_PAYMENT_RAILS"] = "USDC on Solana|dJs4k4PUfH8WVWoECJ925WWP91LcUq8nbZPZcHZCWHp"
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("sol-client", "password123")
            gateway = PaymentGateway(store)
            gateway.checkout(user, {"plan": "pro", "method": "crypto"})
            required_units = str(int(round(store.pending_crypto_invoices()[0].amount * 1_000_000)))

            class FakeWatcher(CryptoPaymentWatcher):
                def _rpc_json(self, url: str, method: str, params: list) -> object:
                    if method == "getTokenAccountsByOwner":
                        return {"value": [{"pubkey": "recipient-token-account"}]}
                    if method == "getSignaturesForAddress":
                        return [{"signature": "solana-paid"}]
                    if method == "getTransaction":
                        return {
                            "transaction": {
                                "message": {
                                    "instructions": [
                                        {
                                            "parsed": {
                                                "info": {
                                                    "destination": "recipient-token-account",
                                                    "mint": self.SOLANA_USDC_MINT,
                                                    "tokenAmount": {"amount": required_units},
                                                }
                                            }
                                        }
                                    ]
                                }
                            },
                            "meta": {},
                        }
                    raise AssertionError(f"unexpected method {method}")

            confirmed = FakeWatcher(store, gateway).check_once()

            assert confirmed == 1
            assert store.pending_crypto_invoices() == []
            assert store.settings_for_user(user.id).subscription_plan == "pro"
    finally:
        _restore_env("MONATISE_CRYPTO_PAYMENT_RAILS", old_rails)
        _restore_key(old_key)


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


def _with_key() -> str:
    key = base64.urlsafe_b64encode(b"1" * 32).decode("utf-8")
    old_key = os.environ.get("MONATISE_ENCRYPTION_KEY")
    os.environ["MONATISE_ENCRYPTION_KEY"] = key
    return old_key or ""


def _restore_key(old_key: str) -> None:
    if old_key:
        os.environ["MONATISE_ENCRYPTION_KEY"] = old_key
    else:
        os.environ.pop("MONATISE_ENCRYPTION_KEY", None)
