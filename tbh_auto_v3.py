import pyautogui
import numpy as np
import cv2
import time
import sys
import threading
import json
import os
from PIL import ImageGrab

# ============================================================
#  TBH: Task Bar Hero - Auto Blue Chest Opener v3.0
#  Simple & Stable - 2 ROI System
# ============================================================

SCAN_INTERVAL = 1.5
CLICK_DELAY   = 0.8
CONFIG_FILE   = "tbh_config.json"

# 2 ROI: จับกล่องฟ้า | จับ Portal
DEFAULT_ROIS = {
    "blue_chest": {
        "left": 800, "top": 250, "right": 1050, "bottom": 450,
        "name": "🔵 Blue Chest", "color": "cyan"
    },
    "portal_btn": {
        "left": 1050, "top": 100, "right": 1450, "bottom": 750,
        "name": "🌀 Portal", "color": "magenta"
    }
}

# สีฟ้า HSV range (ปรับให้ตรงกล่องฟ้า)
BLUE_LOWER = np.array([85, 100, 100])
BLUE_UPPER = np.array([135, 255, 255])
CHEST_MIN_AREA = 200
CHEST_MAX_AREA = 5000

# ด่าน: 1-1 กับ 1-3
STAGE_SEQUENCE = ["1-1", "1-3"]
current_stage_index = 0

overlay_running = True
roi_lock = threading.Lock()
current_rois = {}

# ============================================================
#  Load/Save ROI
# ============================================================

def load_rois():
    global current_rois
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
                current_rois = {k: {**DEFAULT_ROIS[k], **v} 
                               for k, v in data.items() if k in DEFAULT_ROIS}
            print(f"✅ [ROI] โหลดจากไฟล์สำเร็จ")
            for k, v in current_rois.items():
                print(f"   {v['name']}: ({v['left']}, {v['top']}) → ({v['right']}, {v['bottom']})")
            return
        except Exception as e:
            print(f"⚠️ [ROI] ข้อผิดพลาด: {e}")
    
    current_rois = {k: v.copy() for k, v in DEFAULT_ROIS.items()}
    print(f"⚠️ [ROI] ใช้ค่า default - ลากกรอบให้ตรง")

def save_rois():
    data = {k: {x: v[x] for x in ["left", "top", "right", "bottom"]} 
            for k, v in current_rois.items()}
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ============================================================
#  Overlay - 2 กรอบปรับได้
# ============================================================

def draw_overlay():
    import tkinter as tk
    from tkinter import Canvas

    windows = {}
    
    for roi_key in ["blue_chest", "portal_btn"]:
        with roi_lock:
            roi = current_rois[roi_key]
        
        # สร้าง Window แต่ละ ROI
        window = tk.Tk()
        window.title(roi["name"])
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-alpha", 0.5)
        window.configure(bg="black")
        
        rx = roi["left"]
        ry = roi["top"]
        rw = roi["right"] - roi["left"]
        rh = roi["bottom"] - roi["top"]
        
        window.geometry(f"{rw}x{rh}+{rx}+{ry}")
        
        canvas = Canvas(window, bg="black", highlightthickness=0, cursor="fleur")
        canvas.pack(fill="both", expand=True)
        
        color = roi.get("color", "yellow")
        
        # Redraw function
        def make_redraw(w, c, key):
            def redraw():
                c.delete("all")
                width = w.winfo_width()
                height = w.winfo_height()
                
                # กรอบสี
                c.create_rectangle(0, 0, width-1, height-1,
                                  outline=current_rois[key].get("color", "yellow"),
                                  width=3, fill="")
                
                # Label
                c.create_rectangle(0, 0, width, 25, fill="#1a1a00", outline="")
                c.create_text(5, 12, anchor="w",
                             text=f"⠿ {current_rois[key]['name']}",
                             fill="yellow", font=("Arial", 10, "bold"))
            return redraw
        
        redraw = make_redraw(window, canvas, roi_key)
        
        # Drag handlers
        _drag = {"x": 0, "y": 0}
        
        def make_handlers(w, key):
            def on_start(e):
                _drag["x"] = e.x_root - w.winfo_x()
                _drag["y"] = e.y_root - w.winfo_y()
            
            def on_move(e):
                nx = e.x_root - _drag["x"]
                ny = e.y_root - _drag["y"]
                w.geometry(f"+{nx}+{ny}")
                
                with roi_lock:
                    current_rois[key]["left"] = nx
                    current_rois[key]["top"] = ny
                    current_rois[key]["right"] = nx + w.winfo_width()
                    current_rois[key]["bottom"] = ny + w.winfo_height()
            
            def on_release(e):
                save_rois()
            
            return on_start, on_move, on_release
        
        on_start, on_move, on_release = make_handlers(window, roi_key)
        canvas.bind("<ButtonPress-1>", on_start)
        canvas.bind("<B1-Motion>", on_move)
        canvas.bind("<ButtonRelease-1>", on_release)
        
        # Loop redraw
        def make_loop(w, r):
            def loop():
                r()
                if overlay_running:
                    w.after(300, loop)
                else:
                    try:
                        w.destroy()
                    except:
                        pass
            return loop
        
        window.after(100, make_loop(window, redraw))
        windows[roi_key] = window

# ============================================================
#  Core Functions
# ============================================================

def capture_roi(roi_key):
    """จับภาพ ROI"""
    with roi_lock:
        roi = current_rois[roi_key]
        bbox = (roi["left"], roi["top"], roi["right"], roi["bottom"])
    
    try:
        screenshot = ImageGrab.grab(bbox=bbox)
        return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    except Exception as e:
        print(f"❌ จับภาพผิดพลาด: {e}")
        return None

def find_blue_chest():
    """ค้นหากล่องสีฟ้า"""
    img = capture_roi("blue_chest")
    if img is None:
        return None
    
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BLUE_LOWER, BLUE_UPPER)
    
    # Morphology
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    best_chest = None
    best_area = 0
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        
        # Filter by area
        if not (CHEST_MIN_AREA < area < CHEST_MAX_AREA):
            continue
        
        x, y, w, h = cv2.boundingRect(cnt)
        
        # Filter by aspect ratio
        ar = w / h if h > 0 else 0
        if not (0.4 < ar < 2.5):
            continue
        
        # Pick largest valid chest
        if area > best_area:
            best_area = area
            best_chest = (x, y, w, h)
    
    if best_chest:
        x, y, w, h = best_chest
        with roi_lock:
            chest_roi = current_rois["blue_chest"]
            screen_x = chest_roi["left"] + x + w // 2
            screen_y = chest_roi["top"] + y + h // 2
        
        return (screen_x, screen_y)
    
    return None

def click_chest(pos):
    """คลิกเปิดกล่องฟ้า"""
    print(f"🎯 คลิกกล่องฟ้าที่ ({pos[0]}, {pos[1]})")
    pyautogui.moveTo(pos[0], pos[1], duration=0.2)
    time.sleep(0.1)
    pyautogui.click()
    time.sleep(CLICK_DELAY)

def click_portal():
    """คลิก Portal เพื่อเปลี่ยนด่าน"""
    global current_stage_index
    
    with roi_lock:
        portal_roi = current_rois["portal_btn"]
        x = (portal_roi["left"] + portal_roi["right"]) // 2
        y = (portal_roi["top"] + portal_roi["bottom"]) // 2
    
    current_stage_index = (current_stage_index + 1) % len(STAGE_SEQUENCE)
    stage = STAGE_SEQUENCE[current_stage_index]
    
    print(f"🌀 คลิก Portal เพื่อไปด่าน {stage} ที่ ({x}, {y})")
    pyautogui.moveTo(x, y, duration=0.2)
    time.sleep(0.1)
    pyautogui.click()
    time.sleep(CLICK_DELAY)

# ============================================================
#  Main Loop
# ============================================================

def main():
    global overlay_running
    
    load_rois()
    
    print("\n" + "="*60)
    print("  🎮 TBH Auto Chest Opener v3.0")
    print("="*60)
    print("  🔵 จับกล่องสีฟ้า → เปิดอัตโนมัติ")
    print("  🌀 เปลี่ยนด่าน (1-1 ↔ 1-3)")
    print("\n  📋 วิธีใช้:")
    print("    1. ลากกรอบแต่ละอันให้ตรงกับเกม")
    print("    2. กดปุ่มปิด overlay windows")
    print("    3. โปรแกรมจะเริ่มสแกนอัตโนมัติ")
    print("    4. กด Ctrl+C เพื่อหยุด")
    print("="*60 + "\n")
    
    # เปิด Overlay
    t = threading.Thread(target=draw_overlay, daemon=True)
    t.start()
    time.sleep(2)
    
    print("⏳ เริ่มสแกนใน 3 วินาที...\n")
    time.sleep(3)
    
    chest_count = 0
    scan_count = 0
    
    try:
        while True:
            scan_count += 1
            chest_pos = find_blue_chest()
            
            if chest_pos:
                chest_count += 1
                print(f"\n{'='*50}")
                print(f"🎉 กล่องฟ้าที่ {chest_count} พบแล้ว!")
                print(f"{'='*50}")
                
                click_chest(chest_pos)
                time.sleep(1)
                
                click_portal()
                time.sleep(2)
                
                print(f"✅ เสร็จแล้ว! รอด่านถัดไป...\n")
                time.sleep(4)
            
            # Status
            if scan_count % 5 == 0:
                sys.stdout.write(f"\r[สแกน {scan_count}] เปิดไปแล้ว {chest_count} กล่อง")
                sys.stdout.flush()
            
            time.sleep(SCAN_INTERVAL)
    
    except KeyboardInterrupt:
        overlay_running = False
        print(f"\n\n{'='*50}")
        print(f"⏹️  หยุดแล้ว")
        print(f"📊 เปิดกล่องไปทั้งหมด: {chest_count} ครั้ง")
        print(f"{'='*50}\n")

if __name__ == "__main__":
    print("\n🎮 เริ่มโปรแกรมใน 2 วินาที...\n")
    time.sleep(2)
    main()
