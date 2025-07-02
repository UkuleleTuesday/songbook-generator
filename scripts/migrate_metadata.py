#!/usr/bin/env python3
"""
Migration script to apply metadata from tabdb.csv to Google Drive files as custom properties.

This script reads the tabdb.csv file and applies metadata to corresponding Google Drive files
by matching the expected filename pattern "<song title> - <artist>".
"""

import csv
import sys
import re
from typing import Dict, List, Optional
import click
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from difflib import get_close_matches


def authenticate_drive():
    """Authenticate with Google Drive API."""
    creds, _ = default(scopes=["https://www.googleapis.com/auth/drive.file"])
    return build("drive", "v3", credentials=creds)


def normalize_filename(text: str) -> str:
    """
    Normalize text for filename matching by removing special characters
    and converting to lowercase.
    """
    # Remove/replace characters that might cause filename issues
    normalized = re.sub(r'[<>:"/\\|?*]', '', text)
    normalized = re.sub(r'[^\w\s\-\(\)\'&,.]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized.lower()


def construct_expected_filename(song: str, artist: str) -> str:
    """Construct the expected Google Drive filename from song and artist."""
    return f"{song} - {artist}"


def load_csv_data(csv_path: str) -> List[Dict]:
    """Load and parse the tabdb CSV file."""
    songs = []
    with open(csv_path, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            songs.append(row)
    click.echo(f"Loaded {len(songs)} songs from CSV")
    return songs


def get_drive_files(drive, folder_ids: List[str]) -> Dict[str, dict]:
    """Get all files from the specified Drive folders, indexed by normalized name."""
    files = {}
    
    for folder_id in folder_ids:
        click.echo(f"Fetching files from folder {folder_id}...")
        query = f"'{folder_id}' in parents and trashed = false"
        
        page_token = None
        folder_files = []
        
        while True:
            try:
                resp = drive.files().list(
                    q=query,
                    pageSize=1000,
                    fields="nextPageToken, files(id,name,properties)",
                    pageToken=page_token,
                ).execute()
                
                folder_files.extend(resp.get("files", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
                    
            except HttpError as e:
                click.echo(f"Error fetching files from folder {folder_id}: {e}")
                break
        
        click.echo(f"Found {len(folder_files)} files in folder {folder_id}")
        
        for file in folder_files:
            # Remove .pdf extension and normalize for matching
            name_without_ext = file['name'].replace('.pdf', '')
            normalized_name = normalize_filename(name_without_ext)
            files[normalized_name] = file
    
    return files


def find_matching_file(expected_filename: str, drive_files: Dict[str, dict]) -> Optional[dict]:
    """Find the best matching Drive file for the expected filename."""
    normalized_expected = normalize_filename(expected_filename)
    
    # Try exact match first
    if normalized_expected in drive_files:
        return drive_files[normalized_expected]
    
    # Try fuzzy matching
    file_names = list(drive_files.keys())
    matches = get_close_matches(normalized_expected, file_names, n=1, cutoff=0.8)
    
    if matches:
        return drive_files[matches[0]]
    
    return None


def convert_metadata_for_drive(song_data: Dict) -> Dict[str, str]:
    """Convert CSV row data to Google Drive custom properties format."""
    # Google Drive custom properties must be strings
    properties = {}
    
    # Basic metadata
    if song_data.get('artist'):
        properties['artist'] = song_data['artist']
    if song_data.get('year'):
        properties['year'] = song_data['year']
    if song_data.get('difficulty'):
        properties['difficulty'] = song_data['difficulty']
    if song_data.get('duration'):
        properties['duration'] = song_data['duration']
    if song_data.get('language'):
        properties['language'] = song_data['language']
    if song_data.get('gender'):
        properties['gender'] = song_data['gender']
    if song_data.get('type'):
        properties['type'] = song_data['type']
    if song_data.get('tabber'):
        properties['tabber'] = song_data['tabber']
    if song_data.get('source'):
        properties['source'] = song_data['source']
    if song_data.get('date'):
        properties['date'] = song_data['date']
    if song_data.get('specialbooks'):
        properties['specialbooks'] = song_data['specialbooks']
    
    return properties


def apply_metadata_to_file(drive, file_id: str, properties: Dict[str, str], dry_run: bool = False) -> bool:
    """Apply custom properties to a Google Drive file."""
    if dry_run:
        click.echo(f"  [DRY RUN] Would apply properties: {properties}")
        return True
    
    try:
        drive.files().update(
            fileId=file_id,
            body={'properties': properties}
        ).execute()
        return True
    except HttpError as e:
        click.echo(f"  Error applying metadata: {e}")
        return False


@click.command()
@click.option(
    "--csv-path",
    default="tabdb.csv",
    help="Path to the tabdb CSV file"
)
@click.option(
    "--folder-id",
    multiple=True,
    required=True,
    help="Google Drive folder ID(s) containing the song files (can be specified multiple times)"
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be done without actually applying changes"
)
@click.option(
    "--show-unmatched",
    is_flag=True,
    help="Show songs from CSV that couldn't be matched to Drive files"
)
def migrate_metadata(csv_path: str, folder_id: List[str], dry_run: bool, show_unmatched: bool):
    """Migrate metadata from tabdb.csv to Google Drive file custom properties."""
    
    click.echo("Starting metadata migration...")
    
    # Load CSV data
    songs = load_csv_data(csv_path)
    
    # Authenticate and get Drive files
    click.echo("Authenticating with Google Drive...")
    drive = authenticate_drive()
    
    drive_files = get_drive_files(drive, list(folder_id))
    click.echo(f"Total Drive files found: {len(drive_files)}")
    
    # Process each song
    matched = 0
    unmatched = []
    errors = 0
    
    for song_data in songs:
        song_title = song_data['song']
        artist = song_data['artist']
        expected_filename = construct_expected_filename(song_title, artist)
        
        # Find matching Drive file
        matching_file = find_matching_file(expected_filename, drive_files)
        
        if matching_file:
            click.echo(f"✓ Matched: {expected_filename} → {matching_file['name']}")
            
            # Convert metadata to Drive properties format
            properties = convert_metadata_for_drive(song_data)
            
            # Apply metadata
            if apply_metadata_to_file(drive, matching_file['id'], properties, dry_run):
                matched += 1
            else:
                errors += 1
        else:
            unmatched.append(expected_filename)
            if show_unmatched:
                click.echo(f"✗ No match found for: {expected_filename}")
    
    # Summary
    click.echo("\n" + "="*50)
    click.echo("MIGRATION SUMMARY")
    click.echo("="*50)
    click.echo(f"Total songs in CSV: {len(songs)}")
    click.echo(f"Successfully matched: {matched}")
    click.echo(f"Unmatched songs: {len(unmatched)}")
    click.echo(f"Errors: {errors}")
    
    if dry_run:
        click.echo("\n[DRY RUN] No changes were actually applied.")
    
    if unmatched and not show_unmatched:
        click.echo(f"\nUse --show-unmatched to see the {len(unmatched)} unmatched songs.")


if __name__ == "__main__":
    migrate_metadata()
