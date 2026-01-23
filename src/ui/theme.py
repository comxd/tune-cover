"""
Centralized theme and color definitions for the UI.

This module provides a single source of truth for all colors and styles
used throughout the application. Using these constants ensures consistency
and makes it easier to update the visual appearance globally.

Usage:
    from src.ui.theme import Colors, Styles

    label.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
    button.setStyleSheet(Styles.BUTTON_PRIMARY)
"""


class Colors:
    """
    Centralized color palette for the application.

    Colors are organized by semantic meaning rather than visual appearance,
    making it easier to maintain consistent UI behavior.
    """

    # === Primary / Accent ===
    PRIMARY = "#4a90d9"  # Main accent color (selection, focus, spinners)
    PRIMARY_LIGHT = "#5dade2"  # Lighter variant (links, highlights, drop zones)
    PRIMARY_HOVER = "#1976D2"  # Hover state
    PRIMARY_ACTIVE = "#1565C0"  # Active/pressed state
    PRIMARY_BG_TRANSPARENT = "rgba(74, 144, 217, 0.1)"  # Transparent primary for backgrounds

    # === Status Colors ===
    SUCCESS = "#27ae60"  # Success states, positive indicators
    SUCCESS_DARK = "#1e8449"  # Darker variant for borders
    SUCCESS_MATERIAL = "#4CAF50"  # Material Design green
    SUCCESS_BUTTON = "#2E7D32"  # Success button background

    ERROR = "#e74c3c"  # Error states
    ERROR_LIGHT = "#ff6b6b"  # Lighter error (warnings in text)
    ERROR_MATERIAL = "#f44336"  # Material Design red
    ERROR_DARK = "#8b0000"  # Dark red for danger buttons
    ERROR_HOVER = "#a00000"  # Danger button hover
    ERROR_HOVER_BORDER = "#c00000"  # Danger button hover border

    WARNING = "#e67e22"  # Warning states, attention needed
    WARNING_LIGHT = "#f39c12"  # Lighter warning
    WARNING_DARK = "#d35400"  # Darker variant for borders
    WARNING_MATERIAL = "#ff9800"  # Material Design orange

    # === Neutral / Grayscale ===
    # Backgrounds (darkest to lightest)
    BG_DARKEST = "#1e1e1e"  # Deepest background
    BG_DARK = "#2a2a2a"  # Standard dark background
    BG_MEDIUM_DARK = "#333333"  # Slightly lighter
    BG_MEDIUM = "#3a3a3a"  # Medium background
    BG_LIGHT = "#4a4a4a"  # Lighter background
    BG_HOVER_TRANSPARENT = "rgba(255, 255, 255, 0.03)"  # Subtle hover background

    # Borders
    BORDER_DARK = "#444444"  # Standard border
    BORDER_MEDIUM = "#555555"  # Medium border
    BORDER_LIGHT = "#666666"  # Lighter border, hover states

    # Text
    TEXT_PRIMARY = "#ffffff"  # Primary text (white)
    TEXT_SECONDARY = "#666666"  # Secondary/dimmed text
    TEXT_MUTED = "#888888"  # Muted text (labels, hints)

    # Semantic aliases (reference existing colors to avoid duplication)
    TEXT_DISABLED = TEXT_SECONDARY  # Disabled state uses secondary text color

    # === Semantic / Special Purpose ===
    # Links use primary light color, differentiated by underline on hover
    LINK = PRIMARY_LIGHT
    LINK_HOVER = PRIMARY_LIGHT

    # Badges - use semantic colors where applicable
    BADGE_YELLOW = "#f1c40f"  # Yellow badge
    BADGE_YELLOW_BORDER = "#d4ac0d"  # Yellow badge border
    BADGE_PURPLE = "#9b59b6"  # Purple badge (single track)
    BADGE_PURPLE_BORDER = "#8e44ad"  # Purple badge border
    BADGE_ORANGE = WARNING  # Orange badge (forced group, diff)
    BADGE_ORANGE_BORDER = WARNING_DARK  # Orange badge border
    BADGE_GREEN = SUCCESS  # Green badge (AcoustID)
    BADGE_GREEN_BORDER = SUCCESS_DARK  # Green badge border

    # Drag & Drop - use primary light for consistency
    DROP_ZONE_BG = "rgba(93, 173, 226, 0.15)"  # Drop zone overlay
    DROP_ZONE_BORDER = PRIMARY_LIGHT  # Drop zone border


class Styles:
    """
    Pre-composed stylesheet snippets for common UI patterns.

    Use these for consistency across similar components.
    """

    # === Text Styles ===
    TEXT_MUTED = f"color: {Colors.TEXT_MUTED};"
    TEXT_MUTED_SMALL = f"font-size: 10px; color: {Colors.TEXT_MUTED};"
    TEXT_SECONDARY = f"color: {Colors.TEXT_SECONDARY};"
    TEXT_LINK = f"color: {Colors.LINK};"
    TEXT_LINK_HOVER = f"color: {Colors.LINK}; text-decoration: underline;"
    TEXT_WARNING = f"color: {Colors.WARNING};"
    TEXT_ERROR = f"color: {Colors.ERROR_LIGHT};"
    TEXT_SUCCESS = f"color: {Colors.SUCCESS};"

    # === Empty State ===
    EMPTY_STATE = f"color: {Colors.TEXT_MUTED}; font-size: 14px;"

    # === Panel / Container Styles ===
    PANEL_DARK = f"""
        background-color: {Colors.BG_DARK};
        border: 1px solid {Colors.BORDER_DARK};
    """

    PANEL_DARK_ROUNDED = f"""
        background-color: {Colors.BG_DARK};
        border: 1px solid {Colors.BORDER_DARK};
        border-radius: 4px;
    """

    PANEL_HOVER = f"""
        border: 1px solid {Colors.BORDER_LIGHT};
    """

    # === Card Styles ===
    CARD_SELECTED = f"""
        border: 2px solid {Colors.PRIMARY};
        border-radius: 4px;
        background-color: {Colors.PRIMARY_BG_TRANSPARENT};
    """

    CARD_HOVER = f"""
        border: 1px solid {Colors.BORDER_MEDIUM};
        border-radius: 4px;
        background-color: {Colors.BG_HOVER_TRANSPARENT};
    """

    CARD_DEFAULT = f"""
        border: 1px solid {Colors.BG_MEDIUM_DARK};
        border-radius: 4px;
    """

    # === Button Styles ===
    BUTTON_PRIMARY = f"""
        background-color: {Colors.PRIMARY_HOVER};
        color: {Colors.TEXT_PRIMARY};
    """

    BUTTON_SUCCESS = f"""
        background-color: {Colors.SUCCESS_BUTTON};
        color: {Colors.TEXT_PRIMARY};
    """

    BUTTON_DANGER = f"""
        background-color: {Colors.ERROR_DARK};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.ERROR_HOVER};
    """

    BUTTON_DANGER_HOVER = f"""
        background-color: {Colors.ERROR_HOVER};
        border: 1px solid {Colors.ERROR_HOVER_BORDER};
    """

    BUTTON_DISABLED = f"""
        background-color: {Colors.BG_LIGHT};
        color: {Colors.TEXT_MUTED};
        border: 1px solid {Colors.BORDER_MEDIUM};
    """

    # === Input Styles ===
    INPUT_DARK = f"""
        background-color: {Colors.BG_DARK};
        border: 1px solid {Colors.BORDER_DARK};
    """

    INPUT_FOCUS = f"""
        border-color: {Colors.BORDER_LIGHT};
    """

    # === Drag & Drop ===
    DROP_ZONE_ACTIVE = f"""
        background-color: {Colors.DROP_ZONE_BG};
        border: 2px dashed {Colors.DROP_ZONE_BORDER};
        border-radius: 8px;
    """

    # === Graphics View ===
    GRAPHICS_VIEW_DARK = f"""
        QGraphicsView {{
            background-color: {Colors.BG_DARKEST};
            border: 1px solid {Colors.BORDER_DARK};
        }}
    """

    GRAPHICS_VIEW_SELECTED = f"""
        QGraphicsView {{
            background-color: {Colors.BG_DARKEST};
            border: 3px solid {Colors.SUCCESS};
        }}
    """

    # === Forced Group Indicator ===
    FORCED_GROUP_LABEL = f"color: {Colors.WARNING}; font-weight: bold;"

    COVER_FORCED_GROUP = f"""
        background-color: {Colors.BG_DARK};
        border: 2px solid {Colors.WARNING};
    """

    COVER_FORCED_GROUP_HOVER = f"""
        border: 2px solid {Colors.WARNING_LIGHT};
    """
