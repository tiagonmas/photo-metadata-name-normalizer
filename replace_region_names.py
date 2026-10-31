#!/usr/bin/env python3
"""Replace mapped person names in photo metadata using mappings.txt."""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BATCH_SIZE = 250
SUPPORTED_EXTENSIONS = {
    '.jpg', '.jpeg', '.jpe', '.png', '.tif', '.tiff', '.gif', '.bmp',
    '.webp', '.heic', '.heif', '.avif', '.jxl', '.dng', '.raw', '.cr2',
    '.cr3', '.nef', '.nrw', '.arw', '.srf', '.sr2', '.orf', '.rw2',
    '.raf', '.pef', '.srw', '.3fr', '.iiq', '.erf', '.mef', '.mos',
    '.mrw', '.rwl', '.x3f', '.fff', '.cap', '.ptx', '.pxn', '.jp2',
    '.j2k', '.psd', '.psb', '.mov', '.mp4', '.m4v', '.3gp', '.avi',
    '.mkv', '.xmp',
}
METADATA_FIELDS = [
    # JSON key, destination tag, source tag for ExifTool's per-list-item expression
    ('XMP-mwg-rs:RegionName', 'XMP-mwg-rs:RegionName', 'XMP-mwg-rs:RegionName'),
    ('IPTC:Keywords', 'IPTC:Keywords', 'IPTC:Keywords'),
    ('XMP-dc:Subject', 'XMP-dc:Subject', 'XMP-dc:Subject'),
    ('XMP-lr:HierarchicalSubject', 'XMP-lr:HierarchicalSubject', 'XMP-lr:HierarchicalSubject'),
    ('XMP-lr:WeightedFlatSubject', 'XMP-lr:WeightedFlatSubject', 'XMP-lr:WeightedFlatSubject'),
    ('XMP-digiKam:TagsList', 'XMP-digiKam:TagsList', 'XMP-digiKam:TagsList'),
]


class ExifToolSession:
    """Keep one ExifTool process alive for multiple commands."""

    def __init__(self, executable):
        self.executable = executable
        self.stderr_file = tempfile.TemporaryFile(mode='w+b')
        self.process = subprocess.Popen(
            [executable, '-stay_open', 'True', '-@', '-'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_file,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
        )
        self.sequence = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def run(self, arguments):
        arguments = [str(argument) for argument in arguments]
        # Newlines cannot be represented safely in ExifTool's line-based argfile.
        if any('\n' in argument or '\r' in argument for argument in arguments):
            return subprocess.run([self.executable, *arguments], capture_output=True, text=True)

        self.sequence += 1
        marker = f'{{ready{self.sequence}}}'
        self.stderr_file.seek(0, 2)
        stderr_start = self.stderr_file.tell()
        try:
            self.process.stdin.write('\n'.join(arguments) + f'\n-execute{self.sequence}\n')
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise RuntimeError(f'Could not send a command to ExifTool: {error}') from error

        output = []
        while True:
            line = self.process.stdout.readline()
            if line == '':
                raise RuntimeError('ExifTool exited before completing a command.')
            if line.strip() == marker:
                break
            output.append(line)

        self.stderr_file.flush()
        self.stderr_file.seek(stderr_start)
        errors = self.stderr_file.read().decode('utf-8', errors='replace')
        self.stderr_file.seek(0)
        self.stderr_file.truncate(0)
        return subprocess.CompletedProcess(arguments, 0, ''.join(output), errors)

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('-stay_open\nFalse\n')
                self.process.stdin.flush()
                self.process.stdin.close()
                self.process.wait(timeout=10)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        self.stderr_file.close()


def load_mappings(csv_path):
    mappings = []
    with csv_path.open('r', encoding='utf-8-sig', newline='') as stream:
        for row_number, row in enumerate(csv.reader(stream), start=1):
            if not row or len(row) < 2:
                continue
            old, new = row[0].strip(), row[1].strip()
            if not old or not new:
                continue
            if old.casefold() in {'old', 'oldname', 'tag'} and new.casefold() in {'new', 'newname', 'regionname'}:
                continue
            mappings.append((old, new))
    if not mappings:
        raise ValueError(f'No usable old-name/new-name rows found in {csv_path}')
    return mappings


def tag_values(metadata, key):
    value = metadata.get(key, [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def exiftool_substitution(destination_tag, source_tag, changes):
    # The @ suffix applies each substitution to list items individually.
    expressions = []
    for old, new in changes:
        pattern = re.escape(old).replace('/', r'\/')
        replacement = new.replace('\\', '\\\\').replace('$', r'\$').replace('@', r'\@').replace('/', r'\/')
        expressions.append(f's/{pattern}/{replacement}/g')
    return '-' + destination_tag + '<${' + source_tag + '@;' + ';'.join(expressions) + '}'


def show_progress(label, current, total):
    width = 30
    if total == 0:
        percent, filled = 100, width
    else:
        current = min(current, total)
        percent = current * 100 // total
        filled = width * current // total
    bar = '#' * filled + '-' * (width - filled)
    message = f'{label} [{bar}] {percent:3d}% ({current}/{total})'
    if sys.stderr.isatty():
        sys.stderr.write('\r' + message)
        if current >= total:
            sys.stderr.write('\n')
        sys.stderr.flush()
    else:
        print(message, file=sys.stderr)


def copy_target(source):
    # Keep an XMP sidecar paired with the renamed copy it describes.
    if source.suffix.casefold() == '.xmp' and source.with_suffix('').suffix:
        image_path = source.with_suffix('')
        return image_path.with_name(f'{image_path.stem}.regionname{image_path.suffix}.xmp')
    return source.with_name(f'{source.stem}.regionname{source.suffix}')


def main():
    script_folder = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description='Replace mapped names in photo regions, keywords, subjects, and digiKam tag metadata using mappings.txt.'
    )
    parser.add_argument('--folder', type=Path, required=True, metavar='PATH',
                        help='root folder to scan recursively')
    parser.add_argument('--dry-run', '--dryrun', action='store_true', dest='dry_run',
                        help='report planned changes without writing files')
    parser.add_argument('--top', type=int, metavar='N',
                        help='stop after N matching photos (include mapped XMP sidecars; --list counts files with listed metadata)')
    parser.add_argument('--copy', action='store_true',
                        help='write changed files as NAME.regionname.EXT and keep originals')
    parser.add_argument('--view', choices=('true', 'false'), default='false',
                        help='show per-tag change details after each file (default: false)')
    parser.add_argument('--list', action='store_true', dest='list_names',
                        help='list values for every supported metadata field without changing files')
    parser.add_argument('--mappings', '--csv', dest='mappings', type=Path,
                        default=script_folder / 'mappings.txt',
                        help='mapping CSV (default: mappings.txt beside this script)')
    args = parser.parse_args()
    folder = args.folder.expanduser().resolve()
    if not folder.is_dir():
        parser.error(f'--folder must be an existing directory: {folder}')

    if args.top is not None and args.top < 1:
        parser.error('--top must be at least 1')
    if args.list_names:
        mappings = []
    else:
        try:
            mappings = load_mappings(args.mappings)
        except (OSError, ValueError, csv.Error) as error:
            print(f'Error reading mappings: {error}', file=sys.stderr)
            return 2
    if shutil.which('exiftool') is None:
        print('Error: exiftool was not found in PATH.', file=sys.stderr)
        return 2

    mapping_file = args.mappings.resolve()
    script_file = Path(__file__).resolve()

    def files_in(directory, filenames):
        candidates = []
        for filename in filenames:
            path = Path(directory) / filename
            if (path.suffix.casefold() in SUPPORTED_EXTENSIONS and path.is_file()
                    and path.resolve() not in {mapping_file, script_file}
                    and '.regionname.' not in path.name.casefold()):
                candidates.append(path)
        return sorted(candidates)

    # Count first for progress and confirmation, but retain no full-tree path list.
    total_files = 0
    total_folders = 0
    for directory, subdirectories, filenames in os.walk(folder):
        subdirectories.sort()
        candidates = files_in(directory, filenames)
        if candidates:
            total_files += len(candidates)
            total_folders += 1

    default_write_mode = not args.dry_run and args.top is None and not args.copy and not args.list_names
    if default_write_mode:
        print('No operation options were provided. Planned action:')
        print(f'  Read mappings from {args.mappings}.')
        print(f'  Search {total_files} files under {folder} for matching names in the supported metadata fields.')
        print('  Update every matching original file in place; no copies or backups will be made.')
        try:
            answer = input('Continue? [y/N] ').strip().casefold()
        except EOFError:
            answer = ''
        if answer not in {'y', 'yes'}:
            print('Cancelled; no files were changed.')
            return 0
    elif not args.list_names:
        if args.top is None:
            print(f'Scanning {total_files} candidate files with {len(mappings)} mappings, one folder at a time.')
        else:
            print(f'Searching until {args.top} matching photos are found; mapped XMP sidecars are included.')

    def select_top(folder_planned, limit):
        if limit is None:
            return folder_planned, 0
        by_path = {source: changes for source, changes in folder_planned}
        selected = []
        selected_paths = set()
        photos = 0
        for source, changes in folder_planned:
            if source in selected_paths:
                continue
            if source.suffix.casefold() == '.xmp':
                image = source.with_suffix('')
                if image in by_path:
                    continue
            selected.append((source, changes))
            selected_paths.add(source)
            sidecar = source.with_name(source.name + '.xmp')
            if sidecar in by_path:
                selected.append((sidecar, by_path[sidecar]))
                selected_paths.add(sidecar)
            photos += 1
            if photos >= limit:
                break
        return selected, photos

    def apply_files(planned):
        changed = 0
        for source, changes_by_tag in planned:
            target = copy_target(source) if args.copy else source
            if args.dry_run:
                for json_key, (_, _, changes) in changes_by_tag.items():
                    for old, new in changes:
                        print(f'{source} -> {target}: {json_key} {old!r} -> {new!r}')
                continue
            if args.copy:
                if target.exists():
                    print(f'Skipping {source}: output already exists: {target}', file=sys.stderr)
                    continue
                try:
                    shutil.copy2(source, target)
                except OSError as error:
                    print(f'Could not copy {source}: {error}', file=sys.stderr)
                    continue
            command = ['-charset', 'filename=UTF8', '-overwrite_original', '-P']
            for _, (destination_tag, source_tag, changes) in changes_by_tag.items():
                command.append(exiftool_substitution(destination_tag, source_tag, changes))
            command.extend(['--', str(target)])
            result = exiftool.run(command)
            updated = re.search(r'(?m)^\s*[1-9][0-9]*\s+image files updated\s*$', result.stdout)
            has_error = re.search(r'(?im)^\s*Error:', result.stderr + result.stdout)
            if result.returncode != 0 or has_error or not updated:
                detail = result.stderr.strip() or result.stdout.strip() or 'ExifTool did not report an updated file.'
                print(f'ExifTool failed for {target}: {detail}', file=sys.stderr)
                if args.copy:
                    target.unlink(missing_ok=True)
                continue
            changed += 1
            print(f'Changed {target}')
            if args.view == 'true':
                for json_key, (_, _, changes) in changes_by_tag.items():
                    for old, new in changes:
                        print(f'  {json_key}: {old!r} -> {new!r}')
        return changed

    with ExifToolSession(shutil.which('exiftool')) as exiftool:
        scanned = 0
        listed_count = 0
        matching_files = 0
        changed_files = 0
        folders_done = 0
        photos_left = args.top
        if total_files == 0:
            show_progress('Scanning metadata', 0, 0)
        for directory, subdirectories, filenames in os.walk(folder):
            subdirectories.sort()
            candidates = files_in(directory, filenames)
            if not candidates:
                continue
            folder_planned = []
            stop_listing = False
            for start in range(0, len(candidates), BATCH_SIZE):
                batch = candidates[start:start + BATCH_SIZE]
                query = exiftool.run(
                    ['-charset', 'filename=UTF8', '-json', '-G1', '-a',
                     *[f'-{key}' for key, _, _ in METADATA_FIELDS], '--', *map(str, batch)]
                )
                if query.stderr.strip():
                    print(f'Warning from ExifTool: {query.stderr.strip()}', file=sys.stderr)
                try:
                    records = json.loads(query.stdout or '[]')
                except json.JSONDecodeError as error:
                    print(f'Error parsing ExifTool output: {error}\n{query.stderr}', file=sys.stderr)
                    return 2
                records.sort(key=lambda record: record.get('SourceFile', ''))
                for record in records:
                    source = Path(record.get('SourceFile', ''))
                    if args.list_names:
                        listed_fields = [(json_key, tag_values(record, json_key))
                                         for json_key, _, _ in METADATA_FIELDS]
                        listed_fields = [(key, values) for key, values in listed_fields if values]
                        if listed_fields:
                            print(source)
                            for key, values in listed_fields:
                                print(f'  {key}: {", ".join(values)}')
                            listed_count += 1
                            if args.top is not None and listed_count >= args.top:
                                stop_listing = True
                                break
                        continue
                    changes_by_tag = {}
                    for json_key, destination_tag, source_tag in METADATA_FIELDS:
                        field_values = tag_values(record, json_key)
                        changes = [(old, new) for old, new in mappings
                                   if any(old in value for value in field_values)]
                        if changes:
                            changes_by_tag[json_key] = (destination_tag, source_tag, changes)
                    if changes_by_tag:
                        folder_planned.append((source, changes_by_tag))
                scanned += len(batch)
                show_progress('Scanning metadata', scanned, total_files)
                if stop_listing:
                    break

            if args.list_names:
                if stop_listing:
                    break
                continue

            selected, photos_found = select_top(folder_planned, photos_left)
            if photos_left is not None:
                photos_left -= photos_found
            matching_files += len(selected)
            changed_files += apply_files(selected)
            folders_done += 1
            show_progress('Processing folders', folders_done, total_folders)
            if photos_left is not None and photos_left <= 0:
                break

        if args.list_names:
            return 0
        if args.dry_run:
            print(f'Dry run complete: {matching_files} files would be changed.')
        else:
            print(f'Complete: changed {changed_files} of {matching_files} matching files.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
