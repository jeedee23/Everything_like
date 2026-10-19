import importlib.util
import os
import re
import time
from pathlib import Path
import tkinter as tk
from tkinter import font, ttk
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "locate_search", Path(__file__).with_name("locate-search.py")
)
assert spec is not None and spec.loader is not None
app_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_module)


class LocateSearchGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = app_module.LocateSearchApp(self.root)
        self.root.update_idletasks()
        self.populate()

    def tearDown(self) -> None:
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()

    def populate(self) -> None:
        self.app._clear_rows()
        for item, row in (
            ("a", app_module.SearchResult("zeta.txt", "/a", "900 B", "2026-01-01 10:00", 900, 300)),
            ("b", app_module.SearchResult("Alpha.txt", "/z", "1.0 KB", "2026-01-01 10:00", 1024, 100)),
            ("c", app_module.SearchResult("beta.txt", "/m", "2.0 MB", "2026-01-01 10:00", 2097152, 200)),
        ):
            self.app.rows[item] = row
            self.app.results.insert("", "end", iid=item, values=row[:4])

    def test_top_menu(self) -> None:
        menu = self.root.nametowidget(self.root.cget("menu"))
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
        self.assertEqual(labels, ["File", "Edit", "View", "Search", "Help"])
        for i in range(5):
            self.assertTrue(menu.entrycget(i, "menu"))

    def test_maximized_start_and_grid_style(self) -> None:
        self.root.deiconify()
        deadline = time.monotonic() + 3
        while not self.root.attributes("-zoomed") and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.02)
        self.assertTrue(self.root.attributes("-zoomed"))
        self.assertEqual(self.app.grid_image.get(2, 1), (222, 222, 222))
        self.assertEqual(self.app.grid_image.get(1, 2), (222, 222, 222))
        self.assertTrue(self.app.grid_image.transparency_get(0, 0))
        layout = ttk.Style(self.root).layout("Treeview.Cell")
        self.assertEqual(layout[0][0], "LocateGrid.border")
        self.assertEqual(layout[0][1]["children"][0][0], "Treedata.padding")

    def test_compact_default_columns_and_optional_details(self) -> None:
        self.assertEqual(self.app.results.cget("displaycolumns"), ("name", "path"))
        self.assertFalse(self.app.visible_columns["size"].get())
        self.assertFalse(self.app.visible_columns["modified"].get())
        self.app.columns_menu.invoke(2)
        self.assertEqual(
            self.app.results.cget("displaycolumns"), ("name", "path", "size")
        )
        self.app.columns_menu.invoke(3)
        self.assertEqual(
            self.app.results.cget("displaycolumns"), ("name", "path", "size", "modified")
        )

    def test_name_sort_toggles_and_keeps_selection(self) -> None:
        self.app.results.selection_set("b")
        self.app._apply_sort()
        self.assertEqual(self.app.results.get_children(), ("b", "c", "a"))
        self.app._sort_by("name")
        self.assertEqual(self.app.results.get_children(), ("a", "c", "b"))
        self.assertEqual(self.app.results.selection(), ("b",))
        self.assertIn("▼", self.app.results.heading("name", "text"))

    def test_size_sort_uses_bytes_not_formatted_text(self) -> None:
        self.app._sort_by("size")
        self.assertEqual(self.app.results.get_children(), ("a", "b", "c"))
        self.app._sort_by("size")
        self.assertEqual(self.app.results.get_children(), ("c", "b", "a"))

    def test_modified_sort_uses_timestamp_not_minute_display(self) -> None:
        self.app._sort_by("modified")
        self.assertEqual(self.app.results.get_children(), ("b", "c", "a"))

    def test_path_sort(self) -> None:
        self.app._sort_by("path")
        self.assertEqual(self.app.results.get_children(), ("a", "c", "b"))

    def test_column_chooser_and_last_column_guard(self) -> None:
        for key in ("size", "modified", "name"):
            self.app.visible_columns[key].set(False)
            self.app._toggle_column(key)
        self.assertEqual(self.app.results.cget("displaycolumns"), ("path",))
        self.app.results.selection_set("a")
        self.assertEqual(self.app._selected_path(), "/a/zeta.txt")
        self.app.visible_columns["path"].set(False)
        self.app._toggle_column("path")
        self.assertTrue(self.app.visible_columns["path"].get())
        self.app.visible_columns["name"].set(True)
        self.app._toggle_column("name")
        self.assertEqual(self.app.results.cget("displaycolumns"), ("name", "path"))

    def test_sort_retained_for_new_results_and_stale_results_ignored(self) -> None:
        self.app._sort_by("size")
        self.app.messages.put((-1, [self.app.rows["a"]], ""))
        self.app.messages.put((0, list(self.app.rows.values()), ""))
        self.app._drain_messages()
        self.assertEqual(self.app.results.get_children(), ("0", "1", "2"))
        self.assertEqual(self.app.sort_column.get(), "size")
        self.app._sort_by("size")
        self.app.messages.put((0, list(self.app.rows.values()), ""))
        self.app._drain_messages()
        self.assertEqual(self.app.results.get_children(), ("2", "1", "0"))

    def test_menu_sort_selection_and_copy_path(self) -> None:
        self.app.sort_column.set("size")
        self.app.sort_descending.set(True)
        self.app._apply_sort()
        self.assertEqual(self.app.results.get_children(), ("c", "b", "a"))
        self.app.results.selection_set("b")
        self.app._copy_path()
        self.assertEqual(self.root.clipboard_get(), "/z/Alpha.txt")
        with patch.object(self.app, "_launch") as launch:
            self.app._open_selected()
            launch.assert_called_once_with("/z/Alpha.txt")

    def test_real_index_results(self) -> None:
        paths = app_module.search_index("bashrc")
        self.assertTrue(paths)
        row = app_module.describe_path("/etc/bash.bashrc")
        self.assertEqual(row.size_bytes, os.stat("/etc/bash.bashrc").st_size)
        self.assertGreater(row.modified_timestamp, 0)

    def test_installed_monospace_fonts_and_font_sizes(self) -> None:
        self.assertEqual(len(app_module.MONO_FONTS), 6)
        for family in app_module.MONO_FONTS:
            self.assertIn(family, font.families(self.root))
            self.app.font_family.set(family)
            self.app.font_size.set(16)
            self.app._apply_appearance()
            self.assertEqual(self.app.result_font.actual("family"), family)
            self.assertTrue(self.app.result_font.metrics("fixed"))
        self.app.font_size.set(36)
        self.app.row_height.set(24)
        self.app._apply_appearance()
        actual = int(ttk.Style(self.root).lookup("Treeview", "rowheight"))
        self.assertGreaterEqual(actual, self.app.result_font.metrics("linespace") + 8)
        self.app.font_size.set(12)
        self.app.row_height.set(80)
        self.app._apply_appearance()
        self.assertEqual(int(ttk.Style(self.root).lookup("Treeview", "rowheight")), 80)

    def test_filter_menu(self) -> None:
        self.assertEqual(self.app.category.get(), "Everything")
        menu = self.root.nametowidget(self.root.cget("menu"))
        search = self.root.nametowidget(menu.entrycget(3, "menu"))
        self.assertEqual(
            [search.entrycget(i, "label") for i in range(search.index("end") + 1)],
            ["Everything", "Docs", "PDF", "Video", "Audio", "System"],
        )
        with patch.object(self.app, "_clear_rows"):
            search.invoke(2)
        self.assertEqual(self.app.category.get(), "PDF")

    def test_category_query_applied_before_limit_and_no_matches(self) -> None:
        with patch.object(app_module.subprocess, "run") as run:
            run.return_value = app_module.subprocess.CompletedProcess([], 1, b"", b"")
            self.assertEqual(app_module.search_index("a+[b].*", "PDF"), [])
            arguments = run.call_args.args[0]
            self.assertIn("--regex", arguments)
            self.assertIn("--all", arguments)
            self.assertEqual(arguments[-2:], [r"a\+[b]\..*", r"\.pdf$"])
            self.assertEqual(arguments[arguments.index("-l") + 1], "2000")
            run.return_value = app_module.subprocess.CompletedProcess(
                [], 1, b"", b"database missing"
            )
            with self.assertRaisesRegex(RuntimeError, "database missing"):
                app_module.search_index("x", "PDF")

    def test_resize_every_column_with_pointer_events(self) -> None:
        self.root.deiconify()
        self.root.geometry("1500x600")
        for key in app_module.COLUMN_LABELS:
            self.app.visible_columns[key].set(True)
            self.app._toggle_column(key)
            self.app.results.column(key, width=160)
        self.root.update()
        tree = self.app.results
        for column in app_module.COLUMN_LABELS:
            widths = {key: tree.column(key, "width") for key in app_module.COLUMN_LABELS}
            boundary = 0
            for key in app_module.COLUMN_LABELS:
                boundary += widths[key]
                if key == column:
                    break
            # A separator's hit area includes its left edge, including the last column.
            x = next(
                x for x in range(boundary - 4, boundary + 5)
                if tree.identify_region(x, 10) == "separator"
                and tree.identify_column(x) == f"#{list(app_module.COLUMN_LABELS).index(column) + 1}"
            )
            tree.event_generate("<ButtonPress-1>", x=x, y=10)
            tree.event_generate("<B1-Motion>", x=x + 40, y=10)
            tree.event_generate("<ButtonRelease-1>", x=x + 40, y=10)
            self.root.update()
            self.assertEqual(tree.column(column, "width"), widths[column] + 40, column)
            for other in app_module.COLUMN_LABELS:
                if other != column:
                    self.assertEqual(tree.column(other, "width"), widths[other], other)

    def test_real_category_searches(self) -> None:
        for category, query in (
            ("Docs", "readme"), ("PDF", "pdf"), ("Video", "video"),
            ("Audio", "audio"), ("System", "bashrc"),
        ):
            with self.subTest(category=category):
                paths = app_module.search_index(query, category)
                self.assertLessEqual(len(paths), app_module.RESULT_LIMIT)
                for path in paths:
                    self.assertIn(query, path.casefold())
                    self.assertRegex(path.casefold(), app_module.SEARCH_FILTERS[category])
                if category == "System":
                    self.assertIn("/etc/bash.bashrc", paths)

    def test_wildcard_translation(self) -> None:
        for query, matches, misses in (
            ("*.pdf", ["file.pdf", "/dir/File.pdf"], ["fileXpdf", "file.doc"]),
            ("report?.txt", ["report1.txt"], ["report.txt", "report12.txt"]),
            ("[abc].txt", ["a.txt", "b.txt"], ["d.txt"]),
            ("file[0-9]", ["file4"], ["filex"]),
            ("file[!0-9]", ["filex"], ["file4"]),
            ("[[]name[]]", ["[name]"], ["name"]),
            ("a+b.txt", ["a+b.txt"], ["ab.txt"]),
            ("unfinished[", ["unfinished["], ["unfinished"]),
        ):
            with self.subTest(query=query):
                pattern = re.compile(app_module.wildcard_regex(query), re.IGNORECASE)
                for text in matches:
                    self.assertIsNotNone(pattern.search(text), text)
                for text in misses:
                    self.assertIsNone(pattern.search(text), text)
        with self.assertRaisesRegex(RuntimeError, "Invalid wildcard"):
            app_module.wildcard_regex("[z-a]")

    def test_real_wildcards_with_and_without_categories(self) -> None:
        for category in ("Everything", "System"):
            for query in ("bash.bashr?", "bash*rc", "[b]ashrc", "[!x]ashrc"):
                with self.subTest(category=category, query=query):
                    paths = app_module.search_index(query, category)
                    self.assertIn("/etc/bash.bashrc", paths)
        for category in ("Everything", "Docs"):
            paths = app_module.search_index("*readme*", category)
            self.assertTrue(paths)
            for path in paths:
                self.assertIn("readme", path.casefold())
        paths = app_module.search_index("*.pdf", "PDF")
        self.assertTrue(paths)
        self.assertTrue(all(path.casefold().endswith(".pdf") for path in paths))

    def test_space_separated_terms_are_intersected_before_limit(self) -> None:
        with patch.object(app_module.subprocess, "run") as run:
            run.return_value = app_module.subprocess.CompletedProcess([], 1, b"", b"")
            self.assertEqual(app_module.search_index(" invoice  2026\t*.pdf ", "PDF"), [])
            args = run.call_args.args[0]
            self.assertEqual(
                args[args.index("--") + 1:],
                ["invoice", "2026", r".*\.pdf", r"\.pdf$"],
            )
            self.assertIn("--all", args)
            run.reset_mock()
            self.assertEqual(app_module.search_index("  \t "), [])
            run.assert_not_called()

    def test_real_space_separated_and_search(self) -> None:
        for category in ("Everything", "System"):
            for query in ("etc bashrc", "bashrc etc", "etc bash*rc", "  etc   bashrc  "):
                with self.subTest(category=category, query=query):
                    paths = app_module.search_index(query, category)
                    self.assertIn("/etc/bash.bashrc", paths)
                    for path in paths:
                        for term in query.split():
                            self.assertRegex(path.casefold(), app_module.wildcard_regex(term))
        self.assertEqual(
            app_module.search_index("etc bashrc unlikely_nomatch_7d9b4f02"), []
        )


if __name__ == "__main__":
    unittest.main()
