# Photo Metadata Name Normalizer

A Python command-line script for applying name mappings to photo metadata and XMP sidecars. It reads an old-name → new-name CSV and updates matching names in supported metadata fields, including region names, keywords, subjects, and digiKam's Tags List.

## Requirements

- Python 3 (standard library only)
- [ExifTool](https://exiftool.org/) available on `PATH`
- A mapping file named `mappings.txt` beside the script, or a different CSV supplied with `--mappings`

## Setup

Clone the repository, then create your personal mapping file from the sample:

```sh
cp mappings.txt people3.txt
$EDITOR people3.txt
```

`people3.txt` is ignored by Git because it is intended to contain your own names and mappings. Pass it explicitly with `--mappings people3.txt`; when no mapping path is supplied, the script uses the tracked `mappings.txt` sample.

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

The `--folder` argument is required and is scanned recursively. First preview changes with `--dry-run`. To use your private mappings file, pass `--mappings people3.txt`; omitting that option uses `mappings.txt`:

```sh
./replace_region_names.py --folder "/path/to/photos" --mappings people3.txt --dry-run
```

Apply the mappings to original files in place (the script asks for confirmation when no operation option is supplied):

```sh
./replace_region_names.py --folder "/path/to/photos" --mappings people3.txt
```

Create renamed copies and leave originals in place:

```sh
./replace_region_names.py --folder "/path/to/photos" --mappings people3.txt --copy
```

List every supported metadata field and its values without changing files:

```sh
./replace_region_names.py --folder "/path/to/photos" --list
```

Use another mapping file:

```sh
./replace_region_names.py --folder "/path/to/photos" --mappings ./my-mappings.csv --dry-run
```

## Recommended test workflow

Try the mapping on a small folder first. The commands below limit the copy run to 10 matching photos; a matching XMP sidecar is included with its photo.

1. List the current metadata values so you can review what the files contain:

   ```sh
   ./replace_region_names.py --folder "/path/to/test-photos" --list --top 10
   ```

2. Create changed copies and print the old and new values. The originals remain unchanged:

   ```sh
   ./replace_region_names.py --folder "/path/to/test-photos" --mappings ./people3.txt --copy --top 10 --view true
   ```

3. Change to the test photo folder, then compare an original image with its `.regionname` copy:

   ```sh
   cd "/path/to/test-photos"
   exiftool "photo.jpg" -diff "photo.regionname.jpg" --system:all -e
   ```

   For a JPEG XMP sidecar, compare the sidecar files too:

   ```sh
   exiftool "photo.jpg.xmp" -diff "photo.regionname.jpg.xmp" --system:all -e
   ```

   ExifTool prints the metadata differences between the pair. Review that the intended name fields changed as expected.

4. When the copied files look right, run without `--copy` to update originals. This asks for confirmation before writing:

   ```sh
   ./replace_region_names.py --folder "/path/to/photos" --mappings ./people3.txt --view true
   ```

   Existing `.regionname` outputs are skipped by `--copy`, so use a fresh test folder or remove old test copies before repeating the copy step.

## Arguments

| Argument | Description |
| --- | --- |
| `--folder PATH` | Required root folder. The script scans it and its subfolders. |
| `--dry-run` / `--dryrun` | Print planned tag changes without modifying files. |
| `--copy` | Write changed files as `NAME.regionname.EXT`, preserving originals. Existing output files are skipped. |
| `--top N` | Limit processing to the first N matching photos. A matching image and its mapped XMP sidecar are handled together. With `--list`, limits the number of files listed. |
| `--list` | Print values for all supported metadata fields; no mappings are applied. |
| `--mappings PATH` | Mapping CSV path. Defaults to `mappings.txt` beside the script. `--csv` is an alias. |
| `--view true\|false` | Show per-tag old/new values after a successful change. Defaults to `false`; the changed file path is still printed. |
| `-h`, `--help` | Show command help. |

A progress display reports metadata scanning and folder processing. The script counts files first, then reads metadata in batches of 250 and handles one subfolder at a time to limit memory use. It only sends supported photo, video, raw-image, and `.xmp` sidecar files to ExifTool. The extension allowlist covers common JPEG, PNG, TIFF, HEIC, WebP, AVIF, camera RAW, and video formats; add an extension to `SUPPORTED_EXTENSIONS` in the script if your files use another format. One ExifTool process stays open for metadata reads and writes to reduce process startup overhead.

## Examples

Preview a limited run and show the details that would change:

```sh
./replace_region_names.py --folder . --mappings people3.txt --top 10 --dry-run
```

Apply changes in place and print each field's old and new values:

```sh
./replace_region_names.py --folder "/path/to/photos" --mappings people3.txt --view true
```
