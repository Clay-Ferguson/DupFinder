# DupFinder — User Guide

DupFinder finds files with identical contents. You point it at a folder, press **Find Dups**, and it lists every set of files underneath that folder whose bytes are exactly the same — grouped, with the groups wasting the most space first.

It only reports. Nothing is ever deleted, moved or changed: when you have decided which copies to remove, the **Open** and folder buttons take you to them, and you remove them in your file manager.

This guide covers everything the window does. For the configuration file in detail, see [CONFIG.md](CONFIG.md).

---

## Contents

- [Before you start](#before-you-start)
- [Starting DupFinder](#starting-dupfinder)
- [The window at a glance](#the-window-at-a-glance)
- [Finding duplicates](#finding-duplicates)
- [The results](#the-results)
- [Opening a file or its folder](#opening-a-file-or-its-folder)
- [What counts as a duplicate](#what-counts-as-a-duplicate)
- [How it stays fast](#how-it-stays-fast)
- [The Settings dialog](#the-settings-dialog)
- [Messages you may see](#messages-you-may-see)
- [Troubleshooting](#troubleshooting)
- [Where DupFinder keeps things](#where-dupfinder-keeps-things)

---

## Before you start

DupFinder runs on Linux. Installed from its `.deb` package it needs nothing else: `apt` brings in Python, PyQt6 and PyYAML from your distribution. `xdg-open` (from `xdg-utils`, present on nearly every desktop) is what the Open and folder buttons use by default.

Running from the source folder instead needs [uv](https://docs.astral.sh/uv/) and the `windowchrome` folder beside it; the README explains both.

## Starting DupFinder

From the application menu, or from a terminal:

```
dupfinder                   # start on the current folder
dupfinder ~/Pictures        # start on a particular folder
```

From the source folder, `./start.sh` takes the same optional folder.

The folder only fills in the **Folder** row. Nothing is scanned until you press **Find Dups**.

## The window at a glance

- **Folder** — the folder to scan, always including every folder inside it. Type a path (`~` works) or press **…** to pick one.
- **Find Dups** — starts the scan. While a scan runs, the button reads **Stop**.
- **The results** — one group per set of identical files, filling the window.
- **Open** and the **folder button** — under the results, acting on the selected file.
- **The status bar** — what the scan is doing while it runs (green, with a turning spinner), and a summary once it is done.
- **File ▸ Exit**, **Options ▸ Settings** and **Options ▸ User Guide** in the menu bar.

## Finding duplicates

Press **Find Dups**, or Enter in the Folder row. The status bar shows the scan's progress through its stages:

1. **Scanning** — walking the folder, counting files.
2. **Comparing** — checking the start and end of every file that is the same size as another one.
3. **Hashing** — reading in full whatever still matches, with a percentage.

Press **Stop** to end a scan early. A stopped scan shows no results, because a half-finished comparison could list files as duplicates that are not.

The settings are read once, when the scan starts. Changes saved in **Options ▸ Settings** apply from the next **Find Dups**; the Settings item is unavailable while a scan runs.

## The results

Each group starts with a bold row that says how many copies there are, how big each one is, and how much space would be freed by keeping just one:

```
3 copies · 4.2 MiB each · 8.4 MiB reclaimable
    photos/2019/IMG_0042.jpg      4.2 MiB  2019-06-01 10:12
    backup/phone/IMG_0042.jpg     4.2 MiB  2021-03-14 18:40
    Desktop/keep.jpg              4.2 MiB  2023-11-02 09:05
```

The groups are ordered by reclaimable space, largest first, so the copies most worth cleaning up are at the top. Inside a group, the files are in path order.

The **File** column shows each path relative to the scanned folder; hover over it for the full path. **Modified** is the file's last-modified time, which is usually the quickest way to tell the original from the copy. Click the arrow beside a group to fold it away once you have dealt with it.

When the scan is done the status bar sums it up — for example *37 groups · 112 files · 2.4 GiB reclaimable — 45,678 files scanned in /home/you/Pictures*.

## Opening a file or its folder

Select a file row (not a group row) and:

- **Open** runs the Open command on it. By default that is `xdg-open`, which opens the file in whatever application your desktop uses for that type — the image viewer for a photo, the media player for a song. You can change the command in the [Settings dialog](#the-settings-dialog).
- **The folder button** opens the folder holding the file in your file manager, which is where you would delete, move or rename it.

DupFinder does not delete files itself, on purpose.

## What counts as a duplicate

Two files are duplicates when their contents are byte-for-byte identical. Names, dates and permissions do not matter: `report.pdf` and `report (1).pdf` are duplicates if their bytes match, and two files called `notes.txt` are not if they differ by one character.

A few kinds of file are never listed:

- **Empty files.** Every empty file is "identical" to every other, and none of them wastes space.
- **Files smaller than the minimum size** in Settings (0 MB, so nothing, unless you change it).
- **Hard links.** Two names for the same file on disk share its storage, so they are not copies. Only one of the names is considered.
- **Symbolic links.** A link is not a copy, and DupFinder never follows one — into a file or into a folder.
- **Anything that is not a regular file** — devices, sockets, named pipes.
- **Anything the skip list in Settings excludes**, and, when the include list has patterns in it, every file that does not match one of them.

## How it stays fast

Most files are never read at all.

1. Files are first grouped by **size**. A file whose size no other file shares cannot have a duplicate, and is not opened.
2. Files that do share a size have their **first and last 64 KiB** compared. This rules out nearly everything else — including photos and videos that share long identical headers but differ further in. A file of 128 KiB or less has been read completely at this point and needs nothing more.
3. Only files that still match are **read in full** and compared by their SHA-256 hash.

Reading runs on several threads at once. On a fast SSD a scan of a home folder usually takes seconds; on a spinning hard disk, or over a network share, the hashing stage is limited by how fast the disk can deliver the files.

## The Settings dialog

**Options ▸ Settings** edits the configuration file. Press **Save** to write it, or **Cancel** to leave it as it was.

### Compare only these files (empty = every file)

One glob pattern per line, matched against each file's **name** at any depth — `*.jpg`, `*.mp3`, `IMG_*`. Leave it empty to compare every file. Any pattern at all turns it into a whitelist: files matching none of them are ignored. Patterns cannot contain `/`.

Untick the checkbox to compare every file for a while without losing the patterns.

### Skip these files and folders

One pattern per line, in the same form [Sonar](https://github.com/Clay-Ferguson/sonar) uses:

| Pattern | Skips |
|---|---|
| `*/node_modules/*` | every folder named `node_modules`, at any depth — never entered |
| `*/photos/raw/*` | every folder whose path ends in `photos/raw` — never entered |
| `*/docs/*.tmp` | every path matching it, files and folders alike |
| `*.log` | every file or folder whose name matches, at any depth |

A pattern containing `/` must start with `*/`. The list starts with folders like `.git`, `node_modules` and `.venv`, which are full of files that are identical on purpose and would otherwise bury the duplicates you care about. Untick the checkbox to skip nothing for a while without losing the list.

### Ignore files smaller than (MB)

A size in **megabytes** — just the number, such as `0`, `0.5` or `10`. Fractions are allowed, and 1 MB is 1024 × 1024 bytes, the same unit the results list shows sizes in. `0` compares every file. Raising it (to `0.1`, say) keeps hundreds of tiny identical config and icon files out of the results and makes the scan quicker. Empty files are always ignored.

### The Open command

The program the **Open** button runs. The selected file is added as the last argument, or put wherever `%s` appears: `eog`, `/usr/bin/code`, `gnome-terminal -- vim %s`. It is split the way a shell would split it but run without one, so pipes and redirection do not work. Leave it empty to go back to `xdg-open`.

## Messages you may see

- **The settings need fixing first** — a pattern in the configuration file breaks one of the rules above, or the minimum size is not a size. The message names the line; fix it in Options ▸ Settings.
- **Not a folder** — the Folder row does not name a folder that exists.
- **N files or folders could not be read, and were left out** — DupFinder had no permission to read them, or they disappeared during the scan. The rest of the scan is unaffected.
- **Cannot open … is not on PATH** — the Open command names a program that is not installed.
- **Cannot open — the file no longer exists** — it was moved or deleted after the scan. Run **Find Dups** again to refresh the results.

## Troubleshooting

**The scan is slow.** The hashing stage reads every candidate file in full, so a folder holding many large identical files (videos, disk images, backups) takes as long as reading them does. Raise the minimum size, narrow the folder, or add folders you do not care about to the skip list.

**Files I expected are missing.** Check the skip list and the include list in Settings, and the minimum size. Hard-linked files are deliberately shown only once.

**Thousands of tiny duplicates.** Raise **Ignore files smaller than (MB)**, or add the folders they live in to the skip list.

**The settings dialog says the config file could not be read.** The YAML has a mistake in it. The dialog shows the parser's message; saving from the dialog replaces the whole file with what the dialog shows.

## Where DupFinder keeps things

- **Configuration:** `~/.config/dupfinder/dupfinder-config.yaml`, created with defaults on first run. See [CONFIG.md](CONFIG.md).
- **The installed program:** `/usr/bin/dupfinder` and `/usr/lib/dupfinder/`, from the `.deb`. Removing the package leaves your configuration alone.

DupFinder keeps no database or cache: every scan starts fresh.
