"""Reusable UI building blocks."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import STATUS_COLORS, Palette


def card(*children: QWidget, spacing: int = 12, margins=(18, 18, 18, 18)) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for child in children:
        layout.addWidget(child)
    return frame


def page_header(title: str, subtitle: str = "") -> QWidget:
    wrap = QWidget()
    v = QVBoxLayout(wrap)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("pageTitle")
    v.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("pageSubtitle")
        s.setWordWrap(True)
        v.addWidget(s)
    return wrap


def label(text: str, object_name: str = "") -> QLabel:
    lbl = QLabel(text)
    if object_name:
        lbl.setObjectName(object_name)
    lbl.setWordWrap(True)
    return lbl


def status_pill(status: str, text: str = "") -> QLabel:
    color = STATUS_COLORS.get(status, Palette.TEXT_MUTED)
    pill = QLabel(text or status.upper())
    pill.setAlignment(Qt.AlignCenter)
    pill.setStyleSheet(
        f"background-color: {color}; color: #0d1117; font-weight: 700;"
        "border-radius: 9px; padding: 2px 10px; font-size: 11px;"
    )
    pill.setMaximumHeight(22)
    return pill


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"color: {Palette.BORDER}; background: {Palette.BORDER};")
    line.setFixedHeight(1)
    return line


def row(*widgets: QWidget, spacing: int = 8) -> QWidget:
    wrap = QWidget()
    h = QHBoxLayout(wrap)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(spacing)
    for w in widgets:
        h.addWidget(w)
    return wrap
