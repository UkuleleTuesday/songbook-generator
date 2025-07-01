from pdf import generate_songbook
import functions_framework
from flask import make_response
import os


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

    # Handle GET request
    if request.method == "GET":
        headers = {
            "Access-Control-Allow-Origin": "*",
        }
        return make_response(("OK", 200, headers))

    # Handle POST request
    if request.method == "POST":
        headers = {
            "Access-Control-Allow-Origin": "*",
        }
        return make_response(("OK", 200, headers))

