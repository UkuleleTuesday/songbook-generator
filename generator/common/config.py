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
    """
    Load GDrive folder IDs from environment or config file.
    Priority order:
    1. GDRIVE_SONG_SHEETS_FOLDER_IDS environment variable (comma-separated).
    2. Local config file (~/.config/songbook-generator/config.toml).
    3. Hardcoded default.
    """
    env_folders = os.getenv("GDRIVE_SONG_SHEETS_FOLDER_IDS")
    if env_folders:
        return [folder.strip() for folder in env_folders.split(",")]

    config = load_config()
    folder_ids = config.get("song-sheets", {}).get(
        "folder-ids", [DEFAULT_GDRIVE_FOLDER_ID]
    )
    return folder_ids if isinstance(folder_ids, list) else [folder_ids]


def load_cover_config():
    config = load_config()
    return config.get("cover", {}).get("file-id", None)
