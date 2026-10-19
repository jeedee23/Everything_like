#!/usr/bin/env python3
"""Fast filename search GUI backed by the plocate/locate index."""

from __future__ import annotations

import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import font, messagebox, ttk
from typing import NamedTuple

RESULT_LIMIT = 2000
SEARCH_DELAY_MS = 250
SEARCH_TIMEOUT_SECONDS = 45
COLUMN_LABELS = {
    "name": "Name",
    "path": "Path",
    "size": "Size",
    "modified": "Date Modified",
}
MONO_FONTS = (
    "DejaVu Sans Mono", "Liberation Mono", "Nimbus Mono PS",
    "Noto Mono", "Ubuntu Mono", "Ubuntu Sans Mono",
)
SEARCH_FILTERS = {
    "Everything": None,
    "Docs": r"\.(doc|docx|odt|rtf|txt|md|rst|tex|xls|xlsx|ods|csv|ppt|pptx|odp|epub)$",
    "PDF": r"\.pdf$",
    "Video": r"\.(mp4|mkv|avi|mov|webm|m4v|mpg|mpeg|wmv|flv|ogv|mts)$",
    "Audio": r"\.(mp3|wav|flac|ogg|oga|opus|m4a|aac|wma|aiff|aif|mid|midi)$",
    "System": r"^/(etc|usr|bin|sbin|lib|lib32|lib64|boot|opt|var)(/|$)",
}


class SearchResult(NamedTuple):
    name: str
    parent: str
    size: str
    modified: str
    size_bytes: int
    modified_timestamp: float


def wildcard_regex(query: str) -> str:
    """Translate shell-style wildcards to an unanchored POSIX ERE."""
    parts: list[str] = []
    index = 0
    while index < len(query):
        char = query[index]
        index += 1
        if char == "*":
            parts.append(".*")
        elif char == "?":
            parts.append(".")
        elif char == "[":
            start = index
            if index < len(query) and query[index] == "!":
                index += 1
            if index < len(query) and query[index] == "]":
                index += 1
            end = query.find("]", index)
            if end == -1:
                parts.append(r"\[")
                index = start
                continue
            content = query[start:end]
            if content.startswith("!"):
                content = "^" + content[1:]
            elif content.startswith("^"):
                content = "\\^" + content[1:]
            parts.append(r"\[" if content == "[" else "[" + content + "]")
            index = end + 1
        else:
            parts.append(re.sub(r"([.\\^$+{}|()])", r"\\\1", char))
    pattern = "".join(parts)
    try:
        re.compile(pattern)
    except re.error as exc:
        raise RuntimeError(f"Invalid wildcard pattern: {exc}") from exc
    return pattern


def format_size(size: int | None) -> str:
    if size is None:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def search_index(query: str, category: str = "Everything") -> list[str]:
    locate = shutil.which("locate") or shutil.which("plocate")
    if not locate:
        raise RuntimeError("locate is not installed. Install plocate and try again.")

    category_pattern = SEARCH_FILTERS[category]
    patterns = [wildcard_regex(term) for term in query.split()]
    if not patterns:
        return []
    options = ["--regex", "--all"]
    if category_pattern is not None:
        # plocate intersects patterns before applying its result limit.
        patterns.append(category_pattern)
    try:
        result = subprocess.run(
            [locate, "-0", "-i", "-l", str(RESULT_LIMIT), *options, "--", *patterns],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=SEARCH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The indexed search timed out. Try a more specific query.") from exc

    if result.returncode and not (
        result.returncode == 1 and not result.stderr and not result.stdout
    ):
        detail = os.fsdecode(result.stderr).strip()
        raise RuntimeError(detail or f"locate exited with status {result.returncode}.")

    paths = (os.fsdecode(item) for item in result.stdout.split(b"\0"))
    return sorted((path for path in paths if path), key=str.casefold)


def describe_path(path: str) -> SearchResult:
    name = os.path.basename(path.rstrip(os.sep)) or os.sep
    parent = os.path.dirname(path) or os.sep
    try:
        info = os.stat(path)
        size = "" if stat.S_ISDIR(info.st_mode) else format_size(info.st_size)
        modified = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
        size_bytes = -1 if stat.S_ISDIR(info.st_mode) else info.st_size
        modified_timestamp = info.st_mtime
    except OSError:
        size = ""
        modified = ""
        size_bytes = -1
        modified_timestamp = -1
    return SearchResult(name, parent, size, modified, size_bytes, modified_timestamp)


class LocateSearchApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Locate Search")
        self.root.geometry("1120x680")
        self.root.minsize(760, 420)
        self.root.attributes("-zoomed", True)

        self.query = tk.StringVar()
        self.status = tk.StringVar(value="Type to search indexed filenames and paths.")
        self.messages: queue.Queue[tuple[int, list[SearchResult] | None, str]] = (
            queue.Queue()
        )
        self.generation = 0
        self.pending_search: str | None = None
        self.rows: dict[str, SearchResult] = {}
        self.sort_column = tk.StringVar(value="name")
        self.sort_descending = tk.BooleanVar(value=False)
        self.visible_columns = {
            key: tk.BooleanVar(value=key in ("name", "path")) for key in COLUMN_LABELS
        }
        self.category = tk.StringVar(value="Everything")
        self.font_family = tk.StringVar(value=MONO_FONTS[0])
        self.font_size = tk.IntVar(value=12)
        self.row_height = tk.IntVar(value=32)
        self.result_font = font.Font(root=root, family=self.font_family.get(), size=12)
        self.column_drag: tuple[str, int, int] | None = None

        self._build_ui()
        self.query.trace_add("write", self._query_changed)
        self.root.bind("<Control-f>", self._focus_search)
        self.root.bind("<Control-o>", self._open_selected)
        self.root.bind("<Control-Return>", self._show_selected_folder)
        self.root.bind("<Escape>", self._clear_search)
        self.root.bind("<F5>", self._refresh)
        self.root.bind("<Control-Shift-C>", self._copy_path)
        self.root.after(100, self._drain_messages)
        self.search_entry.focus_set()

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "Treeview", background="white", fieldbackground="white",
            foreground="#202020", rowheight=24, borderwidth=0,
        )
        style.configure("Treeview.Heading", background="#f4f4f4", relief="flat", padding=(3, 4))
        style.configure("Search.TEntry", padding=(3, 2))
        self.grid_image = tk.PhotoImage(master=self.root, width=3, height=3)
        self.grid_image.put("#dedede", to=(2, 0, 3, 3))
        self.grid_image.put("#dedede", to=(0, 2, 3, 3))
        style.element_create(
            "LocateGrid.border", "image", self.grid_image,
            border=(0, 0, 1, 1), sticky="nsew",
        )
        style.layout("Treeview.Cell", [
            ("LocateGrid.border", {
                "sticky": "nsew",
                "children": [("Treedata.padding", {
                    "sticky": "nsew",
                    "children": [("Treeitem.text", {"sticky": "nsew"})],
                })],
            }),
        ])

        self._build_menu()

        toolbar = ttk.Frame(self.root, padding=(2, 2, 2, 3))
        toolbar.pack(fill="x")

        self.search_entry = ttk.Entry(
            toolbar, textvariable=self.query, style="Search.TEntry"
        )
        self.search_entry.pack(side="left", fill="x", expand=True)

        table = ttk.Frame(self.root)
        table.pack(fill="both", expand=True, padx=1)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        columns = tuple(COLUMN_LABELS)
        self.results = ttk.Treeview(
            table, columns=columns, displaycolumns=("name", "path"),
            show="headings", selectmode="browse",
        )
        for key, label in COLUMN_LABELS.items():
            self.results.heading(key, text=label, command=lambda key=key: self._sort_by(key))
        self.results.column("name", width=350, minwidth=140, stretch=False)
        self.results.column("path", width=730, minwidth=80, stretch=False)
        self.results.column("size", width=100, minwidth=80, anchor="e", stretch=False)
        self.results.column(
            "modified", width=150, minwidth=130, anchor="center", stretch=False
        )

        vertical = ttk.Scrollbar(table, orient="vertical", command=self.results.yview)
        horizontal = ttk.Scrollbar(
            table, orient="horizontal", command=self.results.xview
        )
        self.results.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        self.results.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.results.bind("<Double-1>", self._open_selected)
        self.results.bind("<Return>", self._open_selected)
        self.results.bind("<Button-3>", self._header_menu)
        self.results.bind("<ButtonPress-1>", self._resize_start)
        self.results.bind("<B1-Motion>", self._resize_drag)
        self.results.bind("<ButtonRelease-1>", self._resize_end)
        self._update_headings()
        self._apply_appearance()

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")
        footer = ttk.Frame(self.root, padding=(3, 2, 3, 2))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status, anchor="w").pack(
            side="left", fill="x", expand=True
        )

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        self.root.configure(menu=menu)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Open", accelerator="Ctrl+O", command=self._open_selected)
        file_menu.add_command(
            label="Open containing folder", accelerator="Ctrl+Enter",
            command=self._show_selected_folder,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Copy full path", accelerator="Ctrl+Shift+C", command=self._copy_path)
        edit_menu.add_command(label="Focus search", accelerator="Ctrl+F", command=self._focus_search)
        edit_menu.add_command(label="Clear search", accelerator="Esc", command=self._clear_search)
        menu.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        self.columns_menu = tk.Menu(view_menu, tearoff=False)
        for key, label in COLUMN_LABELS.items():
            self.columns_menu.add_checkbutton(
                label=label, variable=self.visible_columns[key],
                command=lambda key=key: self._toggle_column(key),
            )
        view_menu.add_cascade(label="Columns", menu=self.columns_menu)
        sort_menu = tk.Menu(view_menu, tearoff=False)
        for key, label in COLUMN_LABELS.items():
            sort_menu.add_radiobutton(
                label=label, variable=self.sort_column, value=key, command=self._apply_sort,
            )
        sort_menu.add_separator()
        sort_menu.add_checkbutton(
            label="Descending", variable=self.sort_descending, command=self._apply_sort,
        )
        view_menu.add_cascade(label="Sort by", menu=sort_menu)
        appearance = tk.Menu(view_menu, tearoff=False)
        families = tk.Menu(appearance, tearoff=False)
        available = set(font.families(self.root))
        for family in MONO_FONTS:
            families.add_radiobutton(
                label=family, variable=self.font_family, value=family,
                state="normal" if family in available else "disabled",
                command=self._apply_appearance,
            )
        appearance.add_cascade(label="Font", menu=families)
        sizes = tk.Menu(appearance, tearoff=False)
        for size in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36):
            sizes.add_radiobutton(
                label=f"{size} pt", variable=self.font_size, value=size,
                command=self._apply_appearance,
            )
        appearance.add_cascade(label="Font size", menu=sizes)
        heights = tk.Menu(appearance, tearoff=False)
        for height in (24, 28, 32, 36, 40, 48, 56, 64, 80):
            heights.add_radiobutton(
                label=f"{height} px", variable=self.row_height, value=height,
                command=self._apply_appearance,
            )
        appearance.add_cascade(label="Row height", menu=heights)
        view_menu.add_cascade(label="Appearance", menu=appearance)
        view_menu.add_separator()
        view_menu.add_command(label="Refresh results", accelerator="F5", command=self._start_search)
        menu.add_cascade(label="View", menu=view_menu)

        search_menu = tk.Menu(menu, tearoff=False)
        for category in SEARCH_FILTERS:
            search_menu.add_radiobutton(
                label=category, variable=self.category, value=category,
                command=self._start_search,
            )
        menu.add_cascade(label="Search", menu=search_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About Locate Search", command=self._about)
        menu.add_cascade(label="Help", menu=help_menu)

    def _about(self) -> None:
        messagebox.showinfo(
            "Locate Search",
            "Fast indexed filename and path search using locate.\n\n"
            "Wildcards: * matches any text, ? matches one character;\n"
            "[abc], [0-9] and [!abc] match character sets/ranges.\n"
            "Separate terms with spaces to require every term (AND).\n"
            "Searches match anywhere in the path, ignoring case.\n\n"
            "Click a column heading to sort; click again to reverse.\n"
            "Choose visible columns in View > Columns or right-click a heading.\n\n"
            "Search filters: Docs excludes PDF; System searches /etc, /usr,\n"
            "/bin, /sbin, /lib*, /boot, /opt and /var.\n"
            "View > Appearance controls font, size and row height.\n"
            "Rows expand automatically if needed to fit the font.\n\n"
            "Refresh reruns the query; it does not rebuild the locate database.\n"
            "New files appear after the periodic index update.",
            parent=self.root,
        )

    def _apply_appearance(self) -> None:
        self.result_font.configure(family=self.font_family.get(), size=self.font_size.get())
        height = max(self.row_height.get(), self.result_font.metrics("linespace") + 8)
        style = ttk.Style(self.root)
        style.configure("Treeview", font=self.result_font, rowheight=height)
        style.configure("Treeview.Heading", font=self.result_font)
        self.search_entry.configure(font=self.result_font)

    def _resize_start(self, event: tk.Event) -> str | None:
        if self.results.identify_region(event.x, event.y) != "separator":
            return None
        column = self.results.identify_column(event.x)
        if column == "#0":
            return None
        self.column_drag = (column, event.x_root, self.results.column(column, "width"))
        return "break"

    def _resize_drag(self, event: tk.Event) -> str | None:
        if self.column_drag is None:
            return None
        column, start, width = self.column_drag
        minimum = self.results.column(column, "minwidth")
        self.results.column(column, width=max(minimum, width + event.x_root - start))
        return "break"

    def _resize_end(self, _event: tk.Event) -> str | None:
        if self.column_drag is None:
            return None
        self.column_drag = None
        return "break"

    def _header_menu(self, event: tk.Event) -> None:
        if self.results.identify_region(event.x, event.y) == "heading":
            try:
                self.columns_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.columns_menu.grab_release()

    def _toggle_column(self, key: str) -> None:
        if not any(value.get() for value in self.visible_columns.values()):
            self.visible_columns[key].set(True)
            self.status.set("At least one result column must remain visible.")
        self.results.configure(
            displaycolumns=tuple(key for key, value in self.visible_columns.items() if value.get())
        )

    def _update_headings(self) -> None:
        for key, label in COLUMN_LABELS.items():
            arrow = ""
            if key == self.sort_column.get():
                arrow = " ▼" if self.sort_descending.get() else " ▲"
            self.results.heading(key, text=label + arrow)

    def _sort_by(self, key: str) -> None:
        if self.sort_column.get() == key:
            self.sort_descending.set(not self.sort_descending.get())
        else:
            self.sort_column.set(key)
            self.sort_descending.set(False)
        self._apply_sort()

    def _apply_sort(self) -> None:
        column = self.sort_column.get()

        def sort_key(item: str) -> tuple[str | int | float, str, str]:
            row = self.rows[item]
            value: str | int | float
            if column == "size":
                value = row.size_bytes
            elif column == "modified":
                value = row.modified_timestamp
            elif column == "path":
                value = row.parent.casefold()
            else:
                value = row.name.casefold()
            return value, row.name.casefold(), row.parent.casefold()

        ordered = sorted(self.rows, key=sort_key, reverse=self.sort_descending.get())
        for position, item in enumerate(ordered):
            self.results.move(item, "", position)
        self._update_headings()

    def _copy_path(self, _event: tk.Event | None = None) -> str:
        path = self._selected_path()
        if path:
            self.root.clipboard_clear()
            self.root.clipboard_append(path)
            self.status.set("Copied full path.")
        return "break"

    def _refresh(self, _event: tk.Event | None = None) -> str:
        self._start_search()
        return "break"

    def _query_changed(self, *_args: object) -> None:
        if self.pending_search is not None:
            self.root.after_cancel(self.pending_search)
        self.pending_search = self.root.after(SEARCH_DELAY_MS, self._start_search)

    def _start_search(self) -> None:
        if self.pending_search is not None:
            self.root.after_cancel(self.pending_search)
        self.pending_search = None
        query = self.query.get().strip()
        category = self.category.get()
        self.generation += 1
        generation = self.generation
        self._clear_rows()
        if not query:
            self.status.set("Type to search indexed filenames and paths.")
            return

        self.status.set(f"Searching for “{query}”…")

        def worker() -> None:
            try:
                paths = search_index(query, category)
                rows = [describe_path(path) for path in paths]
                self.messages.put((generation, rows, ""))
            except RuntimeError as exc:
                self.messages.put((generation, None, str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_messages(self) -> None:
        try:
            while True:
                generation, rows, error = self.messages.get_nowait()
                if generation != self.generation:
                    continue
                if error:
                    self.status.set(error)
                    continue
                assert rows is not None
                self._clear_rows()
                for index, row in enumerate(rows):
                    item = str(index)
                    self.rows[item] = row
                    self.results.insert("", "end", iid=item, values=row[:4])
                self._apply_sort()
                suffix = (
                    f" (showing first {RESULT_LIMIT})"
                    if len(rows) == RESULT_LIMIT
                    else ""
                )
                self.status.set(
                    f"{len(rows):,} object{'s' if len(rows) != 1 else ''}{suffix}"
                    f"  •  {self.category.get()}"
                )
        except queue.Empty:
            pass
        self.root.after(100, self._drain_messages)

    def _clear_rows(self) -> None:
        self.results.delete(*self.results.get_children())
        self.rows.clear()

    def _selected_path(self) -> str | None:
        selection = self.results.selection()
        if not selection:
            return None
        row = self.results.item(selection[0], "values")
        if not row:
            return None
        return os.path.join(row[1], row[0])

    def _launch(self, path: str) -> None:
        try:
            subprocess.Popen(
                ["xdg-open", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            messagebox.showerror("Unable to open", str(exc), parent=self.root)

    def _open_selected(self, _event: tk.Event | None = None) -> str:
        path = self._selected_path()
        if path:
            self._launch(path)
        return "break"

    def _show_selected_folder(self, _event: tk.Event | None = None) -> str:
        path = self._selected_path()
        if path:
            self._launch(os.path.dirname(path) or os.sep)
        return "break"

    def _focus_search(self, _event: tk.Event | None = None) -> str:
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")
        return "break"

    def _clear_search(self, _event: tk.Event | None = None) -> str:
        self.query.set("")
        self.search_entry.focus_set()
        return "break"


def run_self_tests() -> None:
    assert wildcard_regex("bolt") == "bolt"
    assert wildcard_regex("a*[b]?") == "a.*[b]."
    assert format_size(0) == "0 B"
    assert format_size(1024) == "1.0 KB"
    row = describe_path(os.path.abspath(__file__))
    assert row[0] == os.path.basename(__file__)
    assert row[1] == os.path.dirname(os.path.abspath(__file__))
    assert row[2] and row[3]
    print("locate-search self-tests passed")


def main() -> int:
    if "--self-test" in sys.argv:
        run_self_tests()
        return 0
    if not shutil.which("locate") and not shutil.which("plocate"):
        print("locate is not installed. Install plocate and try again.", file=sys.stderr)
        return 1
    root = tk.Tk()
    LocateSearchApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
