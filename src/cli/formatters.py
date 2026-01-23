"""
Output formatters for CLI commands.
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO

from ..core.models import AlbumInfo, CoverStatus
from ..i18n import tr
from ..utils.constants import APP_NAME_SLUG, VERSION


def _validate_output_path(output_path: Path) -> None:
    """
    Validate output path to prevent path traversal attacks.

    Args:
        output_path: Path to validate

    Raises:
        ValueError: If path is invalid or attempts traversal
    """
    # Check for path traversal attempts
    if ".." in output_path.parts:
        raise ValueError(f"Path traversal attempt detected: {output_path}")

    # Ensure parent directory exists and is writable
    parent = output_path.parent
    if parent and str(parent) != ".":
        if not parent.exists():
            raise ValueError(f"Parent directory does not exist: {parent}")
        if not parent.is_dir():
            raise ValueError(f"Parent path is not a directory: {parent}")


def format_scan_summary(albums: list[AlbumInfo], file: TextIO | None = None) -> None:
    """Print scan summary to terminal."""
    if file is None:
        file = sys.stdout

    total = len(albums)
    with_both = len([a for a in albums if a.cover_status == CoverStatus.BOTH])
    embedded_only = len([a for a in albums if a.cover_status == CoverStatus.EMBEDDED_ONLY])
    folder_only = len([a for a in albums if a.cover_status == CoverStatus.FOLDER_ONLY])
    missing = len([a for a in albums if a.cover_status == CoverStatus.NONE])

    # Translate labels (extracted outside f-strings for pybabel)
    lbl_scanned = tr("cli.albums_scanned")
    lbl_full_cover = tr("cli.albums_with_full_cover")
    lbl_embedded = tr("cli.albums_embedded_only")
    lbl_folder = tr("cli.albums_folder_only")
    lbl_without = tr("cli.albums_without_cover")

    print("\n" + "=" * 60, file=file)
    print(tr("cli.scan_summary_title"), file=file)
    print("=" * 60, file=file)
    print(f"{lbl_scanned}:              {total}", file=file)
    print(f"{lbl_full_cover}:  {with_both}", file=file)
    print(f"{lbl_embedded}:   {embedded_only}", file=file)
    print(f"{lbl_folder}:    {folder_only}", file=file)
    print(f"{lbl_without}:           {missing}", file=file)
    print("=" * 60, file=file)

    if missing > 0:
        missing_albums = [a for a in albums if a.cover_status == CoverStatus.NONE]
        lbl_examples = tr("cli.examples_missing_cover")
        print(f"\n{lbl_examples}:", file=file)
        for album in missing_albums[:5]:
            artist = album.artist or tr("cli.unknown_artist")
            title = album.album or tr("cli.unknown_album")
            print(f"  • {artist} - {title}", file=file)
        if missing > 5:
            and_others = tr("cli.and_n_others")
            print(f"  ... {and_others.format(count=missing - 5)}", file=file)


def export_json(albums: list[AlbumInfo], output_path: Path) -> dict:
    """Export scan results to JSON file."""
    # Validate output path
    _validate_output_path(output_path)

    albums_missing = [a for a in albums if a.cover_status == CoverStatus.NONE]
    albums_partial = [
        a for a in albums if a.cover_status in (CoverStatus.EMBEDDED_ONLY, CoverStatus.FOLDER_ONLY)
    ]

    report_data = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "tool": APP_NAME_SLUG,
            "version": VERSION,
        },
        "summary": {
            "total_albums_scanned": len(albums),
            "albums_with_full_cover": len(
                [a for a in albums if a.cover_status == CoverStatus.BOTH]
            ),
            "albums_with_embedded_only": len(
                [a for a in albums if a.cover_status == CoverStatus.EMBEDDED_ONLY]
            ),
            "albums_with_folder_only": len(
                [a for a in albums if a.cover_status == CoverStatus.FOLDER_ONLY]
            ),
            "albums_without_cover": len(albums_missing),
        },
        "albums_missing_cover": [a.to_dict() for a in albums_missing],
        "albums_partial_cover": [a.to_dict() for a in albums_partial],
    }

    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise OSError(tr("cli.error_write_json").format(error=e)) from e

    return report_data


def export_csv(albums: list[AlbumInfo], output_path: Path) -> None:
    """Export scan results to CSV file."""
    # Validate output path
    _validate_output_path(output_path)

    albums_to_export = [a for a in albums if a.cover_status != CoverStatus.BOTH]

    try:
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "path",
                    "artist",
                    "album",
                    "year",
                    "track_count",
                    "has_embedded_cover",
                    "has_folder_cover",
                    "cover_status",
                    "formats",
                ]
            )
            for album in albums_to_export:
                writer.writerow(
                    [
                        str(album.path),
                        album.artist,
                        album.album,
                        album.year,
                        album.track_count,
                        album.cover.has_embedded,
                        album.cover.has_folder,
                        album.cover_status.value,
                        ",".join(album.formats),
                    ]
                )
    except OSError as e:
        raise OSError(tr("cli.error_write_csv").format(error=e)) from e


class FetchProgress:
    """Progress reporter for fetch operations."""

    def __init__(self, total: int, quiet: bool = False):
        self.total = total
        self.current = 0
        self.quiet = quiet
        self.results = {"success": 0, "skipped": 0, "no_match": 0, "no_cover": 0, "error": 0}

    def update(self, status: str, message: str, album_name: str = ""):
        """Update progress."""
        self.current += 1
        if status in self.results:
            self.results[status] += 1

        if not self.quiet:
            icons = {"success": "✓", "skipped": "○", "no_match": "?", "no_cover": "✗", "error": "!"}
            icon = icons.get(status, "?")
            print(f"[{self.current}/{self.total}] {icon} {message}")

    def print_summary(self):
        """Print final summary."""
        # Translate labels (extracted outside f-strings for pybabel)
        lbl_fetched = tr("cli.covers_fetched")
        lbl_skipped = tr("cli.albums_skipped")
        lbl_no_match = tr("cli.no_match_count")
        lbl_no_cover = tr("cli.no_cover_count")
        lbl_errors = tr("cli.errors_count")

        print("\n" + "=" * 60)
        print(tr("cli.processing_summary_title"))
        print("=" * 60)
        print(f"{lbl_fetched}:    {self.results['success']}")
        print(f"{lbl_skipped}:       {self.results['skipped']}")
        print(f"{lbl_no_match}:  {self.results['no_match']}")
        print(f"{lbl_no_cover}:     {self.results['no_cover']}")
        print(f"{lbl_errors}:              {self.results['error']}")
