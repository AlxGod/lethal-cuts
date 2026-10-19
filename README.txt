LETHAL CUTS
===========

Lethal Cuts turns a recording of a Commander game into videos to post:
- Shorts: short vertical 1080x1920 clips for YouTube Shorts and TikTok. You mark
  the good moments while the video plays and drag a tall box over the part of
  the table to keep.
- Long videos: one normal widescreen video of the whole game, with the dead
  stretches (shuffling, long thinks, breaks) cut out.
The volume is evened out automatically either way. It can also record games you
play on the computer, like Tabletop Simulator.


INSTALLING
----------
1. Double-click "Lethal Cuts Setup 0.4.2.exe".
2. Windows will probably show a blue box: "Windows protected your PC".
   That's normal for programs made by a person rather than a big company.
   Click "More info", then "Run anyway".
3. Choose where to install it (the suggested folder is fine). No admin password
   is needed.
4. Choose where to save your videos. Recordings, Shorts and long videos all go
   in that one folder (you can change it later in Settings). Uninstalling or
   updating never deletes anything in it, even if you pick the install folder.
   Pick a drive with lots of room: a 3-hour game is about 20-30 GB.
5. Click through the rest. It puts a Lethal Cuts shortcut on your desktop.

The install folder has two shortcuts: "Lethal Cuts" to open it, and
"Uninstall Lethal Cuts". The program itself sits in its "program" folder.

To check everything works on your PC: Start menu > Lethal Cuts >
"Check that Lethal Cuts works". It plays and exports a tiny test video and
tells you if anything is wrong.


RECORDING A GAME
----------------
On the computer (Tabletop Simulator):
- Install OBS, the free recorder, from obsproject.com (Lethal Cuts uses it).
- Start Tabletop Simulator, then in Lethal Cuts' Record tab click
  "Start recording". It records the game, your computer's sound (including
  everyone on Discord) and your microphone.
- Something great just happened? Press F8, even with the game in front
  (nothing pops up, so keep playing). Each press marks the 5 minutes before it.
  The key and the minutes can be changed in Settings > Recording.
- Click "Stop recording" when the game is over. The recording opens in the
  Editor by itself, with a gold flag at each F8 press.
- The Record tab shows how many hours of recording fit on the drive, and warns
  before you start if a long game won't. Once you've made your videos from a
  recording, it's safe to delete it to free up space.

In person, on an iPhone:
- Settings > Camera > Record Video > 4K at 30 fps.
- In the same menu, turn HDR Video OFF (HDR looks washed out after YouTube/TikTok).
- Clear space first: 4K is about 10 GB an hour, so a 3-hour game needs 30 GB.
- Plug the phone in and turn on Do Not Disturb.
- Mount the phone over the table, looking down, and try not to bump it.
Copy the video to your PC (the .mov file works as it is, no converting) and
open it in the Editor.


MAKING SHORTS
-------------
1. Open the video in the Editor (Open video button, or drag the file onto the window).
2. Skim with the 2x / 3x / 4x buttons or the arrow keys. The Volume slider only
   changes how loud it plays while you edit; exports always even out the volume. Marked moments with F8?
   Press N to jump to a few minutes before each one. On a long game, scroll the
   mouse wheel over the timeline to zoom in (double-click it to zoom back out).
3. Press I when a great moment starts and O when it ends. The video keeps playing.
4. Click a clip's name in the list to name it (the name becomes the file name).
5. Drag the tall box on the video over the cards and players. Press P to preview
   exactly how the phone video will look.
6. Click "Export all clips". They're saved in your videos folder under
   Shorts\<game name>.


MAKING A LONG VIDEO
-------------------
1. Open the video in the Editor and click "Long video" at the top right.
2. Press I where a dead stretch starts and O where it ends. That part is cut out
   (it shows striped red on the timeline). Mark as many as you like.
3. Press P to watch it with the cuts skipped, to check that it flows.
4. Click "Export long video". It's saved in your videos folder under Long videos.
Your Shorts clips and your cuts are kept separately, so you can make both from
the same recording.

How long can a video be?
- YouTube Shorts: up to 3 minutes.
- YouTube videos: up to 15 minutes, until the account verifies a phone number
  (free, once, at youtube.com/verify). Then up to 12 hours.
- TikTok: up to 60 minutes.
Lethal Cuts tells you while you edit when a video is over a limit. Once the
YouTube account is verified, click "It's verified, stop telling me" (Settings >
Posting turns the reminder back on).


POSTING
-------
Everything you export waits in the Post tab, from every game you've done. Click a
video to watch it, then "Post to YouTube" or "Post to TikTok": the upload page
opens and the video is highlighted in its folder, so you can drag it in. Its name
is copied, so paste it as the title. Tick "Posted" once it's up and it moves to
the Posted list, so you always know what's left. About one Short a day does
better than posting them all at once.

Your work saves by itself in a small .lcproj file next to the video. Close the
program whenever you like and open the same video later to carry on.

The first time it opens, a short walkthrough shows you around. You can replay it
from the Guide tab, which also has recording tips, every hotkey, and tips for
strong Shorts. Every "?" button explains the control next to it.


UPDATING
--------
When a new version is out, a gold bar appears at the top of Lethal Cuts when you
open it. Click "Update now": it downloads the new version, installs it and opens
it again by itself, in about a minute. Your settings, videos and Post list are
kept. (Help > Check for updates checks by hand.)


UNINSTALLING
------------
Double-click "Uninstall Lethal Cuts" in the install folder, or use the Start
menu, or Windows Settings > Apps > Installed apps > Lethal Cuts > Uninstall.
Only the program is removed. Your videos are never touched, and neither are your
settings (%APPDATA%\Lethal Cuts) or the .lcproj files next to your videos, in
case you install it again. Delete those by hand if you want them gone.


CHANGING THE PROGRAM
--------------------
The "Lethal Cuts source" folder has the full source code. Open that folder in
Claude Code and describe the change you want; the CLAUDE.md file in it explains
how the program is organized and how to build a new installer.
