from pdf import generate_songbook
import functions_framework
from flask import make_response


@functions_framework.http
def main(request):
    # CORS preflight handler
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
        return ("", 204, headers)

    body = request.json
    print(body)
    source_folders = body["source_folders"]
    cover_file_id = body["cover_file_id"]
    limit = body["limit"]

    pdf_path = generate_songbook(source_folders, limit, cover_file_id)

    if not pdf_path:
        return ("Failed to generate PDF", 500)

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = 'attachment; filename="songbook.pdf"'
    # **Include CORS on the real response too**
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp
