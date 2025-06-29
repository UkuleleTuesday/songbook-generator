import os
import toml

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/songbook-generator/config.toml")


def load_config(config_path=DEFAULT_CONFIG_PATH):
    if os.path.exists(config_path):
        return toml.load(config_path)
    else:
        return toml.loads("")
