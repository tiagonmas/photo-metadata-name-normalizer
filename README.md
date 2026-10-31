# Photo Metadata Name Normalizer

A Python command-line script for applying name mappings to photo metadata and XMP sidecars. It reads an old-name → new-name CSV and updates matching names in supported metadata fields, including region names, keywords, subjects, and digiKam's Tags List.

## Requirements

- Python 3 (standard library only)
- [ExifTool](https://exiftool.org/) available on `PATH`
- A mapping file named `people3.txt` beside the script, or a different CSV supplied with `--csv`

## Setup

Clone the repository, then create your personal mapping file from the sample:

```sh
cp mappings.txt people3.txt
$EDITOR people3.txt
```

`people3.txt` is ignored by Git because it is intended to contain your own names and mappings. The sample is tracked and safe to edit or share.

## Mapping file format

The file is CSV. The first column is the exact old tag/name text to find; the second column is the replacement text. Extra columns are ignored. A header row such as `old_name,new_name` is optional. Use CSV quoting if a value contains a comma.

```csv
old_name,new_name
John.Smith,John Smith
Jane.Doe,Jane Doe
Michael.Brown,Michael Brown
```

For each file, the script checks these metadata fields and applies every mapping whose old value occurs in a field:

- `XMP-mwg-rs:RegionName`
- `IPTC:Keywords`
- `XMP-dc:Subject`
- `XMP-lr:HierarchicalSubject`
- `XMP-lr:WeightedFlatSubject`
- `XMP-digiKam:TagsList` (in XMP sidecars too)

Matching is literal and case-sensitive. Keep mappings specific enough to avoid changing unintended text. When an image has a matching XMP sidecar, the sidecar is scanned too. In `--copy` mode, changed sidecars get a `.regionname` name that pairs with the copied image.

## Usage

The `--folder` argument is required and is scanned recursively. First preview changes with `--dry-run`:

```sh
./replace_region_names.py --folder "/path/to/photos" --dry-run
```

Apply the mappings to original files in place (the script asks for confirmation when no operation option is supplied):

```sh
./replace_region_names.py --folder "/path/to/photos"
```

Create renamed copies and leave originals in place:

```sh
./replace_region_names.py --folder "/path/to/photos" --copy
```

List every supported metadata field and its values without changing files:

```sh
./replace_region_names.py --folder "/path/to/photos" --list
```

Use another mapping file:

```sh
./replace_region_names.py --folder "/path/to/photos" --csv ./my-mappings.csv --dry-run
```

## Arguments

| Argument | Description |
| --- | --- |
| `--folder PATH` | Required root folder. The script scans it and its subfolders. |
| `--dry-run` / `--dryrun` | Print planned tag changes without modifying files. |
| `--copy` | Write changed files as `NAME.regionname.EXT`, preserving originals. Existing output files are skipped. |
| `--top N` | Limit processing to the first N matching photos. A matching image and its mapped XMP sidecar are handled together. With `--list`, limits the number of files listed. |
| `--list` | Print values for all supported metadata fields; no mappings are applied. |
| `--csv PATH` | Mapping CSV path. Defaults to `people3.txt` beside the script. |
| `--view true\|false` | Show per-tag old/new values after a successful change. Defaults to `false`; the changed file path is still printed. |
| `-h`, `--help` | Show command help. |

A progress display reports metadata scanning and folder processing. The script counts files first, then reads metadata in batches of 250 and handles one subfolder at a time to limit memory use. It only sends supported photo, video, raw-image, and `.xmp` sidecar files to ExifTool. The extension allowlist covers common JPEG, PNG, TIFF, HEIC, WebP, AVIF, camera RAW, and video formats; add an extension to `SUPPORTED_EXTENSIONS` in the script if your files use another format. One ExifTool process stays open for metadata reads and writes to reduce process startup overhead.

## Examples

Preview a limited run and show the details that would change:

```sh
./replace_region_names.py --folder . --top 10 --dry-run
```

Apply changes in place and print each field's old and new values:

```sh
./replace_region_names.py --folder "/path/to/photos" --view true
```
