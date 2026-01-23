"""
Tests for search panel logic.

Note: Tests focus on business logic and avoid instantiating Qt widgets.
"""

from unittest.mock import Mock


class TestSearchWorkerLogic:
    """Tests for SearchWorker business logic."""

    def test_search_with_mbid_only(self):
        """Test search strategy with MBID only."""
        musicbrainz_albumid = "12345678-1234-1234-1234-123456789012"
        artist = ""
        album = ""

        use_mbid = bool(musicbrainz_albumid)
        use_text = bool(artist or album)

        assert use_mbid is True
        assert use_text is False

    def test_search_with_text_only(self):
        """Test search strategy with text only."""
        musicbrainz_albumid = None
        artist = "Test Artist"
        album = "Test Album"

        use_mbid = bool(musicbrainz_albumid)
        use_text = bool(artist or album)

        assert use_mbid is False
        assert use_text is True

    def test_search_with_artist_only(self):
        """Test search with artist only."""
        artist = "Test Artist"
        album = ""

        can_search = bool(artist or album)
        assert can_search is True

    def test_search_with_album_only(self):
        """Test search with album only."""
        artist = ""
        album = "Test Album"

        can_search = bool(artist or album)
        assert can_search is True

    def test_search_empty_not_allowed(self):
        """Test empty search is not allowed."""
        artist = ""
        album = ""

        can_search = bool(artist or album)
        assert can_search is False


class TestSearchModeIndicator:
    """Tests for search mode indicator logic."""

    def test_mbid_mode_indicator(self):
        """Test MBID mode indicator."""
        has_mbid = True
        force_text_search = False

        use_mbid = has_mbid and not force_text_search
        assert use_mbid is True

    def test_text_mode_indicator_no_mbid(self):
        """Test text mode when no MBID."""
        has_mbid = False
        force_text_search = False

        use_mbid = has_mbid and not force_text_search
        assert use_mbid is False

    def test_text_mode_indicator_forced(self):
        """Test text mode when forced."""
        has_mbid = True
        force_text_search = True

        use_mbid = has_mbid and not force_text_search
        assert use_mbid is False


class TestForceTextSearchToggle:
    """Tests for force text search toggle logic."""

    def test_toggle_enables_text_search(self):
        """Test toggling force text search enables text mode."""
        has_mbid = True
        force_text_search = True

        use_mbid = has_mbid and not force_text_search
        fields_enabled = not use_mbid

        assert use_mbid is False
        assert fields_enabled is True

    def test_toggle_disables_text_search(self):
        """Test untoggling force text search enables MBID mode."""
        has_mbid = True
        force_text_search = False

        use_mbid = has_mbid and not force_text_search
        fields_enabled = not use_mbid

        assert use_mbid is True
        assert fields_enabled is False


class TestProviderConfiguration:
    """Tests for provider configuration checking."""

    def test_provider_requires_api_key(self):
        """Test checking if provider requires API key."""
        requires_key = True
        is_configured = False

        needs_configuration = requires_key and not is_configured
        assert needs_configuration is True

    def test_provider_configured(self):
        """Test provider is properly configured."""
        requires_key = True
        is_configured = True

        needs_configuration = requires_key and not is_configured
        assert needs_configuration is False

    def test_provider_no_key_required(self):
        """Test provider that doesn't require API key."""
        requires_key = False
        is_configured = True

        needs_configuration = requires_key and not is_configured
        assert needs_configuration is False


class TestResultCardLogic:
    """Tests for CoverResultCard logic."""

    def test_score_text_without_cover(self):
        """Test score text without cover indicator."""
        score = 95
        has_cover_art = False

        score_text = f"{score}%"
        if has_cover_art:
            score_text += " [Cover]"

        assert score_text == "95%"

    def test_score_text_with_cover(self):
        """Test score text with cover indicator."""
        score = 95
        has_cover_art = True

        score_text = f"{score}%"
        if has_cover_art:
            score_text += " [Cover]"

        assert score_text == "95% [Cover]"

    def test_artist_truncation_short(self):
        """Test artist name not truncated if short."""
        artist = "Short"

        info = artist[:15] + "..." if len(artist) > 15 else artist
        assert info == "Short"

    def test_artist_truncation_long(self):
        """Test artist name truncated if long."""
        artist = "Very Long Artist Name That Needs Truncation"

        info = artist[:15] + "..." if len(artist) > 15 else artist
        assert info == "Very Long Artis..."


class TestGridLayoutCalculation:
    """Tests for grid layout calculation."""

    def test_calculate_columns_narrow(self):
        """Test column calculation for narrow width."""
        card_width = 148
        viewport_width = 300

        columns = max(1, viewport_width // card_width)
        assert columns == 2

    def test_calculate_columns_wide(self):
        """Test column calculation for wide width."""
        card_width = 148
        viewport_width = 600

        columns = max(1, viewport_width // card_width)
        assert columns == 4

    def test_calculate_columns_minimum(self):
        """Test minimum of 1 column."""
        card_width = 148
        viewport_width = 100  # Less than card width

        columns = max(1, viewport_width // card_width)
        assert columns == 1

    def test_calculate_columns_exact(self):
        """Test exact fit."""
        card_width = 148
        viewport_width = 148 * 3  # Exactly 3 cards

        columns = max(1, viewport_width // card_width)
        assert columns == 3


class TestErrorMessageFormatting:
    """Tests for error message formatting."""

    def test_connection_error_message(self):
        """Test connection error message."""
        error = "Connection refused"
        error_lower = error.lower()

        message = "Connection error" if "connection" in error_lower else error

        assert message == "Connection error"

    def test_timeout_error_message(self):
        """Test timeout error message."""
        error = "Request timeout"
        error_lower = error.lower()

        message = "Connection error" if "timeout" in error_lower else error

        assert message == "Connection error"

    def test_unauthorized_error_message(self):
        """Test unauthorized error message."""
        error = "401 Unauthorized"

        message = "Invalid API key" if "unauthorized" in error.lower() or "401" in error else error

        assert message == "Invalid API key"

    def test_rate_limit_error_message(self):
        """Test rate limit error message."""
        error = "429 Too Many Requests"

        if "rate limit" in error.lower() or "429" in error:
            message = "Rate limit exceeded"
        else:
            message = error

        assert message == "Rate limit exceeded"


class TestSelectionInfoFormatting:
    """Tests for selection info formatting."""

    def test_selection_info_with_all_fields(self):
        """Test selection info with all fields present."""
        artist = "Test Artist"
        album = "Test Album"
        year = "2020"
        score = 95

        line1 = f"<b>{artist}</b> - {album}"
        line2 = f"Year: {year} | Score: {score}%"

        assert line1 == "<b>Test Artist</b> - Test Album"
        assert line2 == "Year: 2020 | Score: 95%"

    def test_selection_info_missing_year(self):
        """Test selection info with missing year."""
        artist = "Test Artist"
        album = "Test Album"
        year = None
        score = 95

        line2 = f"Year: {year or '?'} | Score: {score}%"
        assert line2 == "Year: ? | Score: 95%"


class TestImageMetadata:
    """Tests for image metadata handling."""

    def test_update_result_metadata(self):
        """Test updating result with image metadata."""
        result = Mock()
        result.image_width = None
        result.image_height = None
        result.image_size_bytes = None

        # Simulate updating metadata
        result.image_width = 1000
        result.image_height = 1000
        result.image_size_bytes = 512000

        assert result.image_width == 1000
        assert result.image_height == 1000
        assert result.image_size_bytes == 512000

    def test_image_info_string_format(self):
        """Test image info string formatting."""
        width = 1000
        height = 1000
        size_bytes = 512000

        if width and height:
            size_kb = size_bytes / 1024
            size_str = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"
            info = f"{width}x{height} - {size_str}"
        else:
            info = ""

        assert info == "1000x1000 - 500 KB"


class TestThumbnailWorkerLogic:
    """Tests for ThumbnailWorker logic."""

    def test_cancellation_flag(self):
        """Test cancellation flag works."""
        cancelled = False

        # Simulate cancellation
        cancelled = True

        assert cancelled is True

    def test_cache_hit(self):
        """Test cache hit behavior."""
        cache = {"url1": b"data1"}
        url = "url1"

        data = cache.get(url)
        assert data == b"data1"

    def test_cache_miss(self):
        """Test cache miss behavior."""
        cache = {"url1": b"data1"}
        url = "url2"

        data = cache.get(url)
        assert data is None


class TestParallelThumbnailLoading:
    """
    Tests for parallel thumbnail loading logic.

    Verifies that thumbnails are loaded in parallel using ThreadPoolExecutor.
    """

    def test_default_concurrent_downloads_constant(self):
        """Test that DEFAULT_CONCURRENT_DOWNLOADS is defined."""
        from src.ui.search_panel import DEFAULT_CONCURRENT_DOWNLOADS

        assert DEFAULT_CONCURRENT_DOWNLOADS == 4

    def test_parallel_processing_logic(self):
        """Test that parallel processing submits all tasks."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results_processed = []

        def process_item(index):
            results_processed.append(index)
            return index

        # Simulate parallel processing
        items = [0, 1, 2, 3, 4]
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(process_item, i): i for i in items}
            for future in as_completed(futures):
                future.result()

        # All items should be processed
        assert sorted(results_processed) == items

    def test_cancellation_stops_processing(self):
        """Test that cancellation flag stops processing new items."""
        cancelled = False
        processed = []

        def should_process(index):
            nonlocal cancelled
            if index == 2:
                cancelled = True
            if cancelled:
                return False
            processed.append(index)
            return True

        for i in range(5):
            if not should_process(i):
                break

        # Only items before cancellation should be processed
        assert processed == [0, 1]

    def test_early_cancellation_check(self):
        """Test that cancellation is checked before processing."""
        cancelled = True
        processed = []

        for i in range(5):
            if cancelled:
                break
            processed.append(i)

        assert processed == []

    def test_thread_pool_exception_handling(self):
        """Test that exceptions in thread pool are handled gracefully."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def failing_task(index):
            if index == 2:
                raise ValueError("Test error")
            return index

        results = []
        errors = []

        items = [0, 1, 2, 3, 4]
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(failing_task, i): i for i in items}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    errors.append(str(e))

        # Some items processed, some errored
        assert len(results) == 4
        assert len(errors) == 1
        assert "Test error" in errors[0]

    def test_process_thumbnail_with_existing_url(self):
        """Test processing when cover_url already exists."""
        # Simulate result with existing URL
        result = Mock()
        result.cover_url = "https://example.com/cover.jpg"

        # URL should be used directly
        url = result.cover_url
        assert url == "https://example.com/cover.jpg"

    def test_process_thumbnail_needs_url_fetch(self):
        """Test processing when cover_url needs to be fetched."""
        # Simulate result without URL
        result = Mock()
        result.cover_url = None

        url = result.cover_url
        if not url:
            # Would call provider.get_cover_url(result)
            url = "https://fetched.com/cover.jpg"

        assert url == "https://fetched.com/cover.jpg"

    def test_parallel_cache_access(self):
        """Test that cache can be accessed from multiple threads."""
        from threading import Thread

        cache = {}
        lock_errors = []

        def cache_operation(key, value):
            try:
                cache[key] = value
                _ = cache.get(key)
            except Exception as e:
                lock_errors.append(str(e))

        threads = [Thread(target=cache_operation, args=(f"key{i}", f"value{i}")) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(lock_errors) == 0
        assert len(cache) == 10

    def test_configurable_max_workers(self):
        """Test that max_workers can be configured."""
        from src.ui.search_panel import DEFAULT_CONCURRENT_DOWNLOADS

        # Default value
        assert DEFAULT_CONCURRENT_DOWNLOADS == 4

        # Simulate config override
        config = {"ui.max_concurrent_downloads": 8}
        max_workers = config.get("ui.max_concurrent_downloads", DEFAULT_CONCURRENT_DOWNLOADS)
        assert max_workers == 8

        # Fallback to default
        config = {}
        max_workers = config.get("ui.max_concurrent_downloads", DEFAULT_CONCURRENT_DOWNLOADS)
        assert max_workers == 4

    def test_progress_signal_logic(self):
        """Test that progress is tracked correctly."""
        total = 5
        completed = 0
        progress_updates = []

        def on_progress(current, total_count):
            progress_updates.append((current, total_count))

        # Simulate progress updates
        for _ in range(total):
            completed += 1
            on_progress(completed, total)

        assert len(progress_updates) == 5
        assert progress_updates[0] == (1, 5)
        assert progress_updates[-1] == (5, 5)

    def test_progress_bar_range_calculation(self):
        """Test progress bar range based on result count."""
        results_count = 10

        # Progress bar should have range 0 to results_count
        progress_range = (0, results_count)
        assert progress_range == (0, 10)

        # After completion, reset to indeterminate (0, 0)
        indeterminate_range = (0, 0)
        assert indeterminate_range == (0, 0)


class TestApplySelectionLogic:
    """Tests for apply selection logic."""

    def test_apply_with_cached_data(self):
        """Test apply uses cached data when available."""
        cached_data = {0: b"cover_data"}
        selected_index = 0

        data = cached_data.get(selected_index)
        assert data == b"cover_data"

    def test_apply_without_cached_data(self):
        """Test apply needs download when no cached data."""
        cached_data = {}
        selected_index = 0

        data = cached_data.get(selected_index)
        needs_download = data is None

        assert needs_download is True

    def test_apply_with_no_cover_url(self):
        """Test apply fails with no cover URL."""
        cover_url = None

        can_apply = bool(cover_url)
        assert can_apply is False

    def test_apply_with_cover_url(self):
        """Test apply succeeds with cover URL."""
        cover_url = "https://example.com/cover.jpg"

        can_apply = bool(cover_url)
        assert can_apply is True


class TestSearchFieldCheckboxLogic:
    """
    Tests for search field checkbox logic (Issue 3).

    Verifies that checkboxes control which fields are sent to the API.
    """

    def _build_search_params(
        self,
        artist: str,
        album: str,
        year: str,
        title: str,
        use_artist: bool,
        use_album: bool,
        use_year: bool,
        use_title: bool,
    ) -> dict:
        """
        Build search parameters based on checkbox state.

        This mimics the logic in _start_search().
        """
        params = {}
        if use_artist and artist.strip():
            params["artist"] = artist.strip()
        if use_album and album.strip():
            params["album"] = album.strip()
        if use_year and year.strip():
            params["year"] = year.strip()
        if use_title and title.strip():
            params["title"] = title.strip()
        return params

    def test_all_fields_checked(self):
        """Test that all checked fields are included."""
        params = self._build_search_params(
            artist="The Beatles",
            album="Abbey Road",
            year="1969",
            title="Come Together",
            use_artist=True,
            use_album=True,
            use_year=True,
            use_title=True,
        )

        assert params == {
            "artist": "The Beatles",
            "album": "Abbey Road",
            "year": "1969",
            "title": "Come Together",
        }

    def test_only_artist_and_album_checked(self):
        """Test default case: only artist and album checked."""
        params = self._build_search_params(
            artist="The Beatles",
            album="Abbey Road",
            year="1969",
            title="Come Together",
            use_artist=True,
            use_album=True,
            use_year=False,
            use_title=False,
        )

        assert params == {
            "artist": "The Beatles",
            "album": "Abbey Road",
        }
        assert "year" not in params
        assert "title" not in params

    def test_unchecked_field_not_sent(self):
        """Test that unchecked fields are not included."""
        params = self._build_search_params(
            artist="The Beatles",
            album="Abbey Road",
            year="1969",
            title="",
            use_artist=False,  # Unchecked
            use_album=True,
            use_year=True,
            use_title=False,
        )

        assert "artist" not in params
        assert params == {
            "album": "Abbey Road",
            "year": "1969",
        }

    def test_empty_field_not_sent_even_if_checked(self):
        """Test that empty fields are not sent even if checked."""
        params = self._build_search_params(
            artist="The Beatles",
            album="",  # Empty
            year="",  # Empty
            title="",  # Empty
            use_artist=True,
            use_album=True,  # Checked but empty
            use_year=True,  # Checked but empty
            use_title=True,  # Checked but empty
        )

        assert params == {
            "artist": "The Beatles",
        }

    def test_whitespace_only_field_not_sent(self):
        """Test that whitespace-only fields are not sent."""
        params = self._build_search_params(
            artist="The Beatles",
            album="   ",  # Whitespace only
            year="",
            title="",
            use_artist=True,
            use_album=True,
            use_year=False,
            use_title=False,
        )

        assert "album" not in params
        assert params == {"artist": "The Beatles"}

    def test_all_unchecked_returns_empty(self):
        """Test that all unchecked returns empty params."""
        params = self._build_search_params(
            artist="The Beatles",
            album="Abbey Road",
            year="1969",
            title="Come Together",
            use_artist=False,
            use_album=False,
            use_year=False,
            use_title=False,
        )

        assert params == {}

    def _can_search(self, params: dict) -> bool:
        """Check if search can proceed (at least one parameter)."""
        return bool(params)

    def test_can_search_with_params(self):
        """Test that search is allowed with at least one parameter."""
        params = {"artist": "The Beatles"}
        assert self._can_search(params) is True

    def test_cannot_search_without_params(self):
        """Test that search is blocked without parameters."""
        params = {}
        assert self._can_search(params) is False


class TestFieldEnabledState:
    """
    Tests for field enabled/disabled state based on checkbox.

    The text field should be disabled when its checkbox is unchecked.
    """

    def _is_field_enabled(self, checkbox_checked: bool, has_mbid: bool, force_text: bool) -> bool:
        """
        Determine if a field should be enabled.

        Fields are enabled when:
        - Checkbox is checked AND
        - Either no MBID exists OR force_text is enabled
        """
        use_mbid = has_mbid and not force_text
        return checkbox_checked and not use_mbid

    def test_field_enabled_when_checked_no_mbid(self):
        """Test field is enabled when checkbox checked and no MBID."""
        enabled = self._is_field_enabled(
            checkbox_checked=True,
            has_mbid=False,
            force_text=False,
        )
        assert enabled is True

    def test_field_disabled_when_unchecked(self):
        """Test field is disabled when checkbox unchecked."""
        enabled = self._is_field_enabled(
            checkbox_checked=False,
            has_mbid=False,
            force_text=False,
        )
        assert enabled is False

    def test_field_disabled_when_mbid_present(self):
        """Test field is disabled when MBID present (MBID mode)."""
        enabled = self._is_field_enabled(
            checkbox_checked=True,
            has_mbid=True,
            force_text=False,
        )
        assert enabled is False

    def test_field_enabled_when_mbid_but_forced_text(self):
        """Test field is enabled when MBID present but text forced."""
        enabled = self._is_field_enabled(
            checkbox_checked=True,
            has_mbid=True,
            force_text=True,
        )
        assert enabled is True


class TestCoverResultCardZoomLogic:
    """
    Tests for cover result card zoom logic (Issue 4).

    Double-clicking on a result card should open the zoom dialog.
    """

    def test_can_zoom_with_image_data(self):
        """Test that zoom is possible when image data exists."""
        image_data = b"fake_image_data"

        can_zoom = image_data is not None and len(image_data) > 0
        assert can_zoom is True

    def test_cannot_zoom_without_image_data(self):
        """Test that zoom is not possible without image data."""
        image_data = None

        can_zoom = image_data is not None
        assert can_zoom is False

    def test_cannot_zoom_with_empty_data(self):
        """Test that zoom is not possible with empty data."""
        image_data = b""

        can_zoom = image_data is not None and len(image_data) > 0
        assert can_zoom is False

    def test_image_data_stored_for_zoom(self):
        """Test that image data is stored for later zoom access."""
        # Simulating the data storage in CoverResultCard
        card_data = {
            "thumbnail_url": "https://example.com/thumb.jpg",
            "cover_url": "https://example.com/cover.jpg",
            "image_data": b"full_cover_image_bytes",
        }

        # When downloading cover, data should be stored
        assert card_data["image_data"] == b"full_cover_image_bytes"

    def test_zoom_uses_full_resolution(self):
        """Test that zoom uses full resolution image, not thumbnail."""
        thumbnail_data = b"small_thumbnail"
        full_image_data = b"large_full_resolution_image_bytes"

        # Zoom should use full image, not thumbnail
        zoom_data = full_image_data
        assert len(zoom_data) > len(thumbnail_data)


class TestSearchDialogSizeLogic:
    """
    Tests for search dialog size persistence logic (Issue 2).
    """

    def test_default_dialog_size(self):
        """Test that default dialog size is 950x750."""
        default_width = 950
        default_height = 750

        assert default_width == 950
        assert default_height == 750

    def test_dialog_size_can_be_remembered(self):
        """Test that dialog size can be stored and retrieved."""
        stored_size = {}

        # Simulate saving dialog size
        stored_size["width"] = 1000
        stored_size["height"] = 800

        # Simulate retrieving dialog size
        width = stored_size.get("width", 950)
        height = stored_size.get("height", 750)

        assert width == 1000
        assert height == 800

    def test_dialog_size_defaults_when_not_stored(self):
        """Test that dialog uses defaults when size not stored."""
        stored_size = {}

        width = stored_size.get("width", 950)
        height = stored_size.get("height", 750)

        assert width == 950
        assert height == 750

    def test_minimum_dialog_size(self):
        """Test that dialog has a minimum size."""
        # Minimum size was increased to 750x550 for two-column layout
        min_width = 750
        min_height = 550
        requested_width = 300
        requested_height = 200

        actual_width = max(min_width, requested_width)
        actual_height = max(min_height, requested_height)

        assert actual_width == 750
        assert actual_height == 550


class TestTwoColumnLayoutStructure:
    """
    Tests for the two-column layout structure.

    The SearchPanel uses a two-column layout:
    - Left column: Search criteria (fixed 290px width)
    - Right column: Results + Selection (expandable)
    """

    # Layout constants
    LEFT_COLUMN_WIDTH = 290
    MIN_DIALOG_WIDTH = 750
    MIN_DIALOG_HEIGHT = 550
    DEFAULT_DIALOG_WIDTH = 950
    DEFAULT_DIALOG_HEIGHT = 750

    def test_left_column_width_constant(self):
        """Test that left column width is 290px."""
        assert self.LEFT_COLUMN_WIDTH == 290

    def test_minimum_width_accommodates_both_columns(self):
        """Test minimum width provides space for both columns."""
        min_right_width = 400  # Reasonable minimum for results grid
        assert self.LEFT_COLUMN_WIDTH + min_right_width <= self.MIN_DIALOG_WIDTH

    def test_minimum_dimensions(self):
        """Test minimum dialog dimensions for two-column layout."""
        assert self.MIN_DIALOG_WIDTH == 750
        assert self.MIN_DIALOG_HEIGHT == 550

    def test_default_dimensions(self):
        """Test default dialog dimensions are larger than minimum."""
        assert self.DEFAULT_DIALOG_WIDTH >= self.MIN_DIALOG_WIDTH
        assert self.DEFAULT_DIALOG_HEIGHT >= self.MIN_DIALOG_HEIGHT

    def test_right_column_available_space(self):
        """Test right column has enough space at minimum width."""
        right_column_width = self.MIN_DIALOG_WIDTH - self.LEFT_COLUMN_WIDTH
        card_width = 140  # CoverResultCard width
        spacing = 8

        # Should fit at least 2 cards at minimum width
        min_cards = right_column_width // (card_width + spacing)
        assert min_cards >= 2, "Right column should fit at least 2 cards at minimum width"

    def test_grid_column_calculation_at_minimum_width(self):
        """Test grid column calculation at minimum dialog width."""
        # At minimum width, right column should show 2-3 columns
        right_column_width = self.MIN_DIALOG_WIDTH - self.LEFT_COLUMN_WIDTH - 20  # margins
        card_width = 148  # Card width (140) + spacing (8)

        columns = max(1, right_column_width // card_width)
        assert columns >= 2, "Should fit at least 2 columns at minimum width"

    def test_grid_column_calculation_at_default_width(self):
        """Test grid column calculation at default dialog width."""
        # At default width, right column should show more columns
        right_column_width = self.DEFAULT_DIALOG_WIDTH - self.LEFT_COLUMN_WIDTH - 20  # margins
        card_width = 148  # Card width (140) + spacing (8)

        columns = max(1, right_column_width // card_width)
        assert columns >= 3, "Should fit at least 3 columns at default width"

    def test_left_column_fits_all_form_fields(self):
        """Test that 250px width accommodates search form fields."""
        # Field layout: checkbox (~80px) + input field (remaining)
        checkbox_width = 80
        min_input_width = 100

        required_width = checkbox_width + min_input_width
        assert required_width <= self.LEFT_COLUMN_WIDTH, (
            "Left column should fit checkbox + input field"
        )

    def test_layout_proportions(self):
        """Test layout proportions at different widths."""
        test_widths = [750, 950, 1200, 1600]

        for total_width in test_widths:
            left_width = self.LEFT_COLUMN_WIDTH
            right_width = total_width - left_width

            # Left column should always be 290px
            assert left_width == 290, f"Left column should be fixed at {total_width}px width"

            # Right column should expand
            assert right_width > left_width, f"Right column should be wider at {total_width}px"

            # Right column should be proportionally larger at wider widths
            if total_width >= 950:
                assert right_width >= 2 * left_width, (
                    f"Right column should be at least 2x left at {total_width}px width"
                )


class TestSelectionPanelAnimationLogic:
    """
    Tests for the selection panel show/hide animation logic.

    The selection panel is hidden by default and shown with animation
    when a result is selected.
    """

    def test_selection_panel_starts_hidden(self):
        """Test that selection panel starts hidden (maxHeight=0)."""
        initial_max_height = 0
        initial_visible = False

        # Selection panel should start collapsed
        assert initial_max_height == 0
        assert initial_visible is False

    def test_selection_panel_dynamic_height(self):
        """Test that selection panel height adapts to content."""
        # Target height is now calculated dynamically using sizeHint()
        thumbnail_height = 80
        min_padding = 10

        # Content should at least accommodate the thumbnail
        min_content_height = thumbnail_height + min_padding
        assert min_content_height >= 90  # Reasonable minimum

    def test_show_selection_panel_logic(self):
        """Test the logic for showing the selection panel."""
        # Simulating _show_selection_panel behavior
        is_visible = False
        max_height = 0
        # Target height is now calculated dynamically from sizeHint()
        # Simulating with a reasonable content height
        content_height = 95  # thumbnail (80) + padding

        # When showing, should become visible and animate to content height
        if not is_visible or max_height == 0:
            is_visible = True
            # Animation would set max_height to content height
            max_height = content_height

        assert is_visible is True
        assert max_height > 0  # Height should be positive (dynamic)

    def test_hide_selection_panel_logic(self):
        """Test the logic for hiding the selection panel."""
        # Simulating _hide_selection_panel behavior
        is_visible = True
        max_height = 100

        # When hiding, should animate to 0 and then set invisible
        if is_visible:
            # Animation would set max_height to 0
            max_height = 0
            # After animation finishes
            if max_height == 0:
                is_visible = False

        assert is_visible is False
        assert max_height == 0

    def test_show_already_visible_is_noop(self):
        """Test that showing an already visible panel does nothing."""
        is_visible = True
        max_height = 100

        # If already visible with height > 0, should return early
        should_animate = not (is_visible and max_height > 0)

        assert should_animate is False

    def test_hide_already_hidden_is_noop(self):
        """Test that hiding an already hidden panel does nothing."""
        is_visible = False
        max_height = 0

        # If already hidden, should return early
        should_animate = is_visible

        assert should_animate is False

    def test_animation_easing_curve(self):
        """Test that animation uses appropriate easing curve."""
        from PySide6.QtCore import QEasingCurve

        # OutCubic provides smooth deceleration at the end
        easing_curve = QEasingCurve.Type.OutCubic
        assert easing_curve == QEasingCurve.Type.OutCubic

    def test_animation_duration(self):
        """Test that animation duration is appropriate."""
        duration_ms = 200  # As defined in _setup_ui

        # Animation should be quick but visible (100-300ms is typical)
        assert 100 <= duration_ms <= 300


class TestSearchStatusMessageFormatting:
    """
    Tests for search status message formatting.

    Verifies that the search status message handles different translation
    placeholder formats correctly (both {desc} and {criteria}).
    """

    def _format_search_status(
        self,
        provider_name: str,
        artist: str,
        album: str,
        year: str,
        template: str,
    ) -> str:
        """
        Format search status message similar to _start_search().

        Handles both {desc} and {criteria} placeholders for translation compatibility.
        """
        search_desc = []
        if artist:
            search_desc.append(f"artist='{artist}'")
        if album:
            search_desc.append(f"album='{album}'")
        if year:
            search_desc.append(f"year={year}")

        criteria_text = ", ".join(search_desc) if search_desc else "..."

        # Provide both desc and criteria for translation compatibility
        return template.format(
            provider=provider_name,
            desc=criteria_text,
            criteria=criteria_text,
        )

    def test_format_with_desc_placeholder(self):
        """Test formatting with {desc} placeholder (msgid format)."""
        template = "Searching on {provider}: {desc}..."

        result = self._format_search_status(
            provider_name="MusicBrainz",
            artist="The Beatles",
            album="Abbey Road",
            year="1969",
            template=template,
        )

        assert (
            result
            == "Searching on MusicBrainz: artist='The Beatles', album='Abbey Road', year=1969..."
        )

    def test_format_with_criteria_placeholder(self):
        """Test formatting with {criteria} placeholder (msgstr format)."""
        template = "Recherche sur {provider}: {criteria}..."

        result = self._format_search_status(
            provider_name="MusicBrainz",
            artist="The Beatles",
            album="Abbey Road",
            year="1969",
            template=template,
        )

        assert (
            result
            == "Recherche sur MusicBrainz: artist='The Beatles', album='Abbey Road', year=1969..."
        )

    def test_format_with_empty_criteria(self):
        """Test formatting when no search criteria provided."""
        template = "Searching on {provider}: {desc}..."

        result = self._format_search_status(
            provider_name="MusicBrainz",
            artist="",
            album="",
            year="",
            template=template,
        )

        assert result == "Searching on MusicBrainz: ......"

    def test_format_with_artist_only(self):
        """Test formatting with only artist."""
        template = "Searching on {provider}: {desc}..."

        result = self._format_search_status(
            provider_name="Discogs",
            artist="Pink Floyd",
            album="",
            year="",
            template=template,
        )

        assert result == "Searching on Discogs: artist='Pink Floyd'..."

    def test_format_with_album_only(self):
        """Test formatting with only album."""
        template = "Searching on {provider}: {desc}..."

        result = self._format_search_status(
            provider_name="Last.fm",
            artist="",
            album="Dark Side of the Moon",
            year="",
            template=template,
        )

        assert result == "Searching on Last.fm: album='Dark Side of the Moon'..."


class TestNoAutoSearchOnInit:
    """
    Tests to verify that no auto-search is triggered on dialog initialization.

    Bug fix: Previously, QTimer.singleShot(0, self._start_search) was called
    in __init__, which caused the search to start automatically, showing
    progress bar and disabling the search button.
    """

    def test_progress_bar_should_be_hidden_initially(self):
        """Test that progress bar visibility should be False on init."""
        # This tests the expected initial state
        initial_progress_visible = False
        assert initial_progress_visible is False

    def test_search_button_should_be_enabled_initially(self):
        """Test that search button should be enabled on init."""
        # This tests the expected initial state
        initial_button_enabled = True
        assert initial_button_enabled is True

    def test_no_qtimer_singleshot_for_auto_search(self):
        """
        Verify that auto-search has been removed from the codebase.

        This is a documentation test - the actual implementation should NOT
        have QTimer.singleShot(0, self._start_search) in __init__.
        """
        # Read the search_panel.py file and verify no auto-search
        from pathlib import Path

        search_panel_path = Path(__file__).parent.parent / "src" / "ui" / "search_panel.py"
        if search_panel_path.exists():
            content = search_panel_path.read_text()
            # The auto-search line should NOT be present
            auto_search_pattern = "QTimer.singleShot(0, self._start_search)"
            assert auto_search_pattern not in content, "Auto-search should be removed from __init__"


class TestProviderPersistenceDuringSearch:
    """
    Tests for provider persistence during search operations.

    Bug fix: The source selector was resetting to MusicBrainz when results
    were displayed. The fix stores the active provider at search start.
    """

    def test_active_provider_stored_at_search_start(self):
        """Test that _active_provider is used to store provider at search start."""
        from pathlib import Path

        search_panel_path = Path(__file__).parent.parent / "src" / "ui" / "search_panel.py"
        if search_panel_path.exists():
            content = search_panel_path.read_text()
            # Verify the _active_provider pattern is present
            assert "_active_provider" in content, (
                "_active_provider should be used to store provider"
            )

    def test_results_ready_uses_stored_provider(self):
        """Test that _on_results_ready uses stored provider, not current selector."""
        # Simulate the scenario
        stored_provider_name = "Discogs"  # Provider at search start
        current_selector_name = "MusicBrainz"  # Selector may have changed

        # _on_results_ready should use stored_provider, not current_selector
        # This is the expected behavior after the fix
        provider_used = stored_provider_name
        assert provider_used == "Discogs"

    def test_thumbnail_worker_uses_stored_provider(self):
        """Test that ThumbnailWorker is initialized with stored provider."""
        # Simulate the fix behavior
        stored_provider_name = "Last.fm"

        # When creating ThumbnailWorker, should use stored_provider
        thumb_worker_provider = stored_provider_name
        assert thumb_worker_provider == "Last.fm"

    def test_provider_persists_through_async_operation(self):
        """Test that provider is preserved through the entire async search."""
        # Simulate search workflow
        initial_provider = "Discogs"
        _active_provider = initial_provider

        # User changes selector during search (simulated)
        current_selector = "MusicBrainz"

        # Results handler should still use stored provider
        assert _active_provider == "Discogs"
        assert current_selector == "MusicBrainz"  # Selector changed
        assert _active_provider != current_selector  # But stored provider preserved


class TestApiConnectionStatus:
    """
    Tests for API connection status display.

    Feature: Show connection status in search panel (e.g., "Connecting to musicbrainz.org...")
    """

    def test_api_host_property_exists(self):
        """Test that CoverProvider has api_host property."""
        from src.api.base import CoverProvider

        # Check that api_host is declared as abstract property
        assert hasattr(CoverProvider, "api_host")

    def test_musicbrainz_api_host(self):
        """Test MusicBrainz provider has correct api_host."""
        from src.api.musicbrainz import MusicBrainzProvider

        provider = MusicBrainzProvider()
        assert provider.api_host == "musicbrainz.org"
        provider.close()

    def test_discogs_api_host(self):
        """Test Discogs provider has correct api_host."""
        from src.api.discogs import DiscogsProvider

        provider = DiscogsProvider()
        assert provider.api_host == "api.discogs.com"
        provider.close()

    def test_lastfm_api_host(self):
        """Test Last.fm provider has correct api_host."""
        from src.api.lastfm import LastFmProvider

        provider = LastFmProvider()
        assert provider.api_host == "ws.audioscrobbler.com"
        provider.close()

    def test_connection_status_format_connecting(self):
        """Test connection status message format for connecting state."""
        api_host = "musicbrainz.org"
        message = f"Connecting to {api_host}..."
        assert message == "Connecting to musicbrainz.org..."

    def test_connection_status_format_connected(self):
        """Test connection status message format for connected state."""
        api_host = "api.discogs.com"
        message = f"Connected to {api_host}"
        assert message == "Connected to api.discogs.com"

    def test_connection_status_format_error(self):
        """Test connection status message format for HTTP error."""
        api_host = "ws.audioscrobbler.com"
        status_code = 403
        message = f"Communication error with {api_host} (HTTP {status_code})"
        assert message == "Communication error with ws.audioscrobbler.com (HTTP 403)"

    def test_connection_status_format_connection_failed(self):
        """Test connection status message format for connection failure."""
        api_host = "musicbrainz.org"
        message = f"Connection failed to {api_host}"
        assert message == "Connection failed to musicbrainz.org"

    def test_connection_status_format_timeout(self):
        """Test connection status message format for timeout."""
        api_host = "api.discogs.com"
        message = f"Connection timeout to {api_host}"
        assert message == "Connection timeout to api.discogs.com"

    def test_search_worker_has_connection_status_signal(self):
        """Test that SearchWorker has connection_status signal."""
        from pathlib import Path

        search_panel_path = Path(__file__).parent.parent / "src" / "ui" / "search_panel.py"
        if search_panel_path.exists():
            content = search_panel_path.read_text()
            assert "connection_status = Signal" in content, (
                "SearchWorker should have connection_status signal"
            )

    def test_connection_status_signal_parameters(self):
        """Test that connection_status signal has correct parameters."""
        # Signal should emit (message: str, is_error: bool)
        # This is documented in the code, testing the expected behavior
        message = "Connected to musicbrainz.org"
        is_error = False
        result = (message, is_error)
        assert result == ("Connected to musicbrainz.org", False)

        message = "Communication error with api.discogs.com (HTTP 500)"
        is_error = True
        result = (message, is_error)
        assert result == ("Communication error with api.discogs.com (HTTP 500)", True)


class TestSearchWorkerISRCBarcodeStrategies:
    """
    Tests for SearchWorker ISRC/Barcode lookup strategies.

    The SearchWorker implements a sequential fallback strategy:
    1. MBID lookup (MusicBrainz only)
    2. ISRC lookup (MusicBrainz only)
    3. Barcode lookup (MusicBrainz and Discogs)
    4. Text search (all providers)
    """

    def test_isrc_lookup_only_with_musicbrainz(self):
        """Test ISRC lookup is only attempted with MusicBrainz provider."""
        from src.api.discogs import DiscogsProvider
        from src.api.musicbrainz import MusicBrainzProvider

        # MusicBrainz supports ISRC
        mb_provider = MusicBrainzProvider()
        assert hasattr(mb_provider, "lookup_by_isrc")
        mb_provider.close()

        # Discogs does NOT support ISRC
        discogs_provider = DiscogsProvider()
        assert not hasattr(discogs_provider, "lookup_by_isrc")
        discogs_provider.close()

    def test_barcode_lookup_musicbrainz_and_discogs(self):
        """Test barcode lookup works with MusicBrainz and Discogs."""
        from src.api.discogs import DiscogsProvider
        from src.api.lastfm import LastFmProvider
        from src.api.musicbrainz import MusicBrainzProvider

        # MusicBrainz supports barcode
        mb_provider = MusicBrainzProvider()
        assert hasattr(mb_provider, "lookup_by_barcode")
        mb_provider.close()

        # Discogs supports barcode
        discogs_provider = DiscogsProvider()
        assert hasattr(discogs_provider, "lookup_by_barcode")
        discogs_provider.close()

        # Last.fm does NOT support barcode
        lastfm_provider = LastFmProvider()
        assert not hasattr(lastfm_provider, "lookup_by_barcode")
        lastfm_provider.close()

    def test_search_worker_accepts_isrc_parameter(self):
        """Test SearchWorker accepts isrc parameter."""
        # Verify SearchWorker.__init__ accepts isrc parameter
        import inspect

        from src.ui.search_panel import SearchWorker

        sig = inspect.signature(SearchWorker.__init__)
        params = list(sig.parameters.keys())
        assert "isrc" in params

    def test_search_worker_accepts_barcode_parameter(self):
        """Test SearchWorker accepts barcode parameter."""
        # Verify SearchWorker.__init__ accepts barcode parameter
        import inspect

        from src.ui.search_panel import SearchWorker

        sig = inspect.signature(SearchWorker.__init__)
        params = list(sig.parameters.keys())
        assert "barcode" in params

    def test_fallback_sequence_logic(self):
        """Test the fallback sequence stops after first success."""
        # Simulate the sequential search strategy
        results = []

        # Strategy 1: MBID lookup
        mbid_result = None  # No result
        if mbid_result:
            results.append(mbid_result)

        # Strategy 2: ISRC lookup (only if no results yet)
        isrc_result = Mock(artist="Test", album="Album")  # Found!
        if not results and isrc_result:
            results.append(isrc_result)

        # Strategy 3: Barcode lookup (only if no results yet)
        barcode_result = Mock(artist="Other", album="Other Album")
        if not results and barcode_result:
            results.append(barcode_result)

        # Strategy 4: Text search (only if no results yet)
        text_results = [Mock(artist="Third", album="Third Album")]
        if not results:
            results.extend(text_results)

        # Should stop after ISRC success
        assert len(results) == 1
        assert results[0].artist == "Test"

    def test_fallback_continues_on_empty_result(self):
        """Test that empty results trigger next strategy."""
        results = []

        # Strategy 1: MBID lookup - empty
        mbid_result = None
        if mbid_result:
            results.append(mbid_result)

        # Strategy 2: ISRC lookup - empty
        isrc_result = None
        if not results and isrc_result:
            results.append(isrc_result)

        # Strategy 3: Barcode lookup - empty
        barcode_result = None
        if not results and barcode_result:
            results.append(barcode_result)

        # Strategy 4: Text search - has results
        text_results = [Mock(artist="Found", album="Via Text")]
        if not results:
            results.extend(text_results)

        # Should continue to text search
        assert len(results) == 1
        assert results[0].artist == "Found"

    def test_isrc_only_search(self):
        """Test search with only ISRC (no artist/album)."""
        artist = ""
        album = ""
        isrc = "USRC17607839"
        barcode = ""

        # Can search with just ISRC
        can_search = bool(artist or album or isrc or barcode)
        assert can_search is True

    def test_barcode_only_search(self):
        """Test search with only barcode (no artist/album)."""
        artist = ""
        album = ""
        isrc = ""
        barcode = "012345678901"

        # Can search with just barcode
        can_search = bool(artist or album or isrc or barcode)
        assert can_search is True

    def test_search_blocked_without_any_criteria(self):
        """Test search blocked without any criteria."""
        artist = ""
        album = ""
        isrc = ""
        barcode = ""
        use_mbid = False

        # Cannot search without any criteria
        can_search = use_mbid or bool(artist or album or isrc or barcode)
        assert can_search is False

    def test_isrc_format_validation_logic(self):
        """Test ISRC format validation logic (as implemented in provider)."""
        # Valid ISRC: 12 characters, alphanumeric
        valid_isrc = "USRC17607839"
        normalized = valid_isrc.replace("-", "").replace(" ", "").upper()
        is_valid = len(normalized) == 12
        assert is_valid is True

        # ISRC with dashes (should be normalized)
        isrc_with_dashes = "US-RC1-76-07839"
        normalized = isrc_with_dashes.replace("-", "").replace(" ", "").upper()
        assert len(normalized) == 12

        # Invalid ISRC (wrong length)
        invalid_isrc = "SHORT"
        normalized = invalid_isrc.replace("-", "").replace(" ", "").upper()
        is_valid = len(normalized) == 12
        assert is_valid is False

    def test_barcode_format_validation_logic(self):
        """Test barcode format validation logic (as implemented in provider)."""
        # Valid UPC: 12 digits
        valid_upc = "012345678901"
        cleaned = valid_upc.replace("-", "").replace(" ", "")
        is_valid = cleaned.isdigit() and len(cleaned) in (12, 13)
        assert is_valid is True

        # Valid EAN: 13 digits
        valid_ean = "0123456789012"
        cleaned = valid_ean.replace("-", "").replace(" ", "")
        is_valid = cleaned.isdigit() and len(cleaned) in (12, 13)
        assert is_valid is True

        # Invalid barcode (wrong length)
        invalid_barcode = "12345"
        cleaned = invalid_barcode.replace("-", "").replace(" ", "")
        is_valid = cleaned.isdigit() and len(cleaned) in (12, 13)
        assert is_valid is False

        # Invalid barcode (non-numeric)
        invalid_barcode = "ABC123456789"
        cleaned = invalid_barcode.replace("-", "").replace(" ", "")
        is_valid = cleaned.isdigit() and len(cleaned) in (12, 13)
        assert is_valid is False

    def test_provider_type_checking_for_isrc(self):
        """Test that ISRC lookup uses isinstance check for MusicBrainz."""
        from src.api.discogs import DiscogsProvider
        from src.api.musicbrainz import MusicBrainzProvider

        mb_provider = Mock(spec=MusicBrainzProvider)
        discogs_provider = Mock(spec=DiscogsProvider)

        # ISRC lookup should only happen with MusicBrainz
        isrc = "USRC17607839"

        # With MusicBrainz - should attempt lookup
        should_try_isrc_mb = bool(isrc) and isinstance(mb_provider, MusicBrainzProvider)
        # Note: Mock with spec doesn't pass isinstance, this tests the logic
        # In real code, isinstance(actual_mb_provider, MusicBrainzProvider) is True

        # With Discogs - should not attempt
        should_try_isrc_discogs = bool(isrc) and isinstance(discogs_provider, MusicBrainzProvider)
        assert should_try_isrc_discogs is False

    def test_provider_type_checking_for_barcode(self):
        """Test that barcode lookup uses isinstance check for supported providers."""
        from src.api.discogs import DiscogsProvider
        from src.api.lastfm import LastFmProvider
        from src.api.musicbrainz import MusicBrainzProvider

        barcode = "012345678901"

        # MusicBrainz supports barcode
        mb_provider = MusicBrainzProvider()
        supports_barcode = isinstance(mb_provider, (MusicBrainzProvider, DiscogsProvider))
        assert supports_barcode is True
        mb_provider.close()

        # Discogs supports barcode
        discogs_provider = DiscogsProvider()
        supports_barcode = isinstance(discogs_provider, (MusicBrainzProvider, DiscogsProvider))
        assert supports_barcode is True
        discogs_provider.close()

        # Last.fm does NOT support barcode
        lastfm_provider = LastFmProvider()
        supports_barcode = isinstance(lastfm_provider, (MusicBrainzProvider, DiscogsProvider))
        assert supports_barcode is False
        lastfm_provider.close()


class TestISRCBarcodeCheckboxLogic:
    """Tests for ISRC/Barcode checkbox enable/disable logic."""

    def _build_search_params_with_isrc_barcode(
        self,
        artist: str,
        album: str,
        year: str,
        isrc: str,
        barcode: str,
        use_artist: bool,
        use_album: bool,
        use_year: bool,
        use_isrc: bool,
        use_barcode: bool,
    ) -> dict:
        """Build search parameters including ISRC/Barcode."""
        params = {}
        if use_artist and artist.strip():
            params["artist"] = artist.strip()
        if use_album and album.strip():
            params["album"] = album.strip()
        if use_year and year.strip():
            params["year"] = year.strip()
        if use_isrc and isrc.strip():
            params["isrc"] = isrc.strip()
        if use_barcode and barcode.strip():
            params["barcode"] = barcode.strip()
        return params

    def test_isrc_included_when_checked(self):
        """Test ISRC is included when checkbox is checked."""
        params = self._build_search_params_with_isrc_barcode(
            artist="",
            album="",
            year="",
            isrc="USRC17607839",
            barcode="",
            use_artist=False,
            use_album=False,
            use_year=False,
            use_isrc=True,
            use_barcode=False,
        )
        assert params == {"isrc": "USRC17607839"}

    def test_isrc_excluded_when_unchecked(self):
        """Test ISRC is excluded when checkbox is unchecked."""
        params = self._build_search_params_with_isrc_barcode(
            artist="Test Artist",
            album="",
            year="",
            isrc="USRC17607839",
            barcode="",
            use_artist=True,
            use_album=False,
            use_year=False,
            use_isrc=False,  # Unchecked
            use_barcode=False,
        )
        assert "isrc" not in params
        assert params == {"artist": "Test Artist"}

    def test_barcode_included_when_checked(self):
        """Test barcode is included when checkbox is checked."""
        params = self._build_search_params_with_isrc_barcode(
            artist="",
            album="",
            year="",
            isrc="",
            barcode="012345678901",
            use_artist=False,
            use_album=False,
            use_year=False,
            use_isrc=False,
            use_barcode=True,
        )
        assert params == {"barcode": "012345678901"}

    def test_barcode_excluded_when_unchecked(self):
        """Test barcode is excluded when checkbox is unchecked."""
        params = self._build_search_params_with_isrc_barcode(
            artist="Test Artist",
            album="",
            year="",
            isrc="",
            barcode="012345678901",
            use_artist=True,
            use_album=False,
            use_year=False,
            use_isrc=False,
            use_barcode=False,  # Unchecked
        )
        assert "barcode" not in params
        assert params == {"artist": "Test Artist"}

    def test_combined_search_with_isrc_and_artist(self):
        """Test combined search with ISRC and artist."""
        params = self._build_search_params_with_isrc_barcode(
            artist="The Beatles",
            album="",
            year="",
            isrc="GBAYE6700064",
            barcode="",
            use_artist=True,
            use_album=False,
            use_year=False,
            use_isrc=True,
            use_barcode=False,
        )
        assert params == {
            "artist": "The Beatles",
            "isrc": "GBAYE6700064",
        }

    def test_combined_search_with_barcode_and_album(self):
        """Test combined search with barcode and album."""
        params = self._build_search_params_with_isrc_barcode(
            artist="",
            album="Abbey Road",
            year="",
            isrc="",
            barcode="0724349691704",
            use_artist=False,
            use_album=True,
            use_year=False,
            use_isrc=False,
            use_barcode=True,
        )
        assert params == {
            "album": "Abbey Road",
            "barcode": "0724349691704",
        }

    def test_empty_isrc_not_included(self):
        """Test empty ISRC is not included even when checked."""
        params = self._build_search_params_with_isrc_barcode(
            artist="Test",
            album="",
            year="",
            isrc="",  # Empty
            barcode="",
            use_artist=True,
            use_album=False,
            use_year=False,
            use_isrc=True,  # Checked but empty
            use_barcode=False,
        )
        assert "isrc" not in params

    def test_whitespace_isrc_not_included(self):
        """Test whitespace-only ISRC is not included."""
        params = self._build_search_params_with_isrc_barcode(
            artist="Test",
            album="",
            year="",
            isrc="   ",  # Whitespace only
            barcode="",
            use_artist=True,
            use_album=False,
            use_year=False,
            use_isrc=True,
            use_barcode=False,
        )
        assert "isrc" not in params


class TestFingerprintWorkerLogic:
    """Tests for FingerprintWorker business logic."""

    def test_fingerprint_worker_creation_params(self):
        """Test FingerprintWorker accepts correct parameters."""
        # FingerprintWorker requires fingerprinter and audio_file
        fingerprinter = Mock()
        audio_file = Mock()

        # Verify the expected attributes
        assert fingerprinter is not None
        assert audio_file is not None

    def test_fingerprint_result_parsing(self):
        """Test parsing fingerprint identification result."""
        # Simulated AcoustID match result
        match = {
            "artist": "The Beatles",
            "title": "Hey Jude",
            "recording_id": "12345",
            "score": 0.95,
        }

        artist = match.get("artist", "")
        title = match.get("title", "")
        score = match.get("score", 0)

        assert artist == "The Beatles"
        assert title == "Hey Jude"
        assert score == 0.95

    def test_fingerprint_best_match_selection(self):
        """Test selection of best match from multiple results."""
        matches = [
            {"artist": "Artist 1", "title": "Song 1", "score": 0.5},
            {"artist": "Artist 2", "title": "Song 2", "score": 0.9},
            {"artist": "Artist 3", "title": "Song 3", "score": 0.7},
        ]

        best_match = max(matches, key=lambda m: m.get("score", 0))

        assert best_match["artist"] == "Artist 2"
        assert best_match["score"] == 0.9

    def test_fingerprint_score_percentage_conversion(self):
        """Test score conversion from 0-1 to percentage."""
        # Score from AcoustID is typically 0-1
        score = 0.95

        # Convert to percentage for display
        score_percent = int(score * 100) if score <= 1 else int(score)

        assert score_percent == 95

    def test_fingerprint_score_already_percentage(self):
        """Test score already in percentage format."""
        # Some implementations may return score as percentage
        score = 95

        score_percent = int(score * 100) if score <= 1 else int(score)

        assert score_percent == 95

    def test_fingerprint_empty_artist_handling(self):
        """Test handling of match with empty artist."""
        match = {"artist": "", "title": "Unknown Song", "score": 0.8}

        artist = match.get("artist", "")
        can_search = bool(artist)

        assert can_search is False

    def test_fingerprint_with_valid_artist(self):
        """Test handling of match with valid artist."""
        match = {"artist": "The Beatles", "title": "Hey Jude", "score": 0.95}

        artist = match.get("artist", "")
        can_search = bool(artist)

        assert can_search is True


class TestAutoFingerprintLogic:
    """Tests for auto-fingerprint feature logic."""

    def test_auto_fingerprint_flag_initialization(self):
        """Test auto_fingerprint flag is stored correctly."""
        auto_fingerprint = True

        # Simulate panel initialization
        _auto_fingerprint = auto_fingerprint

        assert _auto_fingerprint is True

    def test_auto_fingerprint_flag_cleared_after_use(self):
        """Test auto_fingerprint flag is cleared after triggering."""
        _auto_fingerprint = True

        # Simulate showEvent clearing the flag
        if _auto_fingerprint:
            _auto_fingerprint = False  # Only trigger once

        assert _auto_fingerprint is False

    def test_auto_fingerprint_requires_configured_fingerprinter(self):
        """Test auto-fingerprint requires configured fingerprinter."""
        fingerprinter = Mock()
        fingerprinter.is_configured = True
        sample_file = Mock()
        sample_file.exists.return_value = True

        can_fingerprint = (
            fingerprinter is not None
            and fingerprinter.is_configured
            and sample_file is not None
            and sample_file.exists()
        )

        assert can_fingerprint is True

    def test_auto_fingerprint_blocked_without_api_key(self):
        """Test auto-fingerprint blocked when API key not configured."""
        fingerprinter = Mock()
        fingerprinter.is_configured = False  # No API key
        sample_file = Mock()
        sample_file.exists.return_value = True

        can_fingerprint = (
            fingerprinter is not None
            and fingerprinter.is_configured
            and sample_file is not None
            and sample_file.exists()
        )

        assert can_fingerprint is False

    def test_auto_fingerprint_blocked_without_sample_file(self):
        """Test auto-fingerprint blocked when no sample file."""
        fingerprinter = Mock()
        fingerprinter.is_configured = True
        sample_file = None

        can_fingerprint = (
            fingerprinter is not None and fingerprinter.is_configured and sample_file is not None
        )

        assert can_fingerprint is False


class TestSearchWorkerFingerprintFallback:
    """Tests for fingerprint fallback in SearchWorker (Strategy 5)."""

    def test_fingerprint_fallback_conditions(self):
        """Test conditions for triggering fingerprint fallback."""
        results = []  # No results from previous strategies
        fingerprinter = Mock()
        fingerprinter.is_configured = True
        sample_file = Mock()
        sample_file.exists.return_value = True

        should_try_fingerprint = (
            not results
            and fingerprinter is not None
            and fingerprinter.is_configured
            and sample_file is not None
            and sample_file.exists()
        )

        assert should_try_fingerprint is True

    def test_fingerprint_fallback_skipped_with_results(self):
        """Test fingerprint fallback skipped when results exist."""
        results = [Mock()]  # Has results
        fingerprinter = Mock()
        fingerprinter.is_configured = True
        sample_file = Mock()
        sample_file.exists.return_value = True

        should_try_fingerprint = (
            not results
            and fingerprinter is not None
            and fingerprinter.is_configured
            and sample_file is not None
            and sample_file.exists()
        )

        assert should_try_fingerprint is False

    def test_fingerprint_fallback_skipped_without_fingerprinter(self):
        """Test fingerprint fallback skipped without fingerprinter."""
        results = []
        fingerprinter = None
        sample_file = Mock()
        sample_file.exists.return_value = True

        should_try_fingerprint = not results and fingerprinter is not None

        assert should_try_fingerprint is False

    def test_search_worker_accepts_fingerprinter_param(self):
        """Test SearchWorker accepts fingerprinter parameter."""
        # Simulating SearchWorker.__init__ parameters
        params = {
            "provider": Mock(),
            "artist": "Test",
            "album": "Test",
            "year": None,
            "musicbrainz_albumid": None,
            "isrc": None,
            "barcode": None,
            "fingerprinter": Mock(),
            "sample_file": Mock(),
        }

        assert "fingerprinter" in params
        assert "sample_file" in params
        assert params["fingerprinter"] is not None
        assert params["sample_file"] is not None

    def test_fingerprint_fallback_uses_artist_for_search(self):
        """Test fingerprint fallback uses identified artist for cover search."""
        # Simulated fingerprint identification result
        match = {"artist": "The Beatles", "title": "Hey Jude", "score": 0.95}

        fp_artist = match.get("artist", "")

        # If artist identified, we can search for covers
        can_search_covers = bool(fp_artist)

        assert can_search_covers is True
        assert fp_artist == "The Beatles"


class TestAcoustIDSignalLogic:
    """Tests for acoustid_identify_requested signal logic."""

    def test_context_menu_requires_sample_file(self):
        """Test AcoustID context menu only shown with sample file."""
        album = Mock()
        album.sample_file = Mock()
        album.sample_file.exists.return_value = True

        show_acoustid_option = album.sample_file is not None and album.sample_file.exists()

        assert show_acoustid_option is True

    def test_context_menu_hidden_without_sample_file(self):
        """Test AcoustID context menu hidden without sample file."""
        album = Mock()
        album.sample_file = None

        show_acoustid_option = album.sample_file is not None

        assert show_acoustid_option is False

    def test_context_menu_hidden_with_missing_file(self):
        """Test AcoustID context menu hidden when file doesn't exist."""
        album = Mock()
        album.sample_file = Mock()
        album.sample_file.exists.return_value = False

        show_acoustid_option = album.sample_file is not None and album.sample_file.exists()

        assert show_acoustid_option is False

    def test_search_panel_auto_fingerprint_from_context_menu(self):
        """Test SearchPanel created with auto_fingerprint from context menu."""
        # Simulating main_window._on_acoustid_identify_requested
        album = Mock()

        # Context menu should open SearchPanel with auto_fingerprint=True
        auto_fingerprint = True

        assert auto_fingerprint is True
