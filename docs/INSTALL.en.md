# Installing Docker Desktop and starting the program (Windows)

The whole program (web site, database, backups) runs in Docker. You only need to install Docker Desktop, nothing else
(no Python, no PostgreSQL). Time: about 30 minutes, almost all of it spent downloading.

## 0. What you need beforehand

| | |
|---|---|
| System | Windows 10 (22H2, 64-bit) or Windows 11, any edition (Home is fine) |
| Processor | 64-bit with virtualization enabled (almost all modern ones) |
| Memory | 8 GB or more, 16 GB is better; the program itself needs 2–3 GB |
| Disk | 10 GB free |
| Rights | a Windows administrator is needed once (for the installation) |
| Internet | needed for the first installation and the first build (about 1 GB is downloaded), afterwards the program works without internet |

**Docker Desktop licence.** It is free for personal, educational and non-commercial use and for small companies (fewer than 250 employees
and less than 10 million US dollars annual revenue). Large organizations need a paid Docker subscription. For a hospital
or a centre, ask the IT department before installing. An alternative without this restriction: a Linux server (see the end).

## 1. Check virtualization

1. Press `Ctrl+Shift+Esc` (Task Manager) → the **Performance** tab → **CPU**.
2. At the bottom right it should say **Virtualization: Enabled**.
3. If it says “Disabled”, it is switched on in the BIOS/UEFI (press `Del`, `F2` or `F10` when the computer starts): the item
   **Intel Virtualization Technology (VT-x)** or, on AMD, **SVM Mode**, value **Enabled**. Save and restart.
   On hospital work computers the IT department usually does this.

## 2. Download and install

1. Open https://www.docker.com/products/docker-desktop/ and click **Download for Windows**
   (an ordinary computer: **AMD64**; Windows laptops with a Snapdragon processor: ARM64).
2. Run `Docker Desktop Installer.exe` (answer “Yes” to the User Account Control prompt).
3. In the installer window **keep “Use WSL 2 instead of Hyper-V” ticked** (recommended; on Windows Home it is the only option) and
   “Add shortcut to desktop”. Click **OK** and wait for the installation to finish (5–10 minutes).
4. Click **Close and restart** (or **Close** and restart the computer yourself). **A restart is required.**
5. If the installer says WSL must be installed: open **PowerShell as administrator** (right-click Start →
   “Terminal (Admin)”) and run `wsl --install`, restart, then start Docker Desktop again.

## 3. First start

1. After the restart Docker Desktop starts (or find it in the Start menu). Accept the licence terms (**Accept**).
2. The offer to register or sign in can be skipped: **Skip** / “Continue without signing in”. A Docker account is not needed.
3. The “Tell us about yourself” survey can also be skipped.
4. Wait until the icon at the bottom left turns **green** and **Engine running** appears (up to 1–2 minutes the first time).
5. Check: open PowerShell and run

   ```
   docker --version
   docker run --rm hello-world
   ```

   The second command downloads a small image and prints “Hello from Docker!”. Then everything is ready.

**If you do not work as an administrator** (an ordinary hospital account): add the account to the `docker-users` group.
An administrator does this once, in PowerShell as administrator: `net localgroup docker-users "COMPUTER-NAME\user-name" /add`
(for a domain account: `"DOMAIN\name"`), then the user signs out of Windows and signs in again.

## 4. Docker Desktop settings (the gear at the top right)

For a computer on which the program must run all the time (the server):

| Section | Setting | Value |
|---|---|---|
| General | **Start Docker Desktop when you sign in to your computer** | on (otherwise the program does not come up by itself after a restart) |
| General | **Use the WSL 2 based engine** | on |
| General | **Open Docker Dashboard when Docker Desktop starts** | off (the window does not get in the way) |
| General | **Send usage statistics** | off if you like |
| Software updates | automatic update check | optional; update outside working hours |
| Resources → WSL integration | **Enable integration with my default WSL distro** | can be left as it is |

Nothing else needs to be changed. The program's containers are marked `restart: unless-stopped`: after the computer restarts and Docker
Desktop starts, they come up by themselves.

**Memory (optional).** By default WSL may take up to half of the RAM. To limit it: create the file
`C:\Users\YOUR_NAME\.wslconfig` with the text

```
[wsl2]
memory=4GB
processors=2
```

then run `wsl --shutdown` in PowerShell and restart Docker Desktop.

**If the hospital network has a proxy.** Settings → Resources → Proxies: turn on **Manual proxy configuration** and enter the address
given by the IT department. If the build fails with a certificate error while downloading, the IT department has to allow Docker Hub
(`registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com`) or install the corporate certificate.

## 5. Start the program

1. Download the project: on the repository page **Code → Download ZIP**, unpack it, for example, into `C:\trs398` (a path without
   non-Latin letters and spaces is safer). Or `git clone`.
2. Make sure Docker Desktop is running (**Engine running**).
3. Double-click **`start.bat`**. First it checks the computer (Windows, virtualization, WSL 2, Docker Desktop, disk space, port)
   and explains what to fix; it offers to install WSL itself and starts Docker Desktop if needed. At the first start it asks for the language
   (English or Russian; you can change it later with `language.bat`). Then it downloads the images and builds the program the first time (5–15 minutes) and opens the browser at
   `http://localhost:8000`. If Windows says “Windows protected your PC” (SmartScreen), click “More info” → “Run anyway”.
4. The browser shows the **“First start”** page: choose a login, a surname with initials and the administrator's password (at least 10 characters).
5. Then: “Users” (physicists and reviewers), “Equipment”, “Measurements”. Details: [USER_GUIDE.en.md](USER_GUIDE.en.md).

At the first start Windows Firewall may ask about access for Docker/`com.docker.backend`: allow it for **private** networks.

## 6. A server computer for the whole group

1. Do steps 1–5 on one computer that stays switched on.
2. Turn off **sleep** in Windows (Settings → System → Power → “Sleep”: Never) and turn on autostart in Docker Desktop (section 4).
   A user must be signed in to Windows (the screen may be locked, but do not sign out of the account).
3. Run **`lan-on.bat`**: it opens port 8000 for the other computers of the network and shows the addresses. Details: [NETWORK.en.md](NETWORK.en.md).
4. In the router, fix a permanent IP address for the server (or use the computer name).
5. Copy the `backups` folder to another disk or a network folder from time to time.

## 7. If something does not work

The check can be run separately, without starting the program: `powershell -ExecutionPolicy Bypass -File tools\preflight.ps1 -Lang en`.

| What you see | What to do |
|---|---|
| “Docker Desktop is not running” in `start.bat` | start Docker Desktop, wait for **Engine running**, repeat |
| Docker Desktop hangs on “Starting…” | restart the computer; check virtualization (section 1); in PowerShell as administrator `wsl --update` and `wsl --shutdown` |
| “WSL 2 installation is incomplete” | in PowerShell as administrator `wsl --install`, restart |
| The page http://localhost:8000 does not open | wait a minute after the start; `docker ps` should show three `trs398_*` containers with status Up; `docker compose logs app` shows the error |
| Port 8000 or 5433 is used by another program | add `APP_PORT=8080` to `.env` (the address becomes `http://localhost:8080`) and run `docker compose up -d` |
| The disk is full | Docker Desktop → Troubleshoot → Clean / Purge data deletes everything, **including the program's database**; first make a backup (`backup-now.bat`) and copy the `backups` folder |

## Linux or macOS

- **macOS:** Docker Desktop from the same site (choose Apple chip or Intel chip), then the same. Start: `docker compose up -d --build`.
- **Linux (a server without licence restrictions):** install Docker Engine and the Compose plugin following
  https://docs.docker.com/engine/install/ (Ubuntu: `sudo apt install docker.io docker-compose-v2`), add yourself to the group:
  `sudo usermod -aG docker $USER` and sign in again. Then: `cp .env.example .env`, set the three database passwords and `SESSION_SECRET`
  (long random strings), `docker compose up -d --build`. Autostart after a restart: `sudo systemctl enable docker`.

## 8. Installing without the Internet (from a package)

If the computer has neither the Internet nor GitHub, use the package `TRS398-<version>-offline.zip` (the person who releases versions brings it on a USB stick).
Docker Desktop and WSL 2 must be installed beforehand from the installers that the IT department gives you (they are not part of the package).
Unpack the package into a folder without Russian letters (for example `C:\trs398`) and run `start.bat`: the images of the program are loaded from the package
(a few minutes, once), everything else as in section 5. Updating: unpack the new package over the old folder and run `update.bat`.
In detail: [PUBLISHING.en.md](PUBLISHING.en.md).
