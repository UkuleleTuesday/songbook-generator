from pdf import generate_songbook
import functions_framework


@functions_framework.http
def main(request):
    body = request.json
    print(body)
    source_folders = body["source_folders"]
    limit = body["limit"]
    generate_songbook(source_folders, limit)
    return "OK"
