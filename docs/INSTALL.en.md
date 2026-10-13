# Installation and start (Windows)

Windows 10 or 11 is needed. Docker, Python and database servers are **not** needed. PDFs are printed by Microsoft Edge (present in Windows 10/11) or Chrome.

## Installing

**Administrator rights are needed neither for installing nor for working**: the installer writes only into the user profile, the portable version runs from any folder you can write to (desktop, Documents, a USB stick). The exception: the firewall permission for access from other laptops ([NETWORK.en.md](NETWORK.en.md)). If a policy of the organization blocks the start (AppLocker, antivirus), the IT administrator has to add an exception for the program folder.

1. From the **Releases** page of the repository download `TRS398-setup-….exe` and run it. No administrator rights are needed, the program goes into your user profile
   (`%LOCALAPPDATA%\Programs\TRS398`); you may choose another folder and tick "start with Windows".
2. If Windows says "Windows protected your PC" (SmartScreen): click **More info → Run anyway**. This happens with any program without a paid signature.
3. Start **TRS-398** from the Start menu. An icon appears near the clock and `http://localhost:8000` opens.
4. First sign-in: choose the login and password of the administrator (at least 10 characters). This page is available only while the database has no users.

**Without installing:** download `TRS398-portable-….zip`, unpack into any folder (a USB stick or `C:\trs398`), run `TRS398.exe`. The data will be in the folder `data` beside it.

## Everyday work

- The icon near the clock: a click opens the program, the right button gives the menu (backup, data folder, restore, autostart, access from other computers, exit).
  If you do not see the icon, it is hidden under the "^" arrow near the clock.
- Closing the browser leaves the program running; open it again with the icon or the shortcut. To stop it: "Exit".
- Backups are made every day by themselves while the program is running. Every week or two copy the `backups` folder to another medium.

## Updating

To see whether a new version is out: click the version number at the bottom of any page (“About”) and press “Check for updates” (one request to GitHub, only on the button). Download the new installer and run it over the old one: the program is replaced, **the data are not touched**. Portable version: unpack the new zip over the old folder, do not delete `data`.
Make a backup before updating (icon menu).

## Uninstalling

"Settings → Apps → TRS-398 → Uninstall". The data (`%LOCALAPPDATA%\TRS398\data`) are removed only by you, by hand.

## If something does not work

| What you see | What to do |
|---|---|
| The icon is there but the page does not open | Click the icon. If port 8000 is used by another program, change `port` in `settings.json` in the data folder (for example 8100) and restart. |
| Something does not work | Icon menu → "Error log" opens the file `app.log` in the data folder; send it to the developer (it holds no measurement data or passwords). |
| "PDF unavailable" | Edge or Chrome is needed. Fallback: the "Print" button → "Save as PDF". |
| The antivirus removed or blocked the program | Add the program folder to the exceptions. The build is not signed. |
| Forgot the administrator password | Another administrator resets it in "Users". If there is only one: restore a backup where the password is known, or start with an empty database (see README). |
| The data must be brought back | Icon menu → "Restore from a backup…". |

## Running from the sources (for developers)

`pip install -r requirements.txt`, then `python run.py` (no icon) or `python tray.py`. The data: the `data` folder of the project or the `TRS_DATA` variable.
