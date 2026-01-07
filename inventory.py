# inventory.py
import os
import json
import random
from constants import INVENTORY_FILE

class DeviceInventory:
    def __init__(self):
        self.db = []
        self.load()

    def load(self):
        if os.path.exists(INVENTORY_FILE):
            try:
                with open(INVENTORY_FILE, "r") as f:
                    self.db = json.load(f)
            except: self.db = []
        else:
            self.db = []

    def save(self):
        with open(INVENTORY_FILE, "w") as f:
            json.dump(self.db, f)

    def add_track(self, path, artist, title, genre, duration):
        # Prevent duplicates
        for track in self.db:
            if track['path'] == path:
                return
        self.db.append({
            'path': path,
            'artist': artist,
            'title': title,
            'genre': genre,
            'duration': duration
        })

    def remove_folder(self, folder_path):
        # Remove all tracks that start with this folder path
        self.db = [t for t in self.db if not t['path'].startswith(folder_path)]
        self.save()

    def generate_mixtape(self, target_minutes, allowed_genres):
        # 1. Filter
        pool = [t for t in self.db if t['genre'] in allowed_genres]
        if not pool: return []

        # 2. Shuffle
        random.shuffle(pool)

        # 3. Fill Bucket
        playlist = []
        current_seconds = 0
        target_seconds = target_minutes * 60

        for track in pool:
            dur = track.get('duration', 0) or 180 # Default 3 mins if unknown
            if current_seconds + dur <= target_seconds:
                playlist.append(track)
                current_seconds += dur
            
            if current_seconds >= target_seconds:
                break
        
        return playlist, current_seconds

    def save_m3u(self, device_root, playlist_data, filename="AutoMix.m3u"):
        # Rockbox playlists go in /.rockbox/Playlists or root
        # We save relative paths with forward slashes
        save_path = os.path.join(device_root, "Playlists")
        os.makedirs(save_path, exist_ok=True)
        full_path = os.path.join(save_path, filename)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for track in playlist_data:
                # Convert absolute device path to relative path
                # e.g. E:\Music\Song.mp3 -> /Music/Song.mp3
                rel_path = os.path.relpath(track['path'], device_root)
                rockbox_path = "/" + rel_path.replace("\\", "/")
                
                f.write(f"#EXTINF:{int(track.get('duration',0))},{track['artist']} - {track['title']}\n")
                f.write(f"{rockbox_path}\n")
        
        return full_path