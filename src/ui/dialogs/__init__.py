"""
Dialog windows for the TuneCover UI.
"""

from .acoustid_save_dialog import AcoustIdSaveDialog
from .batch_acoustid_dialog import BatchAcoustIdDialog
from .batch_download_dialog import BatchDownloadDialog
from .cover_comparison import CoverComparisonDialog
from .cover_zoom_dialog import CoverZoomDialog
from .statistics_dialog import StatisticsDialog

__all__ = [
    "AcoustIdSaveDialog",
    "BatchAcoustIdDialog",
    "BatchDownloadDialog",
    "CoverComparisonDialog",
    "CoverZoomDialog",
    "StatisticsDialog",
]
