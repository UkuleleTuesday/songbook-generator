import os
import click
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient import errors
from datetime import datetime
import fitz  # PyMuPDF
import toml
from .gdrive import download_file

def load_cover_config():
    config_path = os.path.expanduser("~/.config/songbook-generator/config.toml")
    if os.path.exists(config_path):
        config = toml.load(config_path)
        return config.get("cover", {}).get("file-id", None)
    return None

def generate_cover(drive, cache_dir):
    cover_file_id = load_cover_config()
    if not cover_file_id:
        click.echo("No cover file ID configured. Skipping cover generation.")
        return

    cover_file = {"id": cover_file_id, "name": "cover"}
    cover_dir = os.path.join(cache_dir, "cover")
    os.makedirs(cover_dir, exist_ok=True)
    cached_cover_path = download_file(drive, cover_file, cover_dir)
    try:
        cover_pdf = fitz.open(cached_cover_path)
    except fitz.EmptyFileError:
        raise ValueError(f"Downloaded cover file is corrupted: {cached_cover_path}. Please check the file on Google Drive.")
    return cover_pdf
