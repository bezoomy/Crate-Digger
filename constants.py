# constants.py
import os
import json
import platform
import subprocess
import time
import ctypes
from collections import Counter

SETTINGS_FILE = "rockbox_autofill_settings.json"
INVENTORY_FILE = "device_inventory.json"
SAFETY_MARGIN_MB = 500
MB = 1024 * 1024

PROTECTED_FOLDERS = {
    '.rockbox', 'bootloader', '.spotlight', 'system volume information', 
    '.trash', '.fseventsd', '.ds_store', 'recycler', '$recycle.bin'
}

DEFAULT_GENRES = {
    "Rock": ["rock", "alt", "alternative", "shoegaze", "grunge", "kraut", "psych", "new wave", "garage", "indie"],
    "Metal": [
        "metal", "heavy", "thrash", "doom", "black", "death", "sludge", 
        "stoner", "grind", "speed", "power", "groove", "nu", "viking", 
        "symphonic", "djent", "industrial", "drone", "drone metal", "sunn"
    ],
    "Ambient": [
        "ambient", "drone ambient", "ambient drone", "dark ambient", 
        "drone folk", "field recordings", "soundscape", "chillout", "downtempo"
    ],
    "Electronic": ["electronic", "electronica", "techno", "house", "idm", "synth", "trance", "bass"],
    "Hip-Hop": ["hip hop", "hip-hop", "rap", "trap"],
    "Jazz": ["jazz", "fusion", "bop"],
    "Funk / Soul": ["funk", "soul", "r&b", "motown"],
    "Punk": ["punk", "hardcore", "ska"],
    "Pop": ["pop", "chart"],
    "Classical": ["classical", "baroque", "orchestra", "piano"],
    "Folk": ["folk", "americana", "bluegrass", "singer", "country"],
    "Blues": ["blues"],
    "Reggae": ["reggae", "dub"],
    "Disco": ["disco"],
    "Soundtrack": ["soundtrack", "ost", "score"],
    "Experimental": ["experimental", "noise", "avant"],
    "World": ["world", "latin", "african", "ethnic", "celtic"],
    "Live": ["live"]
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            try:
                data = json.load(f)
                if "canonical_genres" not in data:
                    data["canonical_genres"] = DEFAULT_GENRES
                return data
            except: pass
    return {"canonical_genres": DEFAULT_GENRES}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def suggest_canonical(raw, genre_dict):
    if not raw: return "Unknown", 0
    raw_lower = raw.lower()
    scores = Counter()
    for canon, keywords in genre_dict.items():
        for kw in keywords:
            if kw.lower() in raw_lower:
                scores[canon] += 1
    if not scores: return "Other", 0
    return scores.most_common(1)[0]

def safe_eject(device_path):
    """
    Heavy-duty eject logic using OS-specific APIs.
    """
    system = platform.system()
    mount_point = os.path.abspath(device_path)
    
    # Resolve root path
    while not os.path.ismount(mount_point):
        parent = os.path.dirname(mount_point)
        if parent == mount_point: 
            mount_point = device_path 
            break
        mount_point = parent

    try:
        if system == "Windows":
            # --- Windows CTypes Implementation ---
            drive_letter = os.path.splitdrive(mount_point)[0]
            if not drive_letter:
                return False, "Could not determine drive letter"
                
            # Define constants
            GENERIC_READ = 0x80000000
            GENERIC_WRITE = 0x40000000
            OPEN_EXISTING = 3
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            
            # IOCTL Codes
            FSCTL_LOCK_VOLUME = 0x00090018
            FSCTL_DISMOUNT_VOLUME = 0x00090020
            IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808
            
            # Create Handle
            volume_path = f"\\\\.\\{drive_letter}"
            h_volume = ctypes.windll.kernel32.CreateFileW(
                volume_path,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None
            )
            
            if h_volume == -1:
                return False, "Could not open drive handle (Access Denied?)"
            
            # 1. Lock Volume
            bytes_returned = ctypes.c_ulong(0)
            success = ctypes.windll.kernel32.DeviceIoControl(
                h_volume, FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(bytes_returned), None
            )
            if not success:
                ctypes.windll.kernel32.CloseHandle(h_volume)
                return False, "Could not lock volume (File open?)"
                
            # 2. Dismount
            success = ctypes.windll.kernel32.DeviceIoControl(
                h_volume, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(bytes_returned), None
            )
            if not success:
                ctypes.windll.kernel32.CloseHandle(h_volume)
                return False, "Could not dismount volume"

            # 3. Eject
            success = ctypes.windll.kernel32.DeviceIoControl(
                h_volume, IOCTL_STORAGE_EJECT_MEDIA, None, 0, None, 0, ctypes.byref(bytes_returned), None
            )
            
            ctypes.windll.kernel32.CloseHandle(h_volume)
            
            if success:
                return True, f"Drive {drive_letter} Safe Ejected!"
            else:
                return False, "Eject command failed (Hardware issue?)"

        elif system == "Darwin":
            subprocess.run(["diskutil", "eject", mount_point], check=True)
            return True, "Device ejected (macOS)"
            
        elif system == "Linux":
            try:
                subprocess.run(["udisksctl", "unmount", "-b", mount_point], check=True)
                return True, "Device unmounted (udisksctl)"
            except:
                subprocess.run(["umount", mount_point], check=True)
                return True, "Device unmounted (umount)"
                
        return False, "Unsupported platform"
        
    except Exception as e:
        return False, f"Eject failed: {str(e)}"