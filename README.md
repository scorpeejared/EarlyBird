# EarlyBird 🐦

EarlyBird 🐦 is a Python desktop application that automatically joins your scheduled Google Meet classes or meetings. Simply add your meeting link, choose a date and time (or make it recurring), and the application will handle the rest.

Designed for students and professionals, it drives a real browser profile — its own, or one of yours, in Chrome or Edge — so you stay signed into Google while meetings are prepared and joined without any manual interaction.

---

# Features

## Automatic Meeting Joining

* Schedule unlimited Google Meet links.
* Automatically opens the correct meeting at the scheduled time.
* Optionally join a few minutes before the meeting begins.
* Automatically disables your microphone and camera before joining.
* Clicks the **Join now** button automatically.

---

## Recurring Meetings

Create repeating schedules similar to the Apple Clock app.

Pick any combination of days from Sunday to Saturday, with one-tap **Weekdays** and **Every day** presets — or leave repeat off for a one-time meeting.

Once a recurring class has been joined for the day, EarlyBird moves on to its next occurrence automatically.

---

## Import From a Screenshot

Rather than typing in five classes one at a time, paste or open a screenshot of your timetable and let an AI read it.

EarlyBird extracts the title, day(s) or date, time, and Meet link for each class, then shows them in a **review screen** where every field stays editable. Anything the parser wasn't sure about — an ambiguous AM/PM, a date with no year, a missing link — is flagged with a warning badge so you know where to look.

**Nothing is saved until you confirm.** Parsed rows are a draft, exactly like the Add Class form before you press Save. Rows can be edited or unticked individually, and a class with no Meet link is saved as a manual (non-auto-join) entry rather than blocking the whole import.

### Bring your own AI

EarlyBird doesn't include an AI. You pick a provider and use your own account, under **Settings → Screenshot import → Choose AI provider**:

| Provider | Notes |
|----------|-------|
| **Google Gemini** | Defaults to `gemini-3.6-flash`. Free keys from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). |
| **OpenAI** | Defaults to `gpt-5.6`. Keys from [platform.openai.com/api-keys](https://platform.openai.com/api-keys). |
| **Other (OpenAI-compatible)** | Any server speaking OpenAI's chat API — OpenRouter, Groq, Together, or a local one like Ollama, LM Studio or vLLM. You supply the address and model name. |

Your key is stored in the operating system's credential manager (Windows Credential Manager, macOS Keychain, or the Linux Secret Service) — never in `settings.json`. If no credential manager is available, the app says so plainly before saving anything.

### Privacy

Before the first import, EarlyBird explains exactly where your image is going and asks you to accept. The notice names the provider you actually picked, and each provider's terms differ — Gemini's free tier uses submitted content to improve Google's products, while OpenAI states API content isn't used for training by default. Switching providers asks again, because agreeing to send a screenshot to one company isn't agreeing to send it to another.

> **Tip:** point the compatible provider at a local server such as Ollama and the screenshot never leaves your computer at all.

A syllabus screenshot often includes your name, your school, and classes you aren't importing — crop it first if you'd rather not send those. The image itself is never written to disk: it's held in memory only and discarded as soon as you confirm or cancel the review.

---

## Browser Profile Management

Out of the box, EarlyBird joins through its own isolated Chrome profile. Sign into Google in it once and it stays signed in between launches, without touching your everyday browsing session.

If you would rather join as one of your existing browser profiles, add a **connection** on the Connections page. Two kinds exist:

* **No setup (recommended, Windows only).** EarlyBird drives the browser through Windows UI Automation, the same accessibility API screen readers use. Give it a profile directory name and it launches that profile with the meeting link when the class is due — the browser can be open or closed beforehand.
* **Debug port.** EarlyBird attaches over the browser's remote-debugging port. This needs the browser started from a generated launcher script rather than your normal icon, and since Chrome 136 the debug port is refused for your real default profile — so this option is mainly useful for a dedicated automation profile.

### Supported browsers

Every connection records which browser it drives. Chrome is the default, and a connection saved before this field existed keeps behaving exactly as Chrome.

| Browser | Status | Profile layout | Where to find the profile name |
| --- | --- | --- | --- |
| Google Chrome | Supported | `User Data\Profile N` | `chrome://version` |
| Microsoft Edge | Supported | `User Data\Profile N` | `edge://version` |
| Brave | Supported | `User Data\Profile N` | `brave://version` |
| Opera | Supported | one folder per install | `opera://about` |
| Opera GX | Supported | one folder per install | `opera://about` |

Brave uses exactly the same profile layout as Chrome, so its setup is identical — pick **Brave** in the dropdown and paste the same kind of `Profile N` directory name. One difference worth knowing: Brave is launched from its standard install path (Chrome and Edge go through Playwright's built-in browser support), so a Brave installed somewhere unusual won't be found. The dialog shows this note when Brave is selected.

**Opera and Opera GX need the whole profile path.** When you pick either one, the connection dialog switches to a single **profile folder** field with a Browse button. Paste the `Profile` path exactly as `opera://about` reports it — including the trailing folder, usually `\Default`:

```text
C:\Users\YourName\AppData\Roaming\Opera Software\Opera GX Stable\_side_profiles\<id>\Default
                                                                                    ^^^^^^^ keep this
```

Opera is Chromium underneath: that path is a *profile* inside a parent *user-data-dir*, and both halves are needed to open the right one. EarlyBird splits them for you and shows the result live under the field ("Will open profile 'Default' in …"), so a wrong level is visible before you save. Pasting the parent folder instead also works.

Two Opera-specific behaviours: Opera's own start page (GX Corner on Opera GX) stays open in the joined window, because closing it takes minutes and shuts the browser down; and Opera and Opera GX are listed separately because they share the same `opera.exe` and can only be told apart by install path, which is what stops a class configured for one from attaching to the other.

Auto-join, mic/camera muting, recurring classes and profile reuse work the same way on every supported browser — pick one in the **Browser** dropdown when adding a connection, and the rest of the setup is identical.

---

## Automatic Meeting Cleanup

Before joining a new meeting, EarlyBird closes the window it opened for that connection's previous meeting, so Meet tabs don't pile up over the day.

It only closes windows it opened itself. If the browser joined by opening a tab in a window you already had open, that window is left alone.

---

## Desktop Application

Built with Python, PySide6, and QFluentWidgets for a modern, Fluent-styled
Windows 11 look and feel.

Features include:

* A dashboard of today's, upcoming, and joined classes
* Add, edit, and delete meetings
* Enable or disable auto-join per class, from the list or the toolbar
* A dedicated Connections page for managing browser connections
* Runs quietly in the system tray
* In-app update checks and one-click restart-and-update

---

# Requirements

* Python 3.11 or newer
* Google Chrome, Microsoft Edge, Brave, Opera, or Opera GX
* Windows (recommended)

---

# Installation

Clone the repository:

```bash
git clone https://github.com/scorpeejared/EarlyBird.git
cd EarlyBird
```

Create a virtual environment:

```bash
python -m venv venv
```

Activate it.

Windows:

```bash
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Install Playwright:

```bash
playwright install chrome
```

---

# Running the Application

Start the application with:

```bash
python main.py
```

---

## First-Time Setup

EarlyBird works with no setup at all — classes join through its own isolated Chrome profile, and you sign into Google in it the first time a meeting opens.

To join as one of your existing browser profiles instead, add a connection:

### Step 1: Find your profile directory name

Open the browser and profile you normally use for Google Meet, and go to its version page:

| Browser | Version page | Typical profile path |
| --- | --- | --- |
| Google Chrome | `chrome://version` | `C:\Users\YourName\AppData\Local\Google\Chrome\User Data\Profile 1` |
| Microsoft Edge | `edge://version` | `C:\Users\YourName\AppData\Local\Microsoft\Edge\User Data\Profile 1` |
| Brave | `brave://version` | `C:\Users\YourName\AppData\Local\BraveSoftware\Brave-Browser\User Data\Profile 1` |
| Opera | `opera://about` | `C:\Users\YourName\AppData\Roaming\Opera Software\Opera Stable` |
| Opera GX | `opera://about` | `C:\Users\YourName\AppData\Roaming\Opera Software\Opera GX Stable` |

For Chrome, Edge and Brave, copy only the **last folder** (`Profile 1`). For Opera and Opera GX, copy the **whole path** — that folder is the profile.

Copy the last folder from the **Profile Path** field — the directory name, not the whole path, and not the display name the browser shows in its UI:

```text
C:\Users\YourName\AppData\Local\Google\Chrome\User Data\Profile 1
                                                        ^^^^^^^^^
```

### Step 2: Add the connection

In EarlyBird, open **Connections → Add**, give the connection a name, pick your browser in the **Browser** dropdown (Chrome is preselected), leave the recommended "no manual setup" option selected, and paste `Profile 1` into **&lt;browser&gt; profile directory name**.

The Connections page lists each connection's browser, so several browsers can be configured side by side.

### Step 3: Point a class at it

When adding or editing a class, pick that connection under **Join using**. The class then joins in whichever browser that connection is set to.

> **Note:** Make sure that browser profile is already signed in to the Google account you want to join meetings with.

### Where each browser is installed

EarlyBird looks for these paths automatically; you only need them if you are troubleshooting a "could not find … in standard install locations" message.

| Browser | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Google Chrome | `C:\Program Files\Google\Chrome\Application\chrome.exe` | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` | `google-chrome` |
| Microsoft Edge | `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` | `/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge` | `microsoft-edge` |
| Brave | `C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe` | `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser` | `brave-browser` |
| Opera | `%LOCALAPPDATA%\Programs\Opera\opera.exe` | `/Applications/Opera.app/Contents/MacOS/Opera` | `opera` |
| Opera GX | `%LOCALAPPDATA%\Programs\Opera GX\opera.exe` | `/Applications/Opera GX.app/Contents/MacOS/Opera` | not available |

---

# Scheduling a Meeting

1. Click **Add Meeting**.
2. Enter the meeting title.
3. Paste the Google Meet link.
4. Choose the meeting date and time.
5. Select whether the meeting is:

   * One-time
   * Recurring
6. (Optional) Select the days of the week for recurring meetings.
7. Save.

The application will automatically handle the meeting when its scheduled time arrives.

---

# Project Structure

```text
.
├── main.py                   # Entry point: bootstrap, then the window
├── requirements.txt          # Python dependencies
│
├── data/                     # User data (gitignored)
│   ├── meetings.db           # SQLite database
│   └── settings.json         # App settings and browser connections
│
├── logs/                     # Log files (gitignored)
│   └── automation.log
│
└── src/                      # Application source code
    ├── paths.py              # Where everything the app writes lives
    ├── logging_setup.py      # Shared logger name and log file
    ├── models.py             # Meeting and JoinResult
    ├── storage.py            # Database operations
    ├── settings.py           # Settings and browser connections
    ├── browsers.py           # Per-browser channels, paths and window classes
    ├── scheduler.py          # Background scheduling engine
    ├── notifier.py           # Desktop notifications
    ├── recurrence.py         # Recurring meeting calculations
    ├── launchers.py          # Browser launcher script generator
    ├── import_screenshot.py  # Screenshot -> reviewable draft meetings
    ├── ai_provider.py        # Bring-your-own-AI backends (Gemini/OpenAI/compatible)
    ├── secret_store.py       # API keys, OS credential manager first
    │
    ├── automation.py         # Playwright automation (isolated profile, CDP)
    ├── automation_uia.py     # Windows UI Automation backend
    ├── cdp_probe.py          # Chrome DevTools Protocol probing
    │
    ├── updater/              # Auto-update subsystem
    │
    └── ui/                   # PySide6 + QFluentWidgets presentation layer
        ├── main_window.py    # FluentWindow: navigation + backend wiring
        ├── theme.py          # Accent color and semantic status colors
        ├── pages/            # Classes / Connections / Settings pages
        ├── dialogs/          # Add/Edit class, connections, screenshot import
        └── widgets/          # Stat cards, meeting cards, day picker, etc.
```

`data/` and `logs/` sit in the project root when you run from source. In a packaged build they move to your per-user app-data folder (`%LOCALAPPDATA%\EarlyBird` on Windows) so an update that replaces the executable can never take your saved classes with it. The Settings page shows and opens the exact folder in use.

---

# How It Works

A background thread polls your saved classes every 15 seconds. Five minutes before a class, it sends a desktop notification. When the class is due, EarlyBird 🐦:

1. Closes the window it opened for that connection's last meeting.
2. Opens the browser — its own isolated Chrome profile, or the browser and profile the class's connection points at.
3. Navigates to the Google Meet link.
4. Turns off the microphone.
5. Turns off the camera.
6. Clicks **Join now**.
7. Marks the class joined, so a recurring one is ready for its next occurrence.

Controls are found by their accessible name rather than screen position, so this keeps working across screen sizes and minor Meet redesigns. If the **Join now** button can't be found, EarlyBird saves a screenshot next to the log to show what it was looking at.

---

# Notes

* Your Google credentials are **never** stored by the application.
* Authentication is handled entirely by your own browser profile.
* The application is designed specifically for Google Meet.
* The application must be running for scheduled meetings to be joined automatically.

---

# License

This project is provided for educational and personal use.
