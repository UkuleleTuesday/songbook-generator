from . import generate_songbook
import functions_framework


@functions_framework.http
def main(request):
    body = request.json
    print(body)
    source_folder = body["source_folder"]
    limit = body["limit"]
    generate_songbook(source_folder, limit)
    return "OK"
