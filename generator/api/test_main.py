import json
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_req(method="GET", path="/", json_body=None):
    """Build a minimal mock request object matching the Flask API interface."""
    req = MagicMock()
    req.method = method
    req.path = path
    req.get_json.return_value = json_body or {}
    req.get_data.return_value = json.dumps(json_body or {}).encode()
    return req


def _make_services(tracer=None):
    """Return a minimal services dict with a no-op tracer."""
    if tracer is None:
        tracer = MagicMock()
        tracer.start_as_current_span.return_value.__enter__ = lambda s, *a: MagicMock()
        tracer.start_as_current_span.return_value.__exit__ = lambda s, *a: False
    return {
        "tracer": tracer,
        "db": MagicMock(),
        "publisher": MagicMock(),
        "topic_path": "projects/test/topics/test",
        "firestore_collection": "jobs",
    }


# ---------------------------------------------------------------------------
# GET /editions tests
# ---------------------------------------------------------------------------


class TestHandleGetEditions:
    """Unit tests for handle_get_editions."""

    def test_returns_config_editions(self, mocker):
        """Config editions are always included in the response."""
        from ..common.config import Edition
        from ..common.filters import PropertyFilter, FilterOperator

        mock_edition = Edition(
            id="current",
            title="Current",
            description="Current songs",
            filters=[
                PropertyFilter(
                    key="specialbooks",
                    operator=FilterOperator.CONTAINS,
                    value="regular",
                )
            ],
        )
        mock_settings = MagicMock()
        mock_settings.editions = [mock_edition]
        mocker.patch("generator.api.main.get_settings", return_value=mock_settings)
        mocker.patch("generator.api.main._get_drive_client", return_value=MagicMock())
        mocker.patch("generator.api.main.scan_drive_editions", return_value=([], []))

        from generator.api.main import handle_get_editions

        body, status, headers = handle_get_editions(_make_services())

        assert status == 200
        data = json.loads(body)
        assert len(data["editions"]) == 1
        edition = data["editions"][0]
        assert edition["id"] == "current"
        assert edition["title"] == "Current"
        assert edition["source"] == "config"

    def test_includes_drive_editions(self, mocker):
        """Drive-detected editions are appended after config editions."""
        from ..common.config import Edition
        from ..common.filters import PropertyFilter, FilterOperator

        config_edition = Edition(
            id="current",
            title="Current",
            description="Current songs",
            filters=[
                PropertyFilter(
                    key="specialbooks",
                    operator=FilterOperator.CONTAINS,
                    value="regular",
                )
            ],
        )
        drive_edition = Edition(
            id="drive-ed",
            title="Drive Edition",
            description="A drive edition",
            filters=[
                PropertyFilter(
                    key="specialbooks",
                    operator=FilterOperator.CONTAINS,
                    value="test",
                )
            ],
        )

        mock_settings = MagicMock()
        mock_settings.editions = [config_edition]
        mocker.patch("generator.api.main.get_settings", return_value=mock_settings)

        mock_drive_client = MagicMock()
        mocker.patch(
            "generator.api.main._get_drive_client", return_value=mock_drive_client
        )
        mocker.patch(
            "generator.api.main.scan_drive_editions",
            return_value=([("folder_xyz", drive_edition)], []),
        )

        from generator.api.main import handle_get_editions

        body, status, _ = handle_get_editions(_make_services())

        assert status == 200
        data = json.loads(body)
        editions = data["editions"]
        assert len(editions) == 2

        config_ed = editions[0]
        assert config_ed["source"] == "config"
        assert config_ed["id"] == "current"

        drive_ed = editions[1]
        assert drive_ed["source"] == "drive"
        assert drive_ed["id"] == "folder_xyz"
        assert drive_ed["folder_id"] == "folder_xyz"
        assert drive_ed["title"] == "Drive Edition"

    def test_drive_error_sets_drive_error_field(self, mocker):
        """If Drive access fails the response still succeeds with a drive_error field."""
        from googleapiclient.errors import HttpError

        mock_settings = MagicMock()
        mock_settings.editions = []
        mocker.patch("generator.api.main.get_settings", return_value=mock_settings)

        http_err = HttpError(resp=MagicMock(status=403), content=b"Forbidden")
        mocker.patch("generator.api.main._get_drive_client", side_effect=http_err)

        from generator.api.main import handle_get_editions

        body, status, _ = handle_get_editions(_make_services())

        assert status == 200
        data = json.loads(body)
        assert "drive_error" in data
        assert data["editions"] == []

    def test_no_drive_editions_when_no_files(self, mocker):
        """When Drive has no .songbook.yaml files the list only has config editions."""
        from ..common.config import Edition
        from ..common.filters import PropertyFilter, FilterOperator

        config_edition = Edition(
            id="current",
            title="Current",
            description="Current songs",
            filters=[
                PropertyFilter(
                    key="specialbooks",
                    operator=FilterOperator.CONTAINS,
                    value="regular",
                )
            ],
        )
        mock_settings = MagicMock()
        mock_settings.editions = [config_edition]
        mocker.patch("generator.api.main.get_settings", return_value=mock_settings)

        mock_drive_client = MagicMock()
        mocker.patch(
            "generator.api.main._get_drive_client", return_value=mock_drive_client
        )
        mocker.patch("generator.api.main.scan_drive_editions", return_value=([], []))

        from generator.api.main import handle_get_editions

        body, status, _ = handle_get_editions(_make_services())

        assert status == 200
        data = json.loads(body)
        assert len(data["editions"]) == 1
        assert "drive_error" not in data

    def test_invalid_drive_editions_included_in_response(self, mocker):
        """Drive editions that fail validation appear in the response with
        status='error' and an error message."""
        from ..common.editions import DriveEditionError

        mock_settings = MagicMock()
        mock_settings.editions = []
        mocker.patch("generator.api.main.get_settings", return_value=mock_settings)
        mocker.patch("generator.api.main._get_drive_client", return_value=MagicMock())

        error_entry = DriveEditionError(
            folder_id="folder_bad",
            folder_name="Bad Folder",
            error="Could not parse .songbook.yaml: invalid YAML",
        )
        mocker.patch(
            "generator.api.main.scan_drive_editions",
            return_value=([], [error_entry]),
        )

        from generator.api.main import handle_get_editions

        body, status, _ = handle_get_editions(_make_services())

        assert status == 200
        data = json.loads(body)
        assert len(data["editions"]) == 1
        err_ed = data["editions"][0]
        assert err_ed["id"] == "folder_bad"
        assert err_ed["folder_id"] == "folder_bad"
        assert err_ed["folder_name"] == "Bad Folder"
        assert err_ed["source"] == "drive"
        assert err_ed["status"] == "error"
        assert "Could not parse" in err_ed["error"]
        assert "drive_error" not in data


# ---------------------------------------------------------------------------
# Routing tests – GET /editions is dispatched correctly
# ---------------------------------------------------------------------------


class TestApiMainRouting:
    """Verify that api_main routes GET /editions to handle_get_editions."""

    def test_get_editions_route(self, mocker):
        """GET /editions returns a JSON list of editions."""
        from ..common.config import Edition
        from ..common.filters import PropertyFilter, FilterOperator

        mock_edition = Edition(
            id="current",
            title="Current",
            description="Current songs",
            filters=[
                PropertyFilter(
                    key="specialbooks",
                    operator=FilterOperator.CONTAINS,
                    value="regular",
                )
            ],
        )
        mock_settings = MagicMock()
        mock_settings.editions = [mock_edition]
        mocker.patch("generator.api.main.get_settings", return_value=mock_settings)
        mocker.patch("generator.api.main._get_drive_client", return_value=MagicMock())
        mocker.patch("generator.api.main.scan_drive_editions", return_value=([], []))

        # Patch service init so no real GCP calls happen
        mocker.patch("generator.api.main._get_services", return_value=_make_services())

        from generator.api.main import api_main

        req = _make_req(method="GET", path="/editions")
        body, status, headers = api_main(req)

        assert status == 200
        data = json.loads(body)
        assert "editions" in data
