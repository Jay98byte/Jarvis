# ⚡ Jarvis AI Personal Assistant - Complete Setup

> **A real voice-controlled AI executive assistant for your computer.**
> Features voice app launching, YouTube playback, WhatsApp automation, email briefings, live stock market analysis (Buy/Sell calls), rate-limit failover, and a 3D holographic Iron Man HUD!

---

## 🚀 Quick Start (In 60 Seconds)

### On macOS / Linux:
```bash
chmod +x install.sh
./install.sh
```

### On Windows:
Double-click `install.bat` or run:
```cmd
install.bat
```
After setup, use the **Jarvis AI** shortcut on your Desktop to launch Jarvis
without running the installer again. It opens the Workplace HUD in your browser
and reuses the saved Groq API key through a local Python bridge. Allow operating
system microphone access if prompted. The original native desktop dashboard
remains available with `start_desktop.bat`.

---

## 🎙️ Voice Commands Cheat-Sheet

| What You Say | What Jarvis Does |
| :--- | :--- |
| `"Jarvis, open VS Code"` | Launches Visual Studio Code instantly |
| `"Jarvis, open Spotify"` / `"open Perplexity"` | Opens the matching installed app, local item, or website |
| `"Open Twitter in background"` | Opens the requested app or site minimized without bringing it to the front |
| `"Jarvis, cooldown"` | Shuts down Jarvis |
| `"Play lofi"` / `"Play lofi on Spotify in background"` | Starts the matching track; Spotify stays minimized for background commands |
| `"Play lofi on YouTube"` | Opens YouTube search for lofi |
| `"Stop"` / `"Stop the music"` | Sends a stop command to the active media player |
| `"Close Spotify"` / `"Close the Downloads folder"` | Closes the matching open app or window without force-ending it |
| `"Stock market report"` | Analyzes Nifty, Sensex, Reliance, Nvidia & crypto |
| `"Should I buy Reliance?"` | Checks moving averages and gives Buy/Sell advice |
| `"Read my email"` / `"Check my inbox"` | Reads up to three recent Gmail messages aloud |
| `"What is on my calendar tomorrow?"` | Reads your Google Calendar schedule aloud |
| `"Add task finish report tomorrow at 3 PM"` | Adds a task to Google Calendar |
| `"Schedule meeting with Alex on Friday at 2 PM"` | Adds a timed calendar event |
| `"Reschedule event project review on Friday to Monday at 10 AM"` | Moves a matching event |
| `"Rename event project review to design review on Friday"` | Renames a matching event |
| `"Set location of event design review on Monday to Room 2"` | Updates a matching event's location |
| `"Delete event project review on Friday"` | Deletes a matching event |
| `"Send WhatsApp message to Pallavi"` | Opens WhatsApp Web and drafts a message |
| `"Volume up" / "Mute" / "Unmute"` | Adjusts your system volume hands-free |
| `"Set volume to 50%"` | Sets Windows system volume to the requested percentage |
| `"Set brightness to 60%"` / `"Brightness down"` | Sets or adjusts Windows display brightness |
| `"Compose email to tony23@gmail.com saying Hello Tony..."` | Saves a Gmail draft; requires an explicit confirmation before sending |
| `"Send hi to Tony on WhatsApp"` | Finds an exact WhatsApp chat, announces recipient/message once, then sends |
| `"Message Alex on Discord saying Hello..."` | Opens the selected messaging app and prepares a reviewed handoff |

Jarvis can change system volume and display brightness. Wi-Fi and Bluetooth
controls are not available. Brightness changes require a display that supports
Windows brightness controls. Add `in background` (or `in the background`) to
commands that open an app, file, or website to request a minimized launch. The
option is handled across Jarvis commands; apps that override Windows' minimized
startup request may still choose their own window state.
Google account authorization is interactive: the first sign-in must run in the
foreground once, after which connected email and Calendar commands can run in
the background.
On Windows, spoken responses use the installed Microsoft David male voice when
available. The Workplace HUD prefers Microsoft David from the browser or
operating system's English voices; if unavailable, it uses the system's English
voice. The native desktop app uses Microsoft David when available and otherwise
falls back to the system voice.

### Gmail setup

Enable the Gmail API in your Google Cloud project, create an OAuth client ID
for a **Desktop app**, and place its downloaded JSON file at
`%APPDATA%\OpenJarvis\gmail_client_secret.json`. The first Gmail command opens
Google sign-in; Jarvis stores the resulting token in the same local folder.
Never share either file. Use `compose email to ADDRESS` and then dictate the
message, or include `subject ... saying ...` in one command. Jarvis saves a
draft first and only sends it after you say `confirm send email to ADDRESS`.
Say `cancel email` to discard the pending send confirmation.

### Google Calendar setup

Enable the Google Calendar API in your Google Cloud project, create an OAuth
client ID for a **Desktop app**, and add your Google account as a test user on
the OAuth consent screen if the app is in testing mode. In the Workplace HUD,
open **Settings → Connect Google Calendar**, paste the client ID and client
secret from the downloaded OAuth credentials, and click **Connect Calendar**.
Jarvis saves these locally under `%APPDATA%\OpenJarvis` and opens Google
sign-in to authorize Calendar access; the access token is stored separately as
`calendar_token.json`. Calendar tasks are stored as
Calendar entries prefixed with “Task:”. Use dates such as `today`, `tomorrow`,
a weekday, or `November 14, 2026`; timed entries accept times such as `3:30 PM`
or `15:30`. Entries without a time are all-day. To edit or delete an entry,
include its title and preferably its current date so Jarvis can identify a
unique match. Jarvis can reschedule, rename, and update descriptions or
locations. Deletion takes effect immediately.

WhatsApp sending uses Selenium and a dedicated Microsoft Edge profile for
WhatsApp Web. On first use, sign in by scanning the QR code in that Jarvis Edge
window. For an exact, unique contact match, Jarvis announces the recipient and
message once and sends it. If there is no exact match, it names the closest
match and waits for `yes send to NAME`; `cancel message` cancels it. A message
without text, such as `send WhatsApp message to Tony`, prompts for voice
dictation. Other messaging services still open a draft handoff; Jarvis does
not send from them.

Use **Settings** in the Workplace HUD to change the hologram color, speech,
speech rate, microphone autostart, and the end-of-speech pause from 0.5 to 2
seconds. This pause controls how long Jarvis waits before treating a spoken
phrase as complete, so a longer value joins speech split by a short pause.
Preferences are saved in your browser;
use **Save API Key** to store your Groq key in Jarvis's local user-profile file.
The key is never placed in browser storage. Use **Start Listening** to enable the
microphone.

---

## 🛡️ Best Part: Hybrid Failover (Zero Crashes)
When cloud LLMs hit daily token limits or rate limits (HTTP 429), standard assistants crash and give error messages. 
Jarvis has an **Automatic Cooldown & Local Fallback Engine**:
- Detects the exact rate-limit duration.
- Switches instantly to offline local code.
- Executes your commands locally without interruption!

---

## 🌐 Holographic Iron Man HUD
Run `start_workplace.vbs` on Windows for a fully hidden launch, or
`start_workplace.bat` for the compatibility launcher. Run `python jarvis_workplace_server.py
--show` inside the project environment on macOS/Linux. The bridge runs in the
background and opens the HUD in your browser. To run it without opening a
browser, use `start_workplace.vbs --background` on Windows or start the Python
server with `--background`. The HUD provides voice commands, AI responses, app
actions, live market data, and local system telemetry. Use the HUD's
**Settings** button to save browser preferences. Opening the HTML file directly
does not start the local assistant bridge. The microphone stays off until you
open the HUD and enable listening.
