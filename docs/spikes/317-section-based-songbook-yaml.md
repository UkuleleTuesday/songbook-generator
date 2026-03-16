# 317 – Improved songbook.yaml structure with section-based blocks

## Problem statement

The current `songbook.yaml` schema places all edition configuration fields at
the top level of the `Edition` model:

```yaml
id: "current"
title: "Ukulele Tuesday - Current Songbook"
description: "..."
cover_file_id: "1rxn4Kl6..."
preface_file_ids:
  - "1ZxYst-..."
postface_file_ids:
  - "1Abc123..."
filters:
  - key: "specialbooks"
    operator: "contains"
    value: "regular"
table_of_contents:
  postfixes:
    - postfix: " ☘"
      filters:
        - key: "specialbooks"
          operator: "contains"
          value: "ireland"
```

As the number of edition options grows this flat structure has several
problems:

- **Readability**: `filters` (which selects songs) sits at the same level as
  `table_of_contents` (which only controls rendering). Their relationship to
  each other and to the structure of the PDF is not obvious.
- **Scalability**: Adding new song-selection options (e.g. `sort_by`, `limit`)
  or new per-section options (e.g. `table_of_contents.enabled`) pollutes the
  top-level namespace.
- **Discoverability**: A user reading a `.songbook.yaml` file for the first
  time has no structural cues about which fields relate to which part of the
  output PDF.
- **`cover_file_id` inconsistency**: `cover_file_id` is a scalar that
  describes a content component of the PDF, yet it sits at the same level as
  identity fields like `id` and `title`.

The hypothesis explored here is that grouping configuration into explicit
**section blocks** improves clarity, reduces ambiguity, and provides a natural
extension point for future per-section features.

---

## Proposed new structure

```yaml
id: "current"
title: "Ukulele Tuesday - Current Songbook"
description: "..."
sections:
  cover:
    file_id: "1rxn4Kl6..."
  preface:
    file_ids:
      - "1ZxYst-..."
  table_of_contents:
    postfixes:
      - postfix: " ☘"
        filters:
          - key: "specialbooks"
            operator: "contains"
            value: "ireland"
  songs:
    filters:
      - key: "specialbooks"
        operator: "contains"
        value: "regular"
  postface:
    file_ids:
      - "1Abc123..."
```

### Section inventory

| Section | Fields | Purpose |
|---|---|---|
| `cover` | `file_id` | Single Drive file ID for the cover page |
| `preface` | `file_ids` | Ordered Drive file IDs prepended before the TOC |
| `table_of_contents` | all existing `Toc` fields + `postfixes` | TOC rendering and layout settings |
| `songs` | `filters` | Property-based filter expressions that select which songs are included |
| `postface` | `file_ids` | Ordered Drive file IDs appended after the song pages |

The only remaining top-level fields are:
- **Identity fields**: `id`, `title`, `description`
- **Operational flag**: `use_folder_components`

---

## Migrated config examples

### `current.yaml` (before → after)

**Before:**
```yaml
id: "current"
title: "Ukulele Tuesday - Current Songbook"
description: >
  The current edition...
cover_file_id: "1rxn4Kl6fe-SUFqfYieb5FrxkVwHLLVPbwOXtWRGc740"
preface_file_ids:
  - "1ZxYst-xswtkO6ZSU7tiPKKDoYwvBRWo-ag2tyu6fO2w"
table_of_contents:
  postfixes:
    - postfix: " ☘"
      filters:
        - key: "specialbooks"
          operator: "contains"
          value: "ireland"
filters:
  - key: "specialbooks"
    operator: "contains"
    value: "regular"
```

**After:**
```yaml
id: "current"
title: "Ukulele Tuesday - Current Songbook"
description: >
  The current edition...
sections:
  cover:
    file_id: "1rxn4Kl6fe-SUFqfYieb5FrxkVwHLLVPbwOXtWRGc740"
  preface:
    file_ids:
      - "1ZxYst-xswtkO6ZSU7tiPKKDoYwvBRWo-ag2tyu6fO2w"
  table_of_contents:
    postfixes:
      - postfix: " ☘"
        filters:
          - key: "specialbooks"
            operator: "contains"
            value: "ireland"
  songs:
    filters:
      - key: "specialbooks"
        operator: "contains"
        value: "regular"
```

### `ukulele-hooley-2025.yaml` (before → after)

**Before:**
```yaml
id: "ukulele-hooley-2025"
title: "Ukulele Hooley 2025"
description: "The official songbook for the 2025 Ukulele Hooley Friday jam."
cover_file_id: "1jpZvqrpNF7HjX5_gpjH8FG8DLHKP63JjRU1gWbVpSg8"
preface_file_ids:
  - "1cn7ZzJPD5g4IaPPfx5IJY0L9k7eboMwGV_KEnf4zdXs"
table_of_contents:
  include_difficulty: false
  include_wip_marker: false
  columns_per_page: 1
  column_width: 360
  margin_left: 120
  margin_right: 120
  text_fontsize: 12
  line_spacing: 15
filters:
  - key: "specialbooks"
    operator: "contains"
    value: "hooley-2025"
```

**After:**
```yaml
id: "ukulele-hooley-2025"
title: "Ukulele Hooley 2025"
description: "The official songbook for the 2025 Ukulele Hooley Friday jam."
sections:
  cover:
    file_id: "1jpZvqrpNF7HjX5_gpjH8FG8DLHKP63JjRU1gWbVpSg8"
  preface:
    file_ids:
      - "1cn7ZzJPD5g4IaPPfx5IJY0L9k7eboMwGV_KEnf4zdXs"
  table_of_contents:
    include_difficulty: false
    include_wip_marker: false
    columns_per_page: 1
    column_width: 360
    margin_left: 120
    margin_right: 120
    text_fontsize: 12
    line_spacing: 15
  songs:
    filters:
      - key: "specialbooks"
        operator: "contains"
        value: "hooley-2025"
```

The same pattern applies to `complete.yaml`, `wexford-2026.yaml`, and
`womens-2026.yaml`.

---

## Implementation guide

This section describes every file a future implementor will need to change,
with the exact code changes required.

### 1. `generator/common/config.py` — data model changes

#### 1a. Add five new Pydantic models

Insert after the `Toc` class (before the `Edition` class):

```python
class CoverSection(BaseModel):
    """Configuration for the cover section of a songbook edition."""

    file_id: Optional[str] = None


class PrefaceSection(BaseModel):
    """Configuration for the preface section of a songbook edition."""

    file_ids: Optional[List[str]] = None


class PostfaceSection(BaseModel):
    """Configuration for the postface section of a songbook edition."""

    file_ids: Optional[List[str]] = None


class SongsSection(BaseModel):
    """Configuration for the songs section of a songbook edition."""

    filters: List[Union[FilterGroup, PropertyFilter]] = Field(default_factory=list)


class EditionSections(BaseModel):
    """Section-based configuration blocks for a songbook edition."""

    cover: Optional[CoverSection] = None
    preface: Optional[PrefaceSection] = None
    table_of_contents: Optional[Toc] = None
    songs: SongsSection = Field(default_factory=SongsSection)
    postface: Optional[PostfaceSection] = None
```

#### 1b. Replace the `Edition` model

Replace the current flat `Edition` model:

```python
# BEFORE
class Edition(BaseModel):
    id: str
    title: str
    description: str
    cover_file_id: Optional[str] = None
    preface_file_ids: Optional[List[str]] = None
    postface_file_ids: Optional[List[str]] = None
    filters: List[Union[FilterGroup, PropertyFilter]]
    table_of_contents: Optional[Toc] = None
    use_folder_components: bool = False
```

With the new sections-based model:

```python
# AFTER
class Edition(BaseModel):
    id: str
    title: str
    description: str
    sections: EditionSections = Field(default_factory=EditionSections)
    use_folder_components: bool = False

    @property
    def cover_file_id(self) -> Optional[str]:
        """Convenience accessor for sections.cover.file_id."""
        return self.sections.cover.file_id if self.sections.cover else None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_format(cls, data: object) -> object:
        """Migrate flat legacy fields to the new sections-based format.

        Accepts the old flat structure (``cover_file_id``, ``filters``,
        ``preface_file_ids``, ``postface_file_ids``, ``table_of_contents``
        at the top level) and converts it to the new ``sections``-based
        structure so that existing ``.songbook.yaml`` files hosted in Google
        Drive remain fully backward-compatible without any manual migration.
        """
        if not isinstance(data, dict):
            return data

        sections: dict = data.pop("sections", {})
        if isinstance(sections, dict):
            sections = dict(sections)

        cover_file_id = data.pop("cover_file_id", None)
        if cover_file_id is not None and "cover" not in sections:
            sections["cover"] = {"file_id": cover_file_id}

        preface_ids = data.pop("preface_file_ids", None)
        if preface_ids is not None and "preface" not in sections:
            sections["preface"] = {"file_ids": preface_ids}

        postface_ids = data.pop("postface_file_ids", None)
        if postface_ids is not None and "postface" not in sections:
            sections["postface"] = {"file_ids": postface_ids}

        toc = data.pop("table_of_contents", None)
        if toc is not None and "table_of_contents" not in sections:
            sections["table_of_contents"] = toc

        filters = data.pop("filters", None)
        if filters is not None and "songs" not in sections:
            sections["songs"] = {"filters": filters}

        if sections:
            data["sections"] = sections

        return data
```

> **Note on the `cover_file_id` property:** Many call sites in `pdf.py`,
> `editions.py`, and `test_pdf.py` access `edition.cover_file_id`. Adding the
> property means these do not require immediate changes, giving you a clean
> incremental migration path. You may later choose to remove the property and
> update all call sites to use `edition.sections.cover.file_id` directly.

---

### 2. Config YAML files — migrate to new format

Update all five files under `generator/config/songbooks/` to use the new
`sections` structure. The transformation for each file is mechanical:

| Old top-level field | New location |
|---|---|
| `cover_file_id: "..."` | `sections.cover.file_id: "..."` |
| `preface_file_ids: [...]` | `sections.preface.file_ids: [...]` |
| `postface_file_ids: [...]` | `sections.postface.file_ids: [...]` |
| `table_of_contents: {...}` | `sections.table_of_contents: {...}` |
| `filters: [...]` | `sections.songs.filters: [...]` |

See the [Migrated config examples](#migrated-config-examples) section above
for a full before/after for `current.yaml` and `ukulele-hooley-2025.yaml`.

> **Important:** Because the `migrate_legacy_format` validator runs at parse
> time, _Drive-hosted_ `.songbook.yaml` files do **not** need to be changed.
> Only the checked-in config files under `generator/config/songbooks/` should
> be migrated as part of this work.

---

### 3. `generator/worker/pdf.py` — update field accesses

#### 3a. Add `CoverSection` to imports

```python
# BEFORE
from ..common.config import PrefaceSection, PostfaceSection

# AFTER
from ..common.config import CoverSection, PrefaceSection, PostfaceSection
```

#### 3b. `resolve_folder_components` — switch from flat fields to sections

The function currently checks `edition.cover_file_id`,
`edition.preface_file_ids`, and `edition.postface_file_ids` and stores
resolved values in a flat `updates` dict.  It must instead check and populate
`edition.sections.cover`, `edition.sections.preface`, and
`edition.sections.postface` respectively.

**Current code (abridged):**
```python
updates: dict = {}

# --- Cover ---
if edition.cover_file_id is None:
    ...
    updates["cover_file_id"] = cover_files[0].id

# --- Preface ---
if edition.preface_file_ids is None:
    ...
    updates["preface_file_ids"] = [f.id for f in preface_files]

# --- Postface ---
if edition.postface_file_ids is None:
    ...
    updates["postface_file_ids"] = [f.id for f in postface_files]

if updates:
    return edition.model_copy(update=updates)
return edition
```

**New code:**
```python
sections_updates: dict = {}

# --- Cover ---
if edition.cover_file_id is None:   # cover_file_id property still works
    ...
    sections_updates["cover"] = CoverSection(file_id=cover_files[0].id)

# --- Preface ---
if edition.sections.preface is None:
    ...
    sections_updates["preface"] = PrefaceSection(
        file_ids=[f.id for f in preface_files]
    )

# --- Postface ---
if edition.sections.postface is None:
    ...
    sections_updates["postface"] = PostfaceSection(
        file_ids=[f.id for f in postface_files]
    )

if sections_updates:
    new_sections = edition.sections.model_copy(update=sections_updates)
    return edition.model_copy(update={"sections": new_sections})
return edition
```

#### 3c. `generate_songbook_from_edition` — update filter and field access

```python
# BEFORE
if edition.filters:
    if len(edition.filters) == 1:
        client_filter = edition.filters[0]
    else:
        client_filter = FilterGroup(operator="AND", filters=edition.filters)

return generate_songbook(
    ...
    cover_file_id=edition.cover_file_id,        # still works via property
    preface_file_ids=edition.preface_file_ids,
    postface_file_ids=edition.postface_file_ids,
    edition_toc_config=edition.table_of_contents,
    ...
)

# AFTER
if edition.sections.songs.filters:
    if len(edition.sections.songs.filters) == 1:
        client_filter = edition.sections.songs.filters[0]
    else:
        client_filter = FilterGroup(
            operator="AND", filters=edition.sections.songs.filters
        )

return generate_songbook(
    ...
    cover_file_id=edition.cover_file_id,        # still works via property
    preface_file_ids=(
        edition.sections.preface.file_ids
        if edition.sections.preface is not None
        else None
    ),
    postface_file_ids=(
        edition.sections.postface.file_ids
        if edition.sections.postface is not None
        else None
    ),
    edition_toc_config=edition.sections.table_of_contents,
    ...
)
```

#### 3d. `_build_generation_manifest` — update edition info dict

```python
# BEFORE
manifest["edition"] = {
    "id": edition.id,
    "title": edition.title,
    "description": edition.description,
    "cover_file_id": edition.cover_file_id,
    "preface_file_ids": edition.preface_file_ids,
    "postface_file_ids": edition.postface_file_ids,
    "table_of_contents_config": (
        edition.table_of_contents.model_dump(mode="json")
        if edition.table_of_contents
        else None
    ),
    "filters": [{**f.model_dump(mode="json")} for f in edition.filters]
    if edition.filters
    else [],
}

# AFTER
manifest["edition"] = {
    "id": edition.id,
    "title": edition.title,
    "description": edition.description,
    "cover_file_id": edition.cover_file_id,  # property; no change needed
    "preface_file_ids": (
        edition.sections.preface.file_ids
        if edition.sections.preface is not None
        else None
    ),
    "postface_file_ids": (
        edition.sections.postface.file_ids
        if edition.sections.postface is not None
        else None
    ),
    "table_of_contents_config": (
        edition.sections.table_of_contents.model_dump(mode="json")
        if edition.sections.table_of_contents is not None
        else None
    ),
    "filters": [
        {**f.model_dump(mode="json")}
        for f in edition.sections.songs.filters
    ],
}
```

---

### 4. `generator/cli/editions.py` — update serialization and shortcut creation

#### 4a. `serialize_edition_to_yaml` — strip sections instead of top-level fields

```python
# BEFORE
data = edition.model_dump(mode="json", exclude_unset=True)
if use_folder_components:
    data["use_folder_components"] = True
    data.pop("cover_file_id", None)
    data.pop("preface_file_ids", None)
    data.pop("postface_file_ids", None)

# AFTER
data = edition.model_dump(mode="json", exclude_unset=True)
if use_folder_components:
    data["use_folder_components"] = True
    sections = data.get("sections", {})
    sections.pop("cover", None)
    sections.pop("preface", None)
    sections.pop("postface", None)
    if sections:
        data["sections"] = sections
    else:
        data.pop("sections", None)
```

Also update the docstring: replace references to `cover_file_id`,
`preface_file_ids`, `postface_file_ids` with `sections.cover`,
`sections.preface`, `sections.postface`.

#### 4b. `create_edition_folder_components` — update field access

```python
# BEFORE
if edition.cover_file_id:
    ...create shortcut using edition.cover_file_id...

preface_ids: List[str] = edition.preface_file_ids or []
...
postface_ids: List[str] = edition.postface_file_ids or []

# AFTER
if edition.cover_file_id:   # property; still works
    ...create shortcut using edition.cover_file_id...

preface_ids: List[str] = (
    edition.sections.preface.file_ids
    if edition.sections.preface is not None
    else []
) or []
...
postface_ids: List[str] = (
    edition.sections.postface.file_ids
    if edition.sections.postface is not None
    else []
) or []
```

#### 4c. `_warn_complex_edition_features` — update the drive-edition display logic

Any place that currently reads `edition.preface_file_ids`,
`edition.postface_file_ids`, or `edition.cover_file_id` in the editions
summary/display output should switch to the `sections.*` equivalents.

---

### 5. `generator/cli/songs.py` — update filter access

```python
# BEFORE
client_filter = parse_filters(edition_config.filters)

# AFTER
client_filter = parse_filters(edition_config.sections.songs.filters)
```

> `parse_filters` accepts `List[Union[FilterGroup, PropertyFilter]]`; the
> type is unchanged, only the access path changes.

---

### 6. Tests — update assertions

#### `generator/worker/test_pdf.py`

Any test that constructs an `Edition` with flat keyword arguments will need
updating.  The migration validator handles dicts, but direct Pydantic
construction from keyword arguments bypasses the validator:

```python
# BEFORE — direct construction with flat fields
edition = Edition(
    id="test",
    title="Test",
    description="Test",
    cover_file_id="cover123",
    preface_file_ids=["preface123"],
    filters=[...],
    table_of_contents={"include_difficulty": False},
)

# AFTER — use the dict path (validator runs) or use the new structure
edition = Edition.model_validate({
    "id": "test",
    "title": "Test",
    "description": "Test",
    "cover_file_id": "cover123",        # migrated automatically
    "preface_file_ids": ["preface123"], # migrated automatically
    "filters": [...],                   # migrated automatically
    "table_of_contents": {"include_difficulty": False},  # migrated automatically
})

# — or — use the new structure directly
edition = Edition(
    id="test",
    title="Test",
    description="Test",
    sections=EditionSections(
        cover=CoverSection(file_id="cover123"),
        preface=PrefaceSection(file_ids=["preface123"]),
        table_of_contents=Toc(include_difficulty=False),
        songs=SongsSection(filters=[...]),
    ),
)
```

Any assertion on `edition.cover_file_id` continues to work via the property.

Assertions that previously checked `edition.preface_file_ids` or
`edition.postface_file_ids` should be updated to:
```python
# BEFORE
assert result.preface_file_ids == ["preface123"]
assert result.postface_file_ids is None

# AFTER
assert result.sections.preface.file_ids == ["preface123"]
assert result.sections.postface is None
```

`resolve_folder_components` tests that previously asserted
`result.cover_file_id == "cover_file_id"` still work through the property.
However, if a test verifies the _structure_ of the returned edition it should
also check `result.sections.cover.file_id`.

#### `generator/cli/test_editions.py`

The `serialize_edition_to_yaml` tests will need updating to expect
`sections.cover`/`sections.preface`/`sections.postface` keys in the serialized
YAML output instead of `cover_file_id`/`preface_file_ids`/`postface_file_ids`.

---

## Options considered

### Option A – Section-based blocks at the `sections` key ✅ (recommended)

**How it works**: A top-level `sections` key contains named sub-keys
(`cover`, `preface`, `table_of_contents`, `songs`, `postface`). A
`model_validator(mode="before")` on `Edition` converts old flat files
transparently.

**Pros**:
- Explicit grouping makes the relationships between fields obvious.
- Each section is independently optional with clean defaults.
- Natural extension point: new per-section fields can be added without
  polluting the top-level namespace (e.g. `songs.sort_by`,
  `table_of_contents.enabled: false`, `preface.page_numbers: false`).
- Fully backward-compatible: old flat files continue to work via the migration
  validator.

**Cons**:
- More nesting depth; simple editions have slightly more boilerplate.
- Drive-hosted `.songbook.yaml` files will continue to use the old flat format
  until a user re-uploads via the CLI, which means two valid formats will
  co-exist indefinitely unless a migration tool is built.

### Option B – Keep flat YAML, add typed sub-models internally only

**How it works**: Leave the YAML schema unchanged; only reorganise the
internal Python models.

**Pros**: Zero YAML migration required.

**Cons**: The flat schema problem remains visible to users who write YAML by
hand or inspect Drive-hosted files. Internal refactoring without user benefit.

### Option C – Rename fields without grouping

**How it works**: Replace `filters` with `songs_filters`, keep
`preface_file_ids`, etc.

**Pros**: Single-level; no nesting.

**Cons**: Does not solve the scalability problem; adding new options (e.g.
`songs_sort_by`, `songs_limit`) still pollutes the top level.

---

## Findings

### Backward compatibility is straightforward

The Pydantic `model_validator(mode="before")` hook cleanly separates the
migration concern from the model definition. Old files parsed via
`Edition.model_validate(yaml_data)` are migrated transparently; no call-site
changes are needed in the worker or CLI for the _parsing_ path.

However, **direct Pydantic field construction** (e.g. in tests via
`Edition(cover_file_id=..., filters=...)`) bypasses the validator.  Tests
using this pattern must be updated to use `Edition.model_validate({...})` or
the new `sections=...` structure.

### Drive-hosted files remain valid

The migration validator runs any time an `Edition` is constructed from a dict,
which is the normal path via `yaml.safe_load`. Files in Google Drive with the
old flat format continue to work without requiring manual Drive edits.

### Re-serialization reflects the new structure

When the CLI serializes an edition back to YAML (e.g. during
`editions convert`), `model_dump` will produce the new `sections` structure.
Users who inspect or re-upload the re-generated `.songbook.yaml` will see the
new format. This is the natural migration path for Drive-hosted files.

### The `filters` rename is the most user-visible change

Moving `filters` under `sections.songs.filters` is the change most likely to
confuse users who hand-edit `.songbook.yaml` files in Drive. The migration
validator handles the transition silently, but user-facing documentation and
any schema reference will need to be updated to show the new path.

### The `cover_file_id` property bridges the two worlds cleanly

Because `cover_file_id` is used in many places (`pdf.py`, `editions.py`,
`test_pdf.py`) a backward-compat property on `Edition` allows those call sites
to remain unchanged while the underlying storage moves to
`sections.cover.file_id`. The property can be removed in a follow-on clean-up
PR once all call sites are updated.

---

## Recommendation

**Option A** (section-based blocks) is recommended.  The migration validator
makes the change non-breaking for all existing Drive-hosted files. The code
change is well-contained and the implementation path above describes every
file that needs updating.

Suggested follow-on steps after implementation:

1. **Remove the `cover_file_id` property** and update all call sites to use
   `edition.sections.cover.file_id` directly.
2. **Document the new schema** in the project's user-facing documentation so
   users who hand-write `.songbook.yaml` files know the preferred structure.
3. **Add per-section feature flags** now that the structure supports them — for
   example `songs.limit` (cap number of songs), `table_of_contents.enabled`
   (skip TOC generation), `preface.include_in_toc: false`.
4. **Extend `SongsSection`** with a `sort_by` field to allow per-edition song
   ordering without code changes.
5. **Emit a deprecation warning** in the migration validator when it detects
   legacy flat fields, guiding users to update their Drive-hosted files.
6. **Update the `editions add` CLI command** (when created) to generate YAML in
   the new sections format by default.
