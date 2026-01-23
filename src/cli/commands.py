"""
CLI commands for TuneCover.
"""

import argparse
import contextlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from ..api.musicbrainz import MusicBrainzProvider
from ..core.embedder import CoverEmbedder, detect_image_mime_type
from ..core.models import SearchResult
from ..core.scanner import MusicScanner
from ..i18n import tr
from ..utils.config import Config
from ..utils.constants import APP_NAME, APP_NAME_PASCAL, APP_NAME_SLUG
from .formatters import FetchProgress, export_csv, export_json, format_scan_summary

logger = logging.getLogger(__name__)


def _validate_path_from_json(path_str: str, report_file: Path) -> Path:
    """
    Validate a path from JSON input to prevent path traversal attacks.

    Args:
        path_str: Path string from JSON
        report_file: The report file that contained this path

    Returns:
        Validated Path object

    Raises:
        ValueError: If path is invalid or attempts traversal
    """
    if not path_str:
        raise ValueError("Empty path in JSON report")

    # Check raw string for path traversal BEFORE normalization
    if ".." in path_str:
        raise ValueError(f"Path traversal attempt detected: {path_str}")

    # Convert to Path
    path = Path(path_str)

    # Additional check after normalization
    if ".." in path.parts:
        raise ValueError(f"Path traversal attempt detected: {path_str}")

    # Ensure path exists and is a directory
    if not path.exists():
        raise ValueError(f"Path does not exist: {path_str}")

    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path_str}")

    return path


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME_SLUG,
        description=tr("cli.description"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=tr("cli.epilog"),
    )

    parser.add_argument("-v", "--verbose", action="store_true", help=tr("cli.verbose_help"))
    parser.add_argument("--log-file", type=Path, help=tr("cli.log_file_help"))

    subparsers = parser.add_subparsers(dest="command", help=tr("cli.commands_help"))

    # GUI subcommand
    gui_parser = subparsers.add_parser("gui", help=tr("cli.gui_help"))

    # Scan subcommand
    scan_parser = subparsers.add_parser(
        "scan",
        help=tr("cli.scan_help"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=tr("cli.scan_epilog"),
    )
    scan_parser.add_argument("music_dir", type=Path, help=tr("cli.music_dir_help"))
    scan_parser.add_argument("-o", "--output", type=Path, help=tr("cli.output_help"))
    scan_parser.add_argument(
        "-f", "--format", choices=["json", "csv"], default="json", help=tr("cli.format_help")
    )
    scan_parser.add_argument("-q", "--quiet", action="store_true", help=tr("cli.quiet_help"))
    scan_parser.add_argument(
        "-e", "--exclude", type=str, nargs="+", default=[], help=tr("cli.exclude_help")
    )

    # Fetch subcommand
    fetch_parser = subparsers.add_parser(
        "fetch",
        help=tr("cli.fetch_help"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=tr("cli.fetch_epilog"),
    )
    fetch_parser.add_argument("report", type=Path, help=tr("cli.report_help"))
    fetch_parser.add_argument("--auto", action="store_true", help=tr("cli.auto_help"))
    fetch_parser.add_argument(
        "--min-score",
        type=int,
        default=95,
        choices=range(101),
        metavar="0-100",
        help=tr("cli.min_score_help"),
    )
    fetch_parser.add_argument("--embed", action="store_true", help=tr("cli.embed_help"))
    fetch_parser.add_argument("--dry-run", action="store_true", help=tr("cli.dry_run_help"))
    fetch_parser.add_argument("--log", type=Path, help=tr("cli.log_help"))
    fetch_parser.add_argument("--start-from", type=int, default=0, help=tr("cli.start_from_help"))

    return parser


def run_cli(args: argparse.Namespace) -> int:
    """Run the CLI command based on parsed arguments."""
    if args.command == "scan":
        return cmd_scan(args)
    elif args.command == "fetch":
        return cmd_fetch(args)
    elif args.command == "gui" or args.command is None:
        return cmd_gui(args)
    else:
        print(tr("cli.unknown_command").format(command=args.command))
        return 1


def cmd_gui(args: argparse.Namespace) -> int:
    """Launch the GUI application."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        from ..i18n import setup_translations
        from ..ui.main_window import MainWindow
        from ..utils.config import Config

        # Enable High DPI scaling
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        from ..utils.user_agent import get_version

        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(get_version())
        app.setOrganizationName(APP_NAME_PASCAL)

        # Load config and setup translations
        config = Config()
        setup_translations(app, config.language)

        # Apply custom fpcalc path from config (if set)
        if config.fpcalc_path:
            from ..core.fingerprint import set_fpcalc_path

            set_fpcalc_path(config.fpcalc_path)

        window = MainWindow(config)
        window.show()

        return app.exec()

    except ImportError as e:
        print(tr("cli.pyside6_not_installed"))
        print(tr("cli.pyside6_install_hint"))
        print(tr("cli.detail").format(detail=e))
        return 1


def cmd_scan(args: argparse.Namespace) -> int:
    """Execute the scan command."""
    music_dir = args.music_dir

    if not music_dir.exists():
        print(tr("cli.error_folder_not_exist").format(folder=music_dir))
        return 1

    if not music_dir.is_dir():
        print(tr("cli.error_not_a_folder").format(path=music_dir))
        return 1

    print(tr("cli.scanning_library").format(path=music_dir))
    if args.exclude:
        print(tr("cli.excluded_folders").format(folders=", ".join(args.exclude)))

    # Progress callback
    lbl_progress = tr("cli.progress")

    def progress_callback(current: int, total: int, message: str):
        if not args.quiet and total > 0 and (current % 50 == 0 or current == total):
            print(f"  {lbl_progress}: {current}/{total} ({current * 100 // total}%)")

    # Scan
    scanner = MusicScanner(exclude_patterns=args.exclude, progress_callback=progress_callback)
    albums = scanner.scan_library(music_dir)

    # Output
    format_scan_summary(albums)

    if args.output:
        try:
            if args.format == "json":
                export_json(albums, args.output)
            else:
                export_csv(albums, args.output)
            print(f"\n{tr('cli.report_generated')}: {args.output}")
        except OSError as e:
            print(tr("cli.error_write_report").format(path=args.output, error=e))
            return 1

    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """Execute the fetch command."""
    if not args.report.exists():
        print(tr("cli.error_file_not_exist").format(file=args.report))
        return 1

    # Load report
    print(tr("cli.loading_report").format(file=args.report))
    try:
        with Path(args.report).open(encoding="utf-8") as f:
            report = json.load(f)
    except json.JSONDecodeError as e:
        print(tr("cli.error_invalid_json").format(file=args.report, error=e))
        return 1
    except OSError as e:
        print(tr("cli.error_read_file").format(file=args.report, error=e))
        return 1

    albums_data = report.get("albums_missing_cover", [])
    if not albums_data:
        print(tr("cli.no_albums_without_cover"))
        return 0

    print(f"\n{len(albums_data)} {tr('cli.albums_to_process')}")

    if args.auto:
        print(tr("cli.auto_mode_enabled").format(min_score=args.min_score))
    else:
        print(tr("cli.interactive_mode"))

    if args.dry_run:
        print(tr("cli.dry_run_warning"))

    if args.embed:
        print(tr("cli.embed_enabled"))

    # Validate start_from parameter
    start_from = args.start_from
    if start_from < 0:
        print(tr("cli.error_start_from_negative").format(value=start_from))
        return 1
    if start_from >= len(albums_data):
        print(tr("cli.error_start_from_exceeds").format(value=start_from, total=len(albums_data)))
        return 1

    try:
        input(f"\n{tr('cli.press_enter_to_continue')}")
    except EOFError:
        # Non-interactive mode, continue directly
        print(f"\n({tr('cli.non_interactive_mode')})")

    # Initialize
    config = Config()
    contact_email = config.get("app.contact_email", "")
    provider = MusicBrainzProvider(contact_email=contact_email)
    embedder = CoverEmbedder()
    progress = FetchProgress(len(albums_data), quiet=False)
    results = []

    try:
        # Process albums
        albums_to_process = albums_data[start_from:]

        for album_data in albums_to_process:
            result = process_album(
                album_data,
                provider,
                embedder,
                auto_mode=args.auto,
                min_score=args.min_score,
                embed=args.embed,
                dry_run=args.dry_run,
                report_file=args.report,
            )
            results.append(result)
            progress.update(result["status"], result["message"], album_data.get("album", ""))

            if result["status"] == "quit":
                print(f"\n{tr('cli.interrupted_by_user')}")
                break

        # Summary
        progress.print_summary()

        # Save log
        log_path = args.log
        if log_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = Path(f"cover_fetch_log_{timestamp}.json")

        if save_fetch_log(results, log_path):
            print(f"\n{tr('cli.log_saved')}: {log_path}")

    finally:
        # Clean up provider resources (HTTP session)
        provider.close()

    return 0


def process_album(
    album_data: dict,
    provider: MusicBrainzProvider,
    embedder: CoverEmbedder,
    auto_mode: bool = False,
    min_score: int = 95,
    embed: bool = False,
    dry_run: bool = False,
    report_file: Path | None = None,
) -> dict:
    """
    Process a single album for cover fetching.

    In auto mode, only albums with a valid MusicBrainz ID (MBID) are processed.
    This ensures 100% confidence in the match.
    """
    artist = album_data.get("artist", "")
    album = album_data.get("album", "")
    year = album_data.get("year")
    path_str = album_data.get("path", "")
    mbid = album_data.get("musicbrainz_albumid")

    result = {
        "path": path_str,
        "status": "skipped",
        "message": "",
        "mbid": None,
        "cover_saved_to": None,
    }

    # Validate path from JSON to prevent path traversal
    try:
        folder = _validate_path_from_json(path_str, report_file)
    except ValueError as e:
        result["status"] = "error"
        result["message"] = tr("cli.invalid_path").format(error=e)
        logger.warning(f"Invalid path in JSON: {e}")
        return result

    selected = None

    if auto_mode:
        # Auto mode: Try MBID first (100% match), fallback to text search with min_score
        if mbid:
            # Direct MBID lookup (guaranteed match)
            logger.info(f"Auto mode: MBID lookup for {mbid}")
            direct_result = provider.lookup_by_mbid(mbid)

            if direct_result:
                # Get cover URL for MBID result
                cover_url = provider.get_cover_url(direct_result)
                if cover_url:
                    direct_result.cover_url = cover_url
                    direct_result.has_cover_art = True
                    selected = direct_result
                    logger.info(
                        f"Auto mode: MBID match confirmed (100%): {selected.artist} - {selected.album}"
                    )
                else:
                    result["status"] = "no_cover"
                    result["message"] = tr("cli.auto_mbid_no_cover")
                    result["mbid"] = mbid
                    return result
            else:
                logger.warning(f"Auto mode: MBID lookup failed for {mbid}, trying text search")

        # If no MBID or MBID lookup failed, try text search
        if not selected:
            if not artist and not album:
                result["message"] = tr("cli.auto_no_metadata")
                return result

            # Search by text
            search_results = provider.search(artist, album, year)

            if not search_results:
                result["status"] = "no_match"
                result["message"] = tr("cli.auto_no_results")
                return result

            # Find best match with sufficient score
            for sr in search_results:
                score = provider.calculate_match_score(artist, album, year, sr)
                if score >= min_score:
                    url = provider.get_cover_url(sr)
                    if url:
                        sr.cover_url = url
                        sr.has_cover_art = True
                        sr.score = score
                        selected = sr
                        logger.info(
                            f"Auto mode: Text match found (score={score}%): {sr.artist} - {sr.album}"
                        )
                        break

            if not selected:
                result["status"] = "skipped"
                result["message"] = tr("cli.auto_no_match").format(min_score=min_score)
                return result

    else:
        # Interactive mode: search by text
        if not artist and not album:
            result["message"] = tr("cli.no_metadata")
            return result

        # Search
        search_results = provider.search(artist, album, year)

        if not search_results:
            result["status"] = "no_match"
            result["message"] = tr("cli.no_musicbrainz_results")
            return result

        # Check covers
        for sr in search_results:
            url = provider.get_cover_url(sr)
            if url:
                sr.has_cover_art = True
                sr.cover_url = url

        # Interactive selection
        choice = interactive_select(album_data, search_results)
        if choice == "quit":
            result["status"] = "quit"
            result["message"] = tr("cli.quit_requested")
            return result
        if choice is None:
            result["message"] = tr("cli.skipped_by_user")
            return result
        selected = choice

        if not selected.cover_url:
            url = provider.get_cover_url(selected)
            if url:
                selected.has_cover_art = True
                selected.cover_url = url

    if not selected or not selected.cover_url:
        result["status"] = "no_cover"
        result["message"] = tr("cli.no_cover_available")
        result["mbid"] = selected.mbid if selected else None
        return result

    if dry_run:
        result["status"] = "success"
        result["message"] = tr("cli.dry_run_cover_found").format(
            artist=selected.artist, album=selected.album
        )
        result["mbid"] = selected.mbid
        return result

    # Download
    cover_data = provider.download_cover(selected.cover_url)
    if not cover_data:
        result["status"] = "error"
        result["message"] = tr("cli.download_failed")
        result["mbid"] = selected.mbid
        return result

    # Save (folder already validated at start of function)
    mime_type = detect_image_mime_type(cover_data)
    cover_path = embedder.save_cover_to_folder(cover_data, folder)

    if embed:
        embedder.embed_cover_in_folder(cover_data, folder, mime_type)

    result["status"] = "success"
    result["message"] = tr("cli.cover_fetched").format(artist=selected.artist, album=selected.album)
    result["mbid"] = selected.mbid
    result["cover_saved_to"] = str(cover_path)

    return result


def interactive_select(album_data: dict, results: list[SearchResult]) -> SearchResult | str | None:
    """Interactive selection of search result.

    Returns:
        SearchResult if user selects one, 'quit' if user wants to stop,
        None if user skips this album.
    """
    print(f"\n{'=' * 60}")
    print(f"{tr('cli.local_album')}:")
    print(f"  {tr('cli.artist')}: {album_data.get('artist', tr('cli.unknown'))}")
    print(f"  {tr('cli.album')}: {album_data.get('album', tr('cli.unknown'))}")
    print(f"  {tr('cli.year')}: {album_data.get('year', tr('cli.unknown'))}")
    print(f"  {tr('cli.path')}: {album_data.get('path', '')}")

    if not results:
        print(f"\n  {tr('cli.no_results_musicbrainz')}")
        with contextlib.suppress(EOFError):
            input(f"  {tr('cli.press_enter_to_continue')}")
        return None

    print(f"\n{tr('cli.musicbrainz_results')}:")
    for i, r in enumerate(results, 1):
        cover_status = f"[{tr('cli.has_cover')}]" if r.has_cover_art else f"[{tr('cli.no_cover')}]"
        print(f"  [{i}] {r.artist} - {r.album} ({r.year or '?'})")
        print(f"      Score: {r.score}% | {cover_status}")

    print(f"\n  [0] {tr('cli.skip_album')}")
    print(f"  [q] {tr('cli.quit_processing')}")

    while True:
        try:
            choice = input(f"\n{tr('cli.your_choice')}: ").strip().lower()
        except EOFError:
            # Non-interactive mode, skip this album
            print(f"\n  ({tr('cli.non_interactive_skipped')})")
            return None

        if choice == "q":
            return "quit"

        if choice == "0" or choice == "":
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(results):
                return results[idx]
            print(tr("cli.invalid_choice"))
        except ValueError:
            print(tr("cli.invalid_input"))


def save_fetch_log(results: list[dict], output_path: Path) -> bool:
    """Save fetch processing log.

    Returns:
        True if log was saved successfully, False otherwise
    """
    log_data = {
        "processed_at": datetime.now().isoformat(),
        "summary": {
            "total": len(results),
            "success": len([r for r in results if r["status"] == "success"]),
            "skipped": len([r for r in results if r["status"] == "skipped"]),
            "no_match": len([r for r in results if r["status"] == "no_match"]),
            "no_cover": len([r for r in results if r["status"] == "no_cover"]),
            "errors": len([r for r in results if r["status"] == "error"]),
        },
        "results": results,
    }

    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        logger.error(f"Could not save fetch log to {output_path}: {e}")
        print(tr("cli.error_save_log").format(path=output_path, error=e))
        return False
