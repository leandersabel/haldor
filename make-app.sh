#!/bin/sh
# Build Haldor.app, a Finder launcher for the window. It names this checkout and
# the Python running now, so build it again if either moves.
set -e

here=$(cd "$(dirname "$0")" && pwd)
app=${1:-$here/Haldor.app}
python=$(command -v python3)
"$python" -c 'import sys, tkinter; assert sys.version_info >= (3, 10), sys.version'

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# QuickLook rasterizes the icon, sips cuts the sizes, iconutil packs them.
qlmanage -t -s 1024 -o "$work" "$here/icon.svg" >/dev/null
mkdir "$work/icon.iconset"
for size in 16 32 128 256 512; do
	sips -z $size $size "$work/icon.svg.png" \
		--out "$work/icon.iconset/icon_${size}x${size}.png" >/dev/null
	sips -z $((size * 2)) $((size * 2)) "$work/icon.svg.png" \
		--out "$work/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
iconutil -c icns "$work/icon.iconset" -o "$app/Contents/Resources/Haldor.icns"

cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key><string>Haldor</string>
	<key>CFBundleExecutable</key><string>Haldor</string>
	<key>CFBundleIconFile</key><string>Haldor</string>
	<key>CFBundleIdentifier</key><string>ch.sabel.haldor</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
	<key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$app/Contents/MacOS/Haldor" <<LAUNCH
#!/bin/sh
# A double click lands here. Finder shows nothing when this fails, so say it aloud.
if ! [ -x "$python" ]; then
	osascript -e 'display alert "Haldor" message "$python is gone. Run make-app.sh again."'
	exit 1
fi
exec "$python" "$here/gui.py"
LAUNCH
chmod +x "$app/Contents/MacOS/Haldor"
echo "built $app"
