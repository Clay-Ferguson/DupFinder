#!/usr/bin/env bash
# Build a Debian package (.deb) of DupFinder.
#
# Usage:  packaging/build-deb.sh          (from anywhere)
# Output: dist/dupfinder_<version>_all.deb   (dist/ at the top of the checkout)
# Then:   sudo apt install --reinstall ./dist/dupfinder_<version>_all.deb
#         (--reinstall, or apt skips a rebuild whose version is already installed)
#
# Built by hand with dpkg-deb rather than with debhelper: DupFinder is pure Python
# with no build step, so all the package has to do is put files in the right
# places and name its dependencies. PyQt6 and PyYAML come from the distribution
# (python3-pyqt6, python3-yaml) rather than being bundled, which keeps the
# package architecture-independent and tiny. windowchrome isn't packaged
# anywhere, so its source is copied in from the sibling checkout.
#
# Installed layout:
#   /usr/bin/dupfinder                              launcher
#   /usr/lib/dupfinder/dupfinder/                     the app
#   /usr/lib/dupfinder/windowchrome/                copy of ../windowchrome
#   /usr/lib/dupfinder/docs/                      USER_GUIDE.md, CONFIG.md    }  found through
#                                                 (and img/, once it exists)  }  help.DOCS_DIR
#   /usr/share/applications/dupfinder.desktop       menu entry
#   /usr/share/icons/hicolor/*/apps/dupfinder.png   themed icon, every size
#
# The program is called "DupFinder" and everything installed is named
# "dupfinder" — the desktop entry, the config directory and the window class all
# use that name, and __main__ calls setDesktopFileName("dupfinder") to tie the
# window to it. Renaming any one of them breaks the icon in the dock.
set -euo pipefail

# Every directory the package creates must be 755 and every file 644 or 755,
# whatever the builder's own umask is (Ubuntu's default 002 would otherwise
# leave /usr, /usr/lib and friends group-writable in the package).
umask 022

# HERE is packaging/, which holds what only the package needs (this script, the
# desktop entry template, the icons); ROOT is the checkout, which holds the app.
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname -- "$HERE")"
WINDOWCHROME="$ROOT/../windowchrome/windowchrome"
DIST="$ROOT/dist"
PACKAGE=dupfinder
ARCH=all

die() {
  echo "Error: $*" >&2
  exit 1
}

command -v dpkg-deb >/dev/null 2>&1 || die "dpkg-deb not found (it is part of dpkg, on every Debian-based system)."

VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$ROOT/pyproject.toml" | head -n 1)"
[ -n "$VERSION" ] || die "could not read the version from pyproject.toml."

[ -f "$WINDOWCHROME/__init__.py" ] || die "windowchrome not found at $WINDOWCHROME.
Clone it beside the DupFinder checkout:  git clone https://github.com/Clay-Ferguson/windowchrome.git ../windowchrome"

# The Maintainer field is whoever builds the package, taken from git unless
# DUPFINDER_MAINTAINER="Name <email>" says otherwise. (git reads the global
# config here even though the checkout need not be a repository.)
if [ -z "${DUPFINDER_MAINTAINER:-}" ]; then
  name="$(git -C "$ROOT" config user.name || true)"
  email="$(git -C "$ROOT" config user.email || true)"
  [ -n "$name" ] && [ -n "$email" ] || die "set git user.name and user.email, or DUPFINDER_MAINTAINER=\"Name <email>\"."
  DUPFINDER_MAINTAINER="$name <$email>"
fi

STAGE="$DIST/${PACKAGE}_${VERSION}_${ARCH}"
DEB="$DIST/${PACKAGE}_${VERSION}_${ARCH}.deb"
LIB="$STAGE/usr/lib/$PACKAGE"
rm -rf "$STAGE" "$DEB"

# -- files -------------------------------------------------------------------

install -d -m 755 \
  "$LIB" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/doc/$PACKAGE" \
  "$STAGE/DEBIAN"

# Copy every file of a directory tree into the stage: files 644, and the
# directories `install -D` creates for them 755 (the umask above). Whole trees
# rather than a glob per directory, so a new subpackage or a new kind of file
# under docs/ ships without anyone having to remember a line here — the old
# per-directory copy would have left it out of a package that installed
# cleanly and failed on first use. __pycache__ is left behind on purpose and
# compiled fresh by postinst.
copy_tree() {
  local src="$1" dest="$2" file
  while IFS= read -r -d '' file; do
    install -D -m 644 "$src/$file" "$dest/$file"
  done < <(cd "$src" && find . -name __pycache__ -prune -o -type f -print0)
}

copy_tree "$ROOT/dupfinder" "$LIB/dupfinder"
copy_tree "$WINDOWCHROME" "$LIB/windowchrome"

# docs/ ships because it is *runtime* content, not just repository
# documentation: Options > User Guide renders USER_GUIDE.md straight from here
# (help.DOCS_DIR resolves docs/ beside the package). Everything in it comes
# along — CONFIG.md because the User Guide links to it and those links work in
# the dialog, and img/ once the guide embeds screenshots.
copy_tree "$ROOT/docs" "$LIB/docs"

install -m 644 "$ROOT/LICENSE.md" "$STAGE/usr/share/doc/$PACKAGE/copyright"

# Icon=dupfinder in the desktop entry is a *theme* name, not a path, so the
# PNGs have to land in the hicolor theme for it to resolve. They are checked in
# at every size rather than converted here, which keeps this script free of
# Pillow and ImageMagick; generate them with packaging/icons/make-icons.py from
# the artwork beside it (which is not installed).
#
# Until that artwork exists there are no PNGs, and the package is built without
# an icon rather than not at all: the menu entry then shows the desktop's
# generic one.
shopt -s nullglob
icons=("$HERE"/icons/hicolor/*/apps/dupfinder.png)
shopt -u nullglob
if [ "${#icons[@]}" -eq 0 ]; then
  echo "Warning: no icons in packaging/icons/hicolor yet — building without one."
  echo "         Add packaging/icons/source.png and run packaging/icons/make-icons.py."
fi
for icon in "${icons[@]}"; do
  size_dir="$(basename "$(dirname "$(dirname "$icon")")")"
  install -d -m 755 "$STAGE/usr/share/icons/hicolor/$size_dir/apps"
  install -m 644 "$icon" "$STAGE/usr/share/icons/hicolor/$size_dir/apps/dupfinder.png"
done

# -I (isolated mode) keeps PYTHONPATH and ~/.local site-packages out, so the app
# always runs against the distribution's python3-pyqt6 and python3-yaml rather
# than a pip-installed copy that happens to be lying around.
cat > "$STAGE/usr/bin/$PACKAGE" <<'EOF'
#!/bin/sh
# DupFinder launcher, installed by the dupfinder package.
exec /usr/bin/python3 -I -c 'import sys; sys.path.insert(0, "/usr/lib/dupfinder"); from dupfinder.__main__ import main; sys.exit(main())' "$@"
EOF
chmod 755 "$STAGE/usr/bin/$PACKAGE"

# The desktop entry, pointed at the installed launcher. No folder argument on
# the Exec= line: launched from the application grid DupFinder opens on the current
# working directory and the folder row is editable anyway. Icon= is already the
# theme name and is rewritten only to keep it pinned to $PACKAGE. The template's
# comment lines are dropped, since they only describe the template.
sed \
  -e '/^#/d' \
  -e "s|^Exec=.*|Exec=$PACKAGE|" \
  -e "s|^Icon=.*|Icon=$PACKAGE|" \
  "$HERE/dupfinder.desktop" > "$STAGE/usr/share/applications/dupfinder.desktop"
chmod 644 "$STAGE/usr/share/applications/dupfinder.desktop"

# -- smoke test ----------------------------------------------------------------

# A file the copy missed installs cleanly and fails on first launch, so the
# staged tree is checked before it is packed, with the launcher's own
# interpreter (/usr/bin/python3, not whichever python3 is first on PATH, which
# in an activated venv or a pyenv/conda/uv shell has no python3-yaml) and its
# flags (-I) plus -B so nothing is written into the stage. Three checks, the
# first two needing nothing but Python, so they run on a build machine with no
# Qt:
#
#   - every import inside the staged packages names a file that was staged;
#   - every relative link and image in the staged docs resolves;
#   - the modules import: all of them where /usr/bin/python3 has PyQt6, and
#     otherwise the Qt-free ones, which is still every module but the widgets.
[ -x /usr/bin/python3 ] || die "/usr/bin/python3 not found; it is needed to check the staged files (apt install python3)."
/usr/bin/python3 -I -B - "$LIB" <<'PY' || die "the staged files failed the smoke test (above); nothing was packaged."
import ast
import importlib
import pathlib
import re
import sys

lib = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(lib))
problems = []


def is_module(path):
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


for package in ("dupfinder", "windowchrome"):
    for source in sorted((lib / package).rglob("*.py")):
        where = source.relative_to(lib)
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level:
                base = source.parent
                for _ in range(node.level - 1):
                    base = base.parent
                if node.module:
                    if not is_module(base.joinpath(*node.module.split("."))):
                        problems.append(f"{where}: from {'.' * node.level}{node.module}")
                elif not (base / "__init__.py").is_file():
                    problems.append(f"{where}: from {'.' * node.level} (no package)")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                for name in names:
                    top = name.split(".")[0]
                    if top in ("dupfinder", "windowchrome") and not is_module(lib.joinpath(*name.split("."))):
                        problems.append(f"{where}: import {name}")

for doc in sorted((lib / "docs").rglob("*.md")):
    text = doc.read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)\s]+)", text):
        if re.match(r"[a-z]+:|#", target):
            continue
        if not (doc.parent / target.split("#")[0]).exists():
            problems.append(f"{doc.relative_to(lib)}: link to {target}")
for name in ("USER_GUIDE.md",):
    if not (lib / "docs" / name).is_file():
        problems.append(f"docs/{name} is missing (help.DOCS_DIR opens it)")

try:
    import PyQt6.QtWidgets  # noqa: F401
    modules = [p.stem for p in (lib / "dupfinder").glob("*.py") if p.stem != "__init__"]
    scope = "every module"
except ImportError:
    modules = "config patterns sizes scanner launch".split()
    scope = "the Qt-free modules (no PyQt6 for this python3)"
for name in sorted(modules):
    try:
        importlib.import_module(f"dupfinder.{name}")
    except Exception as exc:
        problems.append(f"import dupfinder.{name}: {exc!r}")

if problems:
    print("\n".join(problems), file=sys.stderr)
    sys.exit(1)
print(f"Smoke test passed: imports resolve, doc links resolve, {scope} import.")
PY

# -- package metadata --------------------------------------------------------

# Compiled as root at install time, since a user running DupFinder can't write
# __pycache__ under /usr/lib; without it every launch compiles in memory.
# The two cache refreshes are what make the icon and the menu entry appear
# without a logout; both are absent on a bare system and harmless when they are.
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  python3 -m compileall -q /usr/lib/dupfinder >/dev/null 2>&1 || true
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
EOF

# Removes what postinst compiled, so dpkg can remove the directories it
# installed (it only deletes files it knows about). Runs before upgrades too;
# the new version's postinst compiles again.
cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
find /usr/lib/dupfinder -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
EOF

# The icon is gone by now, so the cache has to be rebuilt again or the desktop
# keeps showing it in menus until something else refreshes it.
cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
EOF
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"

INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"

# Nothing beyond Python, Qt and YAML is needed to scan: the duplicate search is
# plain Python. xdg-utils backs the Open default and the folder button
# (xdg-open), and qt6-wayland gives a native window on a Wayland desktop;
# neither is needed to run, so both are recommendations.
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.11), python3-pyqt6, python3-yaml
Recommends: xdg-utils, qt6-wayland
Maintainer: $DUPFINDER_MAINTAINER
Installed-Size: $INSTALLED_SIZE
Homepage: https://github.com/Clay-Ferguson/DupFinder
Description: find duplicate files under a folder
 DupFinder scans every file under a folder and lists the ones whose contents
 are identical, in groups, largest wasted space first. Files are compared by
 size, then by sampled bytes, then by a full SHA-256 hash, so most files are
 never read at all. Open and an Open Folder button hand a file to your
 applications, and a Delete button removes the selected file after asking.
EOF

# -- build -------------------------------------------------------------------

# --root-owner-group: files owned by root without needing fakeroot.
# -Zxz: every dpkg can read xz; Ubuntu's default zstd is not readable by
# older Debian dpkg releases.
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$DEB" >/dev/null
rm -rf "$STAGE"

echo "Built $DEB"
echo ""
echo "Install:  sudo apt install --reinstall $DEB"
echo "Remove:   sudo apt remove $PACKAGE"
