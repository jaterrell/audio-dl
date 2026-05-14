# Installing the audio-dl macOS .app

audio-dl ships as a macOS `.app` bundle for Apple Silicon Macs. It's
**unsigned** — distributed for trusted testers, not through the App Store
or the Apple notarization pipeline. macOS Gatekeeper will block the first
launch by default; the steps below get past it once, after which the app
opens normally.

If you're on an Intel Mac or want to compile from source, see the
"macOS `.app` bundle" section of the README for the build-from-source
path.

## Download

1. Go to <https://github.com/jaterrell/audio-dl/releases>.
2. From the latest release, grab:
   - `audio-dl-vX.Y.Z-macos-arm64.zip` — the bundle.
   - `SHA256SUMS` — (optional) the integrity checksum.

## Verify the download (optional)

In Terminal, in the directory you downloaded both files into:

```
shasum -a 256 -c SHA256SUMS
```

You should see `audio-dl-vX.Y.Z-macos-arm64.zip: OK`. If you see `FAILED`,
the file was corrupted in transit — delete and re-download.

## Install

1. Double-click the zip to unpack it. You'll get a folder containing
   `audio-dl.app` and `README-FIRST.txt`.
2. (Optional) drag `audio-dl.app` to your `/Applications` folder. The app
   also runs fine from `~/Downloads` or anywhere else.

## First launch — getting past Gatekeeper

macOS will block the first launch with a dialog like:

> *"audio-dl" can't be opened because Apple cannot check it for malicious
> software.*

This is expected — the app is unsigned. Two ways to bypass it:

**Right-click → Open (recommended).** In Finder, right-click (or
two-finger click) `audio-dl.app` and choose **Open**. macOS shows a
slightly different dialog with an **Open** button. Click it. macOS only
asks once per app — after that, double-clicking works normally.

**Power-user shortcut.** In Terminal:

```
xattr -d com.apple.quarantine /path/to/audio-dl.app
```

Replace `/path/to/audio-dl.app` with wherever you put the app. This
removes the "downloaded from the internet" marker that triggers
Gatekeeper.

## Using audio-dl

Once running:

- Your browser opens to <http://127.0.0.1:8000/>.
- Paste one or more URLs (YouTube, SoundCloud, etc.) into the textarea.
- Pick a format (mp3, m4a, flac, etc.) and click **Download**.
- Click **Reveal** next to a finished download to open it in Finder.

Quitting the app from the Dock (right-click → Quit, or ⌘Q while it's
focused) stops the embedded web server.

## Updating

When a new release comes out:

1. Quit the running app.
2. Download the new zip from the Releases page.
3. Replace your existing `audio-dl.app` with the new one. Existing
   downloads in your output directory are untouched.

## Troubleshooting

**"Port 8000 already in use."** Something else on your Mac is bound to
8000. Quit it, or relaunch audio-dl with a different port: in Terminal,
run `/path/to/audio-dl.app/Contents/MacOS/audio-dl --port 9000`.

**Browser doesn't open automatically.** Open one yourself and navigate
to <http://127.0.0.1:8000/>.

**"ffmpeg not found" dialog.** This shouldn't happen — ffmpeg is bundled
inside the `.app` as of v1.3. If you see it, file an issue at
<https://github.com/jaterrell/audio-dl/issues> with the macOS version
and the output of `dist/audio-dl.app/Contents/MacOS/audio-dl --no-browser`
from Terminal.
