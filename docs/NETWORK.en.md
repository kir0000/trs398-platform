# Access from several computers (local network)

The program runs **on one laptop** (called the server); the other physicists open it in a browser, nothing has to be installed.
The department's servers that are medical devices are not used for this: any ordinary Windows laptop will do, switched on during working hours and connected to the same network.

## Switch on

1. On the laptop with the program tick **"Allow connections from other computers"**: in the tray icon menu or on the **"Settings"** page (administrator). The port is changed there too.
   The program shows an address like `http://192.168.1.20:8000`.
2. At the first switching on Windows asks for the firewall permission: tick **"Private networks"** and click "Allow".
   This is the only action that needs Windows administrator rights (to allow incoming connections for the program). If you do not have them, ask the administrator of the computer to click "Allow" once or to create a rule for port 8000. Work on one laptop (`http://localhost:8000`) needs no administrator rights.
3. The others open this address in a browser and sign in with their own account (created by the administrator in "Users").
   The name of the laptop (`http://laptop-name:8000`) is handier than the address, which may change.
4. Switch off: clear the tick in the same menu.

## Limiting the access

Administrator: “Settings” → “Network security”.

- **Allowed addresses.** Empty: any address of the network may connect (the default). If you list addresses and networks (`192.168.1.0/24, 10.0.0.15`), the others get the page “403, access from this address is not allowed”. The laptop itself (`127.0.0.1`) is always allowed. The program does not let you save a list without your own address (otherwise you would lock yourself out). Refused requests are written to the audit log (no more than once an hour for one address). It is better to fix the address of the laptop in the router so that it does not change. The environment variable `TRS_ALLOWED_NETWORKS` is stronger than the setting.
- **Lifetime of a session.** “A session lasts no longer than” (hours, 8 by default): after that you have to sign in again. “End the session after an idle time” (minutes, 0 — do not end): 30–60 is reasonable for shared laptops; an unsaved form is lost when the session ends. The sign-in page tells why the session ended.

This does not replace encryption: the connection is still http.

## Points to note

- While the server laptop is off or asleep the others cannot work. Disable sleep when on mains power.
- The connection is not encrypted (http): passwords cross the network in clear text. Use it only inside the department network, never open the port to the internet. HTTPS is not included in version 2.0.
- The backups lie on the server laptop; copy the `backups` folder to another medium.
- 2-5 people working at the same time is safe: the database is a SQLite file, writes are made one after another.

## How working together is organised

- **One server, one database.** Everything is kept on the server laptop; the others work in the browser. Do not put the database file on a network folder and do not run two programs on one database: SQLite is not made for that.
- **Writes one after another.** A write takes milliseconds, so two people saving at the same time do not disturb each other (checked: 3 authors and a reviewer, 190 requests in 6 seconds, 65 ms on average, no errors). Viewing pages does not block writing.
- **Every record has one owner.** A draft and a returned record are edited by their author only; another person checks and approves (the rule of two persons).
- **If two people press at the same moment.** A decision is made once: the second reviewer (or the author who edited a record while it was being approved) sees “The record has already been changed by another user: refresh the page”; nothing is lost or duplicated.
- **Protocols.** The protocol numbers are issued by the database, two equal numbers cannot occur.
- **Heavy operations.** Printed PDFs are built two at a time at most, the others wait their turn. A restore from a backup puts the others on a waiting page for a minute.
- **Sign-in.** Everybody has their own account; a session is limited by age and by idle time (see “Limiting access”). The administrator can change a password.
- **What the server laptop needs.** Switched on and awake, in the right network, makes a backup at night (at 02:00; if it was off, the backup is made at the next start). Copy the folder `backups` to another medium or switch on the “Second copy” on the “Backups” page.
- If the laptop is in another subnet or the network blocks connections between computers, ask the network administrator to allow incoming TCP connections to port 8000.
