import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / ".github" / "scripts" / "config-requires-regen.py"

BASE = 'id: "e"\ntitle: "E"\ndescription: "D"\n'


def _requires_regen(tmp_path, old: str, new: str) -> bool:
    (tmp_path / "old.yaml").write_text(old)
    (tmp_path / "new.yaml").write_text(new)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), tmp_path / "old.yaml", tmp_path / "new.yaml"],
        capture_output=True,
    )
    return result.returncode == 0


@pytest.mark.parametrize(
    "old, new, expected",
    [
        (BASE, BASE + 'sections: {cover: {file_id: "x"}}\n', True),
        (BASE, BASE + "publish: {pinned: true}\n", False),
        (
            BASE + "frozen: true\n",
            BASE + 'frozen: true\nsections: {cover: {file_id: "x"}}\n',
            False,
        ),
        (BASE, BASE + 'frozen: true\nsections: {cover: {file_id: "x"}}\n', False),
        (BASE + "frozen: true\n", BASE, True),
    ],
    ids=[
        "content change",
        "publish-only change",
        "frozen edition changed",
        "freezing with a change",
        "unfreezing",
    ],
)
def test_config_requires_regen(tmp_path, old, new, expected):
    assert _requires_regen(tmp_path, old, new) is expected
