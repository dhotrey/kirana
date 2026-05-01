import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _install_dependency_stubs():
    pydantic = types.ModuleType("pydantic")

    class BaseModel:
        @classmethod
        def model_validate(cls, value):
            return cls(**value)

    class SecretStr:
        def __init__(self, value):
            self._value = value

        def get_secret_value(self):
            return self._value

    pydantic.BaseModel = BaseModel
    pydantic.SecretStr = SecretStr
    sys.modules["pydantic"] = pydantic

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None
    sys.modules["dotenv"] = dotenv

    loguru = types.ModuleType("loguru")

    class Logger:
        def debug(self, *_args, **_kwargs):
            pass

        def info(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    loguru.logger = Logger()
    sys.modules["loguru"] = loguru

    cloudflare = types.ModuleType("cloudflare")
    cloudflare.Cloudflare = object
    sys.modules["cloudflare"] = cloudflare

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *_args, **_kwargs: None
    sys.modules["boto3"] = boto3

    botocore = types.ModuleType("botocore")
    botocore_client = types.ModuleType("botocore.client")
    botocore_client.Config = object
    sys.modules["botocore"] = botocore
    sys.modules["botocore.client"] = botocore_client


def _load_setup_module():
    _install_dependency_stubs()
    backend_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))
    spec = importlib.util.spec_from_file_location("setup_module", backend_dir / "setup.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


setup = _load_setup_module()


class Accounts:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.get_calls = []
        self.list_calls = []

    def get(self, *, account_id):
        self.get_calls.append(account_id)
        if self.fail:
            raise RuntimeError("not found")
        return object()

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        raise AssertionError("account ID validation must not use the name filter")


class Client:
    def __init__(self, accounts):
        self.accounts = accounts


class ValidateCloudflareAccountTests(unittest.TestCase):
    def test_validates_account_id_with_account_lookup(self):
        accounts = Accounts()

        setup.validate_cloudflare_account(
            Client(accounts), setup.SecretStr("023e105f4ecef8ad9ca31a8372d0c353")
        )

        self.assertEqual(accounts.get_calls, ["023e105f4ecef8ad9ca31a8372d0c353"])
        self.assertEqual(accounts.list_calls, [])

    def test_empty_account_id_raises_without_api_call(self):
        accounts = Accounts()

        with self.assertRaisesRegex(setup.SetupError, "CLOUDFLARE_ACCOUNT_ID is not set"):
            setup.validate_cloudflare_account(Client(accounts), setup.SecretStr(""))

        self.assertEqual(accounts.get_calls, [])
        self.assertEqual(accounts.list_calls, [])

    def test_failed_account_lookup_raises_setup_error(self):
        accounts = Accounts(fail=True)

        with self.assertRaisesRegex(setup.SetupError, "Cloudflare account is not found"):
            setup.validate_cloudflare_account(
                Client(accounts), setup.SecretStr("023e105f4ecef8ad9ca31a8372d0c353")
            )

        self.assertEqual(accounts.get_calls, ["023e105f4ecef8ad9ca31a8372d0c353"])


if __name__ == "__main__":
    unittest.main()
