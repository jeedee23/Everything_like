import importlib.util
import os
import json
import re
import tempfile
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
        self.config = tempfile.TemporaryDirectory()
        self.addCleanup(self.config.cleanup)
        environment = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.config.name})
        environment.start()
        self.addCleanup(environment.stop)
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

    def preferences_widgets(self):
        self.app._preferences()

        def children(widget):
            for child in widget.winfo_children():
                yield child
                yield from children(child)

        return list(children(self.app.preferences_window))

    def test_preferences_menu_and_cancel(self) -> None:
        menu = self.root.nametowidget(self.root.cget("menu"))
        edit = self.root.nametowidget(menu.entrycget(1, "menu"))
        self.assertEqual(edit.entrycget(edit.index("end"), "label"), "Preferences…")
        widgets = self.preferences_widgets()
        window = self.app.preferences_window
        self.app._preferences()
        self.assertIs(self.app.preferences_window, window)
        next(w for w in widgets if isinstance(w, ttk.Entry)).delete(0, "end")
        next(w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == "Cancel").invoke()
        self.assertEqual(self.app.font_size.get(), 12)
        self.assertFalse(app_module.preferences_path().exists())

    def test_preferences_apply_save_reload_and_defaults(self) -> None:
        widgets = self.preferences_widgets()
        entries = [w for w in widgets if type(w) is ttk.Entry]
        for entry, value in zip(entries, ("18", "48", "500", "123")):
            entry.delete(0, "end")
            entry.insert(0, value)
        apply = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == "Apply")
        apply.invoke()
        settings = json.loads(app_module.preferences_path().read_text())
        self.assertEqual(settings["font_size"], 18)
        self.assertEqual(settings["row_height"], 48)
        self.assertEqual(self.app.search_delay_ms, 500)
        self.assertEqual(self.app.result_limit, 123)
        other_root = tk.Tk()
        other_root.withdraw()
        try:
            other = app_module.LocateSearchApp(other_root)
            self.assertEqual(other.font_size.get(), 18)
            self.assertEqual(other.result_limit, 123)
        finally:
            for callback in other_root.tk.call("after", "info"):
                other_root.after_cancel(callback)
            other_root.destroy()
        next(w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == "Restore defaults").invoke()
        apply.invoke()
        self.assertEqual(self.app.font_size.get(), 12)
        self.assertEqual(self.app.result_limit, 2000)

    def test_preferences_invalid_input_does_not_save(self) -> None:
        widgets = self.preferences_widgets()
        entry = next(w for w in widgets if type(w) is ttk.Entry)
        entry.delete(0, "end")
        entry.insert(0, "invalid")
        with patch.object(app_module.messagebox, "showerror") as error:
            next(w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == "Apply").invoke()
        error.assert_called_once()
        self.assertFalse(app_module.preferences_path().exists())
        self.assertEqual(self.app.font_size.get(), 12)

    def test_manual_search_and_delay(self) -> None:
        self.app.search_as_you_type = False
        self.app.query.set("bashrc")
        self.assertIsNone(self.app.pending_search)
        self.assertIn("Enter", self.app.status.get())
        self.app.search_as_you_type = True
        self.app.search_delay_ms = 900
        with patch.object(self.root, "after", return_value="pending") as after:
            self.app._query_changed()
        after.assert_called_once_with(900, self.app._start_search)
        self.app.pending_search = None

    def test_preferences_validation_and_save_failure(self) -> None:
        for values in (
            {"columns": []}, {"result_limit": 0}, {"search_delay_ms": -1},
            {"font_size": True}, {"category": "unknown"}, {"descending": "yes"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                app_module.validate_preferences(values)
        widgets = self.preferences_widgets()
        with (
            patch.object(app_module, "save_preferences", side_effect=OSError("read only")),
            patch.object(app_module.messagebox, "showerror") as error,
        ):
            next(w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == "Apply").invoke()
        error.assert_called_once()
        self.assertIn("read only", error.call_args.args[1])

    def test_configured_limit_reaches_locate(self) -> None:
        with patch.object(app_module.subprocess, "run") as run:
            run.return_value = app_module.subprocess.CompletedProcess([], 1, b"", b"")
            self.assertEqual(app_module.search_index("bashrc", result_limit=123), [])
            arguments = run.call_args.args[0]
            self.assertEqual(arguments[arguments.index("-l") + 1], "123")

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

    def test_themes_apply_to_widgets_and_save(self) -> None:
        for theme in ("Grey", "Dark", "Light"):
            with self.subTest(theme=theme):
                settings = app_module.validate_preferences({"theme": theme})
                self.app._use_preferences(settings)
                palette = app_module.THEMES[theme]
                self.assertEqual(self.root.cget("background"), palette["background"])
                self.assertEqual(ttk.Style(self.root).lookup("Treeview", "fieldbackground"),
                                 palette["field"])
                self.assertEqual(ttk.Style(self.root).lookup("TEntry", "foreground"),
                                 palette["foreground"])
                menu = self.root.nametowidget(self.root.cget("menu"))
                self.assertEqual(str(menu.cget("background")), palette["background"])
                self.assertEqual(
                    str(self.app.results.tag_configure("relevance-10", "background")),
                    app_module.relevance_color(theme, 1),
                )
                app_module.save_preferences(settings)
                self.assertEqual(json.loads(app_module.preferences_path().read_text())["theme"],
                                 theme)
        with self.assertRaises(ValueError):
            app_module.validate_preferences({"theme": "missing"})

    def test_theme_controls_and_relevance_preferences_reload(self) -> None:
        widgets = self.preferences_widgets()
        theme = next(w for w in widgets if isinstance(w, ttk.Combobox)
                     and tuple(w.cget("values")) == tuple(app_module.THEMES))
        theme.set("Dark")
        for widget in widgets:
            if isinstance(widget, ttk.Checkbutton) and widget.cget("text") in (
                "Color results by relevance (red to green)", "Show Relevance",
            ):
                widget.invoke()
        next(w for w in widgets if isinstance(w, ttk.Button)
             and w.cget("text") == "Apply").invoke()
        self.assertEqual(self.app.theme, "Dark")
        self.assertFalse(self.app.relevance_colors)
        self.assertIn("relevance", self.app.results.cget("displaycolumns"))
        saved = json.loads(app_module.preferences_path().read_text())
        self.app._use_preferences(app_module.validate_preferences({}))
        self.app._use_preferences(app_module.validate_preferences(saved))
        self.assertEqual(self.app.theme, "Dark")
        self.assertFalse(self.app.relevance_colors)
        self.assertIn("relevance", self.app.results.cget("displaycolumns"))

    def test_relevance_score_order_and_wildcards(self) -> None:
        score = app_module.match_relevance
        self.assertEqual(score("report", "/tmp/report"), 1)
        self.assertGreater(score("report", "/tmp/report.pdf"),
                           score("report", "/report/other.txt"))
        self.assertGreater(score("report", "/tmp/report.pdf"),
                           score("report", "/tmp/long-report-backup.pdf"))
        self.assertEqual(score("REPORT", "/tmp/report"), 1)
        self.assertEqual(score("", "/tmp/report"), 0)
        self.assertEqual(score("*.pdf", "/tmp/report.pdf"), 1)
        self.assertEqual(score("[r]eport", "/tmp/report"), 1)
        self.assertGreater(score("report 2026", "/tmp/report-2026.txt"),
                           score("report 2026", "/report/2026/other.txt"))

    def test_relevance_colors_and_numeric_column_sort(self) -> None:
        self.app.display_query = "report"
        rows = [app_module.SearchResult(name, parent, "", "", 0, 0)
                for name, parent in (("other.txt", "/report"),
                                     ("report.pdf", "/tmp"),
                                     ("report", "/tmp"))]
        self.app.messages.put((0, rows, ""))
        self.app._drain_messages()
        self.assertEqual(self.app.results.item("2", "values")[-1], "100%")
        self.assertEqual(self.app.results.item("2", "tags"), ("relevance-10",))
        self.assertNotEqual(self.app.results.item("0", "tags"), ("relevance-10",))
        self.app._sort_by("relevance")
        self.assertEqual(self.app.results.get_children(), ("2", "1", "0"))
        self.app._sort_by("relevance")
        self.assertEqual(self.app.results.get_children(), ("0", "1", "2"))
        self.app.visible_columns["relevance"].set(True)
        self.app._toggle_column("relevance")
        self.assertIn("relevance", self.app.results.cget("displaycolumns"))
        self.app.relevance_colors = False
        self.app._apply_theme()
        self.assertFalse(self.app.results.item("2", "tags"))
        self.assertEqual(self.app.results.item("2", "values")[-1], "100%")

    def test_relevance_color_endpoints_and_contrast(self) -> None:
        def luminance(color):
            channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                      for c in channels]
            return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        for theme, palette in app_module.THEMES.items():
            for level in range(11):
                color = app_module.relevance_color(theme, level / 10)
                text = luminance(palette["foreground"])
                background = luminance(color)
                contrast = (max(text, background) + 0.05) / (min(text, background) + 0.05)
                self.assertGreaterEqual(contrast, 4.5, (theme, color))
            red = app_module.relevance_color(theme, 0)
            green = app_module.relevance_color(theme, 1)
            self.assertGreater(int(red[1:3], 16), int(red[3:5], 16))
            self.assertGreater(int(green[3:5], 16), int(green[1:3], 16))

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
