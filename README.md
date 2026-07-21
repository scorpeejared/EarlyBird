# EarlyBird 🐦

EarlyBird 🐦 is a Python desktop application that automatically joins your scheduled Google Meet classes or meetings. Simply add your meeting link, choose a date and time (or make it recurring), and the application will handle the rest.

Designed for students and professionals, the application uses your own Chrome profile so you remain signed into Google while automatically preparing and joining meetings without requiring manual interaction.

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

Supported options include:

* Every Monday
* Every Tuesday
* Every Wednesday
* Every Thursday
* Every Friday
* Multiple selected days
* One-time meetings

After a recurring meeting finishes, the application automatically schedules its next occurrence.

---

## Smart Chrome Profile Management

The application uses a dedicated Chrome profile so you only need to sign into Google once.

It intelligently:

* Reuses the existing Chrome automation session whenever possible.
* Opens new meetings using the same signed-in profile.
* Keeps your Google login between launches.
* Avoids interfering with your normal browsing session.

---

## Automatic Meeting Cleanup

If a previous meeting was accidentally left open, the application automatically cleans up the old meeting before joining the next scheduled one.

This prevents:

* Multiple Google Meet tabs remaining open.
* Joining two meetings simultaneously.
* Accumulating unused browser tabs throughout the day.

---

## Desktop Application

Built with Python and Tkinter.

Features include:

* Add meetings
* Edit meetings
* Delete meetings
* Enable or disable Auto Join
* View upcoming meetings
* Runs quietly in the system tray

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
cd meet-auto-joiner
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

Before using EarlyBird, you need to configure the Chrome profile that will be used to join your meetings.

### Step 1: Open your Chrome profile

Launch Google Chrome using the profile you normally use for Google Meet (the one that's already signed in to your Google account).

### Step 2: Find your profile path

In the Chrome address bar, navigate to:

```text
chrome://version
```

Locate the **Profile Path** field and copy its value.

For example:

```text
C:\Users\YourName\AppData\Local\Google\Chrome\User Data\Profile 1
```

### Step 3: Configure EarlyBird

Open EarlyBird and paste the copied **Profile Path** into the Chrome Profile setting.

### That's it!

Once configured, EarlyBird will:

* Reuse your existing Chrome profile.
* Keep you signed in to your Google account.
* Automatically use the same profile for future meetings.
* Preserve your existing Chrome settings, cookies, and saved sessions.

> **Note:** Make sure the selected Chrome profile is already signed in to the Google account you want to use for joining meetings.

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
├── main.py                  # Entry point (runs the app)
├── requirements.txt         # Python dependencies
│
├── data/                    # User-specific data (gitignored)
│   ├── meetings.db          # SQLite database
│   └── settings.json        # App settings
│
├── logs/                    # Log files (gitignored)
│   └── automation.log
│
└── src/                     # Application source code
    ├── models.py            # Data models (Meeting class)
    ├── storage.py           # Database operations
    ├── settings.py          # Configuration management
    ├── scheduler.py         # Background scheduling engine
    ├── notifier.py          # Desktop notifications
    ├── recurrence.py        # Recurring meeting calculations
    ├── launchers.py         # Chrome launcher script generator
    │
    │
    ├── automation.py    # Playwright browser automation
    ├── automation_uia.py # UI Automation fallback
    ├── cdp_probe.py     # Chrome DevTools Protocol probing
    │
    │
    ├── tray.py          # System tray integration
```

---

# How It Works

When a meeting becomes due, EarlyBird 🐦:

1. Calculates whether the meeting should be joined.
2. Opens (or reuses) the Chrome automation profile.
3. Cleans up any previous meeting tabs if necessary.
4. Navigates to the Google Meet link.
5. Turns off the microphone.
6. Turns off the camera.
7. Clicks **Join now**.
8. Updates recurring meetings to their next scheduled occurrence.

---

# Notes

* Your Google credentials are **never** stored by the application.
* Authentication is handled entirely by your own Chrome profile.
* The application is designed specifically for Google Meet.
* The application must be running for scheduled meetings to be joined automatically.

---

# License

This project is provided for educational and personal use.
