import unittest
from types import SimpleNamespace

from pydantic import SecretStr

from setup import SetupError, validate_cloudflare_account_id


class FakeAccounts:
    def __init__(self):
        self.requested_account_id = None

    def get(self, *, account_id):
        self.requested_account_id = account_id
        return SimpleNamespace(id=account_id)

    def list(self, **_kwargs):
        raise AssertionError("account validation must not filter by account name")


class FakeCloudflareClient:
    def __init__(self):
        self.accounts = FakeAccounts()


class CloudflareAccountValidationTests(unittest.TestCase):
    def test_validates_configured_account_id_directly(self):
        client = FakeCloudflareClient()

        validate_cloudflare_account_id(client, SecretStr("023e105f4ecef8ad9ca31a8372d0c353"))

        self.assertEqual(
            client.accounts.requested_account_id,
            "023e105f4ecef8ad9ca31a8372d0c353",
        )

    def test_rejects_missing_account_id(self):
        with self.assertRaisesRegex(SetupError, "CLOUDFLARE_ACCOUNT_ID is not set"):
            validate_cloudflare_account_id(FakeCloudflareClient(), SecretStr(""))

    def test_wraps_account_lookup_failure(self):
        client = FakeCloudflareClient()
        client.accounts.get = lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("not found")
        )

        with self.assertRaisesRegex(SetupError, "Cloudflare account is not found"):
            validate_cloudflare_account_id(client, SecretStr("bad-account-id"))


if __name__ == "__main__":
    unittest.main()
