# The clips folder (owner guide)

Save a video into one iCloud folder and the studio takes it as a drop. No terminal, no link, no upload by hand.

- **Where it is.** iPhone: Files app > iCloud Drive > **ODD EYES clips**. Mac: Finder > iCloud Drive > **ODD EYES clips**. Put clips straight in that folder, not in a sub-folder.
- **From TikTok.** Share > Save video, then Photos > the video > Share > Save to Files > iCloud Drive > ODD EYES clips.
- **From Instagram.** Share > Download, when the reel offers it (not every reel does), then Photos > Share > Save to Files as above. A reel with no Download button: drop its link on the terminal as before.
- **From Safari.** Tap the video's Download (or Share > Save to Files) and pick ODD EYES clips.
- **From Photos.** Open the video > Share > Save to Files > ODD EYES clips.
- **What "Added" means.** About every 5 minutes the Mac looks in the folder. Each new clip becomes a drop (the terminal shows it under "In the works") and is moved into the **Added** sub-folder, so what is left at the top is what has not been taken yet. The same clip saved twice makes one drop.
- **The Mac must be awake** and you logged in. A clip is taken only once it has finished syncing to the Mac, so on a slow connection give it a few minutes. Only videos up to 200 MB are taken; anything else stays where it is.
- **First time:** macOS may ask on screen whether `uv` / python may use iCloud Drive. Click Allow. If you said no by mistake: System Settings > Privacy & Security > Full Disk Access, add the `uv` binary, then run `bin/install-clip-sync` again.
- **See what it did:** `tail -n 30 ~/Library/Logs/odd-eyes-clip-sync.log` (a line per run, with what was added or why a clip was skipped).
- **Turn it off:** `bin/install-clip-sync --uninstall` (the folder and its Added clips stay). Turn it back on: `bin/install-clip-sync`.
