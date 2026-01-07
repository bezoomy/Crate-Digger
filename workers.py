# workers.py
import os
import shutil
import time
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from PySide6.QtCore import QThread, Signal

# Try importing Pillow for Image Resizing
try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    import musicbrainzngs
    HAS_MUSICBRAINZ = True
except ImportError:
    HAS_MUSICBRAINZ = False

from constants import PROTECTED_FOLDERS, SAFETY_MARGIN_MB, MB, suggest_canonical

def folder_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try: total += os.path.getsize(os.path.join(root, f))
            except: pass
    return total

def album_genre(album_path):
    for f in os.listdir(album_path):
        if f.lower().endswith(".mp3"):
            try:
                tags = EasyID3(os.path.join(album_path, f))
                return tags.get("genre", [""])[0]
            except: return ""
    return ""

# --- Workers ---

class ScanWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    result = Signal(list, list)

    def __init__(self, music_dir, genre_dict):
        super().__init__()
        self.music_dir = music_dir
        self.genre_dict = genre_dict

    def run(self):
        album_db = []
        try:
            artists = [os.path.join(self.music_dir, a) for a in os.listdir(self.music_dir)
                       if os.path.isdir(os.path.join(self.music_dir, a)) and not a.startswith('.')]
        except OSError: artists = []

        total = len(artists) or 1
        scanned = 0
        for i, artist_path in enumerate(artists):
            artist = os.path.basename(artist_path)
            try: albums = os.listdir(artist_path)
            except: continue

            for album in albums:
                if album.startswith('.'): continue
                album_path = os.path.join(artist_path, album)
                if not os.path.isdir(album_path): continue

                if scanned % 5 == 0: self.status.emit(f"Scanning: {artist} — {album}")
                raw_genre = album_genre(album_path)
                size = folder_size(album_path)
                album_db.append((album_path, artist, album, raw_genre, size))
                scanned += 1
            self.progress.emit(int((i + 1) / total * 90))

        self.status.emit("Analyzing genres...")
        from collections import Counter
        cnt = Counter()
        for _, _, _, raw, _ in album_db: cnt[raw] += 1
        
        stats = []
        total_stats = len(cnt)
        for idx, (raw, c) in enumerate(cnt.items()):
            canon, score = suggest_canonical(raw, self.genre_dict)
            stats.append((raw, canon, score, c))
            if idx % 10 == 0 and total_stats > 0: self.progress.emit(90 + int((idx / total_stats) * 10))
                
        stats.sort(key=lambda x: -x[3])
        self.progress.emit(100)
        self.result.emit(album_db, stats)

class CopyWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    copy_finished = Signal()
    track_copied = Signal(str, str, str, str, float)

    def __init__(self, albums, device_dir, skip_existing, genre_dict):
        super().__init__()
        self.albums = albums
        self.device_dir = device_dir
        self.skip_existing = skip_existing
        self.genre_dict = genre_dict
        self.paused = False
        self.cancelled = False

    def run(self):
        total_albums = len(self.albums)
        for idx, (path, artist, album, raw_genre, _) in enumerate(self.albums):
            if self.cancelled: break
            dest_artist = os.path.join(self.device_dir, artist)
            dest_album = os.path.join(dest_artist, album)
            
            canon_genre, _ = suggest_canonical(raw_genre, self.genre_dict)

            if any(p in album.lower() for p in PROTECTED_FOLDERS): continue
            
            if self.skip_existing and os.path.exists(dest_album):
                self.progress.emit(int((idx + 1) / total_albums * 100))
                continue
            
            try:
                if shutil.disk_usage(self.device_dir).free < SAFETY_MARGIN_MB * MB:
                    self.status.emit("⚠️ Disk full"); break
            except: pass
            
            self.status.emit(f"Copying [{idx+1}/{total_albums}]: {artist} - {album}")
            os.makedirs(dest_album, exist_ok=True)
            
            # Artwork Handling
            art_src = None
            for f in os.listdir(path):
                if f.lower() in ["folder.jpg", "cover.jpg", "front.jpg", "album.jpg"]:
                    art_src = os.path.join(path, f)
                    break
            
            if art_src and HAS_PILLOW:
                try:
                    img = Image.open(art_src)
                    img = img.resize((200, 200), Image.Resampling.LANCZOS)
                    img = img.convert('RGB')
                    img.save(os.path.join(dest_album, "cover.bmp"))
                except: pass
            
            for root, _, files in os.walk(path):
                rel_path = os.path.relpath(root, path)
                dest_root = os.path.join(dest_album, rel_path)
                os.makedirs(dest_root, exist_ok=True)
                
                for file in files:
                    if file.startswith('.') or not file.lower().endswith('.mp3'): continue
                    if self.cancelled: return
                    while self.paused: time.sleep(0.1)
                    
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(dest_root, file)
                    
                    try: 
                        shutil.copy2(src_file, dst_file)
                        try:
                            audio = MP3(dst_file)
                            dur = audio.info.length
                            tags = EasyID3(dst_file)
                            t_title = tags.get('title', [file])[0]
                            t_artist = tags.get('artist', [artist])[0]
                            self.track_copied.emit(dst_file, t_artist, t_title, canon_genre, dur)
                        except: pass
                    except: pass
            
            self.progress.emit(int((idx + 1) / total_albums * 100))
        
        self.status.emit("Copy cancelled" if self.cancelled else "Copy complete!")
        self.copy_finished.emit()
    
    def pause(self): self.paused = True
    def resume(self): self.paused = False
    def cancel(self): self.cancelled = True

class DeleteWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    del_finished = Signal()
    folder_deleted = Signal(str)

    def __init__(self, paths_to_delete):
        super().__init__()
        self.paths = paths_to_delete

    def run(self):
        total = len(self.paths)
        if total == 0: self.del_finished.emit(); return
        for i, path in enumerate(self.paths):
            folder_name = os.path.basename(path)
            self.status.emit(f"Deleting: {folder_name}")
            try:
                if os.path.isdir(path): 
                    shutil.rmtree(path)
                    self.folder_deleted.emit(path)
                else: 
                    os.remove(path)
            except Exception as e: print(f"Error: {e}")
            self.progress.emit(int((i + 1) / total * 100))
        self.status.emit("Deletion complete.")
        self.del_finished.emit()

class GenreSearchWorker(QThread):
    progress = Signal(str)
    finished = Signal(list)

    def __init__(self, items_to_search, email):
        super().__init__()
        self.items = items_to_search 
        self.email = email

    def run(self):
        if not HAS_MUSICBRAINZ: self.finished.emit([]); return
        musicbrainzngs.set_useragent("CrateDigger", "1.0", self.email)
        results = []
        total = len(self.items)
        for idx, (path, artist, album, current_genre) in enumerate(self.items):
            self.progress.emit(f"Searching [{idx+1}/{total}]: {artist} - {album}")
            try:
                resp = musicbrainzngs.search_release_groups(artist=artist, release=album, limit=1)
                if resp['release-group-list']:
                    rg = resp['release-group-list'][0]
                    rg_id = rg['id']
                    
                    details = musicbrainzngs.get_release_group_by_id(rg_id, includes=["tags"])
                    
                    best_tag = "Unknown"
                    if "tag-list" in details["release-group"]:
                        tags = details["release-group"]["tag-list"]
                        tags.sort(key=lambda x: int(x.get("count", 0)), reverse=True)
                        if tags: best_tag = tags[0]["name"].title()
                    
                    results.append({
                        "path": path, 
                        "artist": artist, 
                        "album": album,
                        "current": current_genre, 
                        "found": best_tag,
                        "mbid": rg_id 
                    })
                time.sleep(1.1)
            except Exception as e: print(f"Err: {e}"); time.sleep(1)
        self.finished.emit(results)

class DeviceScanWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    track_found = Signal(str, str, str, str, float)
    scan_finished = Signal()

    def __init__(self, device_dir, genre_dict, genre_map):
        super().__init__()
        self.device_dir = device_dir
        self.genre_dict = genre_dict
        self.genre_map = genre_map

    def run(self):
        scan_root = os.path.join(self.device_dir, "Music")
        if not os.path.exists(scan_root): scan_root = self.device_dir
        
        self.status.emit("Discovering files...")
        all_files = []
        count = 0
        for root, _, files in os.walk(scan_root):
            for f in files:
                if f.lower().endswith(".mp3"):
                    all_files.append(os.path.join(root, f))
                    count += 1
                    if count % 50 == 0: self.status.emit(f"Found {count} files...")
        
        total = len(all_files)
        if total == 0: self.scan_finished.emit(); return

        for i, path in enumerate(all_files):
            filename = os.path.basename(path)
            self.status.emit(f"[{i+1}/{total}] Indexing: {filename}")
            self.progress.emit(int((i/total)*100))
            
            try:
                audio = MP3(path)
                dur = audio.info.length
                tags = EasyID3(path)
                title = tags.get('title', [filename])[0]
                artist = tags.get('artist', ["Unknown"])[0]
                raw_genre = tags.get('genre', ["Unknown"])[0]
                
                if raw_genre in self.genre_map:
                    canon = self.genre_map[raw_genre]
                else:
                    canon, _ = suggest_canonical(raw_genre, self.genre_dict)
                
                self.track_found.emit(path, artist, title, canon, dur)
            except: pass
            
        self.scan_finished.emit()

# NEW: Worker to write tags to files in background
class TagWriterWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal()

    def __init__(self, items, new_genre):
        super().__init__()
        self.items = items # List of folder paths
        self.new_genre = new_genre

    def run(self):
        total = len(self.items)
        for i, folder_path in enumerate(self.items):
            self.status.emit(f"Updating tags in: {os.path.basename(folder_path)}")
            for root, _, files in os.walk(folder_path):
                for f in files:
                    if f.lower().endswith('.mp3'):
                        try:
                            path = os.path.join(root, f)
                            tags = EasyID3(path)
                            tags['genre'] = self.new_genre
                            tags.save()
                        except: pass
            self.progress.emit(int((i + 1) / total * 100))
        self.finished.emit()