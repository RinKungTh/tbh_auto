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
#  TBH: Task Bar Hero - Auto Chest Opener & Stage Switcher
#  Version 2.0 - 3 ROI System
# ============================================================

SCAN_INTERVAL = 2
CLICK_DELAY   = 1.5
CONFIG_FILE   = "tbh_roi.json"

# 3 ROI: เกม | เปิดกล่อง | Portal
DEFAULT_ROIS = {
    "game_area": {"left": 700, "top": 200, "right": 1400, "bottom": 720, "name": "🎮 Game Area", "color": "cyan"},
    "chest_btn":  {"left": 1050, "top": 730, "right": 1200, "bottom": 820, "name": "📦 Chest Button", "color": "lime"},
    "portal_btn": {"left": 1220, "top": 730, "right": 1400, "bottom": 820, "name": "🌀 Portal Button", "color": "magenta"}
}

STAGE_COORDS   = {"1-1": (1255, 575), "1-3": (1305, 510)}
STAGE_SEQUENCE = ["1-1", "1-3"]
current_stage_index = 0

BLUE_CHEST_LOWER = np.array([90, 150, 100])
BLUE_CHEST_UPPER = np.array([130, 255, 255])
CHEST_MIN_AREA   = 300
CHEST_MAX_AREA   = 8000

overlay_running  = True
roi_lock         = threading.Lock()
current_rois     = {}

# ============================================================
#  บันทึก/โหลด ROI
# ============================================================

def load_rois():
    global current_rois
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
                current_rois = {k: {**DEFAULT_ROIS[k], **v} for k, v in data.items()}
            print(f"[ROI] โหลดจากไฟล์สำเร็จ")
            return
        except Exception as e:
            print(f"[!] โหลดไฟล์ผิดพลาด: {e}")
    
    current_rois = DEFAULT_ROIS.copy()

def save_rois():
    with open(CONFIG_FILE, "w") as f:
        json.dump({k: {x: v[x] for x in ["left", "top", "right", "bottom"]} 
                   for k, v in current_rois.items()}, f, indent=2)

# ============================================================
#  OVERLAY — 3 กรอบปรับได้
# ============================================================

def draw_overlay():
    import tkinter as tk
    from tkinter import Canvas

    root = tk.Tk()
    root.title("TBH ROI Setup")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.7)
    root.configure(bg="black")

    # สร้าง frame สำหรับแต่ละ ROI
    frames = {}
    roi_names = list(current_rois.keys())
    
    for roi_key in roi_names:
        with roi_lock:
            roi = current_rois[roi_key]
        
        frame = tk.Tk()
        frame.title(roi["name"])
        frame.overrideredirect(True)
        frame.attributes("-topmost", True)
        frame.attributes("-alpha", 0.6)
        frame.configure(bg="black")
        
        rx = roi["left"]
        ry = roi["top"]
        rw = roi["right"] - roi["left"]
        rh = roi["bottom"] - roi["top"]
        
        frame.geometry(f"{rw}x{rh}+{rx}+{ry}")
        
        canvas = Canvas(frame, bg="black", highlightthickness=0, cursor="fleur")
        canvas.pack(fill="both", expand=True)
        
        color = roi.get("color", "yellow")
        roi_key_ref = roi_key
        
        def make_redraw(fr, canvas, key):
            def redraw():
                canvas.delete("all")
                w = fr.winfo_width()
                h = fr.winfo_height()
                # กรอบสี
                canvas.create_rectangle(1, 1, w-1, h-1,
                                       outline=current_rois[key].get("color", "yellow"), 
                                       width=3, fill="")
                # แถบลาก
                canvas.create_rectangle(0, 0, w, 20,
                                       fill="#333300", outline="")
                canvas.create_text(4, 10, anchor="w",
                                  text=f"⠿ {current_rois[key]['name']}  [ลาก=เลื่อน]",
                                  fill="yellow", font=("Arial", 9, "bold"))
            return redraw
        
        redraw_func = make_redraw(frame, canvas, roi_key)
        
        _drag = {"x": 0, "y": 0}
        
        def make_drag_handlers(fr, key):
            def on_drag_start(e):
                _drag["x"] = e.x_root - fr.winfo_x()
                _drag["y"] = e.y_root - fr.winfo_y()
            
            def on_drag_move(e):
                nx = e.x_root - _drag["x"]
                ny = e.y_root - _drag["y"]
                fr.geometry(f"+{nx}+{ny}")
                
                with roi_lock:
                    current_rois[key]["left"] = nx
                    current_rois[key]["top"] = ny
                    current_rois[key]["right"] = nx + fr.winfo_width()
                    current_rois[key]["bottom"] = ny + fr.winfo_height()
            
            def on_release(e):
                save_rois()
            
            return on_drag_start, on_drag_move, on_release
        
        on_start, on_move, on_release = make_drag_handlers(frame, roi_key)
        
        canvas.bind("<ButtonPress-1>", on_start)
        canvas.bind("<B1-Motion>", on_move)
        canvas.bind("<ButtonRelease-1>", on_release)
        
        def make_loop(fr, redraw):
            def loop_redraw():
                redraw()
                if overlay_running:
                    fr.after(500, loop_redraw)
                else:
                    fr.destroy()
            return loop_redraw
        
        frame.after(100, make_loop(frame, redraw_func))
        frames[roi_key] = frame

# ============================================================
#  CORE FUNCTIONS
# ============================================================

def capture_roi(roi_key):
    with roi_lock:
        roi = current_rois[roi_key]
        bbox = (roi["left"], roi["top"], roi["right"], roi["bottom"])
    screenshot = ImageGrab.grab(bbox=bbox)
    return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

def find_blue_chest():
    """สแกนหากล่องฟ้าจากกรอบเกม"""
    roi_img = capture_roi("game_area")
    hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BLUE_CHEST_LOWER, BLUE_CHEST_UPPER)
    
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if CHEST_MIN_AREA < area < CHEST_MAX_AREA:
            x, y, w, h = cv2.boundingRect(cnt)
            ar = w / h if h > 0 else 0
            if not (0.5 < ar < 2.5):
                continue
            
            with roi_lock:
                game_roi = current_rois["game_area"]
                sx = game_roi["left"] + x + w // 2
                sy = game_roi["top"] + y + h // 2
            
            print(f"[+] พบกล่องฟ้าที่ ({sx}, {sy}) ขนาด {w}x{h} area={area:.0f}")
            return (sx, sy)
    
    return None

def click_pos(x, y, delay=0.3):
    """คลิกที่ตำแหน่ง (x, y)"""
    pyautogui.moveTo(x, y, duration=0.3)
    time.sleep(0.1)
    pyautogui.click()
    time.sleep(delay)

def open_chest():
    """คลิกปุ่มเปิดกล่องฟ้า"""
    with roi_lock:
        chest_roi = current_rois["chest_btn"]
        x = (chest_roi["left"] + chest_roi["right"]) // 2
        y = (chest_roi["top"] + chest_roi["bottom"]) // 2
    
    print(f"[*] คลิกเปิดกล่องที่ ({x}, {y})")
    click_pos(x, y, CLICK_DELAY)

def open_portal():
    """คลิกปุ่ม Portal (เปลี่ยนด่าน)"""
    with roi_lock:
        portal_roi = current_rois["portal_btn"]
        x = (portal_roi["left"] + portal_roi["right"]) // 2
        y = (portal_roi["top"] + portal_roi["bottom"]) // 2
    
    print(f"[*] คลิก Portal เพื่อเปลี่ยนด่านที่ ({x}, {y})")
    click_pos(x, y, CLICK_DELAY)

# ============================================================
#  MAIN
# ============================================================

def main():
    global overlay_running
    load_rois()
    
    print("=" * 60)
    print("  TBH Auto - Chest Opener & Stage Switcher v2.0")
    print("=" * 60)
    print("  🎮 Game Area  : สแกนหากล่องฟ้า")
    print("  📦 Chest Btn  : คลิกเปิดกล่อง")
    print("  🌀 Portal Btn : เปลี่ยนด่าน")
    print("  ")
    print("  คำแนะนำ:")
    print("    - ลากกรอบแต่ละอันไปยังพื้นที่ที่ถูกต้องในเกม")
    print("    - กด Ctrl+C เพื่อหยุด")
    print("=" * 60)
    
    # แสดง overlay
    t = threading.Thread(target=draw_overlay, daemon=True)
    t.start()
    time.sleep(2)
    
    chest_count = 0
    try:
        while True:
            chest_pos = find_blue_chest()
            
            if chest_pos:
                chest_count += 1
                print(f"\n{'='*40}")
                print(f"  🎉 กล่องฟ้าที่ {chest_count} พบแล้ว!")
                print(f"{'='*40}")
                open_chest()
                time.sleep(1)
                open_portal()
                print("[+] เสร็จแล้ว! รอด่านถัดไป...\n")
                time.sleep(5)
            else:
                sys.stdout.write(
                    f"\r[สแกน] หากล่องฟ้า... (เปิดไปแล้ว {chest_count} ครั้ง)  "
                )
                sys.stdout.flush()
            
            time.sleep(SCAN_INTERVAL)
    
    except KeyboardInterrupt:
        overlay_running = False
        print(f"\n\n[!] หยุดแล้ว เปิดกล่องไปทั้งหมด {chest_count} ครั้ง")

if __name__ == "__main__":
    print("\n🎮 เริ่มใน 3 วินาที... สลับไปที่หน้าจอเกมก่อนนะครับ!\n")
    time.sleep(3)
    main()
