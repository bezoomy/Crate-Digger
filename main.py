# main.py
import sys
import os
import shutil
import json
import random
import time
import urllib.request
from collections import Counter

from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout,
    QFileDialog, QProgressBar, QListWidget, QListWidgetItem,
    QCheckBox, QTableWidget, QTableWidgetItem, QComboBox, QSplitter, QLineEdit,
    QMessageBox, QDialog, QDialogButtonBox, QHeaderView, QInputDialog, QAbstractItemView,
    QSlider, QSpinBox, QFrame, QGridLayout, QRadioButton, QButtonGroup, QMenu
)
from PySide6.QtCore import Qt, QThread, Signal, QRunnable, QThreadPool, QObject, QSize, QUrl
from PySide6.QtGui import QColor, QBrush, QPixmap, QAction, QDesktopServices

from constants import (
    DEFAULT_GENRES, MB, SAFETY_MARGIN_MB, PROTECTED_FOLDERS,
    load_settings, save_settings, suggest_canonical, safe_eject
)
from workers import ScanWorker, CopyWorker, DeleteWorker, GenreSearchWorker, DeviceScanWorker, TagWriterWorker, HAS_MUSICBRAINZ
from inventory import DeviceInventory

# --- Helper: Worker Signals for Threading ---
class WorkerSignals(QObject):
    result = Signal(int, object, bytes) # row_index, pixmap, raw_data

# --- Helper: Runnable for fetching individual covers ---
class ArtFetchRunnable(QRunnable):
    def __init__(self, row, mbid):
        super().__init__()
        self.row = row
        self.mbid = mbid
        self.signals = WorkerSignals()

    def run(self):
        try:
            # 1. Try to get the 250px thumbnail first (faster)
            url = f"https://coverartarchive.org/release-group/{self.mbid}/front-250"
            req = urllib.request.Request(url, headers={'User-Agent': 'CrateDigger/1.0'})
            data = urllib.request.urlopen(req, timeout=10).read()
            
            # 2. Convert to Pixmap for display
            pix = QPixmap()
            pix.loadFromData(data)
            
            # 3. Return the row, the image, and the raw bytes (for saving later)
            self.signals.result.emit(self.row, pix, data)
        except:
            # If failed, send None
            self.signals.result.emit(self.row, None, None)

# --- Dialog Classes ---

class PlaylistGenerator(QDialog):
    def __init__(self, inventory, device_dir, canonical_genres, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mixtape Generator")
        self.resize(600, 500)
        self.inventory = inventory
        self.device_dir = device_dir
        self.genres = canonical_genres
        
        layout = QVBoxLayout(self)
        
        self.status_lbl = QLabel(f"Inventory: {len(self.inventory.db)} tracks indexed.")
        layout.addWidget(self.status_lbl)
        
        self.sync_btn = QPushButton("🔄 Sync Inventory (Scan Device)")
        self.sync_btn.clicked.connect(self.start_sync)
        layout.addWidget(self.sync_btn)
        
        grid = QHBoxLayout()
        g_wid = QWidget(); gl = QVBoxLayout(g_wid)
        gl.addWidget(QLabel("<b>Include Genres:</b>"))
        
        sel_row = QHBoxLayout()
        btn_all = QPushButton("All"); btn_all.clicked.connect(self.sel_all)
        btn_none = QPushButton("None"); btn_none.clicked.connect(self.sel_none)
        sel_row.addWidget(btn_all); sel_row.addWidget(btn_none)
        gl.addLayout(sel_row)
        
        self.g_list = QListWidget()
        for g in sorted(self.genres.keys()) + ["Other"]:
            it = QListWidgetItem(g)
            it.setCheckState(Qt.Checked)
            self.g_list.addItem(it)
        gl.addWidget(self.g_list)
        
        t_wid = QWidget(); tl = QVBoxLayout(t_wid)
        tl.addWidget(QLabel("<b>Duration (Minutes):</b>"))
        
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(10, 300)
        self.time_slider.setValue(60)
        self.time_spin = QSpinBox()
        self.time_spin.setRange(10, 300)
        self.time_spin.setValue(60)
        
        self.time_slider.valueChanged.connect(self.time_spin.setValue)
        self.time_spin.valueChanged.connect(self.time_slider.setValue)
        
        tl.addWidget(self.time_slider); tl.addWidget(self.time_spin); tl.addStretch()
        grid.addWidget(g_wid); grid.addWidget(t_wid)
        layout.addLayout(grid)

        nl = QHBoxLayout()
        nl.addWidget(QLabel("Playlist Name:"))
        self.name_input = QLineEdit(); self.name_input.setText("Mixtape.m3u")
        nl.addWidget(self.name_input)
        layout.addLayout(nl)
        
        self.prog = QProgressBar(); self.prog.hide()
        layout.addWidget(self.prog)
        
        self.gen_btn = QPushButton("🎲 Generate & Save Playlist")
        self.gen_btn.setStyleSheet("font-size: 14pt; padding: 10px; font-weight: bold;")
        self.gen_btn.clicked.connect(self.generate)
        layout.addWidget(self.gen_btn)

    def sel_all(self):
        for i in range(self.g_list.count()): self.g_list.item(i).setCheckState(Qt.Checked)
    def sel_none(self):
        for i in range(self.g_list.count()): self.g_list.item(i).setCheckState(Qt.Unchecked)

    def start_sync(self):
        if not self.device_dir: return
        self.sync_btn.setEnabled(False); self.gen_btn.setEnabled(False); self.prog.show()
        self.inventory.db = []
        main_app = self.parent()
        user_map = main_app.genre_map if main_app else {}
        self.worker = DeviceScanWorker(self.device_dir, self.genres, user_map)
        self.worker.progress.connect(self.prog.setValue)
        self.worker.status.connect(self.status_lbl.setText)
        self.worker.track_found.connect(self.inventory.add_track)
        self.worker.scan_finished.connect(self.sync_done)
        self.worker.start()

    def sync_done(self):
        self.inventory.save()
        self.sync_btn.setEnabled(True); self.gen_btn.setEnabled(True); self.prog.hide()
        self.status_lbl.setText(f"Inventory: {len(self.inventory.db)} tracks ready.")
        QMessageBox.information(self, "Done", "Device scan complete!")

    def generate(self):
        if not self.inventory.db: QMessageBox.warning(self, "Empty", "Please Sync Inventory first!"); return
        allowed = [self.g_list.item(i).text() for i in range(self.g_list.count()) if self.g_list.item(i).checkState() == Qt.Checked]
        mins = self.time_spin.value()
        tracks, seconds = self.inventory.generate_mixtape(mins, allowed)
        if not tracks: QMessageBox.information(self, "Oops", "No matching tracks found."); return
        fname = self.name_input.text().strip()
        if not fname.lower().endswith(".m3u"): fname += ".m3u"
        path = self.inventory.save_m3u(self.device_dir, tracks, fname)
        QMessageBox.information(self, "Success", f"Created playlist '{fname}' with {len(tracks)} tracks ({int(seconds/60)}m).\nSaved to: {path}")
        self.accept()

class UnknownGenreDialog(QDialog):
    def __init__(self, unknowns, categories, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Genres Found")
        self.resize(600, 400)
        self.table = QTableWidget(len(unknowns), 2)
        self.table.setHorizontalHeaderLabels(["Found Genre", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout = QVBoxLayout(self); layout.addWidget(self.table)
        cat_list = sorted(categories.keys())
        for r, genre in enumerate(unknowns):
            self.table.setItem(r, 0, QTableWidgetItem(genre))
            combo = QComboBox()
            combo.addItem(f"New Category: '{genre}'", "new")
            for cat in cat_list: combo.addItem(f"Add to '{cat}'", cat)
            combo.addItem("Ignore", "ignore")
            gl = genre.lower()
            for i in range(combo.count()):
                if combo.itemData(i) in cat_list and combo.itemData(i).lower() in gl: combo.setCurrentIndex(i); break
            self.table.setCellWidget(r, 1, combo)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)
    def get_decisions(self):
        res = {}
        for r in range(self.table.rowCount()): res[self.table.item(r, 0).text()] = self.table.cellWidget(r, 1).currentData()
        return res

class GenreEditor(QDialog):
    def __init__(self, current_genres, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Genre Definitions")
        self.resize(800, 600)
        self.genres = json.loads(json.dumps(current_genres))
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget(); ll = QVBoxLayout(left); ll.addWidget(QLabel("Categories"))
        self.cat_list = QListWidget(); self.cat_list.itemClicked.connect(self.load_keywords)
        ll.addWidget(self.cat_list)
        lb = QHBoxLayout(); addc = QPushButton("Add"); delc = QPushButton("Remove")
        addc.clicked.connect(self.add_cat); delc.clicked.connect(self.del_cat)
        lb.addWidget(addc); lb.addWidget(delc); ll.addLayout(lb)
        right = QWidget(); rl = QVBoxLayout(right); self.kw_label = QLabel("Keywords")
        rl.addWidget(self.kw_label); self.kw_list = QListWidget()
        rl.addWidget(self.kw_list)
        rb = QHBoxLayout(); addk = QPushButton("Add"); delk = QPushButton("Remove")
        addk.clicked.connect(self.add_kw); delk.clicked.connect(self.del_kw)
        rb.addWidget(addk); rb.addWidget(delk); rl.addLayout(rb)
        splitter.addWidget(left); splitter.addWidget(right); layout.addWidget(splitter)
        bbox = QHBoxLayout(); rst = QPushButton("Reset"); sav = QPushButton("Save"); can = QPushButton("Cancel")
        rst.clicked.connect(self.reset); sav.clicked.connect(self.accept); can.clicked.connect(self.reject)
        bbox.addWidget(rst); bbox.addStretch(); bbox.addWidget(sav); bbox.addWidget(can)
        layout.addLayout(bbox)
        self.refresh()
    def refresh(self):
        curr = self.cat_list.currentItem().text() if self.cat_list.currentItem() else None
        self.cat_list.clear()
        for c in sorted(self.genres.keys()): self.cat_list.addItem(c)
        if curr: 
            items = self.cat_list.findItems(curr, Qt.MatchExactly)
            if items: self.cat_list.setCurrentItem(items[0]); self.load_keywords(items[0])
    def load_keywords(self, item):
        cat = item.text(); self.kw_label.setText(f"Keywords for {cat}")
        self.kw_list.clear()
        for k in sorted(self.genres[cat]): self.kw_list.addItem(k)
    def add_cat(self):
        t, ok = QInputDialog.getText(self, "New", "Name:"); 
        if ok and t and t not in self.genres: self.genres[t]=[]; self.refresh()
    def del_cat(self):
        r = self.cat_list.currentRow(); 
        if r>=0 and QMessageBox.question(self,"Confirm","Delete?")==QMessageBox.Yes: del self.genres[self.cat_list.item(r).text()]; self.refresh()
    def add_kw(self):
        if not self.cat_list.currentItem(): return
        c = self.cat_list.currentItem().text(); t, ok = QInputDialog.getText(self, "New", f"Add to {c}:")
        if ok and t: self.genres[c].append(t.lower()); self.load_keywords(self.cat_list.currentItem())
    def del_kw(self):
        if self.cat_list.currentItem() and self.kw_list.currentItem():
            self.genres[self.cat_list.currentItem().text()].remove(self.kw_list.currentItem().text())
            self.load_keywords(self.cat_list.currentItem())
    def reset(self):
        if QMessageBox.question(self,"Reset","Reset defaults?")==QMessageBox.Yes: 
            self.genres = json.loads(json.dumps(DEFAULT_GENRES)); self.refresh()

# --- Auto-Downloading Preview Dialog ---
class GenrePreviewDialog(QDialog):
    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Genre & Art Preview")
        self.resize(1100, 700)
        self.results = results
        self.applied_changes = []
        
        # Thread pool for parallel downloads
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(4) # Download 4 at a time
        
        layout = QVBoxLayout(self)
        
        # Instructions
        info = QLabel("<b>Review Changes:</b><br>Cover art is downloading automatically. Uncheck any you DO NOT want to save.")
        layout.addWidget(info)
        
        # The Table
        self.table = QTableWidget(len(results), 5)
        self.table.setIconSize(QSize(80, 80)) 
        self.table.setHorizontalHeaderLabels(["Artist", "Album", "Genre Change", "Write Genre?", "Save Cover?"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(90) # Taller rows
        
        for r, res in enumerate(results):
            # 1. Artist
            self.table.setItem(r, 0, QTableWidgetItem(res['artist']))
            
            # 2. Album
            self.table.setItem(r, 1, QTableWidgetItem(res['album']))
            
            # 3. Genre Info
            old = res['current'] or "-"
            gt = f"{old} \n⬇\n {res['found']}"
            g_item = QTableWidgetItem(gt)
            g_item.setTextAlignment(Qt.AlignCenter)
            if old.lower() != res['found'].lower():
                g_item.setBackground(QColor(230, 255, 230)) # Green tint if changing
            self.table.setItem(r, 2, g_item)
            
            # 4. Genre Checkbox
            w_gen = QWidget(); l_gen = QHBoxLayout(w_gen); c_gen = QCheckBox()
            c_gen.setChecked(True)
            l_gen.addWidget(c_gen); l_gen.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(r, 3, w_gen)
            
            # 5. Art Checkbox + Preview Placeholder
            # Check if we already have local art
            has_local = False
            try:
                for f in os.listdir(res['path']):
                    if f.lower() in ["folder.jpg", "cover.jpg", "front.jpg"]: has_local = True; break
            except: pass

            w_art = QWidget(); l_art = QVBoxLayout(w_art); 
            l_art.setContentsMargins(2, 2, 2, 2)
            
            if has_local:
                lbl = QLabel("Existing Art"); lbl.setStyleSheet("color: green; font-weight: bold;")
                l_art.addWidget(lbl); l_art.setAlignment(Qt.AlignCenter)
                self.table.item(r, 0).setData(Qt.UserRole + 2, "skip") # Mark to skip download
            elif 'mbid' not in res or not res['mbid']:
                lbl = QLabel("No ID"); lbl.setStyleSheet("color: gray;")
                l_art.addWidget(lbl); l_art.setAlignment(Qt.AlignCenter)
                self.table.item(r, 0).setData(Qt.UserRole + 2, "skip")
            else:
                # Setup for download
                c_art = QCheckBox("Save?")
                c_art.setChecked(True) # Default to YES
                l_art.addWidget(c_art)
                
                # Placeholder Label for Image
                img_lbl = QLabel("Downloading...")
                img_lbl.setAlignment(Qt.AlignCenter)
                img_lbl.setStyleSheet("font-size: 9pt; color: gray;")
                l_art.addWidget(img_lbl)
                
                l_art.setAlignment(Qt.AlignCenter)
                
                # Store references to update later
                self.table.item(r, 0).setData(Qt.UserRole + 2, "download") # Mark for download
            
            self.table.setCellWidget(r, 4, w_art)
            self.table.item(r, 0).setData(Qt.UserRole, res) # Store full data
            
        layout.addWidget(self.table)
        
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.save_all)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
        # Start Downloads immediately
        self.start_downloads()

    def start_downloads(self):
        for r in range(self.table.rowCount()):
            status = self.table.item(r, 0).data(Qt.UserRole + 2)
            if status == "download":
                data = self.table.item(r, 0).data(Qt.UserRole)
                worker = ArtFetchRunnable(r, data['mbid'])
                worker.signals.result.connect(self.update_row_art)
                self.thread_pool.start(worker)

    def update_row_art(self, row, pixmap, raw_data):
        # This runs when a download finishes
        widget = self.table.cellWidget(row, 4)
        if not widget: return
        
        img_lbl = widget.findChild(QLabel)
        checkbox = widget.findChild(QCheckBox)
        
        if pixmap and not pixmap.isNull():
            # Update the label with the image
            img_lbl.setText("")
            img_lbl.setPixmap(pixmap.scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            
            # Store raw bytes in the item so we don't have to download again on save
            self.table.item(row, 0).setData(Qt.UserRole + 3, raw_data)
        else:
            img_lbl.setText("No Art Found")
            if checkbox: checkbox.setChecked(False); checkbox.setEnabled(False)

    def save_all(self):
        from mutagen.easyid3 import EasyID3
        
        # Show a quick spinner while writing to disk
        prog = QDialog(self); prog.setWindowTitle("Saving..."); prog.resize(300, 100)
        pl = QVBoxLayout(prog); pl.addWidget(QLabel("Applying changes to files..."))
        prog.show()
        QApplication.processEvents()
        
        count_tags = 0
        count_art = 0
        
        for r in range(self.table.rowCount()):
            d = self.table.item(r, 0).data(Qt.UserRole)
            
            # 1. Save Genre
            w_gen = self.table.cellWidget(r, 3)
            if w_gen and w_gen.findChild(QCheckBox).isChecked():
                try:
                    for root, _, files in os.walk(d['path']):
                        for f in files:
                            if f.lower().endswith('.mp3'):
                                try: 
                                    a = EasyID3(os.path.join(root, f))
                                    a['genre'] = d['found']
                                    a.save()
                                except: pass
                    self.applied_changes.append({"path": d['path'], "new_genre": d['found']})
                    count_tags += 1
                except: pass
            
            # 2. Save Art
            w_art = self.table.cellWidget(r, 4)
            cb_art = w_art.findChild(QCheckBox)
            
            # Only save if checkbox exists, is checked, and we actually have data
            raw_data = self.table.item(r, 0).data(Qt.UserRole + 3)
            
            if cb_art and cb_art.isChecked() and raw_data:
                try:
                    save_path = os.path.join(d['path'], "folder.jpg")
                    with open(save_path, 'wb') as f:
                        f.write(raw_data)
                    count_art += 1
                except Exception as e:
                    print(f"Write Error: {e}")

        prog.close()
        QMessageBox.information(self, "Complete", f"Updated {count_tags} Genres.\nSaved {count_art} Covers.")
        self.accept()

class DeviceManager(QDialog):
    def __init__(self, device_dir, parent=None):
        super().__init__(parent)
        self.device_dir = device_dir; self.parent_app = parent
        self.setWindowTitle("Manage Device Content")
        self.resize(600, 750)
        l = QVBoxLayout(self)
        try:
            total, used, free = shutil.disk_usage(self.device_dir)
            gb = 1024 * 1024 * 1024
            pct = (used / total) * 100
            info_text = f"<b>Storage Usage:</b> {used/gb:.1f} GB Used / {total/gb:.1f} GB Total <span style='color:gray'>({free/gb:.1f} GB Free)</span>"
            l.addWidget(QLabel(info_text))
            bar = QProgressBar()
            bar.setValue(int(pct))
            bar.setTextVisible(True)
            bar.setFormat(f"{pct:.1f}% Used")
            color = "#4caf50" # Green
            if pct > 75: color = "#ff9800" # Orange
            if pct > 90: color = "#f44336" # Red
            bar.setStyleSheet(f"QProgressBar {{ border: 1px solid #999; border-radius: 4px; text-align: center; height: 25px; background-color: #f0f0f0; font-weight: bold; }} QProgressBar::chunk {{ background-color: {color}; border-radius: 3px; }}")
            l.addWidget(bar)
            l.addSpacing(10)
        except Exception as e: l.addWidget(QLabel(f"Could not read disk usage: {e}"))
        l.addWidget(QLabel(f"<b>Browsing:</b> {self.device_dir}"))
        self.list_widget = QListWidget()
        l.addWidget(self.list_widget)
        sel = QHBoxLayout()
        b_all = QPushButton("Select All"); b_all.clicked.connect(self.select_all)
        b_none = QPushButton("Select None"); b_none.clicked.connect(self.select_none)
        sel.addWidget(b_all); sel.addWidget(b_none)
        l.addLayout(sel)
        self.progress = QProgressBar(); self.progress.hide()
        l.addWidget(self.progress)
        self.status = QLabel(""); l.addWidget(self.status)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        self.btn_del = QPushButton("🗑️ Delete Selected Folders")
        self.btn_del.setStyleSheet("QPushButton { background-color: #ffebee; color: #c62828; font-weight: bold; padding: 6px; } QPushButton:hover { background-color: #ffcdd2; }")
        box.addButton(self.btn_del, QDialogButtonBox.ActionRole)
        box.rejected.connect(self.reject)
        self.btn_del.clicked.connect(self.start_delete)
        l.addWidget(box)
        self.refresh_list()
    def refresh_list(self):
        self.list_widget.clear()
        target_dir = os.path.join(self.device_dir, "Music")
        if not os.path.exists(target_dir): target_dir = self.device_dir
        try:
            for item in sorted(os.listdir(target_dir)):
                if item.lower() in PROTECTED_FOLDERS or item.startswith('.'): continue
                fp = os.path.join(target_dir, item)
                if os.path.isdir(fp):
                    iw = QListWidgetItem(f"📁 {item}")
                    iw.setCheckState(Qt.Unchecked)
                    iw.setData(Qt.UserRole, fp)
                    self.list_widget.addItem(iw)
        except Exception as e: self.status.setText(str(e))
    def select_all(self):
        for i in range(self.list_widget.count()): self.list_widget.item(i).setCheckState(Qt.Checked)
    def select_none(self):
        for i in range(self.list_widget.count()): self.list_widget.item(i).setCheckState(Qt.Unchecked)
    def start_delete(self):
        paths = [self.list_widget.item(i).data(Qt.UserRole) for i in range(self.list_widget.count()) if self.list_widget.item(i).checkState() == Qt.Checked]
        if not paths: return
        reply = QMessageBox.warning(self, "Confirm Delete", f"Are you sure you want to permanently delete {len(paths)} folders?", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes: return
        self.list_widget.setEnabled(False); self.btn_del.setEnabled(False); self.progress.show()
        self.worker = DeleteWorker(paths)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.status.connect(self.status.setText)
        if self.parent_app: self.worker.folder_deleted.connect(self.parent_app.inventory.remove_folder)
        self.worker.del_finished.connect(lambda: [self.list_widget.setEnabled(True), self.btn_del.setEnabled(True), self.progress.hide(), self.refresh_list(), self.status.setText("Deletion complete.")])
        self.worker.start()

# --- Main Window ---

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CrateDigger")
        self.resize(1000, 750)
        
        self.settings = load_settings()
        self.canonical_genres = self.settings.get("canonical_genres", DEFAULT_GENRES)
        self.inventory = DeviceInventory()
        self.album_db = []
        self.genre_map = self.settings.get("genre_map", {})
        self.album_overrides = self.settings.get("album_overrides", {})
        self.selected_albums = []
        self.recently_modified = set()
        
        # UI
        layout = QVBoxLayout(self)
        
        # --- TOP ---
        top = QWidget(); tl = QVBoxLayout(top)
        
        # Paths
        self.music_btn = QPushButton("🎵 Select Music Library"); self.music_btn.clicked.connect(self.pick_music)
        self.music_lbl = QLabel("Music: -")
        self.dev_btn = QPushButton("📱 Select Device (Root)"); self.dev_btn.clicked.connect(self.pick_device)
        self.dev_lbl = QLabel("Device: -")
        tl.addWidget(self.music_btn); tl.addWidget(self.music_lbl)
        tl.addWidget(self.dev_btn); tl.addWidget(self.dev_lbl)
        
        # Actions
        act_row = QHBoxLayout()
        self.scan_btn = QPushButton("🔍 Scan Library"); self.scan_btn.clicked.connect(self.start_scan)
        self.edit_btn = QPushButton("🏷️ Edit Genres"); self.edit_btn.clicked.connect(self.edit_genres)
        act_row.addWidget(self.scan_btn); act_row.addWidget(self.edit_btn)
        tl.addLayout(act_row)
        
        # --- MIDDLE: SPLITTER ---
        splitter = QSplitter(Qt.Horizontal)
        
        # 1. Left (Genres)
        left = QWidget(); ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>1. Categories</b>"))
        self.g_list = QListWidget()
        self.g_list.itemClicked.connect(self.show_albums)
        ll.addWidget(self.g_list)
        
        # 2. Middle (Albums & Tools)
        mid = QWidget(); ml = QVBoxLayout(mid)
        ml.addWidget(QLabel("<b>2. Albums</b>"))
        
        self.a_list = QListWidget()
        self.a_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.a_list.itemSelectionChanged.connect(self.update_ovr)
        
        # --- NEW: Context Menu (Right Click) ---
        self.a_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.a_list.customContextMenuRequested.connect(self.show_album_context_menu)
        
        ml.addWidget(self.a_list)
        
        # --- Genre Correction Tools ---
        ml.addSpacing(10)
        ml.addWidget(QLabel("<b>Genre Correction:</b>"))
        
        # 1. The Dropdowns
        gen_grid = QGridLayout()
        
        gen_grid.addWidget(QLabel("Main:"), 0, 0)
        self.ovr_box = QComboBox(); self.ovr_box.setMinimumWidth(120)
        self.ovr_box.addItems(["Select..."] + sorted(self.canonical_genres.keys()) + ["Other"])
        self.ovr_box.currentTextChanged.connect(self.update_sub_combo) # Trigger Sub update
        gen_grid.addWidget(self.ovr_box, 0, 1)
        
        gen_grid.addWidget(QLabel("Sub:"), 1, 0)
        self.sub_box = QComboBox(); self.sub_box.setMinimumWidth(120)
        # When user picks a subgenre, automatically switch the radio button to "Use Sub"
        self.sub_box.activated.connect(lambda: self.rb_sub.setChecked(True)) 
        gen_grid.addWidget(self.sub_box, 1, 1)
        
        ml.addLayout(gen_grid)

        # 2. The "What to Write" Choice
        self.write_tags_cb = QCheckBox("Update File Tags")
        self.write_tags_cb.setChecked(True) # Default to On
        ml.addWidget(self.write_tags_cb)

        rb_layout = QHBoxLayout()
        rb_layout.addWidget(QLabel("Tag As:"))
        self.rb_main = QRadioButton("Main")
        self.rb_sub = QRadioButton("Sub")
        self.rb_main.setChecked(True) # Default to Main
        
        # Group them so they are exclusive
        self.rb_group = QButtonGroup(self)
        self.rb_group.addButton(self.rb_main)
        self.rb_group.addButton(self.rb_sub)
        
        rb_layout.addWidget(self.rb_main)
        rb_layout.addWidget(self.rb_sub)
        ml.addLayout(rb_layout)

        # 3. Action Buttons
        self.ovr_lbl = QLabel("Current: -")
        ml.addWidget(self.ovr_lbl)
        
        btn_row = QHBoxLayout()
        self.ovr_btn = QPushButton("✏️ Apply Override"); self.ovr_btn.clicked.connect(self.apply_ovr)
        self.find_btn = QPushButton("🌍 Find Online"); self.find_btn.clicked.connect(self.find_online)
        btn_row.addWidget(self.ovr_btn); btn_row.addWidget(self.find_btn)
        ml.addLayout(btn_row)

        # 3. Right (Art)
        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(QLabel("<b>3. Cover Art</b>"))
        self.art_frame = QFrame()
        self.art_frame.setFrameShape(QFrame.StyledPanel)
        self.art_frame.setMinimumHeight(250)
        al = QVBoxLayout(self.art_frame)
        self.art_lbl = QLabel("Select an Album")
        self.art_lbl.setAlignment(Qt.AlignCenter)
        self.art_lbl.setStyleSheet("background-color: #f0f0f0; color: #666; font-style: italic;")
        al.addWidget(self.art_lbl)
        rl.addWidget(self.art_frame)
        rl.addStretch() # Push art to top
        
        splitter.addWidget(left)
        splitter.addWidget(mid)
        splitter.addWidget(right)
        
        # Set Default Widths (1:2:1 ratio)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)
        
        layout.addWidget(top); layout.addWidget(splitter); 
        
        # --- BOTTOM ---
        bot = QWidget(); bl = QVBoxLayout(bot)
        bl.addWidget(QLabel("<b>4. Filter & Roll</b>"))
        
        fl = QHBoxLayout()
        self.lim_box = QComboBox(); self.lim_box.addItems(["No Limit", "1", "2", "3", "5"])
        self.inc_txt = QLineEdit(); self.inc_txt.setPlaceholderText("Include...")
        self.exc_txt = QLineEdit(); self.exc_txt.setPlaceholderText("Exclude...")
        fl.addWidget(QLabel("Max/Artist:")); fl.addWidget(self.lim_box)
        fl.addWidget(self.inc_txt); fl.addWidget(self.exc_txt); bl.addLayout(fl)
        
        self.roll_btn = QPushButton("🎲 Roll Random Albums"); self.roll_btn.clicked.connect(self.roll)
        bl.addWidget(self.roll_btn)
        self.sel_list = QListWidget(); self.sel_list.setMaximumHeight(80); bl.addWidget(self.sel_list)
        
        self.info = QLabel("Ready"); self.skip_cb = QCheckBox("Skip Existing"); self.skip_cb.setChecked(True)
        bl.addWidget(self.info); bl.addWidget(self.skip_cb)
        
        cp_row = QHBoxLayout()
        self.cp_btn = QPushButton("🚀 Start Copy"); self.cp_btn.setStyleSheet("background-color: #e8f5e9; font-weight: bold; font-size: 11pt; padding: 8px;")
        self.cp_btn.clicked.connect(self.copy)
        self.ps_btn = QPushButton("⏸️ Pause"); self.ps_btn.clicked.connect(self.pause); self.ps_btn.setEnabled(False)
        self.cn_btn = QPushButton("🛑 Cancel"); self.cn_btn.clicked.connect(self.cancel); self.cn_btn.setEnabled(False)
        cp_row.addWidget(self.cp_btn); cp_row.addWidget(self.ps_btn); cp_row.addWidget(self.cn_btn)
        self.prog = QProgressBar(); cp_row.addWidget(self.prog)
        bl.addLayout(cp_row)
        
        mgr_row = QHBoxLayout()
        self.mgr_btn = QPushButton("📂 Manage Device"); self.mgr_btn.clicked.connect(self.manage)
        self.plist_btn = QPushButton("🎛️ Playlist Generator"); self.plist_btn.clicked.connect(self.open_playlist_gen)
        self.eje_btn = QPushButton("⏏️ Safe Eject"); self.eje_btn.clicked.connect(self.eject)
        mgr_row.addWidget(self.mgr_btn); mgr_row.addWidget(self.plist_btn); mgr_row.addWidget(self.eje_btn)
        bl.addLayout(mgr_row)

        layout.addWidget(bot)

        if "music_dir" in self.settings:
            self.music_dir = self.settings["music_dir"]
            self.music_lbl.setText(f"Music: {self.music_dir}")
        if "device_dir" in self.settings:
            self.device_dir = self.settings["device_dir"]
            self.dev_lbl.setText(f"Device: {self.device_dir}")
            
            # --- Auto-Check Logic on Startup ---
            if os.path.exists(self.device_dir):
                music_sub = os.path.join(self.device_dir, "Music")
                if os.path.exists(music_sub):
                    self.dev_lbl.setText(f"Device: {self.device_dir}   ✅ (Target: /Music)")
                    self.dev_lbl.setStyleSheet("color: green; font-weight: bold;")
                else:
                    self.dev_lbl.setText(f"Device: {self.device_dir}")
                    self.dev_lbl.setStyleSheet("color: black;")
            # -----------------------------------

    # --- Logic ---
    
    def pick_music(self):
        d = QFileDialog.getExistingDirectory(self, "Music Lib")
        if d: self.music_dir = d; self.music_lbl.setText(f"Music: {d}"); self.settings["music_dir"] = d; save_settings(self.settings)

    def pick_device(self):
        d = QFileDialog.getExistingDirectory(self, "Device (Select Drive Root)")
        if d:
            # 1. Smart Detection: Did they pick the specific Music folder by mistake?
            if os.path.basename(d).lower() == "music":
                # Move one level up to get the true Root
                d = os.path.dirname(d)

            music_subfolder = os.path.join(d, "Music")
            
            # 2. Check if Music folder exists
            if os.path.exists(music_subfolder):
                self.device_dir = d
                # Update UI to confirm we found the subfolder
                self.dev_lbl.setText(f"Device: {d}   ✅ (Target: /Music)")
                self.dev_lbl.setStyleSheet("color: green; font-weight: bold;")
            else:
                # 3. If missing, prompt to create
                reply = QMessageBox.question(
                    self, "Setup Device", 
                    f"Selected Root: {d}\n\n"
                    "No 'Music' folder found here.\n"
                    "Create one automatically? (Recommended)",
                    QMessageBox.Yes | QMessageBox.No
                )
                
                if reply == QMessageBox.Yes:
                    try:
                        os.makedirs(music_subfolder)
                        self.device_dir = d
                        self.dev_lbl.setText(f"Device: {d}   ✅ (Target: /Music)")
                        self.dev_lbl.setStyleSheet("color: green; font-weight: bold;")
                        QMessageBox.information(self, "Success", "Created 'Music' folder.")
                    except Exception as e:
                        QMessageBox.warning(self, "Error", f"Could not create folder: {e}")
                        self.device_dir = d
                        self.dev_lbl.setText(f"Device: {d} (No Music Folder)")
                        self.dev_lbl.setStyleSheet("color: red;")
                else:
                    # User said No, use root directly
                    self.device_dir = d
                    self.dev_lbl.setText(f"Device: {d} (Root)")
                    self.dev_lbl.setStyleSheet("color: black;")

            self.settings["device_dir"] = self.device_dir
            save_settings(self.settings)

    def start_scan(self):
        if not hasattr(self, 'music_dir'): return
        self.scan_btn.setEnabled(False); self.album_db = []
        self.worker = ScanWorker(self.music_dir, self.canonical_genres)
        self.worker.progress.connect(self.prog.setValue)
        self.worker.status.connect(self.info.setText)
        self.worker.result.connect(self.scan_done)
        self.worker.start()
    def scan_done(self, db, stats):
        self.album_db = db; self.scan_btn.setEnabled(True); self.info.setText(f"Found {len(db)} albums"); self.reanalyze()
    def reanalyze(self):
        current = self.g_list.currentItem().text().split(" (")[0] if self.g_list.currentItem() else None
        self.g_list.clear(); cnt = Counter()
        for path, _, _, raw, _ in self.album_db:
            if path in self.album_overrides: eff = self.album_overrides[path]
            elif raw in self.genre_map: eff = self.genre_map[raw]
            else: eff, _ = suggest_canonical(raw, self.canonical_genres)
            cnt[eff] += 1
        for g in sorted(self.canonical_genres.keys()) + ["Other", "Unknown"]:
            item = QListWidgetItem(f"{g} ({cnt[g]})"); item.setCheckState(Qt.Checked)
            self.g_list.addItem(item)
            if current and g == current: self.g_list.setCurrentItem(item); self.show_albums(item)

    def show_albums(self, item):
        cat = item.text().split(" (")[0]; self.a_list.clear()
        self.art_lbl.setText("Select an Album") # Reset Art
        self.art_lbl.setPixmap(QPixmap())
        
        for path, artist, album, raw, _ in self.album_db:
            if path in self.album_overrides: eff = self.album_overrides[path]
            elif raw in self.genre_map: eff = self.genre_map[raw]
            else: eff, _ = suggest_canonical(raw, self.canonical_genres)
            if eff == cat:
                ovr = " ✓" if path in self.album_overrides else ""
                it = QListWidgetItem(f"{artist} - {album}{ovr}"); it.setData(Qt.UserRole, path)
                if ovr: it.setBackground(QBrush(QColor(220, 255, 220)))
                elif path in self.recently_modified: it.setBackground(QBrush(QColor(220, 240, 255)))
                self.a_list.addItem(it)

    # --- New Context Menu Logic ---
    def show_album_context_menu(self, pos):
        item = self.a_list.itemAt(pos)
        if not item: return
        
        menu = QMenu(self)
        
        # 1. Open Folder Action
        action_open = QAction("📂 Open Folder", self)
        action_open.triggered.connect(lambda: self.open_album_folder(item))
        
        # 2. Preview Action
        action_play = QAction("▶️ Preview Track", self)
        action_play.triggered.connect(lambda: self.preview_album_track(item))
        
        menu.addAction(action_open)
        menu.addAction(action_play)
        
        menu.exec(self.a_list.mapToGlobal(pos))

    def open_album_folder(self, item):
        path = item.data(Qt.UserRole)
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "Error", "Folder not found.")

    def preview_album_track(self, item):
        path = item.data(Qt.UserRole)
        try:
            # Find the first audio file in the folder
            audio_exts = ('.mp3', '.m4a', '.flac', '.wav', '.ogg')
            for f in os.listdir(path):
                if f.lower().endswith(audio_exts):
                    full_path = os.path.join(path, f)
                    # Open with the system's default media player
                    QDesktopServices.openUrl(QUrl.fromLocalFile(full_path))
                    return
            QMessageBox.information(self, "No Audio", "No compatible audio files found in this folder.")
        except Exception as e:
            print(f"Error previewing: {e}")
            QMessageBox.warning(self, "Error", f"Could not play track: {e}")

    def update_sub_combo(self, text):
        self.sub_box.clear()
        if text in self.canonical_genres:
            # Fill with the keywords/subgenres defined in your Genre Editor
            subs = sorted(self.canonical_genres[text])
            if subs:
                self.sub_box.addItems(subs)
                self.sub_box.setEnabled(True)
            else:
                self.sub_box.addItem("- No Subs -")
                self.sub_box.setEnabled(False)
        else:
            self.sub_box.addItem("-")
            self.sub_box.setEnabled(False)
        
        # Reset Radio Button to Main when changing categories
        self.rb_main.setChecked(True)

    def update_ovr(self):
        sel = self.a_list.selectedItems()
        if not sel: 
            self.ovr_lbl.setText("Current: -")
            return
        path = sel[0].data(Qt.UserRole)
        
        # --- SHOW ARTWORK LOGIC ---
        found_art = False
        try:
            for f in os.listdir(path):
                if f.lower() in ["folder.jpg", "cover.jpg", "front.jpg", "album.jpg"]:
                    pix = QPixmap(os.path.join(path, f))
                    self.art_lbl.setPixmap(pix.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    found_art = True; break
            if not found_art: self.art_lbl.setText("No Cover Art Found")
        except: self.art_lbl.setText("Error loading art")
        # --------------------------

        raw = next((r for p, _, _, r, _ in self.album_db if p == path), "")
        
        # Determine effective genre
        if path in self.album_overrides: eff = self.album_overrides[path]
        elif raw in self.genre_map: eff = self.genre_map[raw]
        else: eff, _ = suggest_canonical(raw, self.canonical_genres)
            
        self.ovr_lbl.setText(f"Current: {eff}")
        
        # Auto-select the Main Dropdown (triggers update_sub_combo)
        idx = self.ovr_box.findText(eff)
        if idx >= 0: self.ovr_box.setCurrentIndex(idx)

    def apply_ovr(self):
        sel = self.a_list.selectedItems()
        main_genre = self.ovr_box.currentText()
        sub_genre = self.sub_box.currentText()
        
        if not sel or main_genre == "Select...": return
        
        # 1. Update Internal Map (Always use MAIN to keep folder sorting consistent)
        for i in sel: 
            self.album_overrides[i.data(Qt.UserRole)] = main_genre
        self.settings["album_overrides"] = self.album_overrides; save_settings(self.settings)
        
        # 2. Update File Tags (Write Main OR Sub depending on user choice)
        if self.write_tags_cb.isChecked():
            tag_to_write = sub_genre if self.rb_sub.isChecked() else main_genre
            
            paths = [i.data(Qt.UserRole) for i in sel]
            self.tag_worker = TagWriterWorker(paths, tag_to_write)
            self.tag_worker.status.connect(self.info.setText)
            self.tag_worker.progress.connect(self.prog.setValue)
            self.tag_worker.finished.connect(lambda: [self.prog.setValue(0), self.info.setText(f"Tags updated to: {tag_to_write}")])
            self.prog.show()
            self.tag_worker.start()
        
        self.reanalyze()
        if not self.write_tags_cb.isChecked():
            self.info.setText("Override applied (Internal only)")

    def edit_genres(self):
        d = GenreEditor(self.canonical_genres, self)
        if d.exec():
            self.canonical_genres = d.genres; self.settings["canonical_genres"] = self.canonical_genres
            save_settings(self.settings); self.ovr_box.clear()
            self.ovr_box.addItems(["Select..."] + sorted(self.canonical_genres.keys()) + ["Other"])
            if self.album_db: self.reanalyze()

    def find_online(self):
        sel = self.a_list.selectedItems()
        if not sel or not HAS_MUSICBRAINZ: return
        if not self.settings.get("mb_email"):
            t, ok = QInputDialog.getText(self, "Setup", "Enter email for MusicBrainz:")
            if ok: self.settings["mb_email"] = t; save_settings(self.settings)
            else: return
        items = []
        for i in sel:
            path = i.data(Qt.UserRole)
            for p, ar, al, ra, _ in self.album_db:
                if p == path: items.append((p, ar, al, ra)); break
        self.gs = GenreSearchWorker(items, self.settings["mb_email"])
        self.gs.progress.connect(self.info.setText)
        self.gs.finished.connect(self.online_done)
        self.gs.start(); self.find_btn.setEnabled(False)

    def online_done(self, res):
        self.find_btn.setEnabled(True); self.info.setText(f"Found {len(res)}")
        if not res: return
        found = set(r['found'] for r in res)
        unk = [f for f in found if not any(f.lower() in [k.lower() for k in self.canonical_genres.get(c,[])] for c in self.canonical_genres)]
        unk = [f for f in unk if f not in self.canonical_genres]
        if unk:
            ud = UnknownGenreDialog(unk, self.canonical_genres, self)
            if ud.exec():
                decs = ud.get_decisions()
                changed = False
                for g, act in decs.items():
                    if act == "new": self.canonical_genres[g] = [g.lower()]; changed = True
                    elif act != "ignore": self.canonical_genres[act].append(g.lower()); changed = True
                if changed:
                    self.settings["canonical_genres"] = self.canonical_genres; save_settings(self.settings)
                    self.ovr_box.clear(); self.ovr_box.addItems(["Select..."] + sorted(self.canonical_genres.keys()) + ["Other"])
        d = GenrePreviewDialog(res, self)
        if d.exec():
            changes = {c['path']: c['new_genre'] for c in d.applied_changes}
            new_db = []
            for path, ar, al, ra, sz in self.album_db:
                if path in changes:
                    new_db.append((path, ar, al, changes[path], sz))
                    self.recently_modified.add(path)
                else: new_db.append((path, ar, al, ra, sz))
            self.album_db = new_db; self.reanalyze()

    def roll(self):
        # 1. Check if a device directory has been selected in settings
        if not hasattr(self, 'device_dir') or not self.device_dir:
            QMessageBox.warning(self, "Missing Device", "Please select a device folder first (e.g., E:/).")
            return

        # 2. Check if the device is actually plugged in/accessible
        if not os.path.exists(self.device_dir):
            QMessageBox.critical(self, "Connection Error", 
                f"Could not find the device at:\n{self.device_dir}\n\n"
                "Please plug in your device and try again.")
            return

        self.sel_list.clear(); self.selected_albums = []
        
        # Gather allowed genres
        allowed = {self.g_list.item(i).text().split(" (")[0] for i in range(self.g_list.count()) if self.g_list.item(i).checkState() == Qt.Checked}
        
        pool = []
        for path, ar, al, ra, sz in self.album_db:
            # FIX IS HERE: Changed 'raw' to 'ra' to fix the crash
            if path in self.album_overrides: c = self.album_overrides[path]
            elif ra in self.genre_map: c = self.genre_map[ra]
            else: c, _ = suggest_canonical(ra, self.canonical_genres)
            
            if c not in allowed: continue
            
            s = f"{ar} {al}".lower()
            inc = self.inc_txt.text().lower()
            exc = self.exc_txt.text().lower()
            
            if exc and exc in s: continue
            score = 100 if inc and inc in s else 0
            pool.append((score, path, ar, al, ra, sz))
            
        random.shuffle(pool)
        pool.sort(key=lambda x: -x[0])

        # 3. Check Free Space (Now safe because we checked os.path.exists above)
        try: 
            free = shutil.disk_usage(self.device_dir).free - (SAFETY_MARGIN_MB * MB)
        except Exception as e:
            QMessageBox.warning(self, "Storage Error", f"Could not read device storage:\n{e}")
            return

        limit = int(self.lim_box.currentText()) if self.lim_box.currentText() != "No Limit" else 9999
        cnt = Counter()
        used = 0
        
        for _, path, ar, al, ra, sz in pool:
            if cnt[ar] >= limit: continue
            
            # Stop if we run out of space
            if used + sz > free: 
                print(f"Stopping: Storage full. (Used: {used/MB:.1f}MB, Free: {free/MB:.1f}MB)")
                break
                
            used += sz
            cnt[ar] += 1
            self.selected_albums.append((path, ar, al, ra, sz))
            self.sel_list.addItem(f"{ar} - {al}")
            
        self.info.setText(f"Selected {len(self.selected_albums)} ({int(used/MB)} MB)")
        
        if len(self.selected_albums) == 0:
            QMessageBox.information(self, "No Albums", "No albums were selected.\n\nCheck if your device is full or if you excluded too many genres.")

    def copy(self):
        if not self.selected_albums or not hasattr(self, 'device_dir'): return
        self.cp_btn.setEnabled(False); self.ps_btn.setEnabled(True); self.cn_btn.setEnabled(True)
        self.cw = CopyWorker(self.selected_albums, self.device_dir, self.skip_cb.isChecked(), self.canonical_genres)
        self.cw.progress.connect(self.prog.setValue); self.cw.status.connect(self.info.setText)
        self.cw.track_copied.connect(self.inventory.add_track)
        self.cw.copy_finished.connect(self.copy_done)
        self.cw.start()

    def pause(self):
        if self.cw.paused: self.cw.resume(); self.ps_btn.setText("Pause")
        else: self.cw.pause(); self.ps_btn.setText("Resume")
    def cancel(self): self.cw.cancel()
    def copy_done(self):
        self.inventory.save()
        self.cp_btn.setEnabled(True); self.ps_btn.setEnabled(False); self.cn_btn.setEnabled(False)
        self.info.setText("Copy Complete")
    def manage(self):
        if not hasattr(self, 'device_dir'): return
        DeviceManager(self.device_dir, self).exec()
    def eject(self):
        if hasattr(self, 'device_dir'): 
            success, msg = safe_eject(self.device_dir)
            if success: QMessageBox.information(self, "Success", msg)
            else: QMessageBox.warning(self, "Failed", msg)
    def open_playlist_gen(self):
        if not hasattr(self, 'device_dir'): return
        PlaylistGenerator(self.inventory, self.device_dir, self.canonical_genres, self).exec()

if __name__ == "__main__":
    app = QApplication([])
    w = App()
    w.show()
    app.exec()