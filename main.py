#!/usr/bin/env python3
import argparse
import curses
import json
import curses.ascii
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from html.parser import HTMLParser


DATA_FILE = Path(
    os.environ.get(
        "MARKS_DATA_FILE",
        Path.home() / ".local" / "share" / "marks" / "bookmarks.json",
    )
)

CONFIG_FILE = Path.home() / ".config" / "marks" / "config"
TERM_COLORS = [
    (1, "Red"),
    (2, "Green"),
    (3, "Yellow"),
    (4, "Blue"),
    (5, "Magenta"),
    (6, "Cyan"),
    (7, "White"),
]

SHORTCUTS_SEGMENTS = [
    ("j/k", True),
    (" Move  ", False),
    ("g/G", True),
    (" Top/Bottom  ", False),
    ("/", True),
    (" Search  ", False),
    ("f", True),
    (" Filter  ", False),
    ("a", True),
    (" Add  ", False),
    ("e", True),
    (" Edit  ", False),
    ("m", True),
    (" Move folder  ", False),
    ("o", True),
    (" Open in browser  ", False),
    ("d", True),
    (" Delete  ", False),
    ("q", True),
    (" Quit", False),
]


def load_bookmarks() -> List[Dict[str, str]]:
    try:
        with DATA_FILE.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
            cleaned = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                url = str(item.get("url", "")).strip()
                folder = str(item.get("folder", "General")).strip() or "General"
                note = str(item.get("note", "")).strip()
                if title or url:
                    cleaned.append(
                        {"title": title, "url": url, "folder": folder, "note": note}
                    )
            return cleaned
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []


def save_bookmarks(bookmarks: List[Dict[str, str]]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as fh:
        json.dump(bookmarks, fh, indent=2)


def load_config() -> Dict[str, int]:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            return data
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_config(config: Dict[str, int]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)


def make_bookmark(title: str, url: str, folder: str = "General", note: str = "") -> Dict[str, str]:
    cleaned_title = (title or "").strip()
    cleaned_url = (url or "").strip()
    if not cleaned_title or not cleaned_url:
        raise ValueError("Title and URL are required.")
    cleaned_folder = (folder or "General").strip() or "General"
    cleaned_note = (note or "").strip()
    return {
        "title": cleaned_title,
        "url": cleaned_url,
        "folder": cleaned_folder,
        "note": cleaned_note,
    }


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


def ensure_visible(selected: int, offset: int, list_height: int) -> int:
    if selected < offset:
        return selected
    if selected >= offset + list_height:
        return selected - list_height + 1
    return offset


def draw_shortcuts(stdscr, y: int, width: int, highlight_attr: int) -> None:
    col = 0
    max_width = max(1, width)
    for text, highlighted in SHORTCUTS_SEGMENTS:
        if col >= max_width:
            break
        chunk = text[: max_width - col]
        attr = highlight_attr if highlighted else curses.A_NORMAL
        stdscr.addnstr(y, col, chunk, max_width - col, attr)
        col += len(chunk)


def draw_segments_line(stdscr, y: int, width: int, segments: List[Tuple[str, bool]], key_attr: int) -> None:
    if not segments:
        return
    cols = max(1, min(5, len(segments)))
    cell_width = max(1, width // cols)
    for idx, (text, highlighted) in enumerate(segments[:cols]):
        start_x = idx * cell_width
        attr = key_attr if highlighted else curses.A_NORMAL
        stdscr.addnstr(y, start_x, text[: cell_width - 1], cell_width - 1, attr)


def command_rows(segments: List[Tuple[str, bool]]) -> List[List[Tuple[str, bool, str]]]:
    commands: List[Tuple[str, bool, str]] = []
    i = 0
    while i < len(segments):
        key, key_hl = segments[i]
        desc = segments[i + 1][0].strip() if i + 1 < len(segments) else ""
        if key or desc:
            commands.append((key.strip(), key_hl, desc))
        i += 2
    while len(commands) < 10:
        commands.append(("", False, ""))
    return [commands[:5], commands[5:10]]


def draw_menu_rows(
    stdscr,
    footer_y: int,
    width: int,
    rows: List[List[Tuple[str, bool, str]]],
    key_attr: int,
) -> None:
    cell_width = max(1, width // 5)
    for idx_row, row in enumerate(rows):
        y = footer_y + 1 + idx_row
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        for idx_col, (key, highlighted, desc) in enumerate(row[:5]):
            start_x = idx_col * cell_width
            rem = cell_width - 1
            col = start_x
            if key:
                chunk = key[: rem]
                attr = key_attr if highlighted else curses.A_NORMAL
                stdscr.addnstr(y, col, chunk, rem, attr)
                col += len(chunk)
                rem -= len(chunk)
            if rem > 0 and desc:
                stdscr.addnstr(y, col, " ", 1)
                col += 1
                rem -= 1
                stdscr.addnstr(y, col, desc[: rem], rem)


def draw_footer(
    stdscr,
    footer_y: int,
    width: int,
    status: str,
    rows: List[List[Tuple[str, bool]]],
    key_attr: int,
) -> None:
    # Clear footer area to avoid leftover margins
    h = stdscr.getmaxyx()[0]
    for y in range(footer_y, h):
        stdscr.move(y, 0)
        stdscr.clrtoeol()
    stdscr.hline(footer_y, 0, curses.ACS_HLINE, width)
    line_offset = 1
    if status:
        stdscr.move(footer_y + line_offset, 0)
        stdscr.clrtoeol()
        stdscr.addnstr(footer_y + line_offset, 0, status[: width - 1], width - 1)
        line_offset += 1
    # Ensure exactly two rows; pad with empties if needed
    normalized_rows = rows[:2] + [[] for _ in range(max(0, 2 - len(rows)))]
    draw_menu_rows(stdscr, footer_y + line_offset - 1, width, normalized_rows, key_attr)


def draw_box(stdscr, top: int, left: int, height: int, width: int, attr: int = curses.A_NORMAL) -> None:
    if height < 2 or width < 2:
        return
    right = left + width - 1
    bottom = top + height - 1
    stdscr.addch(top, left, curses.ACS_ULCORNER, attr)
    stdscr.hline(top, left + 1, curses.ACS_HLINE, width - 2, attr)
    stdscr.addch(top, right, curses.ACS_URCORNER, attr)
    stdscr.addch(bottom, left, curses.ACS_LLCORNER, attr)
    stdscr.hline(bottom, left + 1, curses.ACS_HLINE, width - 2, attr)
    stdscr.addch(bottom, right, curses.ACS_LRCORNER, attr)
    for y in range(top + 1, bottom):
        stdscr.addch(y, left, curses.ACS_VLINE, attr)
        stdscr.addch(y, right, curses.ACS_VLINE, attr)


def gather_folders(bookmarks: List[Dict[str, str]]) -> List[str]:
    folders = sorted({bm.get("folder", "General") or "General" for bm in bookmarks})
    return folders or ["General"]


def prompt_input(
    stdscr,
    prompt: str,
    default: str = "",
    on_change: Optional[Callable[[str], None]] = None,
) -> str:
    curses.curs_set(1)
    h, w = stdscr.getmaxyx()
    label_y = h - 2
    input_y = h - 1
    if input_y < 0:
        curses.curs_set(0)
        return ""
    prompt_label = f"{prompt}:"
    try:
        accent_attr = curses.color_pair(2) | curses.A_BOLD
    except curses.error:
        accent_attr = curses.A_BOLD
    max_len = max(3, w - 1)  # room for overflow markers
    buf = list(default)
    pos = len(buf)
    view_start = 0
    changed = True

    while True:
        if changed and on_change is not None:
            on_change("".join(buf))
        for y in (label_y, input_y):
            stdscr.move(y, 0)
            stdscr.clrtoeol()
        stdscr.addnstr(label_y, 0, prompt_label[: w - 1], w - 1, accent_attr)
        display_width = max_len - 2
        if pos < view_start:
            view_start = pos
        elif pos > view_start + display_width:
            view_start = pos - display_width
        view_start = max(0, min(view_start, max(0, len(buf) - display_width)))

        slice_text = "".join(buf[view_start : view_start + display_width])
        left_marker = "<" if view_start > 0 else " "
        right_marker = ">" if view_start + display_width < len(buf) else " "
        render = f"{left_marker}{slice_text.ljust(display_width)}{right_marker}"
        stdscr.addnstr(input_y, 0, render[: max_len], max_len)

        cursor_col = 1 + min(pos - view_start, display_width)
        cursor_col = min(cursor_col, max_len - 1)
        stdscr.move(input_y, cursor_col)
        stdscr.refresh()

        ch = stdscr.getch()
        changed = False
        if ch in (curses.ascii.LF, curses.ascii.CR, curses.KEY_ENTER):
            break
        if ch in (27,):  # ESC cancels
            buf = []
            changed = True
            break
        if ch in (curses.KEY_LEFT, curses.ascii.STX):
            pos = max(0, pos - 1)
            continue
        if ch in (curses.KEY_RIGHT, curses.ascii.ACK):
            pos = min(len(buf), pos + 1)
            continue
        if ch in (curses.KEY_BACKSPACE, curses.ascii.BS, curses.ascii.DEL, 127):
            if pos > 0:
                buf.pop(pos - 1)
                pos -= 1
                changed = True
            continue
        if curses.ascii.isprint(ch):
            buf.insert(pos, chr(ch))
            pos += 1
            changed = True

    curses.curs_set(0)
    return "".join(buf).strip()


def folder_picker(stdscr, options: List[str], initial_idx: int) -> str:
    if not options:
        return ""
    h, w = stdscr.getmaxyx()
    width = min(w - 2, max(len(f) for f in options) + 4)
    height = min(len(options) + 2, h - 2)
    starty = max(0, h - height - 2)
    startx = 2
    win = curses.newwin(height, width, starty, startx)
    win.keypad(True)

    try:
        highlight_attr = curses.color_pair(1)
    except curses.error:
        highlight_attr = curses.A_REVERSE

    idx = initial_idx

    while True:
        win.erase()
        win.box()
        for i, folder in enumerate(options[: height - 2]):
            attr = highlight_attr if i == idx else curses.A_NORMAL
            win.addnstr(1 + i, 1, folder.ljust(width - 2), width - 2, attr)
        win.refresh()

        ch = win.getch()
        if ch in (curses.KEY_UP, ord("k")):
            idx = (idx - 1) % len(options)
        elif ch in (curses.KEY_DOWN, ord("j")):
            idx = (idx + 1) % len(options)
        elif ch in (curses.ascii.LF, curses.ascii.CR, curses.KEY_ENTER):
            return options[idx]
        elif ch in (27, curses.ascii.ESC, ord("q")):
            return options[initial_idx]


def prompt_folder(stdscr, bookmarks: List[Dict[str, str]], default: str) -> str:
    folders = gather_folders(bookmarks)
    current_default = default or "General"
    options = ["<Add new>"] + folders
    try:
        initial_idx = options.index(current_default)
    except ValueError:
        initial_idx = 0

    choice = folder_picker(stdscr, options, initial_idx)
    if choice == "<Add new>":
        new_val = prompt_input(stdscr, "Folder", "")
        return new_val or current_default
    return choice or current_default


def normalize_search(query: str) -> List[str]:
    if not query:
        return []
    cleaned = query.strip()
    while cleaned.startswith("/"):
        cleaned = cleaned[1:]
    tokens = [t for t in cleaned.split() if t]
    return tokens


def draw_ui(
    stdscr,
    display_items: List[Tuple[int, Dict[str, str]]],
    selected: int,
    offset: int,
    status: str,
    highlight_attr: int,
    shortcut_attr: int,
    detail_title: str,
    detail_lines: List[str],
    folder_filter: str,
    search_query: str,
    shortcuts_visible: bool,
    focus_detail: bool,
    detail_selected: int,
    focus_border_attr: int,
) -> Tuple[int, int]:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    header_height = 3  # boxed header
    rows_for_menu = command_rows(SHORTCUTS_SEGMENTS) if shortcuts_visible else []
    rows_count = len(rows_for_menu)
    status_rows = 1 if status else 0
    footer_rows = 1 + status_rows + rows_count
    footer_rows = max(1, footer_rows)
    body_height = max(3, h - footer_rows - header_height)
    list_height = max(1, body_height - 2)
    list_width = max(20, int(w * 0.55))
    list_width = min(list_width, max(10, w))
    detail_width = max(0, w - list_width)
    footer_y = h - footer_rows
    list_start_y = header_height

    header_parts = ["Bookmarks"]
    if folder_filter:
        header_parts.append(f"[{folder_filter}]")
    if search_query:
        header_parts.append(f"/{search_query}")
    header = " ".join(header_parts)
    # Draw full-width box header
    stdscr.addch(0, 0, curses.ACS_ULCORNER)
    stdscr.hline(0, 1, curses.ACS_HLINE, max(0, w - 2))
    stdscr.addch(0, max(0, w - 1), curses.ACS_URCORNER)
    stdscr.addch(header_height - 1, 0, curses.ACS_LLCORNER)
    stdscr.hline(header_height - 1, 1, curses.ACS_HLINE, max(0, w - 2))
    stdscr.addch(header_height - 1, max(0, w - 1), curses.ACS_LRCORNER)
    for y in range(1, header_height - 1):
        stdscr.addch(y, 0, curses.ACS_VLINE)
        stdscr.addch(y, max(0, w - 1), curses.ACS_VLINE)
    if header:
        text_x = max(2, (w - len(header)) // 2)
        stdscr.addnstr(1, text_x, header[: max(0, w - text_x - 2)], max(0, w - text_x - 2), shortcut_attr)

    # List pane with box
    list_border_attr = focus_border_attr if not focus_detail else curses.A_NORMAL
    draw_box(stdscr, list_start_y, 0, body_height, list_width, list_border_attr)
    visible = display_items[offset : offset + list_height]
    for idx, (absolute_idx, bookmark) in enumerate(visible):
        y = list_start_y + 1 + idx
        folder = bookmark.get("folder", "General")
        line = f"{absolute_idx + 1:>3} [{folder}] {bookmark.get('title', '')}"
        attr = highlight_attr if (offset + idx) == selected else curses.A_NORMAL
        stdscr.addnstr(y, 1, line.ljust(list_width - 2), list_width - 2, attr)

    # Detail pane with box
    if detail_width >= 6:
        detail_border_attr = focus_border_attr if focus_detail else curses.A_NORMAL
        draw_box(stdscr, list_start_y, list_width, body_height, detail_width, detail_border_attr)
        if detail_lines:
            for i, line in enumerate(detail_lines[: body_height - 2]):
                attr = highlight_attr if focus_detail and i == detail_selected else curses.A_NORMAL
                stdscr.addnstr(list_start_y + 1 + i, list_width + 1, line.ljust(detail_width - 2), detail_width - 2, attr)

    if shortcuts_visible:
        draw_footer(stdscr, footer_y, w, status, rows_for_menu, shortcut_attr)
    else:
        stdscr.hline(footer_y, 0, curses.ACS_HLINE, w)
        for y in range(footer_y + 1, h):
            stdscr.move(y, 0)
            stdscr.clrtoeol()
    stdscr.refresh()
    return list_height, list_width


def draw_settings_screen(
    stdscr,
    colors: List[Tuple[int, str]],
    selected_idx: int,
    accent_fg: int,
    status: str,
    highlight_attr: int,
    shortcut_attr: int,
    view: str,
) -> None:
    h, w = stdscr.getmaxyx()
    footer_rows = 3
    footer_y = h - footer_rows
    segments = [
        ("q", True),
        (" Quit  ", False),
        ("c", True),
        (" Color  ", False),
    ]
    rows = command_rows(segments)

    # Update footer only
    draw_footer(stdscr, footer_y, w, status, rows, shortcut_attr)

    if view != "colors":
        stdscr.refresh()
        return

    # Full-width color picker screen
    stdscr.erase()
    header_height = 3
    footer_rows = 3
    body_height = max(6, h - footer_rows - header_height)
    footer_y_full = h - footer_rows

    # Header
    stdscr.addch(0, 0, curses.ACS_ULCORNER)
    stdscr.hline(0, 1, curses.ACS_HLINE, max(0, w - 2))
    stdscr.addch(0, max(0, w - 1), curses.ACS_URCORNER)
    stdscr.addch(header_height - 1, 0, curses.ACS_LLCORNER)
    stdscr.hline(header_height - 1, 1, curses.ACS_HLINE, max(0, w - 2))
    stdscr.addch(header_height - 1, max(0, w - 1), curses.ACS_LRCORNER)
    for y in range(1, header_height - 1):
        stdscr.addch(y, 0, curses.ACS_VLINE)
        stdscr.addch(y, max(0, w - 1), curses.ACS_VLINE)
    title = "Accent Color"
    text_x = max(2, (w - len(title)) // 2)
    stdscr.addnstr(1, text_x, title[: max(0, w - text_x - 2)], max(0, w - text_x - 2), shortcut_attr)

    # Body single list
    list_start_y = header_height
    draw_box(stdscr, list_start_y, 0, body_height, w, curses.A_NORMAL)
    bar_width = min(24, max(8, w // 6))
    bar_start = max(6, (w - bar_width) // 2)
    marker_x = max(2, bar_start - 6)
    max_rows = max(0, (body_height - 2) // 2)
    for idx, (code, name) in enumerate(colors[: max_rows]):
        y = list_start_y + 1 + idx * 2
        marker = "[X]" if code == accent_fg else "[ ]"
        attr = highlight_attr if idx == selected_idx else curses.A_NORMAL
        stdscr.addnstr(y, marker_x, marker, 3, attr)
        try:
            pair_id = 50 + (code + 1 if code >= 0 else 0)
            curses.init_pair(pair_id, curses.COLOR_BLACK, code if code >= 0 else -1)
            bar_attr = curses.color_pair(pair_id)
        except curses.error:
            bar_attr = curses.A_REVERSE
        bar_draw_width = min(bar_width, max(1, w - bar_start - 2))
        stdscr.addnstr(y, bar_start, " " * bar_draw_width, bar_draw_width, bar_attr)
        name_x = bar_start + bar_draw_width + 2
        stdscr.addnstr(y, name_x, name[: max(0, w - name_x - 2)], max(0, w - name_x - 2), attr)

    # Footer for picker
    picker_segments = [
        ("q", True),
        (" Quit  ", False),
        ("SPC", True),
        (" Select  ", False),
        ("j/k", True),
        (" Move", False),
    ]
    picker_rows = command_rows(picker_segments)
    stdscr.hline(footer_y_full, 0, curses.ACS_HLINE, w)
    stdscr.move(footer_y_full + 1, 0)
    stdscr.clrtoeol()
    stdscr.addnstr(footer_y_full + 1, 0, status[: w - 1], w - 1)
    draw_menu_rows(stdscr, footer_y_full, w - 1, picker_rows, shortcut_attr)
    stdscr.refresh()


def main(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    config = load_config()
    accent_fg = int(config.get("accent_color", 6)) if isinstance(config, dict) else 6
    try:
        curses.init_pair(1, accent_fg, -1)
        highlight_attr = curses.color_pair(1) | curses.A_BOLD
        curses.init_pair(2, accent_fg, -1)
        shortcut_attr = curses.color_pair(2) | curses.A_BOLD
        curses.init_pair(3, accent_fg, -1)
        focus_border_attr = curses.color_pair(3) | curses.A_BOLD
    except curses.error:
        highlight_attr = curses.A_REVERSE
        shortcut_attr = curses.A_BOLD
        focus_border_attr = curses.A_BOLD

    bookmarks = load_bookmarks()
    selected = 0
    offset = 0
    status = ""
    folder_filter = ""
    last_folder = folder_filter or "General"
    search_query = ""
    last_key = None
    message_clear_time = 0.0
    shortcuts_visible = True
    focus = "list"
    detail_selected = 0
    settings_mode = False
    settings_view = "menu"
    settings_selected_idx = 0
    available_colors = [(code, name) for code, name in TERM_COLORS if code < curses.COLORS or code == -1]
    if available_colors:
        try:
            settings_selected_idx = [code for code, _ in available_colors].index(accent_fg)
        except ValueError:
            settings_selected_idx = 0

    def apply_accent(fg_color: int) -> None:
        nonlocal accent_fg, shortcut_attr, focus_border_attr, highlight_attr
        accent_fg = clamp(fg_color, -1, max(0, curses.COLORS - 1))
        try:
            curses.init_pair(1, accent_fg, -1)
            highlight_attr = curses.color_pair(1) | curses.A_BOLD
        except curses.error:
            highlight_attr = curses.A_REVERSE
        curses.init_pair(2, accent_fg, -1)
        shortcut_attr = curses.color_pair(2) | curses.A_BOLD
        curses.init_pair(3, accent_fg, -1)
        focus_border_attr = curses.color_pair(3) | curses.A_BOLD
        config["accent_color"] = accent_fg
        save_config(config)

    def set_status(message: str, duration: float = 0.0) -> None:
        return

    def build_display_items(query: str) -> List[Tuple[int, Dict[str, str]]]:
        items = [
            (idx, bm)
            for idx, bm in enumerate(bookmarks)
            if (not folder_filter)
            or bm.get("folder", "General").lower() == folder_filter.lower()
        ]
        tokens = normalize_search(query)
        if tokens:
            items = [
                item
                for item in items
                if all(
                    token
                    in " ".join(
                        [
                            (item[1].get(field, "") or "").lower()
                            for field in ("title", "url", "folder", "note")
                        ]
                    )
                    for token in tokens
                )
            ]
        return items

    def render_search_preview(current: str) -> None:
        nonlocal search_query, selected, offset, detail_selected
        search_query = current.strip()
        selected = 0
        offset = 0
        detail_selected = 0
        display_items = build_display_items(search_query)
        total = len(display_items)
        selected = clamp(selected, 0, max(0, total - 1))
        h, w = stdscr.getmaxyx()
        header_height = 3
        footer_rows = 3
        body_height = max(3, h - footer_rows - header_height)
        list_width = min(max(20, int(w * 0.55)), max(10, w))
        detail_width = max(0, w - list_width)
        detail_lines: List[str] = []
        detail_title = ""
        if detail_width >= 6 and display_items and 0 <= selected < len(display_items):
            _, current_item = display_items[selected]
            detail_title = current_item.get("title", "")
            detail_lines = [
                f"Folder: {current_item.get('folder', '')}",
                f"Title:  {current_item.get('title', '')}",
                f"URL:    {current_item.get('url', '')}",
                f"Note:   {current_item.get('note', '')}",
            ]
        draw_ui(
            stdscr,
            display_items,
            selected,
            offset,
            status,
            highlight_attr,
            shortcut_attr,
            detail_title,
            detail_lines,
            folder_filter,
            search_query,
            shortcuts_visible,
            focus == "detail",
            detail_selected,
            focus_border_attr,
        )

    while True:
        if settings_mode:
            draw_settings_screen(
                stdscr,
                available_colors,
                settings_selected_idx,
                accent_fg,
                status,
                highlight_attr,
                shortcut_attr,
                settings_view,
            )
            key = stdscr.getch()
            last_key = None
            if key in (ord("q"), ord("Q")):
                settings_mode = False
                settings_view = "menu"
                continue
            if not available_colors:
                continue
            if settings_view == "menu":
                if key in (ord("c"), ord("C")):
                    settings_view = "colors"
                continue
            if key in (ord("k"), curses.KEY_UP):
                settings_selected_idx = (settings_selected_idx - 1) % len(available_colors)
                continue
            if key in (ord("j"), curses.KEY_DOWN):
                settings_selected_idx = (settings_selected_idx + 1) % len(available_colors)
                continue
            if key in (curses.ascii.LF, curses.ascii.CR, curses.KEY_ENTER, ord(" ")):
                fg_code = available_colors[settings_selected_idx][0]
                apply_accent(fg_code)
                continue
            continue

        display_items = build_display_items(search_query)
        total = len(display_items)
        selected = clamp(selected, 0, max(0, total - 1))
        # Precompute layout to know if detail pane is available
        h, w = stdscr.getmaxyx()
        header_height = 3
        footer_rows = 3
        body_height = max(3, h - footer_rows - header_height)
        list_width = min(max(20, int(w * 0.55)), max(10, w))
        detail_width = max(0, w - list_width)
        detail_lines: List[str] = []
        detail_title = ""
        if detail_width >= 6 and display_items and 0 <= selected < len(display_items):
            _, current = display_items[selected]
            detail_title = current.get("title", "")
            detail_lines = [
                f"Folder: {current.get('folder', '')}",
                f"Title:  {current.get('title', '')}",
                f"URL:    {current.get('url', '')}",
                f"Note:   {current.get('note', '')}",
            ]
        detail_selected = clamp(detail_selected, 0, max(0, len(detail_lines) - 1))
        list_height, _ = draw_ui(
            stdscr,
            display_items,
            selected,
            offset,
            status,
            highlight_attr,
            shortcut_attr,
            detail_title,
            detail_lines,
            folder_filter,
            search_query,
            shortcuts_visible,
            focus == "detail",
            detail_selected,
            focus_border_attr,
        )
        offset = ensure_visible(selected, offset, list_height)

        key = stdscr.getch()
        if key in (9, curses.KEY_BTAB):
            if focus == "list" and detail_width >= 6 and detail_lines:
                focus = "detail"
                detail_selected = clamp(detail_selected, 0, max(0, len(detail_lines) - 1))
            else:
                focus = "list"
            last_key = None
            continue
        if key in (ord("q"), ord("Q")):
            break
        if key in (ord("s"), ord("S")):
            settings_mode = True
            last_key = None
            if available_colors:
                try:
                    settings_selected_idx = [code for code, _ in available_colors].index(accent_fg)
                except ValueError:
                    settings_selected_idx = 0
            continue
        elif key in (ord("k"), curses.KEY_UP):
            if focus == "detail":
                detail_selected -= 1
                detail_selected = clamp(detail_selected, 0, max(0, len(detail_lines) - 1))
            else:
                selected -= 1
        elif key in (ord("j"), curses.KEY_DOWN):
            if focus == "detail":
                detail_selected += 1
                detail_selected = clamp(detail_selected, 0, max(0, len(detail_lines) - 1))
            else:
                selected += 1
        elif key in (ord("g"),):
            selected = 0
        elif key in (ord("G"),):
            selected = max(0, total - 1)
        elif key == curses.KEY_HOME:
            selected = 0
        elif key == curses.KEY_END:
            selected = max(0, total - 1)
        elif key in (ord("o"), ord("O")):
            if not display_items:
                set_status("Nothing to open.")
                continue
            _, current = display_items[selected]
            url = current.get("url", "")
            if not url:
                set_status("Bookmark has no URL.")
                continue
            try:
                webbrowser.open(url)
                set_status(f"Opened {url}")
            except Exception as exc:  # pragma: no cover - defensive
                set_status(f"Failed to open: {exc}")
        elif key in (ord("a"), ord("A")):
            default_folder = last_folder or folder_filter or "General"
            folder = prompt_folder(stdscr, bookmarks, default_folder)
            title = prompt_input(stdscr, "Title")
            if not title:
                set_status("Add canceled (empty title).")
                continue
            url = prompt_input(stdscr, "URL")
            if not url:
                set_status("Add canceled (empty URL).")
                continue
            note = prompt_input(stdscr, "Note (optional)", "")
            bookmarks.append({"title": title, "url": url, "folder": folder, "note": note})
            last_folder = folder
            display_items = [
                (idx, bm)
                for idx, bm in enumerate(bookmarks)
                if (not folder_filter)
                or bm.get("folder", "General").lower() == folder_filter.lower()
            ]
            if display_items:
                selected = len(display_items) - 1
            set_status(f"Added '{title}'.")
        elif key in (ord("e"), ord("E")):
            if not display_items:
                set_status("Nothing to edit.")
                continue
            original_index, current = display_items[selected]
            folder = current.get("folder", "General")
            if focus == "detail" and detail_lines:
                idx = clamp(detail_selected, 0, len(detail_lines) - 1)
                if idx == 0:
                    new_folder = prompt_folder(stdscr, bookmarks, folder)
                    if not new_folder:
                        set_status("Edit canceled (empty folder).")
                        continue
                    bookmarks[original_index]["folder"] = new_folder
                    last_folder = new_folder
                    set_status(f"Folder set to '{new_folder}'.")
                elif idx == 1:
                    title = prompt_input(stdscr, "Edit title", current.get("title", ""))
                    if not title:
                        set_status("Edit canceled (empty title).")
                        continue
                    bookmarks[original_index]["title"] = title
                    set_status(f"Updated title to '{title}'.")
                elif idx == 2:
                    url = prompt_input(stdscr, "Edit URL", current.get("url", ""))
                    if not url:
                        set_status("Edit canceled (empty URL).")
                        continue
                    bookmarks[original_index]["url"] = url
                    set_status("Updated URL.")
                else:
                    note = prompt_input(stdscr, "Edit note", current.get("note", ""))
                    bookmarks[original_index]["note"] = note
                    set_status("Updated note.")
            else:
                title = prompt_input(stdscr, "Edit title", current.get("title", ""))
                if not title:
                    set_status("Edit canceled (empty title).")
                    continue
                url = prompt_input(stdscr, "Edit URL", current.get("url", ""))
                if not url:
                    set_status("Edit canceled (empty URL).")
                    continue
                note = prompt_input(stdscr, "Edit note", current.get("note", ""))
                bookmarks[original_index] = {
                    "title": title,
                    "url": url,
                    "folder": folder,
                    "note": note,
                }
                last_folder = folder
                set_status(f"Updated '{title}'.")
        elif key in (ord("m"), ord("M")):
            if not display_items:
                set_status("Nothing to move.")
                continue
            original_index, current = display_items[selected]
            new_folder = prompt_folder(stdscr, bookmarks, current.get("folder", "General"))
            if not new_folder:
                set_status("Move canceled (empty folder).")
                continue
            bookmarks[original_index]["folder"] = new_folder
            last_folder = new_folder
            display_items = [
                (idx, bm)
                for idx, bm in enumerate(bookmarks)
                if (not folder_filter)
                or bm.get("folder", "General").lower() == folder_filter.lower()
            ]
            if search_query:
                tokens = normalize_search(search_query)
                display_items = [
                    item
                    for item in display_items
                    if all(
                        token
                        in " ".join(
                            [
                                (item[1].get(field, "") or "").lower()
                                for field in ("title", "url", "folder", "note")
                            ]
                        )
                        for token in tokens
                        )
                ]
            selected = clamp(selected, 0, max(0, len(display_items) - 1))
            set_status(f"Moved to '{new_folder}'.")
        elif key in (ord("d"), ord("D")):
            if not display_items:
                status = ""
                continue
            curses.curs_set(0)
            h, w = stdscr.getmaxyx()
            msg1 = "Do you really want to delete this entry?"
            msg2 = "[y/n]"
            stdscr.move(h - 2, 0)
            stdscr.clrtoeol()
            stdscr.addnstr(h - 2, 0, msg1[: w - 1], w - 1)
            stdscr.move(h - 1, 0)
            stdscr.clrtoeol()
            stdscr.addnstr(h - 1, 0, msg2[: w - 1], w - 1)
            stdscr.refresh()
            confirm = None
            while confirm not in (ord("y"), ord("Y"), ord("n"), ord("N")):
                confirm = stdscr.getch()
            if confirm in (ord("y"), ord("Y")):
                original_index, removed = display_items[selected]
                bookmarks.pop(original_index)
                display_items = [
                    (idx, bm)
                    for idx, bm in enumerate(bookmarks)
                    if (not folder_filter)
                    or bm.get("folder", "General").lower() == folder_filter.lower()
                ]
                selected = clamp(selected, 0, max(0, len(display_items) - 1))
            status = ""
        elif key == ord("/"):
            search_query = ""
            selected = 0
            offset = 0
            new_query = prompt_input(
                stdscr,
                "Search",
                "",
                on_change=render_search_preview,
            )
            search_query = new_query.strip()
            selected = 0
            offset = 0
            set_status("Search cleared." if not search_query else f"Searching for '{search_query}'.")
        elif key in (ord("f"), ord("F")):
            folders = gather_folders(bookmarks)
            options = ["<All>"] + folders
            try:
                initial_idx = options.index(folder_filter) if folder_filter else 0
            except ValueError:
                initial_idx = 0
            selection = folder_picker(stdscr, options, initial_idx)
            if selection == "<All>":
                folder_filter = ""
                set_status("Filter cleared.")
            else:
                folder_filter = selection
                set_status(f"Filtering by '{folder_filter}'.")
            selected = 0
            offset = 0
        else:
            pass
        last_key = None

    save_bookmarks(bookmarks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal terminal bookmark manager.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-a",
        "--add",
        action="store_true",
        help="Add a bookmark from CLI flags and exit (no TUI).",
    )
    mode.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List bookmarks to stdout (tab-delimited) and exit (no TUI).",
    )
    mode.add_argument(
        "-r",
        "--rofi",
        action="store_true",
        help="Show bookmarks in rofi -dmenu and open the selection (no TUI).",
    )
    mode.add_argument(
        "--import-html",
        metavar="FILE",
        help="Import bookmarks from a browser-exported bookmarks HTML file and exit (no TUI).",
    )
    parser.add_argument("-n", "--name", help="Bookmark title (required with --add).")
    parser.add_argument("-u", "--url", help="Bookmark URL (required with --add).")
    parser.add_argument(
        "-f",
        "--folder",
        default="General",
        help="Folder name (default: General).",
    )
    parser.add_argument("--note", default="", help="Optional note content.")
    parser.add_argument(
        "--include-note",
        action="store_true",
        help="Include note as a 4th column when using --list.",
    )
    return parser.parse_args()


def handle_cli_add(args: argparse.Namespace) -> int:
    if not args.name or not args.url:
        print("Error: --name and --url are required with --add.", file=sys.stderr)
        return 2

    bookmarks = load_bookmarks()
    try:
        bookmarks.append(make_bookmark(args.name, args.url, args.folder, args.note))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    save_bookmarks(bookmarks)
    added = bookmarks[-1]
    message = f"Added '{added['title']}' to folder '{added['folder']}'."
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "marks", message], check=False)
    else:
        print(message)
    return 0


def handle_cli_list(args: argparse.Namespace) -> int:
    bookmarks = load_bookmarks()

    def clean(value: str) -> str:
        return (value or "").replace("\n", " ").replace("\t", " ").strip()

    for bm in bookmarks:
        folder = clean(bm.get("folder", "General") or "General")
        title = clean(bm.get("title", ""))
        url = clean(bm.get("url", ""))
        line = f"[{folder}] {title} - {url}"
        if args.include_note:
            note = clean(bm.get("note", ""))
            if note:
                line = f"{line} | {note}"
        print(line.strip())
    return 0


def handle_cli_rofi(args: argparse.Namespace) -> int:
    if not shutil.which("rofi"):
        print("Error: rofi not found. Install rofi or use --list with your launcher.", file=sys.stderr)
        return 2

    bookmarks = load_bookmarks()

    def clean(value: str) -> str:
        return (value or "").replace("\n", " ").replace("\t", " ").strip()

    entries = []
    for bm in bookmarks:
        folder = clean(bm.get("folder", "General") or "General")
        title = clean(bm.get("title", ""))
        url = clean(bm.get("url", ""))
        if not url:
            continue
        line = f"[{folder}] {title} - {url}"
        entries.append(line.strip())

    if not entries:
        print("No bookmarks to show.", file=sys.stderr)
        return 1

    proc = subprocess.run(
        ["rofi", "-dmenu", "-p", "", "-i"],
        input="\n".join(entries),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return 1

    choice = proc.stdout.strip()
    if not choice:
        return 1

    if " - " in choice:
        _, url = choice.rsplit(" - ", 1)
    else:
        url = choice
    url = url.strip()
    if not url:
        print("Selected entry missing URL.", file=sys.stderr)
        return 2

    opener = ["xdg-open", url] if shutil.which("xdg-open") else None
    if opener:
        subprocess.run(opener, check=False)
    else:
        webbrowser.open(url)
    return 0


class BookmarkHTMLParser(HTMLParser):
    def __init__(self, standard_folders: set[str]):
        super().__init__()
        self.standard_folders = {name.lower() for name in standard_folders}
        self.folder_stack: List[str] = []
        self.bookmarks: List[Dict[str, str]] = []
        self._capture_data = False
        self._current_link: Dict[str, str] = {}
        self._current_folder: str = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "h3":
            self._capture_data = True
            self._current_folder = ""
        elif tag.lower() == "a":
            href = attrs_dict.get("href", "")
            self._current_link = {"url": href, "title": "", "folder": ""}
            self._capture_data = True

    def handle_endtag(self, tag):
        if tag.lower() == "h3":
            folder_name = self._current_folder.strip()
            self._capture_data = False
            self._current_folder = ""
            if folder_name:
                if folder_name.lower() not in self.standard_folders:
                    self.folder_stack.append(folder_name)
        elif tag.lower() == "dl":
            if self.folder_stack:
                self.folder_stack.pop()
        elif tag.lower() == "a":
            self._capture_data = False
            folder = self.folder_stack[-1] if self.folder_stack else "Import"
            title = self._current_link.get("title", "").strip()
            url = self._current_link.get("url", "").strip()
            if url and title:
                self.bookmarks.append({"title": title, "url": url, "folder": folder, "note": ""})
            self._current_link = {}

    def handle_data(self, data):
        if not self._capture_data:
            return
        if self._current_link:
            self._current_link["title"] = self._current_link.get("title", "") + data
        else:
            self._current_folder += data


def import_bookmarks_html(path: Path) -> List[Dict[str, str]]:
    standard = {
        "bookmarks toolbar",
        "bookmark toolbar",
        "bookmarks bar",
        "bookmarks menu",
        "other bookmarks",
        "other favourites",
    }
    parser = BookmarkHTMLParser(standard)
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return parser.bookmarks


def handle_cli_import(args: argparse.Namespace) -> int:
    source = Path(args.import_html)
    if not source.exists():
        print(f"Error: file not found: {source}", file=sys.stderr)
        return 2

    imported = import_bookmarks_html(source)
    if not imported:
        print("No bookmarks found in the HTML file.", file=sys.stderr)
        return 1

    bookmarks = load_bookmarks()
    bookmarks.extend(imported)
    save_bookmarks(bookmarks)
    message = f"Imported {len(imported)} bookmarks from {source.name}."
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "marks", message], check=False)
    else:
        print(message)
    return 0


if __name__ == "__main__":
    cli_args = parse_args()
    if cli_args.import_html:
        raise SystemExit(handle_cli_import(cli_args))
    if cli_args.rofi:
        raise SystemExit(handle_cli_rofi(cli_args))
    if cli_args.list:
        raise SystemExit(handle_cli_list(cli_args))
    if cli_args.add:
        raise SystemExit(handle_cli_add(cli_args))

    curses.wrapper(main)
