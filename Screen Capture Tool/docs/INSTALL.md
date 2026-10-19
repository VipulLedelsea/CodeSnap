# Installing CodeSnap

For anyone who just wants to use it. About five minutes. You need a Mac (macOS 12 or later) and an Anthropic API key.

## 1. Install

1. Open **CodeSnap-macOS.dmg**.
2. Drag **CodeSnap** onto **Applications**.
3. Open it from Applications (not from the disk image or Downloads).
4. The first time, macOS may say it cannot verify the developer. **Right-click CodeSnap → Open → Open.** You only do this once.
   (A build signed with a Developer ID opens with no warning.)

## 2. Allow what it needs

CodeSnap shows a banner at the top until these three are on. Each button opens the right page of System Settings:

| Permission | Why |
|---|---|
| **Screen Recording** | to read the code on your screen |
| **Accessibility** | so CodeSnap can work with your editor window |
| **Input Monitoring** | so the capture hotkeys can hear your key presses |

Turn **CodeSnap** on in each list. **Input Monitoring only takes effect after you quit and reopen CodeSnap.**

## 3. Add your API key

Paste your key (it starts with `sk-ant-`) into the one-time setup box and press **Save key**. It is stored only on your Mac, in `~/.codesnap/.env`.

## 4. Capture something

1. Open the file you want in your editor and make the code fill the window. A larger, clear font reads best.
2. In CodeSnap, open **Platform Holistic Review**, pick or create a **program**, and press **Pick code area** to draw a box around only the code.
3. Press **Start capture**, switch to your editor, and scroll slowly from the first line to the last. CodeSnap scrolls to the top for you before it starts.
4. Press **Cmd+Shift+9** (or Stop in the app) when you reach the end. Reading takes a minute or two per file.
5. When every file is read, press **View report** or download the Word / PDF report and the executive summary.

Before you send a report on, open **Report details** (the note next to the download links tells you what is still blank) and fill in the client, engagement and application ID.

## Hotkeys

| Keys | What it does |
|---|---|
| Cmd+Shift+1 | start / stop a capture |
| Cmd+Shift+0 | pause / resume |
| Cmd+Shift+9 | quit the capture |

## Where things are kept

Everything lives in **~/CodeSnap**: your programs, scratch screenshots and exported reports. Deleting or updating the app never touches it.

## If something is off

- **"Needs attention" on a file**: open it and choose *Review with screenshots*. CodeSnap lines up the screenshot with the text and asks one question at a time.
- **Hotkeys do nothing**: Input Monitoring is off for CodeSnap (see step 2), or you have not quit and reopened the app since turning it on. After an update that is not signed with a Developer ID, macOS treats the app as new: run `tccutil reset All com.ledelsea.codesnap` in Terminal, reopen CodeSnap and grant the permissions again.
- **The capture is blank or shows only the desktop**: Screen Recording is off for CodeSnap.
- **Settings → About** shows the version and where your data is. Include it when you ask for help.
