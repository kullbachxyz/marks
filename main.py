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
from typing import List, Dict, Tuple
from html.parser import HTMLParser


DATA_FILE = Path(
    os.environ.get(
        "MARKS_DATA_FILE",
        Path.home() / ".local" / "share" / "marks" / "bookmarks.json",
    )
)

SHORTCUTS_SEGMENTS = [
    ("j/k", True),
    (" Move  ", False),
    ("g/G", True),
    (" Top/Bottom  ", False),
    ("/", True),
    (" Search  ", False),
    ("f", True),
    (" Folder  ", False),
    ("a", True),
    (" Add  ", False),
    ("e", True),
    (" Edit  ", False),
    ("m", True),
    (" Move folder  ", False),
    ("o", True),
    (" Open  ", False),
    ("D/dd", True),
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


def draw_box(stdscr, top: int, left: int, height: int, width: int) -> None:
    if height < 2 or width < 2:
        return
    right = left + width - 1
    bottom = top + height - 1
    stdscr.addch(top, left, curses.ACS_ULCORNER)
    stdscr.hline(top, left + 1, curses.ACS_HLINE, width - 2)
    stdscr.addch(top, right, curses.ACS_URCORNER)
    stdscr.addch(bottom, left, curses.ACS_LLCORNER)
    stdscr.hline(bottom, left + 1, curses.ACS_HLINE, width - 2)
    stdscr.addch(bottom, right, curses.ACS_LRCORNER)
    for y in range(top + 1, bottom):
        stdscr.addch(y, left, curses.ACS_VLINE)
        stdscr.addch(y, right, curses.ACS_VLINE)


def gather_folders(bookmarks: List[Dict[str, str]]) -> List[str]:
    folders = sorted({bm.get("folder", "General") or "General" for bm in bookmarks})
    return folders or ["General"]


def prompt_input(stdscr, prompt: str, default: str = "") -> str:
    curses.curs_set(1)
    h, w = stdscr.getmaxyx()
    prompt_y = h - 2  # status line; keep shortcuts visible on last line
    if prompt_y < 0:
        curses.curs_set(0)
        return ""
    stdscr.move(prompt_y, 0)
    stdscr.clrtoeol()

    prompt_text = f"{prompt} "
    stdscr.addnstr(prompt_y, 0, prompt_text, w - 1)
    max_len = max(1, w - len(prompt_text) - 1)
    buf = list(default)
    pos = len(buf)

    while True:
        display = "".join(buf)
        stdscr.addnstr(prompt_y, len(prompt_text), display[: max_len], max_len)
        # Clear any trailing characters from previous longer inputs
        if len(display) < max_len:
            stdscr.addnstr(prompt_y, len(prompt_text) + len(display), " " * (max_len - len(display)), max_len - len(display))
        cursor_col = len(prompt_text) + min(pos, max_len - 1)
        stdscr.move(prompt_y, cursor_col)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (curses.ascii.LF, curses.ascii.CR, curses.KEY_ENTER):
            break
        if ch in (27,):  # ESC cancels
            buf = []
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
            continue
        if curses.ascii.isprint(ch):
            buf.insert(pos, chr(ch))
            pos += 1

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
    folder_filter: str,
    search_query: str,
    shortcuts_visible: bool,
) -> Tuple[int, int]:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    header_height = 3  # boxed header
    footer_rows = 3  # separator + status + shortcuts
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
    draw_box(stdscr, list_start_y, 0, body_height, list_width)
    visible = display_items[offset : offset + list_height]
    for idx, (absolute_idx, bookmark) in enumerate(visible):
        y = list_start_y + 1 + idx
        folder = bookmark.get("folder", "General")
        line = f"{absolute_idx + 1:>3} [{folder}] {bookmark.get('title', '')}"
        attr = highlight_attr if (offset + idx) == selected else curses.A_NORMAL
        stdscr.addnstr(y, 1, line.ljust(list_width - 2), list_width - 2, attr)

    # Detail pane with box
    if detail_width >= 6:
        draw_box(stdscr, list_start_y, list_width, body_height, detail_width)
        if display_items and 0 <= selected < len(display_items):
            _, current = display_items[selected]
            detail_lines = [
                f"Folder: {current.get('folder', '')}",
                f"Title:  {current.get('title', '')}",
                f"URL:    {current.get('url', '')}",
                f"Note:   {current.get('note', '')}",
            ]
            for i, line in enumerate(detail_lines[: body_height - 2]):
                stdscr.addnstr(list_start_y + 1 + i, list_width + 1, line, detail_width - 2)

    stdscr.hline(footer_y, 0, curses.ACS_HLINE, w)
    stdscr.addnstr(footer_y + 1, 0, status[: w - 1], w - 1)
    if shortcuts_visible:
        draw_shortcuts(stdscr, footer_y + 2, w - 1, shortcut_attr)
    else:
        stdscr.move(footer_y + 2, 0)
        stdscr.clrtoeol()
    stdscr.refresh()
    return list_height, list_width


def main(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    try:
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
        highlight_attr = curses.color_pair(1)
        curses.init_pair(2, 6, -1)
        shortcut_attr = curses.color_pair(2) | curses.A_BOLD
    except curses.error:
        highlight_attr = curses.A_REVERSE
        shortcut_attr = curses.A_BOLD

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

    def set_status(message: str, duration: float = 3.0) -> None:
        nonlocal status, message_clear_time, shortcuts_visible
        status = message
        message_clear_time = time.monotonic() + max(0.0, duration)
        shortcuts_visible = True

    while True:
        # Reset double-press tracking unless the previous key was 'd'
        if last_key != ord("d"):
            last_key = None

        now = time.monotonic()
        if message_clear_time and now >= message_clear_time:
            status = ""
            message_clear_time = 0.0

        display_items = [
            (idx, bm)
            for idx, bm in enumerate(bookmarks)
            if (not folder_filter)
            or bm.get("folder", "General").lower() == folder_filter.lower()
        ]
        tokens = normalize_search(search_query)
        if tokens:
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
        total = len(display_items)
        selected = clamp(selected, 0, max(0, total - 1))
        list_height, _ = draw_ui(
            stdscr,
            display_items,
            selected,
            offset,
            status,
            highlight_attr,
            shortcut_attr,
            folder_filter,
            search_query,
            shortcuts_visible,
        )
        offset = ensure_visible(selected, offset, list_height)

        key = stdscr.getch()
        if key == ord("d") and last_key == ord("d"):
            if not display_items:
                set_status("Nothing to delete.")
                last_key = None
                continue
            original_index, removed = display_items[selected]
            bookmarks.pop(original_index)
            display_items = [
                (idx, bm)
                for idx, bm in enumerate(bookmarks)
                if (not folder_filter)
                or bm.get("folder", "General").lower() == folder_filter.lower()
            ]
            selected = clamp(selected, 0, max(0, len(display_items) - 1))
            set_status(f"Deleted '{removed.get('title', '')}'.")
            last_key = None
            continue
        if key in (ord("q"), ord("Q")):
            break
        elif key in (ord("k"), curses.KEY_UP):
            selected -= 1
        elif key in (ord("j"), curses.KEY_DOWN):
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
        elif key in (ord("D"),):
            if not display_items:
                set_status("Nothing to delete.")
                continue
            confirm = prompt_input(stdscr, "Delete this bookmark? (y/N)", "n")
            if confirm.lower().startswith("y"):
                original_index, removed = display_items[selected]
                bookmarks.pop(original_index)
                display_items = [
                    (idx, bm)
                    for idx, bm in enumerate(bookmarks)
                    if (not folder_filter)
                    or bm.get("folder", "General").lower() == folder_filter.lower()
                ]
                selected = clamp(selected, 0, max(0, len(display_items) - 1))
                set_status(f"Deleted '{removed.get('title', '')}'.")
            else:
                set_status("Delete canceled.")
        elif key == ord("/"):
            new_query = prompt_input(stdscr, "Search (blank=clear)", search_query)
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
            set_status("Unknown key. Use the hints below.")
        last_key = key if key == ord("d") else None

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
        ["rofi", "-dmenu", "-p", "Bookmark", "-i"],
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
