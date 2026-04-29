import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeSecretStr:
    def __init__(self, value):
        self._value = value

    def get_secret_value(self):
        return self._value


class FakeLogger:
    def debug(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass


class FakeDatabase:
    def __init__(self):
        self.created = []
        self.queries = []

    def create(self, *, account_id, name):
        self.created.append({"account_id": account_id, "name": name})
        return types.SimpleNamespace(uuid="created-db-id", name=name)

    def query(self, *, database_id, account_id, sql):
        self.queries.append(
            {"database_id": database_id, "account_id": account_id, "sql": sql}
        )
        return {"success": True}


class FakeCloudflare:
    instances = []

    def __init__(self, *, api_token):
        self.api_token = api_token
        self.accounts = types.SimpleNamespace(list=lambda name: [name])
        self.d1 = types.SimpleNamespace(database=FakeDatabase())
        FakeCloudflare.instances.append(self)


class SetupScriptTest(unittest.TestCase):
    def setUp(self):
        FakeCloudflare.instances.clear()
        self._module_names = ["cloudflare", "dotenv", "loguru", "pydantic", "setup"]
        self._saved_modules = {
            name: sys.modules[name] for name in self._module_names if name in sys.modules
        }
        for name in self._module_names:
            sys.modules.pop(name, None)

        sys.modules["cloudflare"] = types.SimpleNamespace(Cloudflare=FakeCloudflare)
        sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda: None)
        sys.modules["loguru"] = types.SimpleNamespace(logger=FakeLogger())
        sys.modules["pydantic"] = types.SimpleNamespace(SecretStr=FakeSecretStr)

    def tearDown(self):
        for name in self._module_names:
            sys.modules.pop(name, None)
        sys.modules.update(self._saved_modules)

    def test_first_run_creates_database_then_initializes_schema(self):
        env = {
            "CLOUDFLARE_ACCOUNT_ID": "account-id",
            "CLOUDFLARE_API_TOKEN": "api-token",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, env, clear=True), patch.object(
                os, "getcwd", return_value=tmpdir
            ):
                old_cwd = Path.cwd()
                try:
                    os.chdir(tmpdir)
                    setup = importlib.import_module("setup")
                    setup.main()
                finally:
                    os.chdir(old_cwd)

        self.assertEqual(1, len(FakeCloudflare.instances))
        database = FakeCloudflare.instances[0].d1.database
        self.assertEqual([{"account_id": "account-id", "name": "kirana"}], database.created)
        self.assertEqual(4, len(database.queries))
        self.assertEqual(
            {"created-db-id"},
            {query["database_id"] for query in database.queries},
        )


if __name__ == "__main__":
    unittest.main()
