# Everything_like — Locate Search

A lightweight Ubuntu desktop file-search GUI inspired by the compact layout of
Voidtools Everything. This is an independent project, not affiliated with
Voidtools. It searches the local **plocate** index, not file contents.

## Requirements

Tested on Ubuntu 26.04 with Python 3.14, Tk 8.6 and plocate 1.1.23.
Python 3.10 or newer is required. No pip packages are needed.

```sh
sudo apt install python3 python3-tk plocate xdg-utils
sudo updatedb
```

`updatedb` builds the system index. Subsequent refreshes are normally scheduled
by the distribution's `plocate-updatedb.timer`. The GUI's Refresh command only
reruns the current search; it does not rebuild the database.

## Run

```sh
python3 locate-search.py
```

The window opens maximized with native window controls.

## Debian package

Version: **2026.0.10.19**

### Download and install

Open the [latest release](https://github.com/jeedee23/Everything_like/releases/latest)
and download the `.deb` and `SHA256SUMS`. For this version:

- [locate-search_2026.0.10.19_all.deb](https://github.com/jeedee23/Everything_like/releases/download/V2026.0.10.19/locate-search_2026.0.10.19_all.deb)
- [SHA256SUMS](https://github.com/jeedee23/Everything_like/releases/download/V2026.0.10.19/SHA256SUMS)

From the directory containing both downloads:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./locate-search_2026.0.10.19_all.deb
locate-search
```

### Build from source

Build without sudo (Python standard library and `dpkg-deb` only):

```sh
python3 build_deb.py
```

The package is written to `dist/locate-search_2026.0.10.19_all.deb`.
It contains architecture-independent Python code and declares dependencies on
Python 3.10+, Tkinter, plocate, and xdg-utils.

```sh
sudo apt install ./dist/locate-search_2026.0.10.19_all.deb
locate-search
```

The package installs `/usr/bin/locate-search` and an Applications-menu entry.
It does not alter your keyboard shortcuts, desktop icons, index configuration,
or user preferences. For packaged installations, set your custom shortcut
command to `/usr/bin/locate-search`, or run `python3 install.py` from a permanent
checkout to install the per-user launchers and GNOME shortcut. Existing user launchers created by
`install.py` still point to the checkout and override the system menu entry;
they are deliberately not removed automatically.

## Desktop installation

Keep this checkout in its permanent location, then run:

```sh
python3 install.py
```

This creates an Applications-menu entry and a desktop launcher for the current
user. It points to this checkout, so moving the checkout requires rerunning the
installer. On GNOME it also registers **Ctrl+Shift+Alt+F** for the current user.
Rerunning it does not duplicate the shortcut. Other custom shortcuts are preserved;
if another custom command uses that binding or the installer's shortcut path,
installation reports a conflict rather than overwriting it. Locked settings and
gsettings failures are reported explicitly. It does not install packages or require sudo.
On GNOME, right-click the desktop icon and choose **Allow Launching**
if prompted.

On other desktops, automatic shortcut setup is skipped with a message; configure
the printed command using your desktop's shortcut settings. To configure it manually
on GNOME, open **Settings > Keyboard > Custom Shortcuts**,
add **Locate Search**, and use the command printed by the installer. Suggested
binding: **Ctrl+Shift+Alt+F**. Do not overwrite another application's binding.

## Search

- Plain text matches anywhere in the path, ignoring case.
- Spaces separate AND terms: `invoice 2026 *.pdf` requires all three patterns,
  in any order.
- `*` matches any text; `?` matches one character.
- `[abc]`, `[0-9]`, and `[!abc]` match sets, ranges, and negated sets.
- Dots and regex punctuation are literal. Use `[*]`, `[?]`, and `[[]` to find
  literal wildcard characters.
- Search categories: Everything (default), Docs, PDF, Video, Audio, System.
  Docs includes common office/text formats, excluding PDF. System means paths
  rooted in `/etc`, `/usr`, `/bin`, `/sbin`, `/lib`, `/lib32`, `/lib64`, `/boot`,
  `/opt`, or `/var`.

## Interface

- Click a column heading to sort; click again to reverse.
- Resize any column, including the last, by dragging its right separator.
- Use **View > Columns** or right-click a heading to choose visible columns.
- **View > Appearance** controls font, font size, and row height.
- Font choices: DejaVu Sans Mono, Liberation Mono, Nimbus Mono PS, Noto Mono,
  Ubuntu Mono, Ubuntu Sans Mono. Missing fonts are disabled; the app installs
  none. Rows expand when necessary to accommodate the font.
- Subtle grey row/column gridlines separate results.
- **Edit > Preferences > Theme** offers Light (default), Grey and Dark.
  Themes apply to controls, menus, search field, result rows and gridlines.
- Results use a red-to-green relevance gradient: greener means a stronger match.
  Each query term scores higher when it matches the filename rather than only
  a parent path, and higher when it covers more of that filename. Scores are
  averaged across AND terms, ignoring case and honoring the existing wildcards.
  This is a relevance indicator, not a fuzzy search: matching rules are unchanged.
  Selected rows retain a contrasting selection color.
- Enable **Relevance** under **View > Columns** (or Preferences) to see scores as
  percentages. Click its heading to sort best-first, then click again to reverse;
  **View > Sort by > Relevance** is also available. Sorting uses unrounded scores
  within the returned result limit, not the entire index.
- Disable **Color results by relevance** in Preferences for plain themed rows.
  Theme and relevance-color choices are saved across restarts.

| Shortcut | Action |
|---|---|
| Ctrl+F | Focus search |
| Ctrl+O / Enter | Open selected item |
| Ctrl+Enter | Open containing folder |
| Ctrl+Shift+C | Copy selected full path |
| Escape | Clear search |
| F5 | Rerun search |

## Limitations

- The index is periodic, not a real-time filesystem watcher. Only indexed paths
  visible to the current user appear; results can be stale.
- By default at most 2,000 results are shown (configurable in Preferences); sorting applies to these results. All query
  terms and category filters are applied before the limit.
- Blank queries show a typing prompt, not every indexed file.
- **Edit > Preferences** configures font, size, minimum row height, visible columns,
  default sort/order and filter, search-as-you-type, search delay (0–5000 ms),
  and maximum results (1–100000). Enter in the search field or F5 always searches.
  Apply saves and applies settings; OK also closes the dialog. Cancel discards
  unapplied edits. Restore defaults fills the dialog with original defaults;
  choose Apply or OK to save them.
- Preferences are saved atomically in
  `$XDG_CONFIG_HOME/locate-search/preferences.json` (normally
  `~/.config/locate-search/preferences.json`) and loaded on startup. Invalid files
  produce a status/stderr warning and use defaults; save failures are shown in
  the dialog without applying changes. View/Search menus remain session overrides;
  opening Preferences and applying saves the current choices.
- Inspired by [Everything's documented Options](https://www.voidtools.com/support/everything/options/):
  Home defaults, Search timing and Results/View appearance. This is not a full
  implementation of Everything's options; Windows services, NTFS indexing,
  tray/background operation and tabs are not provided.
- Linux/Tk desktop support is required; Windows/macOS are not supported.

## Tests

Run from the checkout in a graphical desktop session:

```sh
python3 -B -W error -m unittest -v test_locate_search test_install test_build_deb
python3 -B locate-search.py --self-test
```

The GUI tests exercise Tk widgets, installed fonts, pointer resizing and actual
plocate results. They expect the six fonts above and a populated system index
with standard Ubuntu files. Maximization tests need a window manager; a bare
headless display is insufficient.

## Publishing

This repository contains only application code, tests, the desktop installer,
and project documentation. It deliberately excludes machine inventories,
personal data, generated indexes, credentials, and local audit reports.
No redistribution license has been selected yet.
