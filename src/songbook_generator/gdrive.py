
def download_files(drive, files, cache_dir):
    pdf_paths = []
    for f in files:
        file_id = f['id']
        file_name = f['name']
        file_details = drive.files().get(fileId=file_id, fields='modifiedTime').execute()
        song_sheets_dir = os.path.join(cache_dir, "song-sheets")
        os.makedirs(song_sheets_dir, exist_ok=True)
        cached_pdf_path = os.path.join(song_sheets_dir, f"{file_id}.pdf")
        if os.path.exists(cached_pdf_path):
            local_creation_time = os.path.getmtime(cached_pdf_path)
            remote_modified_time = file_details.get('modifiedTime')
            remote_modified_timestamp = datetime.fromisoformat(remote_modified_time.replace("Z", "+00:00"))
            local_creation_datetime = datetime.fromtimestamp(local_creation_time).astimezone()
            if remote_modified_timestamp <= local_creation_datetime:
                click.echo(f"Using cached version: {cached_pdf_path}")
                pdf_paths.append(cached_pdf_path)
                continue
        request = drive.files().export_media(fileId=file_id, mimeType='application/pdf')
        with open(cached_pdf_path, 'wb') as pdf_file:
            downloader = MediaIoBaseDownload(pdf_file, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        click.echo(f"Downloading file: {file_name} (ID: {file_id})...")
        pdf_paths.append(cached_pdf_path)
    return pdf_paths
