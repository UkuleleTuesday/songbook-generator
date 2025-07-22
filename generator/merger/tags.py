from typing import Any, Callable, Dict, List, Optional

# A list to hold all tagged functions
_TAGGERS: List[Callable[[Dict[str, Any]], Any]] = []

# Folder IDs for status checking.
# Ref: generator/common/config.py:DEFAULT_GDRIVE_FOLDER_IDS
FOLDER_ID_APPROVED = "1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95"
FOLDER_ID_READY_TO_PLAY = "1bvrIMQXjAxepzn4Vx8wEjhk3eQS5a9BM"


def tag(func: Callable[[Dict[str, Any]], Any]) -> Callable[[Dict[str, Any]], Any]:
    """Decorator to register a function as a tag generator."""
    _TAGGERS.append(func)
    return func


class Tagger:
    def __init__(self, drive_service: Any):
        self.drive_service = drive_service

    def update_tags(self, file: Dict[str, Any]):
        """
        Update Google Drive file properties based on registered tag functions.

        For each function decorated with @tag, this function calls it with the
        file object. If the function returns a value other than None, it updates
        the file's `appProperties` with the function name as the key and the
        return value as the value.
        """
        properties_to_update = {}
        for tagger in _TAGGERS:
            tag_name = tagger.__name__
            tag_value = tagger(file)
            if tag_value is not None:
                properties_to_update[tag_name] = str(tag_value)

        if properties_to_update:
            # Note: This will overwrite existing appProperties. A
            # read-modify-write would be needed to preserve other properties.
            # For now, this is fine.
            self.drive_service.files().update(
                fileId=file["id"],
                body={"properties": properties_to_update},
                fields="properties",
            ).execute()


@tag
def status(file: Dict[str, Any]) -> Optional[str]:
    """Determine the status of a file based on its parent folder."""
    parents = file.get("parents", [])
    if FOLDER_ID_APPROVED in parents:
        return "APPROVED"
    if FOLDER_ID_READY_TO_PLAY in parents:
        return "READY_TO_PLAY"
    return None
