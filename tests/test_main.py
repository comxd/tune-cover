"""
Tests for main entry point module.
"""

from unittest.mock import MagicMock, patch


class TestCheckCoreDependencies:
    """Tests for check_core_dependencies function."""

    def test_all_dependencies_present(self):
        """Test when all dependencies are installed."""
        from src.main import check_core_dependencies

        # Should not raise or exit
        check_core_dependencies()

    def test_dependency_check_logic(self):
        """Test the dependency check logic."""
        # Test the logic that would be used for missing deps
        missing = []

        # Simulate checking mutagen (present)
        try:
            import mutagen
        except ImportError:
            missing.append("mutagen")

        # Simulate checking requests (present)
        try:
            import requests
        except ImportError:
            missing.append("requests")

        # Both present, so missing should be empty
        assert len(missing) == 0

    def test_dependencies_list(self):
        """Test that expected dependencies are checked."""
        # Core dependencies expected
        import mutagen
        import requests

        # Both should be importable
        assert mutagen is not None
        assert requests is not None


class TestMainFunction:
    """Tests for main function."""

    def test_main_calls_parser(self):
        """Test main calls create_parser."""
        with patch("src.main.check_core_dependencies"):
            with patch("src.cli.commands.create_parser") as mock_create:
                with patch("src.cli.commands.run_cli") as mock_run:
                    with patch("src.utils.logging.setup_logging"):
                        mock_parser = MagicMock()
                        mock_args = MagicMock()
                        mock_args.verbose = False
                        mock_args.log_file = None
                        mock_parser.parse_args.return_value = mock_args
                        mock_create.return_value = mock_parser
                        mock_run.return_value = 0

                        from src.main import main

                        result = main()

                        mock_create.assert_called_once()
                        mock_parser.parse_args.assert_called_once()
                        mock_run.assert_called_once_with(mock_args)

    def test_main_setup_logging_with_verbose(self):
        """Test main sets up logging with verbose flag."""
        with patch("src.main.check_core_dependencies"):
            with patch("src.cli.commands.create_parser") as mock_create:
                with patch("src.cli.commands.run_cli") as mock_run:
                    with patch("src.utils.logging.setup_logging") as mock_logging:
                        mock_parser = MagicMock()
                        mock_args = MagicMock()
                        mock_args.verbose = True
                        mock_args.log_file = "/tmp/test.log"
                        mock_parser.parse_args.return_value = mock_args
                        mock_create.return_value = mock_parser
                        mock_run.return_value = 0

                        from src.main import main

                        main()

                        mock_logging.assert_called_once_with(verbose=True, log_file="/tmp/test.log")

    def test_main_returns_cli_result(self):
        """Test main returns the CLI result code."""
        with patch("src.main.check_core_dependencies"):
            with patch("src.cli.commands.create_parser") as mock_create:
                with patch("src.cli.commands.run_cli") as mock_run:
                    with patch("src.utils.logging.setup_logging"):
                        mock_parser = MagicMock()
                        mock_args = MagicMock()
                        mock_args.verbose = False
                        mock_args.log_file = None
                        mock_parser.parse_args.return_value = mock_args
                        mock_create.return_value = mock_parser
                        mock_run.return_value = 1  # Error code

                        from src.main import main

                        result = main()

                        assert result == 1


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_has_docstring(self):
        """Test module has proper docstring."""
        import src.main

        assert src.main.__doc__ is not None
        assert "TuneCover" in src.main.__doc__

    def test_docstring_includes_usage(self):
        """Test docstring includes usage examples."""
        import src.main

        assert "python -m src.main" in src.main.__doc__
        assert "gui" in src.main.__doc__
        assert "scan" in src.main.__doc__
        assert "fetch" in src.main.__doc__
