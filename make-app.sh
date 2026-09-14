#!/bin/sh
# Build Haldor.app, the window as a double-clickable app. PyInstaller puts a Python
# and Tk inside the bundle, so the app needs nothing installed. CI runs this script.
# Building it here needs a network and what the Brewfile names: brew bundle.
set -e

here=$(cd "$(dirname "$0")" && pwd)
version=${VERSION:-0.0.0}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# The Brewfile names the Python that carries Tk 9, and its version names the binary,
# so the two cannot drift apart.
pyver=$(sed -n 's/^brew "python-tk@\(.*\)"/\1/p' "$here/Brewfile")
python="$(brew --prefix)/bin/python$pyver"
"$python" -c 'import tkinter' 2>/dev/null ||
	{ echo "no python$pyver with Tk. run: brew bundle --file $here/Brewfile" >&2; exit 1; }

# QuickLook rasterizes the icon, sips cuts the sizes, iconutil packs them.
qlmanage -t -s 1024 -o "$work" "$here/icon.svg" >/dev/null
mkdir "$work/icon.iconset"
for size in 16 32 128 256 512; do
	sips -z $size $size "$work/icon.svg.png" \
		--out "$work/icon.iconset/icon_${size}x${size}.png" >/dev/null
	sips -z $((size * 2)) $((size * 2)) "$work/icon.svg.png" \
		--out "$work/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$work/icon.iconset" -o "$work/Haldor.icns"

"$python" -m venv "$work/venv"
# PyInstaller is pinned: it decides the bundle's layout, and a release of it can
# change that under an unchanged tag of this. certifi is a trust store rather than a
# library, so it floats and every build carries the roots current on the day.
"$work/venv/bin/pip" install --quiet --disable-pip-version-check \
	"pyinstaller==6.22.3" "certifi>=2026.7.22"
certs=$("$work/venv/bin/python" -c 'import certifi; print(certifi.where())')

"$work/venv/bin/pyinstaller" --noconfirm --clean --log-level WARN \
	--windowed --name Haldor --icon "$work/Haldor.icns" \
	--osx-bundle-identifier io.github.leandersabel.haldor \
	--add-data "$here/bepinex-arm64/core:bepinex-arm64/core" \
	--add-data "$here/shaderfix:shaderfix" \
	--add-data "$certs:certs" \
	--distpath "$work/dist" --workpath "$work/build" --specpath "$work" \
	"$here/gui.py"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $version" \
	"$work/dist/Haldor.app/Contents/Info.plist"
rm -rf "$here/Haldor.app"
cp -R "$work/dist/Haldor.app" "$here/Haldor.app"

# Nobody vouches for an ad hoc signature, but Apple Silicon runs no unsigned code.
# Signing refuses to seal extended attributes, which the copies above pick up.
xattr -cr "$here/Haldor.app"
codesign --force --sign - "$here/Haldor.app"
echo "built $here/Haldor.app $version"
