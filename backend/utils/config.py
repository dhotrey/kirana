import tomllib
from utils.types import Config


def load_config(config_path: str) -> Config:
    """Read config.toml and return a typed infrastructure config.

    Returns:
        Config: a typed object from the config.toml file
    """
    with open(config_path, "rb") as f:
        infra_config = tomllib.load(f)
        return Config.model_validate(
            {
                "cloudflare": infra_config["cloudflare"],
                "kirana": infra_config["kirana"],
                "tigris": infra_config["tigris"],
                "log_level": infra_config["kirana"]["log_level"],
                "kb": infra_config["knowledge_base"],
            }
        )
