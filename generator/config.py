import os
import toml

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/songbook-generator/config.toml")

DEFAULT_GDRIVE_FOLDER_ID = "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95"


def load_config(config_path=DEFAULT_CONFIG_PATH):
    if os.path.exists(config_path):
        return toml.load(config_path)
    else:
        return toml.loads("")


def load_config_folder_ids():
    config = load_config()
    folder_ids = config.get("song-sheets", {}).get(
        "folder-ids", [DEFAULT_GDRIVE_FOLDER_ID]
    )
    return folder_ids if isinstance(folder_ids, list) else [folder_ids]
