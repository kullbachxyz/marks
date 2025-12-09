#!/usr/bin/env python3
import curses
import json
import curses.ascii
import webbrowser
from pathlib import Path
from typing import List, Dict, Tuple


DATA_FILE = Path("bookmarks.json")


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
    with DATA_FILE.open("w", encoding="utf-8") as fh:
        json.dump(bookmarks, fh, indent=2)


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


def ensure_visible(selected: int, offset: int, list_height: int) -> int:
    if selected < offset:
        return selected
    if selected >= offset + list_height:
        return selected - list_height + 1
    return offset


def gather_folders(bookmarks: List[Dict[str, str]]) -> List[str]:
    folders = sorted({bm.get("folder", "General") or "General" for bm in bookmarks})
    return folders or ["General"]


def prompt_input(stdscr, prompt: str, default: str = "") -> str:
    curses.curs_set(1)
    h, w = stdscr.getmaxyx()
    # Clear footer lines to avoid visual noise during input
    for y in (h - 2, h - 1):
        stdscr.move(y, 0)
        stdscr.clrtoeol()

    prompt_text = f"{prompt} "
    stdscr.addnstr(h - 1, 0, prompt_text, w - 1)
    max_len = max(1, w - len(prompt_text) - 1)
    buf = list(default)
    pos = len(buf)

    while True:
        display = "".join(buf)
        stdscr.addnstr(h - 1, len(prompt_text), display[: max_len], max_len)
        # Clear any trailing characters from previous longer inputs
        if len(display) < max_len:
            stdscr.addnstr(h - 1, len(prompt_text) + len(display), " " * (max_len - len(display)), max_len - len(display))
        cursor_col = len(prompt_text) + min(pos, max_len - 1)
        stdscr.move(h - 1, cursor_col)
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
    folder_filter: str,
    search_query: str,
) -> Tuple[int, int]:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    list_height = max(1, h - 3)
    list_width = max(20, int(w * 0.55))
    detail_width = max(0, w - list_width - 2)

    header_parts = ["Bookmarks"]
    if folder_filter:
        header_parts.append(f"[{folder_filter}]")
    if search_query:
        header_parts.append(f"/{search_query}")
    header = " ".join(header_parts)
    stdscr.addnstr(0, 0, header, w - 1)
    stdscr.hline(1, 0, "-", w)

    visible = display_items[offset : offset + list_height]
    for idx, (absolute_idx, bookmark) in enumerate(visible):
        y = 2 + idx
        folder = bookmark.get("folder", "General")
        line = f"{absolute_idx + 1:>3} [{folder}] {bookmark.get('title', '')}"
        attr = highlight_attr if (offset + idx) == selected else curses.A_NORMAL
        stdscr.addnstr(y, 0, line.ljust(list_width - 1), list_width - 1, attr)

    if detail_width > 0:
        for y in range(2, 2 + list_height):
            stdscr.addch(y, list_width, "|")
        if display_items and 0 <= selected < len(display_items):
            _, current = display_items[selected]
            detail_lines = [
                f"Folder: {current.get('folder', '')}",
                f"Title:  {current.get('title', '')}",
                f"URL:    {current.get('url', '')}",
                f"Note:   {current.get('note', '')}",
            ]
            for i, line in enumerate(detail_lines):
                if 2 + i < h - 2:
                    stdscr.addnstr(2 + i, list_width + 2, line, detail_width)

    stdscr.hline(h - 3, 0, "-", w)
    stdscr.addnstr(h - 2, 0, status[: w - 1], w - 1)
    stdscr.addnstr(
        h - 1,
        0,
        "[j/k] Move  [g/G] Top/Bottom  [/] Search  [a] Add  [e] Edit  [m] Move folder  [d] Delete  [f] Folder  [o] Open  [q] Quit",
        w - 1,
    )
    stdscr.refresh()
    return list_height, list_width


def main(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    try:
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
        highlight_attr = curses.color_pair(1)
    except curses.error:
        highlight_attr = curses.A_REVERSE

    bookmarks = load_bookmarks()
    selected = 0
    offset = 0
    status = "Ready"
    folder_filter = ""
    last_folder = folder_filter or "General"
    search_query = ""

    while True:
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
            folder_filter,
            search_query,
        )
        offset = ensure_visible(selected, offset, list_height)

        key = stdscr.getch()
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
                status = "Nothing to open."
                continue
            _, current = display_items[selected]
            url = current.get("url", "")
            if not url:
                status = "Bookmark has no URL."
                continue
            try:
                webbrowser.open(url)
                status = f"Opened {url}"
            except Exception as exc:  # pragma: no cover - defensive
                status = f"Failed to open: {exc}"
        elif key in (ord("a"), ord("A")):
            default_folder = last_folder or folder_filter or "General"
            folder = prompt_folder(stdscr, bookmarks, default_folder)
            title = prompt_input(stdscr, "Title")
            if not title:
                status = "Add canceled (empty title)."
                continue
            url = prompt_input(stdscr, "URL")
            if not url:
                status = "Add canceled (empty URL)."
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
            status = f"Added '{title}'."
        elif key in (ord("e"), ord("E")):
            if not display_items:
                status = "Nothing to edit."
                continue
            original_index, current = display_items[selected]
            folder = current.get("folder", "General")
            title = prompt_input(stdscr, "Edit title", current.get("title", ""))
            if not title:
                status = "Edit canceled (empty title)."
                continue
            url = prompt_input(stdscr, "Edit URL", current.get("url", ""))
            if not url:
                status = "Edit canceled (empty URL)."
                continue
            note = prompt_input(stdscr, "Edit note", current.get("note", ""))
            bookmarks[original_index] = {
                "title": title,
                "url": url,
                "folder": folder,
                "note": note,
            }
            last_folder = folder
            status = f"Updated '{title}'."
        elif key in (ord("m"), ord("M")):
            if not display_items:
                status = "Nothing to move."
                continue
            original_index, current = display_items[selected]
            new_folder = prompt_folder(stdscr, bookmarks, current.get("folder", "General"))
            if not new_folder:
                status = "Move canceled (empty folder)."
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
            status = f"Moved to '{new_folder}'."
        elif key in (ord("d"), ord("D")):
            if not display_items:
                status = "Nothing to delete."
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
                status = f"Deleted '{removed.get('title', '')}'."
            else:
                status = "Delete canceled."
        elif key == ord("/"):
            new_query = prompt_input(stdscr, "Search (blank=clear)", search_query)
            search_query = new_query.strip()
            selected = 0
            offset = 0
            status = "Search cleared." if not search_query else f"Searching for '{search_query}'."
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
                status = "Filter cleared."
            else:
                folder_filter = selection
                status = f"Filtering by '{folder_filter}'."
            selected = 0
            offset = 0
        else:
            status = "Unknown key. Use the hints below."

    save_bookmarks(bookmarks)


if __name__ == "__main__":
    curses.wrapper(main)
