# In-folder Components for Drive-based Songbook Editions

## Overview

When building a songbook from a Google Drive folder that contains a
`.songbook.yaml` file, cover, preface, and postface pages can be sourced
automatically from **dedicated subfolders** inside the edition folder.
This removes the need to hard-code Drive file IDs in the YAML configuration
and makes it straightforward for non-technical users to update these
components directly in Drive.

---

## How It Works

When the `use_folder_components: true` option is set in an edition's
`.songbook.yaml`, the generator scans the edition folder for subfolders
whose names match the following (case-insensitive):

| Subfolder name | Component |
|---|---|
| `Cover` | Cover page – the first file (alphabetically) is used |
| `Preface` | Preface pages – all files, ordered alphabetically |
| `Postface` | Postface pages – all files, ordered alphabetically |

### Precedence rules

Explicit file IDs in the `.songbook.yaml` always take priority over
subfolder-detected files:

| YAML field | Subfolder exists | Result |
|---|---|---|
| `cover_file_id` set | — | YAML value used (subfolder ignored) |
| `cover_file_id` **not** set | Yes | First file in `Cover/` subfolder used |
| `cover_file_id` **not** set | No | No cover page |

The same logic applies to `preface_file_ids` / `Preface/` and
`postface_file_ids` / `Postface/`.

### Supported file types

Any file type that the generator can download and render as PDF is valid:
Google Docs (exported to PDF automatically), PDF files, or shortcuts to
either.

---

## Setup

### Folder structure

```
My Edition/                   ← edition folder
├── .songbook.yaml            ← edition config with use_folder_components: true
├── Cover/                    ← cover subfolder
│   └── Cover Page.gdoc       ← first file is used as the cover
├── Preface/                  ← preface subfolder
│   ├── 01 Welcome.gdoc       ← inserted in alphabetical order
│   └── 02 About Us.gdoc
├── Postface/                 ← postface subfolder
│   └── Credits.gdoc
└── (songs are selected via filters defined in .songbook.yaml)
```

### `.songbook.yaml` configuration

Add `use_folder_components: true` to enable the feature:

```yaml
id: "my-edition"
title: "My Special Songbook"
description: "A custom edition assembled in Drive."
use_folder_components: true     # ← enables subfolder detection

filters:
  - key: "specialbooks"
    operator: "contains"
    value: "my-edition"
```

To override a specific component with an explicit file ID while keeping
subfolder detection enabled for the others:

```yaml
id: "my-edition"
title: "My Special Songbook"
description: "A custom edition assembled in Drive."
use_folder_components: true

cover_file_id: "1aBcDeFgH..."   # explicit cover – subfolder ignored

# preface_file_ids not set → resolved from Preface/ subfolder if present
# postface_file_ids not set → resolved from Postface/ subfolder if present

filters:
  - key: "specialbooks"
    operator: "contains"
    value: "my-edition"
```

---

## Feature toggle

`use_folder_components` defaults to `false`.  When `false`:

- No subfolder scanning takes place.
- Existing YAML-based editions work exactly as before.

Set it to `true` only for editions that use the subfolder layout described
above.

---

## Notes

- Subfolder names are matched **case-insensitively** (`cover`, `Cover`,
  `COVER` are all valid).
- If a subfolder exists but contains no files, the component is skipped and
  a warning is logged.
- Songs are still selected via the `filters` field in `.songbook.yaml`;
  the `Cover`, `Preface`, and `Postface` subfolders contain structural pages
  only, not songs.
- Shortcuts inside the component subfolders are resolved to their target
  files automatically.

---

## Backward compatibility

All existing YAML editions (with or without explicit file IDs) continue to
work unchanged because `use_folder_components` defaults to `false`.
