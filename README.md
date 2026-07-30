# EarlyBird 🐦

EarlyBird 🐦 is a Python desktop application that automatically joins your scheduled Google Meet classes or meetings. Simply add your meeting link, choose a date and time (or make it recurring), and the application will handle the rest.

Designed for students and professionals, it drives a real Chrome profile — its own, or one of yours — so you stay signed into Google while meetings are prepared and joined without any manual interaction.

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

## Chrome Profile Management

Out of the box, EarlyBird joins through its own isolated Chrome profile. Sign into Google in it once and it stays signed in between launches, without touching your everyday browsing session.

If you would rather join as one of your existing Chrome profiles, add a **connection** on the Connections page. Two kinds exist:

* **No setup (recommended, Windows only).** EarlyBird drives Chrome through Windows UI Automation, the same accessibility API screen readers use. Give it a profile directory name and it launches that profile with the meeting link when the class is due — Chrome can be open or closed beforehand.
* **Debug port.** EarlyBird attaches over Chrome's remote-debugging port. This needs Chrome started from a generated launcher script rather than your normal icon, and since Chrome 136 the debug port is refused for your real default profile — so this option is mainly useful for a dedicated automation profile.

---

## Automatic Meeting Cleanup

Before joining a new meeting, EarlyBird closes the window it opened for that connection's previous meeting, so Meet tabs don't pile up over the day.

It only closes windows it opened itself. If Chrome joined by opening a tab in a window you already had open, that window is left alone.

---

## Desktop Application

Built with Python, PySide6, and QFluentWidgets for a modern, Fluent-styled
Windows 11 look and feel.

Features include:

* A dashboard of today's, upcoming, and joined classes
* Add, edit, and delete meetings
* Enable or disable auto-join per class, from the list or the toolbar
* A dedicated Connections page for managing Chrome connections
* Runs quietly in the system tray
* In-app update checks and one-click restart-and-update

---

# Requirements

* Python 3.11 or newer
* Google Chrome
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

To join as one of your existing Chrome profiles instead, add a connection:

### Step 1: Find your profile directory name

Open Chrome using the profile you normally use for Google Meet, and go to:

```text
chrome://version
```

Copy the last folder from the **Profile Path** field — the directory name, not the whole path, and not the display name Chrome shows in its UI:

```text
C:\Users\YourName\AppData\Local\Google\Chrome\User Data\Profile 1
                                                        ^^^^^^^^^
```

### Step 2: Add the connection

In EarlyBird, open **Connections → Add**, give the connection a name, leave the recommended "no manual setup" option selected, and paste `Profile 1` into **Chrome profile directory name**.

### Step 3: Point a class at it

When adding or editing a class, pick that connection under **Join using**.

> **Note:** Make sure that Chrome profile is already signed in to the Google account you want to join meetings with.

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
│   └── settings.json         # App settings and Chrome connections
│
├── logs/                     # Log files (gitignored)
│   └── automation.log
│
└── src/                      # Application source code
    ├── paths.py              # Where everything the app writes lives
    ├── logging_setup.py      # Shared logger name and log file
    ├── models.py             # Meeting and JoinResult
    ├── storage.py            # Database operations
    ├── settings.py           # Settings and Chrome connections
    ├── scheduler.py          # Background scheduling engine
    ├── notifier.py           # Desktop notifications
    ├── recurrence.py         # Recurring meeting calculations
    ├── launchers.py          # Chrome launcher script generator
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
        ├── dialogs/          # Add/Edit class, Add/Edit connection
        └── widgets/          # Stat cards, meeting cards, day picker, etc.
```

`data/` and `logs/` sit in the project root when you run from source. In a packaged build they move to your per-user app-data folder (`%LOCALAPPDATA%\EarlyBird` on Windows) so an update that replaces the executable can never take your saved classes with it. The Settings page shows and opens the exact folder in use.

---

# How It Works

A background thread polls your saved classes every 15 seconds. Five minutes before a class, it sends a desktop notification. When the class is due, EarlyBird 🐦:

1. Closes the window it opened for that connection's last meeting.
2. Opens Chrome — its own isolated profile, or the one the class's connection points at.
3. Navigates to the Google Meet link.
4. Turns off the microphone.
5. Turns off the camera.
6. Clicks **Join now**.
7. Marks the class joined, so a recurring one is ready for its next occurrence.

Controls are found by their accessible name rather than screen position, so this keeps working across screen sizes and minor Meet redesigns. If the **Join now** button can't be found, EarlyBird saves a screenshot next to the log to show what it was looking at.

---

# Notes

* Your Google credentials are **never** stored by the application.
* Authentication is handled entirely by your own Chrome profile.
* The application is designed specifically for Google Meet.
* The application must be running for scheduled meetings to be joined automatically.

---

# License

This project is provided for educational and personal use.
