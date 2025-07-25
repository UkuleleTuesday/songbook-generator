from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class File:
    """Represents a file from Google Drive."""

    id: str
    name: str
    properties: Dict[str, str] = field(default_factory=dict)
    mimeType: Optional[str] = None
    parents: List[str] = field(default_factory=list)
