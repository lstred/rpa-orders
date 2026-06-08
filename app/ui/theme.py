"""Premium dark theme: color palette + global Qt stylesheet."""
from __future__ import annotations


class Palette:
    BG = "#0d1117"
    BG_ELEV = "#161b22"
    PANEL = "#1a212b"
    PANEL_HOVER = "#222b36"
    BORDER = "#2a3340"
    ACCENT = "#2f81f7"
    ACCENT_HOVER = "#4793ff"
    ACCENT_PRESSED = "#1f6feb"
    TEXT = "#e6edf3"
    TEXT_MUTED = "#8b949e"
    SUCCESS = "#3fb950"
    WARNING = "#d29922"
    DANGER = "#f85149"
    SIDEBAR = "#11161d"


STATUS_COLORS = {
    "ok": Palette.SUCCESS,
    "review": Palette.WARNING,
    "unmatched": Palette.DANGER,
    "missing": Palette.DANGER,
    "skipped": Palette.TEXT_MUTED,
}


def stylesheet() -> str:
    p = Palette
    return f"""
    * {{
        font-family: 'Segoe UI', 'Inter', sans-serif;
        font-size: 13px;
        color: {p.TEXT};
        outline: none;
    }}
    QWidget#root {{ background-color: {p.BG}; }}

    /* ---------- Sidebar ---------- */
    QFrame#sidebar {{
        background-color: {p.SIDEBAR};
        border-right: 1px solid {p.BORDER};
    }}
    QLabel#brand {{
        font-size: 17px;
        font-weight: 700;
        padding: 18px 16px 4px 16px;
        color: {p.TEXT};
    }}
    QLabel#brandSub {{
        font-size: 11px;
        color: {p.TEXT_MUTED};
        padding: 0 16px 14px 16px;
    }}
    QPushButton#navButton {{
        text-align: left;
        padding: 11px 16px;
        margin: 2px 10px;
        border: none;
        border-radius: 8px;
        background: transparent;
        color: {p.TEXT_MUTED};
        font-size: 13px;
    }}
    QPushButton#navButton:hover {{
        background-color: {p.PANEL_HOVER};
        color: {p.TEXT};
    }}
    QPushButton#navButton:checked {{
        background-color: {p.ACCENT};
        color: white;
        font-weight: 600;
    }}

    /* ---------- Cards / panels ---------- */
    QFrame#card {{
        background-color: {p.PANEL};
        border: 1px solid {p.BORDER};
        border-radius: 12px;
    }}
    QLabel#pageTitle {{ font-size: 22px; font-weight: 700; }}
    QLabel#pageSubtitle {{ font-size: 13px; color: {p.TEXT_MUTED}; }}
    QLabel#cardTitle {{ font-size: 15px; font-weight: 600; }}
    QLabel#muted {{ color: {p.TEXT_MUTED}; }}
    QLabel#statBig {{ font-size: 30px; font-weight: 700; }}

    /* ---------- Buttons ---------- */
    QPushButton {{
        background-color: {p.PANEL};
        border: 1px solid {p.BORDER};
        border-radius: 8px;
        padding: 8px 16px;
        color: {p.TEXT};
    }}
    QPushButton:hover {{ background-color: {p.PANEL_HOVER}; }}
    QPushButton#primary {{
        background-color: {p.ACCENT};
        border: none;
        color: white;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background-color: {p.ACCENT_HOVER}; }}
    QPushButton#primary:pressed {{ background-color: {p.ACCENT_PRESSED}; }}
    QPushButton#danger {{ color: {p.DANGER}; border-color: {p.DANGER}; }}
    QPushButton#danger:hover {{ background-color: rgba(248,81,73,0.12); }}
    QPushButton:disabled {{ color: {p.TEXT_MUTED}; background-color: {p.BG_ELEV}; }}

    /* ---------- Inputs ---------- */
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{
        background-color: {p.BG_ELEV};
        border: 1px solid {p.BORDER};
        border-radius: 8px;
        padding: 7px 10px;
        selection-background-color: {p.ACCENT};
    }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {p.ACCENT};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background-color: {p.BG_ELEV};
        border: 1px solid {p.BORDER};
        selection-background-color: {p.ACCENT};
    }}
    QCheckBox {{ spacing: 8px; }}

    /* ---------- Tables ---------- */
    QTableWidget, QTableView {{
        background-color: {p.BG_ELEV};
        border: 1px solid {p.BORDER};
        border-radius: 10px;
        gridline-color: {p.BORDER};
        selection-background-color: rgba(47,129,247,0.25);
    }}
    QHeaderView::section {{
        background-color: {p.PANEL};
        color: {p.TEXT_MUTED};
        padding: 8px;
        border: none;
        border-bottom: 1px solid {p.BORDER};
        font-weight: 600;
    }}
    QTableWidget::item {{ padding: 4px; }}

    /* ---------- Lists ---------- */
    QListWidget {{
        background-color: {p.BG_ELEV};
        border: 1px solid {p.BORDER};
        border-radius: 10px;
        padding: 4px;
    }}
    QListWidget::item {{ padding: 9px 10px; border-radius: 6px; }}
    QListWidget::item:hover {{ background-color: {p.PANEL_HOVER}; }}
    QListWidget::item:selected {{ background-color: {p.ACCENT}; color: white; }}

    /* ---------- Scrollbars ---------- */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {p.BORDER}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p.TEXT_MUTED}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p.BORDER}; border-radius: 5px; }}

    /* ---------- Misc ---------- */
    QTabWidget::pane {{ border: 1px solid {p.BORDER}; border-radius: 10px; }}
    QTabBar::tab {{
        background: transparent; padding: 9px 16px; color: {p.TEXT_MUTED};
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {p.TEXT}; border-bottom: 2px solid {p.ACCENT}; }}
    QProgressBar {{
        border: none; border-radius: 6px; background: {p.BG_ELEV};
        height: 8px; text-align: center;
    }}
    QProgressBar::chunk {{ background-color: {p.ACCENT}; border-radius: 6px; }}
    QToolTip {{
        background-color: {p.PANEL}; color: {p.TEXT};
        border: 1px solid {p.BORDER}; padding: 6px; border-radius: 6px;
    }}
    """
