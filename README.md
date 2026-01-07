# 🎵 CrateDigger

**A smart music randomizer and sync tool for your iPod and portable devices.**

> **Note:** This project is open source! Feel free to fork it, fix it, or improve it.

## 📖 About
**CrateDigger** is a Python desktop application for music collectors. Instead of manually dragging and dropping folders, CrateDigger helps you "roll" a random selection of albums based on your preferred genres.

It automatically calculates file sizes and fills your device up to a safety limit (e.g., leaving around 500MB free), ensuring you maximize space without crashing your device's database.

### 💡 Why I Built This: The Cure for Decision Fatigue

> We've all been there: You have **2TB** of music on your hard drive, but your portable player only holds **128GB**. You spend hours staring at your library, trying to curate the "perfect" sync list, only to end up listening to the same 10 albums.
>
> **CrateDigger** solves the "Analysis Paralysis" of the music hoarder. It takes the decision-making out of the equation, rolling the dice to fill your device with a fresh mix of forgotten gems and old favorites—instantly.

## ✨ Key Features
* **🎲 Storage-Aware Randomizer:** Automatically selects random albums to fill your device until it hits a specific free-space safety margin.
* **📂 Genre Canonicalization:** Maps messy metadata (e.g., "90s Alt Rock", "Indie Pop") into clean, main categories (e.g., "Rock", "Pop") for better folder sorting.
* **🎨 Automatic Art Fetcher:** Identifies albums missing cover art and automatically fetches them from MusicBrainz/CoverArtArchive.
* **🏷️ Tag & Genre Correction:** Verify and update MP3 tags directly within the app.
* **🎛️ Playlist Generator:** Create "Mixtape" M3U playlists based on duration (e.g., "Make me a 60-minute Rock playlist").
* **🚀 Smart Syncing:** Logic checks for existing albums to avoid re-copying files.

---

## 🛠️ Installation

### Prerequisites
* Python 3.8 or higher
* `pip` (Python package manager)

### Setup Steps
1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/bezoomy/Crate-Digger.git](https://github.com/bezoomy/Crate-Digger.git)
    cd Crate-Digger
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(If `requirements.txt` is missing, run: `pip install PySide6 mutagen requests`)*

3.  **Run the application:**
    ```bash
    python main.py
    ```

---

## 📖 User Guide

### 🚀 Quick Start: "Just Fill My iPod"
Follow these steps to instantly fill your device with a random selection of music.

1.  **Select Paths:**
    * Click **🎵 Select Music Library** and choose the folder on your computer where your MP3s live.
    * Click **📱 Select Device (Root)** and pick your device drive (e.g., `E:/`).
    * *Note: If your device is empty, the app will offer to create a 'Music' folder for you.*

2.  **Scan:**
    * Click **🔍 Scan Library**. The app will index your albums and sort them into clean categories (Rock, Pop, Electronic, etc.).

3.  **Roll:**
    * Click **🎲 Roll Random Albums**.
    * The app will select albums until your device is full (leaving a safety buffer of free space).

4.  **Sync:**
    * Click **🚀 Start Copy**.
    * The app will copy the files. It automatically skips albums that are already on the device to save time.

### 🎛️ The "Filter & Roll" Section
Located at the bottom of the window, these controls determine exactly which albums get picked during the randomization process.

* **Genre Selection (Left List):** Uncheck any genre here to exclude it completely. (e.g., Uncheck "Holiday" to ensure Christmas music isn't synced in July).
* **Max/Artist (Dropdown):** Limits how many albums from a single artist can be picked.
    * *Example:* Set to **3**. If the randomizer picks 3 David Bowie albums, it will stop picking Bowie and move to other artists.
* **Include Text:** Prioritizes albums containing these words (e.g., `Best Of`).
* **Exclude Text:** Skips any album containing these words (e.g., `Live`, `Demo`).
* **Skip Existing:** If checked, the app will not try to re-copy albums that are already on the device.

### 🏷️ Editing Genres & Categories
Your music library probably has messy genres. CrateDigger groups these into clean **Main Categories** (e.g., "Rock") so your device folders stay organized.

1.  Click **🏷️ Edit Genres** at the top.
2.  **Categories (Left):** These are the folder names that will appear on your device.
3.  **Keywords (Right):** These are the raw genre names found in your MP3 tags.
    * *Logic:* If you map "grunge" to the "Rock" category, any album tagged "Grunge" will be sorted into the "Rock" folder on your device.

### 🛠️ Correction & Tagging Tools
Use the middle column to fix specific albums.

* **Manual Override:** Select an album and use the **Main** dropdown to change its sorting folder.
* **Update File Tags:** Check the box **"Update File Tags"** and click **✏️ Apply Override** to permanently update the ID3 tags in your MP3 files.
* **Find Online:** Click **🌍 Find Online** to search MusicBrainz. This will suggest the correct genre and **automatically download cover art** for you.
* **Context Menu:** Right-click any album in the list to **Open Folder** or **Preview Track**.

### ⚡ Extra Tools
* **Mixtape Generator:** Create a random `.m3u` playlist based on a specific duration (e.g., 60 minutes).
* **Device Manager:** Visualize storage usage and manually delete folders to free up space.

---

## 📜 License
This project is open source. You are free to use, modify, distribute, and sell this software.