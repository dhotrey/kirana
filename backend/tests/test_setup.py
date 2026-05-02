import importlib
import sys
import types
import unittest


class _SecretStr:
    def __init__(self, value):
        self._value = value

    def get_secret_value(self):
        return self._value


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def _install_dependency_stubs():
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None
    sys.modules.setdefault("dotenv", dotenv)

    pydantic = types.ModuleType("pydantic")
    pydantic.SecretStr = _SecretStr
    sys.modules.setdefault("pydantic", pydantic)

    loguru = types.ModuleType("loguru")
    loguru.logger = _Logger()
    sys.modules.setdefault("loguru", loguru)

    cloudflare = types.ModuleType("cloudflare")
    cloudflare.Cloudflare = object
    sys.modules.setdefault("cloudflare", cloudflare)

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: None
    sys.modules.setdefault("boto3", boto3)

    botocore = types.ModuleType("botocore")
    botocore_client = types.ModuleType("botocore.client")
    botocore_client.Config = object
    sys.modules.setdefault("botocore", botocore)
    sys.modules.setdefault("botocore.client", botocore_client)

    utils_types = types.ModuleType("utils.types")
    utils_types.InfraConfig = object
    sys.modules.setdefault("utils.types", utils_types)


_install_dependency_stubs()
setup = importlib.import_module("setup")


class _Account:
    def __init__(self, account_id):
        self.id = account_id


class _Accounts:
    def __init__(self, accounts):
        self.accounts = accounts
        self.list_kwargs = None

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return self.accounts


class _CloudflareClient:
    def __init__(self, accounts):
        self.accounts = _Accounts(accounts)


class CloudflareAccountExistsTest(unittest.TestCase):
    def test_matches_account_by_id(self):
        client = _CloudflareClient([_Account("expected-account-id")])

        self.assertTrue(setup.cloudflare_account_exists(client, "expected-account-id"))
        self.assertEqual({}, client.accounts.list_kwargs)

    def test_rejects_when_no_returned_account_has_id(self):
        client = _CloudflareClient([_Account("other-account-id")])

        self.assertFalse(setup.cloudflare_account_exists(client, "expected-account-id"))


if __name__ == "__main__":
    unittest.main()
