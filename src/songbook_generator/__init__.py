import click
from google.auth import default
from googleapiclient.discovery import build


@click.command()
@click.option(
    '--source-folder', '-s',
    required=True,
    help='Drive folder ID to read files from'
)
@click.option(
    '--dest-folder', '-d',
    required=True,
    help='Drive folder ID to write output to (not used yet)'
)
@click.option(
    '--limit', '-l',
    type=int,
    default=100,
    help='Limit the number of files to process (default is 100)'
)
def main(source_folder: str, dest_folder: str, limit: int):
    """
    MVP: list files in SOURCE_FOLDER. DEST_FOLDER is reserved for the merged PDF.
    """
    # 1) Authenticate with ADC
    creds, _ = default(
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    drive = build('drive', 'v3', credentials=creds)

    # 2) Query files in the source folder
    query = f"'{source_folder}' in parents and trashed = false"
    resp = drive.files().list(
        q=query,
        pageSize=1000,  # Fetch a large number of files to ensure all are retrieved
        fields="files(id,name)"
    ).execute()

    files = sorted(resp.get('files', []), key=lambda f: f['name'])[:limit]
    if not files:
        click.echo(f'No files found in folder {source_folder}.')
        return

    # 3) Print them out
    click.echo(f'Files in folder {source_folder}:')
    for f in files:
        click.echo(f" • {f['name']}  ({f['id']})")

if __name__ == '__main__':
    main()
