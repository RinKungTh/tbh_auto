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
# ============================================================

SCAN_INTERVAL = 2
CLICK_DELAY   = 1.5
CONFIG_FILE   = "tbh_roi.json"

# ROI เริ่มต้น — กรอบเล็กๆ แถวขวาล่าง (ปรับลากได้)
DEFAULT_ROI = {"left": 1050, "top": 730, "right": 1460, "bottom": 820}

STAGE_COORDS   = {"1-1": (1255, 575), "1-3": (1305, 510)}
STAGE_SEQUENCE = ["1-1", "1-3"]
current_stage_index = 0

# สีกล่องฟ้า (HSV)
BLUE_CHEST_LOWER = np.array([90, 150, 100])
BLUE_CHEST_UPPER = np.array([130, 255, 255])
CHEST_MIN_AREA   = 300
CHEST_MAX_AREA   = 8000

# สีPortal แดง (HSV)
RED_PORTAL_LOWER = np.array([0, 150, 100])
RED_PORTAL_UPPER = np.array([10, 255, 255])
PORTAL_MIN_AREA  = 300
PORTAL_MAX_AREA  = 8000

overlay_running  = True
roi_lock         = threading.Lock()
current_roi      = DEFAULT_ROI.copy()

# ============================================================
#  บันทึก/โหลด ROI
# ============================================================

def load_roi():
    global current_roi
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                current_roi = json.load(f)
            print(f"[ROI] โหลดจากไฟล์: {current_roi}")
            return
        except Exception:
            pass
    current_roi = DEFAULT_ROI.copy()

def save_roi():
    with open(CONFIG_FILE, "w") as f:
        json.dump(current_roi, f)

# ============================================================
#  OVERLAY — กรอบเหลืองลากได้ + ปรับขนาดได้
# ============================================================

def draw_overlay():
    import tkinter as tk

    root = tk.Tk()
    root.title("TBH Scan Zone")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.85)
    root.configure(bg="black")

    # ขนาดเริ่มต้น
    with roi_lock:
        rx = current_roi["left"]
        ry = current_roi["top"]
        rw = current_roi["right"]  - current_roi["left"]
        rh = current_roi["bottom"] - current_roi["top"]

    root.geometry(f"{rw}x{rh}+{rx}+{ry}")

    canvas = tk.Canvas(root, bg="black", highlightthickness=0,
                       cursor="fleur")
    canvas.pack(fill="both", expand=True)

    # วาดกรอบ + label
    def redraw():
        canvas.delete("all")
        w = root.winfo_width()
        h = root.winfo_height()
        # กรอบเหลือง
        canvas.create_rectangle(1, 1, w-1, h-1,
                                 outline="yellow", width=2, fill="")
        # แถบด้านบน (drag handle)
        canvas.create_rectangle(0, 0, w, 18,
                                 fill="#333300", outline="")
        canvas.create_text(4, 9, anchor="w",
                           text="⠿ TBH SCAN  [ลาก=เลื่อน | มุมล่างขวา=ปรับขนาด]",
                           fill="yellow", font=("Arial", 8, "bold"))
        # มุมปรับขนาด
        canvas.create_rectangle(w-12, h-12, w, h,
                                 fill="yellow", outline="")

    # --- Drag to move ---
    _drag = {"x": 0, "y": 0}

    def on_drag_start(e):
        _drag["x"] = e.x_root - root.winfo_x()
        _drag["y"] = e.y_root - root.winfo_y()

    def on_drag_move(e):
        nx = e.x_root - _drag["x"]
        ny = e.y_root - _drag["y"]
        root.geometry(f"+{nx}+{ny}")
        _sync_roi()

    # --- Resize (bottom-right corner) ---
    _resize = {"x": 0, "y": 0, "w": 0, "h": 0}

    def on_resize_start(e):
        _resize["x"] = e.x_root
        _resize["y"] = e.y_root
        _resize["w"] = root.winfo_width()
        _resize["h"] = root.winfo_height()

    def on_resize_move(e):
        nw = max(60, _resize["w"] + (e.x_root - _resize["x"]))
        nh = max(30, _resize["h"] + (e.y_root - _resize["y"]))
        root.geometry(f"{nw}x{nh}")
        _sync_roi()
        redraw()

    def _sync_roi():
        with roi_lock:
            current_roi["left"]   = root.winfo_x()
            current_roi["top"]    = root.winfo_y()
            current_roi["right"]  = root.winfo_x() + root.winfo_width()
            current_roi["bottom"] = root.winfo_y() + root.winfo_height()
        save_roi()

    # bind drag บนแถบบน (y < 18)
    canvas.bind("<ButtonPress-1>",   lambda e: on_resize_start(e) if _is_corner(e) else on_drag_start(e))
    canvas.bind("<B1-Motion>",        lambda e: on_resize_move(e)  if _is_corner(e) else on_drag_move(e))
    canvas.bind("<ButtonRelease-1>", lambda e: save_roi())

    def _is_corner(e):
        w = root.winfo_width()
        h = root.winfo_height()
        return e.x > w - 16 and e.y > h - 16

    # อัปเดต redraw ทุก 500ms
    def loop_redraw():
        redraw()
        if overlay_running:
            root.after(500, loop_redraw)
        else:
            root.destroy()

    root.after(100, loop_redraw)
    root.mainloop()

# ============================================================
#  CORE FUNCTIONS
# ============================================================

def capture_roi():
    with roi_lock:
        bbox = (current_roi["left"], current_roi["top"],
                current_roi["right"], current_roi["bottom"])
    screenshot = ImageGrab.grab(bbox=bbox)
    return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

def find_blue_chest(roi_img):
    hsv  = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BLUE_CHEST_LOWER, BLUE_CHEST_UPPER)

    kernel = np.ones((5, 5), np.uint8)
    mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)
    mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if CHEST_MIN_AREA < area < CHEST_MAX_AREA:
            x, y, w, h = cv2.boundingRect(cnt)
            ar = w / h if h > 0 else 0
            if not (0.5 < ar < 2.5):
                continue
            with roi_lock:
                sx = current_roi["left"] + x + w // 2
                sy = current_roi["top"]  + y + h // 2
            print(f"[+] พบกล่องฟ้าที่ ({sx}, {sy}) ขนาด {w}x{h} area={area:.0f}")
            return (sx, sy)
    return None

def find_red_portal(roi_img):
    hsv  = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, RED_PORTAL_LOWER, RED_PORTAL_UPPER)

    kernel = np.ones((5, 5), np.uint8)
    mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)
    mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if PORTAL_MIN_AREA < area < PORTAL_MAX_AREA:
            x, y, w, h = cv2.boundingRect(cnt)
            ar = w / h if h > 0 else 0
            if not (0.5 < ar < 2.5):
                continue
            with roi_lock:
                sx = current_roi["left"] + x + w // 2
                sy = current_roi["top"]  + y + h // 2
            print(f"[+] พบ Portal แดงที่ ({sx}, {sy}) ขนาด {w}x{h} area={area:.0f}")
            return (sx, sy)
    return None

def click_pos(x, y, delay=0.3):
    pyautogui.moveTo(x, y, duration=0.4)
    time.sleep(0.15)
    pyautogui.click(x, y)
    time.sleep(delay)

def open_chest(pos):
    print(f"[*] คลิกเปิดกล่องที่ {pos}")
    click_pos(pos[0], pos[1])
    time.sleep(CLICK_DELAY)

def open_portal(pos):
    print(f"[*] คลิกเปิด Portal ที่ {pos}")
    click_pos(pos[0], pos[1])
    time.sleep(CLICK_DELAY)

def switch_stage():
    global current_stage_index
    current_stage_index = (current_stage_index + 1) % len(STAGE_SEQUENCE)
    stage  = STAGE_SEQUENCE[current_stage_index]
    coords = STAGE_COORDS[stage]
    print(f"[*] เปลี่ยนไปด่าน {stage} → {coords}")
    click_pos(coords[0], coords[1])
    time.sleep(CLICK_DELAY)

# ============================================================
#  MAIN
# ============================================================

def main():
    global overlay_running
    load_roi()

    print("=" * 50)
    print("  TBH Auto - Chest Opener & Stage Switcher")
    print("=" * 50)
    print(f"  Scan Zone : {current_roi}")
    print(f"  ลากกรอบเหลืองเพื่อเลื่อน")
    print(f"  ลากมุมขวาล่างเพื่อปรับขนาด")
    print(f"  กด Ctrl+C เพื่อหยุด")
    print("=" * 50)

    t = threading.Thread(target=draw_overlay, daemon=True)
    t.start()

    chest_count = 0
    try:
        while True:
            roi_img   = capture_roi()
            chest_pos = find_blue_chest(roi_img)
            portal_pos = find_red_portal(roi_img)

            if chest_pos:
                chest_count += 1
                print(f"\n{'='*30}")
                print(f"  กล่องฟ้าที่ {chest_count} พบแล้ว!")
                print(f"{'='*30}")
                open_chest(chest_pos)
                time.sleep(1)
                switch_stage()
                print("[+] เสร็จแล้ว! รอด่านถัดไป...\n")
                time.sleep(5)
            elif portal_pos:
                print(f"\n{'='*30}")
                print(f"  พบ Portal แดง!")
                print(f"{'='*30}")
                open_portal(portal_pos)
                time.sleep(1)
                switch_stage()
                print("[+] เปลี่ยนด่านแล้ว รอสักครู่...\n")
                time.sleep(5)
            else:
                sys.stdout.write(
                    f"\r[สแกน] หากล่องฟ้า/Portal... (เปิดไปแล้ว {chest_count} กล่อง)  "
                )
                sys.stdout.flush()

            time.sleep(SCAN_INTERVAL)

    except KeyboardInterrupt:
        overlay_running = False
        print(f"\n\n[!] หยุดแล้ว เปิดกล่องไปทั้งหมด {chest_count} ครั้ง")

if __name__ == "__main__":
    print("เริ่มใน 3 วินาที... สลับไปที่หน้าจอเกมก่อนนะครับ!")
    time.sleep(3)
    main()
