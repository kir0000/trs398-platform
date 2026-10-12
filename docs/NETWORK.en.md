# Access from several computers (local network)

The program is installed **on one computer** (the server); the other physicists open it in the browser, nothing has to be installed.

## How it works

Docker runs only on the **server**. Inside the container the web site works; Docker forwards its port 8000 to the server computer.
The other computers need neither Docker nor Python nor the program itself: a browser (Chrome, Edge, Firefox) and the address of the server are enough,
as for any internal site. The data and the users are shared and stored on the server. While access from the network is off (the default),
the site opens only on the server itself at `http://localhost:8000`.

## Turn it on

1. On the server computer run `start.bat` (once), then **`lan-on.bat`**. The window asks for administrator rights:
   port 8000 has to be opened in Windows Firewall (for private and domain networks only).
2. The script shows the addresses, for example `http://PC-PHYSICS:8000` and `http://192.168.1.20:8000`.
   The others open either of them in the browser and sign in with their own account.
3. To turn the network access off: **`lan-off.bat`**.

Linux/macOS: add the line `APP_BIND=0.0.0.0` to `.env`, open port 8000 (`ufw allow 8000/tcp`), then `docker compose up -d`.

## What you need to know

- The server computer must be switched on and Docker Desktop running. Turn on “Start Docker Desktop when you sign in” in Docker Desktop
  and turn off sleep in Windows, otherwise the others lose access.
- Give the server a permanent address: in the router fix an IP address for it (or use the computer name).
- The database stays closed: the PostgreSQL port (5433) is available only on the server itself.
- Create a separate account for each user (“Users”): the roles and the two-person rule work the same way.
- The backups are on the server in the `backups` folder (automatically every day). Copy it to another disk or a network folder.
- Without encryption the passwords travel over the network in clear text. Inside a closed hospital network this is usually acceptable;
  if you need encryption, turn on HTTPS (below). Do not open the port to the internet.

## Optional: HTTPS (encryption)

1. On the server run **`https-on.bat`** (it asks for administrator rights). If `certs` holds no certificate, the script creates a
   self-signed one (`cert.pem`, `key.pem`, 825 days, for the computer name and its IP addresses), sets `HTTPS_ONLY=1`,
   closes port 8000 to the network in the firewall and opens 8443. Internet is needed once (a small `alpine/openssl` image is pulled).
2. The address for everyone, the server included: `https://computer-name:8443`. Plain `http://...:8000` no longer works for sign-in.
3. On the first visit the browser warns about the certificate (it is self-signed). Either choose “Advanced → Proceed”, or add
   `certs\cert.pem` once to the trusted root certificates of every computer (double-click → “Install certificate” →
   “Local machine” → “Trusted Root Certification Authorities”). Or ask the IT department for a certificate for the server name and
   put it into `certs` as `cert.pem` and `key.pem` (before running `https-on.bat`).
4. If the server gets another IP address or name, delete the `certs` folder and run `https-on.bat` again.
5. Switch off: **`https-off.bat`** (the program is again available on the server only, at `http://localhost:8000`; then `lan-on.bat` for the network).

By hand (Linux/macOS): put `cert.pem` and `key.pem` into `certs`, add `HTTPS_ONLY=1` and `APP_BIND=127.0.0.1` to `.env`,
then `docker compose up -d app` and `docker compose --profile https up -d`; open port 8443 in the firewall.
