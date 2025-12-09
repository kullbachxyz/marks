# marks

Minimal ncurses-style bookmark manager (keyboard only).

## Run

```
python main.py
```

## Keys

- Up/Down (or j/k): move selection
- g / G: jump to top / bottom (Home/End also work)
- a: add bookmark (folder, title, URL)
- e: edit selected bookmark (title/URL/note)
- m: move selected bookmark to another folder
- d: delete selected bookmark (with confirm)
- f: filter by folder (blank to show all)
- o: open selected bookmark in browser
- /: search (full text: folder/title/url/note)
- q: quit (auto-saves to `bookmarks.json`)
