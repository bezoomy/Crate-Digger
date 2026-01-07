# 🎵 CrateDigger

**A smart music randomizer and sync tool for your iPod and portable devices.**

> **Note:** This project is totally open source! It was originally my idea to solve the problem of large libraries vs. small storage, but I am releasing it to the world. Feel free to fork it, fix it, improve it, or do whatever you like with it.

## 📖 About
**CrateDigger** is a Python desktop application designed for music collectors who have massive local libraries but limited space on their portable devices (like iPods, Walkmans, or SD cards).

Instead of manually dragging and dropping folders, CrateDigger helps you "roll" a random selection of albums based on your preferred genres. It automatically calculates the file sizes and fills your device up to a safety limit (e.g., leaving exactly 200MB free), ensuring you maximize space without crashing your device's database.

## ✨ Key Features
* **🎲 Storage-Aware Randomizer:** Automatically selects random albums to fill your device until it hits a specific free-space safety margin.
* **📂 Genre Canonicalization:** Maps messy metadata (e.g., "90s Alt Rock", "Indie Pop") into clean, main categories (e.g., "Rock", "Pop") for better folder sorting on the device.
* **🎨 Automatic Art Fetcher:** Identifies albums missing cover art and automatically fetches them from MusicBrainz/CoverArtArchive.
* **🏷️ Tag & Genre Correction:** Verify and update MP3 tags directly within the app.
* **🎛️ Playlist Generator:** Create "Mixtape" M3U playlists based on duration (e.g., "Make me a 60-minute Rock playlist").
* **🚀 Smart Syncing:** specific logic to handle file copying, ensuring existing albums aren't re-copied to save time.
* **🎧 Instant Preview:** Right-click any album to open the folder or preview a track instantly.

## 🛠️ Installation

### Prerequisites
* Python 3.8+
* `pip`

### Setup
1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/yourusername/cratedigger.git](https://github.com/yourusername/cratedigger.git)
    cd cratedigger
    ```

2.  **Install dependencies:**
    ```bash
    pip install PySide6 mutagen requests
    ```

3.  **Run the application:**
    ```bash
    python main.py
    ```

## 📦 Basic Usage
1.  **Select Folders:** Point the app to your computer's Music Library and your Device's root folder.
2.  **Scan:** Click "Scan Library" to index your music.
3.  **Filter:** Select which genres you want to include in the random roll.
4.  **Roll:** Click the dice icon! The app will select albums until your device is full.
5.  **Copy:** Click "Start Copy" to move the files to your device.

## 📦 Genre Tag Fixing
1.  **Select Folders:** Point the app to your computer's Music Library and your Device's root folder.
2.  **Scan:** Click "Scan Library" to index your music.
3.  **Filter:** Select which genres you want to include in the random roll.
4.  **Roll:** Click the dice icon! The app will select albums until your device is full.
5.  **Copy:** Click "Start Copy" to move the files to your device.

## 🤝 Contributing
I threw this code together to solve a specific need, but there is plenty of room for improvement!

* **Found a bug?** Please open an issue.
* **Have a feature idea?** Fork the repo and submit a Pull Request.
* **UI/UX:** If you are good with PySide6 styling, feel free to make it look prettier!

## 📜 License & Credits
**Original Concept by:** BEZOOMY

This project is open source. You are free to use, modify, distribute, and sell this software.