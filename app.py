import os
import cv2
import time
import math
import numpy as np
import collections
import mysql.connector

# Try to load local environment variables from a .env file if it exists
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_DATABASE", "cognitive_engine")
}


# Default zones, will be seeded if MySQL table is empty
ZONES = {
    "Drawer": (50, 50, 300, 300),
    "Table":  (350, 200, 800, 500),
    "Shelf":  (400, 20,  700, 180),
}

def draw_text_with_shadow(frame, text, pos, font, scale, color, thickness=1):
    x, y = pos
    # Draw drop shadow (offset by 1px)
    cv2.putText(frame, text, (x + 1, y + 1), font, scale, (0, 0, 0), thickness + 1)
    # Draw main text
    cv2.putText(frame, text, (x, y), font, scale, color, thickness)

def _get_db_conn():
    """Get a MySQL connection with error handling."""
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Could not connect to MySQL: {e}")
        return None


def init_db():
    try:
        conn = mysql.connector.connect(
            host=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"]
        )
        cursor = conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS cognitive_engine")
        conn.commit()
        conn.close()
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Failed to create database: {e}")
        return

    conn = _get_db_conn()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS zones (
                name VARCHAR(50) PRIMARY KEY,
                x1 INT,
                y1 INT,
                x2 INT,
                y2 INT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS object_states (
                label VARCHAR(50) PRIMARY KEY,
                state VARCHAR(50),
                stable_zone VARCHAR(50),
                last_seen_zone VARCHAR(50),
                last_x INT,
                last_y INT,
                last_seen_time DOUBLE,
                still_since DOUBLE,
                first_seen_time DOUBLE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS object_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                label VARCHAR(50),
                timestamp DOUBLE,
                time_str VARCHAR(20),
                zone VARCHAR(50),
                event VARCHAR(50)
            )
        """)
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM zones")
        if cursor.fetchone()[0] == 0:
            default_zones = [
                ("Drawer", 50, 50, 300, 300),
                ("Table", 350, 200, 800, 500),
                ("Shelf", 400, 20, 700, 180)
            ]
            cursor.executemany("INSERT INTO zones VALUES (%s, %s, %s, %s, %s)", default_zones)
            conn.commit()
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Failed to initialize tables: {e}")
    finally:
        conn.close()


def load_zones():
    global ZONES
    conn = _get_db_conn()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name, x1, y1, x2, y2 FROM zones")
        rows = cursor.fetchall()
        ZONES.clear()
        for row in rows:
            ZONES[row[0]] = (row[1], row[2], row[3], row[4])
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Failed to load zones: {e}")
    finally:
        conn.close()


def save_zone(name, x1, y1, x2, y2):
    conn = _get_db_conn()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO zones VALUES (%s, %s, %s, %s, %s)", (name, x1, y1, x2, y2))
        conn.commit()
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Failed to save zone: {e}")
    finally:
        conn.close()


def delete_zone_from_db(name):
    conn = _get_db_conn()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM zones WHERE name = %s", (name,))
        conn.commit()
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Failed to delete zone: {e}")
    finally:
        conn.close()


def save_object_state(mem):
    conn = _get_db_conn()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            REPLACE INTO object_states (label, state, stable_zone, last_seen_zone, last_x, last_y, last_seen_time, still_since, first_seen_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (mem.label, mem.state, mem.stable_zone, mem.last_seen_zone, mem.last_x, mem.last_y, mem.last_seen_time, mem.still_since, mem.first_seen_time))
        conn.commit()
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Failed to save object state: {e}")
    finally:
        conn.close()


def save_object_history(label, timestamp, time_str, zone, event):
    conn = _get_db_conn()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO object_history (label, timestamp, time_str, zone, event)
            VALUES (%s, %s, %s, %s, %s)
        """, (label, timestamp, time_str, zone, event))
        conn.commit()
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Failed to save object history: {e}")
    finally:
        conn.close()


def delete_object_state(label):
    conn = _get_db_conn()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM object_states WHERE label = %s", (label,))
        cursor.execute("DELETE FROM object_history WHERE label = %s", (label,))
        conn.commit()
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Failed to delete object state: {e}")
    finally:
        conn.close()


def load_memory_bank():
    memory_bank = {}
    conn = _get_db_conn()
    if conn is None:
        return memory_bank
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT label, state, stable_zone, last_seen_zone, last_x, last_y, last_seen_time, still_since, first_seen_time FROM object_states")
        rows = cursor.fetchall()
        for row in rows:
            label, state, stable_zone, last_seen_zone, last_x, last_y, last_seen_time, still_since, first_seen_time = row
            mem = ObjectMemory(label)
            mem.state = state
            mem.stable_zone = stable_zone
            mem.last_seen_zone = last_seen_zone
            mem.last_x = last_x
            mem.last_y = last_y
            mem.last_seen_time = last_seen_time
            mem.still_since = still_since
            mem.first_seen_time = first_seen_time
            mem.visible = False

            cursor.execute("SELECT timestamp, time_str, zone, event FROM object_history WHERE label = %s ORDER BY id DESC LIMIT 10", (label,))
            hist_rows = cursor.fetchall()
            for hr in reversed(hist_rows):
                ts, t_str, zone, event = hr
                mem.event_log.append({
                    "time": ts,
                    "time_str": t_str,
                    "zone": zone,
                    "event": event
                })
                if event in ("moved", "placed", "picked up", "removed"):
                    mem.movement_history.append({
                        "time_str": t_str,
                        "event": event,
                        "zone": zone
                    })
            memory_bank[label] = mem
    except mysql.connector.Error as e:
        print(f"[DB ERROR] Failed to load memory bank: {e}")
    finally:
        conn.close()
    return memory_bank

ZONE_MARGIN = 12
VALID_CLASSES = ["cell phone", "bottle", "cup", "laptop", "remote", "book", "mouse", "scissors"]

# Class-specific confidence thresholds to prevent false positive misclassifications
# E.g. raising cell phone threshold to 0.75 prevents computer mouse from being misclassified as a phone.
CONF_THRESHOLDS = {
    "cell phone": 0.75,
    "mouse":      0.60,
    "bottle":     0.60,
    "cup":        0.60,
    "laptop":     0.60,
    "remote":     0.65,
    "book":       0.60,
    "scissors":   0.60
}

MEMORY_DECAY = {
    10:  100,
    60:  70,
    300: 40,
    600: 15,
}

drawing_state = {"active": False, "start": None, "current": None, "delete_mode": False, "drawing_mode": False}
global_log = collections.deque(maxlen=10)
_log_cooldowns = {}


def get_zone(cx, cy):
    for name, (x1, y1, x2, y2) in ZONES.items():
        margin_x = min(ZONE_MARGIN, max(0, (x2 - x1) // 2 - 1))
        margin_y = min(ZONE_MARGIN, max(0, (y2 - y1) // 2 - 1))
        if (x1 + margin_x) <= cx <= (x2 - margin_x) and \
           (y1 + margin_y) <= cy <= (y2 - margin_y):
            return name
    return "unknown"


def dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def memory_confidence(seconds_missing):
    for cap, conf in sorted(MEMORY_DECAY.items()):
        if seconds_missing <= cap:
            return conf
    return 0


def add_log(msg, priority=1, cooldown=2.5):
    now = time.time()
    if now - _log_cooldowns.get(msg, 0) < cooldown:
        return
    _log_cooldowns[msg] = now
    # Prune stale cooldown entries to prevent unbounded memory growth
    if len(_log_cooldowns) > 200:
        stale = [k for k, v in _log_cooldowns.items() if now - v > 60]
        for k in stale:
            del _log_cooldowns[k]
    entry = {"time": time.strftime("%H:%M:%S"), "msg": msg, "priority": priority, "ts": now}
    global_log.append(entry)
    print(f"[{entry['time']}] {msg}")




class ObjectMemory:
    def __init__(self, label):
        self.label = label
        self.uid = label
        self.display_name = label

        self.raw_zone = "unknown"
        self.stable_zone = "unknown"
        self.zone_strike = 0
        self.STABILITY_FRAMES = 15
        self.zone_entry_time = time.time()
        self.placement_duration_required = 4.0

        self.state = "initialized"
        self.last_x = None
        self.last_y = None
        self.speed = 0.0
        self.still_since = None
        self.last_event_times = {}

        self.first_seen_time = time.time()
        self.last_seen_time = time.time()
        self.last_seen_zone = "unknown"
        self.event_log = collections.deque(maxlen=20)
        self.visible = False
        self.movement_history = collections.deque(maxlen=10)

    def remember(self, event, zone, cooldown=3.0):
        now = time.time()
        key = f"{event}_{zone}"
        if now - self.last_event_times.get(key, 0) < cooldown:
            return False
        self.last_event_times[key] = now
        t_str = time.strftime("%H:%M:%S")
        self.event_log.append({
            "time": now,
            "time_str": t_str,
            "zone": zone,
            "event": event,
        })
        if event in ("moved", "placed", "picked up", "removed"):
            self.movement_history.append({
                "time_str": t_str,
                "event": event,
                "zone": zone,
            })
        # Sync the event history to the MySQL database
        save_object_history(self.label, now, t_str, zone, event)
        return True

    def seconds_missing(self):
        return time.time() - self.last_seen_time

    def is_likely_lost(self):
        return not self.visible and self.seconds_missing() > 300

    def answer_query(self, question, visible_uids):
        q = question.lower()
        name = self.display_name

        if self.uid in visible_uids:
            location = self.stable_zone if self.stable_zone != "unknown" else "visible but not in a defined zone"
            state_desc = {
                "placed":    "sitting still",
                "moving":    "currently moving",
                "idle":      "stationary",
                "picked up": "being picked up",
                "removed":   "just removed from a zone",
            }.get(self.state, self.state)
            return f"{name} is currently in {location} and is {state_desc}."

        sm = int(self.seconds_missing())
        conf = memory_confidence(sm)

        if conf == 0:
            return f"{name}: memory has expired. Last seen too long ago to be reliable."

        zone = self.last_seen_zone if self.last_seen_zone != "unknown" else "an unknown location"
        last_event = self.event_log[-1]["event"] if self.event_log else "detected"
        time_str = f"{sm} seconds ago" if sm < 60 else f"{sm // 60} minutes ago"

        if "lost" in q or "missing" in q or "find" in q:
            if self.is_likely_lost():
                return f"{name} may be lost. Last seen in {zone} {time_str}. Confidence {conf} percent."
            return f"{name} is not currently visible but was last seen in {zone} {time_str}. Confidence {conf} percent."

        if "move" in q or "moved" in q:
            moves =[e for e in self.movement_history if e["event"] in ("moved", "picked up", "removed")]
            if not moves:
                return f"{name} has not been observed moving since tracking began."
            last = moves[-1]
            return f"{name} last moved at {last['time_str']}, event was {last['event']} in {last['zone']}."

        if "where" in q or "location" in q or "zone" in q:
            return f"{name} was last seen in {zone} {time_str}. Confidence {conf} percent."

        if "history" in q or "log" in q:
            if not self.movement_history:
                return f"No movement history recorded for {name}."
            lines =[f"{e['time_str']}: {e['event']} in {e['zone']}" for e in list(self.movement_history)[-3:]]
            return f"{name} movement history. " + ". ".join(lines)

        return f"{name}: last seen in {zone} {time_str}, event was {last_event}. Confidence {conf} percent."


class QueryEngine:
    ALIASES = {
        "phone":    "cell phone",
        "mobile":   "cell phone",
        "laptop":   "laptop",
        "remote":   "remote",
        "bottle":   "bottle",
        "cup":      "cup",
        "book":     "book",
        "mouse":    "mouse",
        "scissors": "scissors",
    }

    def __init__(self, memory_bank):
        self.memory_bank = memory_bank

    def resolve_label(self, question):
        q = question.lower()
        for alias, label in self.ALIASES.items():
            if alias in q:
                return label
        return None

    def query(self, question, visible_uids):
        label = self.resolve_label(question)
        if label is None:
            return "I am not sure which object you mean. Try asking about phone, laptop, bottle, cup, remote, book, mouse, or scissors."
        matches =[m for m in self.memory_bank.values() if m.label == label]
        if not matches:
            return f"I have no memory of a {label}. It may not have been detected yet."
        return " ".join(m.answer_query(question, visible_uids) for m in matches)

def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = current_line + " " + word if current_line else word
        (tw, _), _ = cv2.getTextSize(test_line, font, 0.44, 1)
        if tw > max_width:
            if current_line:
                lines.append(current_line)
            current_line = word
        else:
            current_line = test_line
    if current_line:
        lines.append(current_line)
    return lines


def mouse_callback(event, x, y, flags, param):
    # Check if delete_mode is active
    if drawing_state.get("delete_mode", False):
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked_zone = None
            # Search reversed list to delete the top-most drawn overlapping zone first
            for name, (x1, y1, x2, y2) in reversed(list(ZONES.items())):
                if x1 <= x <= x2 and y1 <= y <= y2:
                    clicked_zone = name
                    break
            if clicked_zone:
                ZONES.pop(clicked_zone, None)
                delete_zone_from_db(clicked_zone)
                add_log(f"Zone '{clicked_zone}' deleted", priority=1)
                drawing_state["delete_mode"] = False
            return
        return

    # Only allow zone drawing when drawing_mode is active (press 'z' first)
    if not drawing_state.get("drawing_mode", False):
        return

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing_state["active"] = True
        drawing_state["start"] = (x, y)
    elif event == cv2.EVENT_MOUSEMOVE and drawing_state["active"]:
        drawing_state["current"] = (x, y)
    elif event == cv2.EVENT_LBUTTONUP and drawing_state["active"]:
        drawing_state["active"] = False
        if drawing_state["start"] and drawing_state["current"]:
            sx, sy = drawing_state["start"]
            x1, y1, x2, y2 = min(sx, x), min(sy, y), max(sx, x), max(sy, y)
            if (x2 - x1) >= 15 and (y2 - y1) >= 15:
                idx = 1
                while f"Zone{idx}" in ZONES:
                    idx += 1
                name = f"Zone{idx}"
                ZONES[name] = (x1, y1, x2, y2)
                save_zone(name, x1, y1, x2, y2)
                add_log(f"Zone '{name}' created", priority=1)
            else:
                add_log("Zone creation ignored: size too small", priority=2)
        drawing_state["start"] = None
        drawing_state["current"] = None
        drawing_state["drawing_mode"] = False  # Exit drawing mode after one zone


def draw_zones(frame):
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.60
    thickness = 2

    for name, (x1, y1, x2, y2) in ZONES.items():
        # Ensure coordinates are within frame bounds for ROI
        h, w = frame.shape[:2]
        x1_roi, y1_roi = max(0, x1), max(0, y1)
        x2_roi, y2_roi = min(w, x2), min(h, y2)
        
        if x1_roi < x2_roi and y1_roi < y2_roi:
            roi = frame[y1_roi:y2_roi, x1_roi:x2_roi]
            rect_overlay = np.zeros_like(roi)
            rect_overlay[:] = (200, 100, 100) # Slightly brighter zone fill
            cv2.addWeighted(rect_overlay, 0.15, roi, 0.85, 0, roi)
            
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 120, 120), 2) # Brighter coral borders

        (tw, th), _ = cv2.getTextSize(name, font, font_scale, thickness)
        zone_cx = (x1 + x2) // 2
        zone_cy = (y1 + y2) // 2
        tx = zone_cx - tw // 2
        ty = zone_cy + th // 2

        cv2.rectangle(frame, (tx - 6, ty - th - 6), (tx + tw + 6, ty + 6), (20, 20, 20), -1)
        cv2.rectangle(frame, (tx - 6, ty - th - 6), (tx + tw + 6, ty + 6), (255, 120, 120), 1)
        cv2.putText(frame, name, (tx, ty), font, font_scale, (255, 255, 255), thickness)


def draw_event_log(frame):
    h, w = frame.shape[:2]
    # Guard: skip panel if frame is too small
    if w < 460 or h < 230:
        return
    # Draw translucent event panel backbox
    sub_img = frame[10:210, w - 430:w - 10]
    black_rect = np.zeros_like(sub_img)
    black_rect[:] = (15, 15, 15)
    cv2.addWeighted(black_rect, 0.75, sub_img, 0.25, 0, sub_img)
    cv2.rectangle(frame, (w - 430, 10), (w - 10, 210), (255, 80, 255), 1)

    draw_text_with_shadow(frame, "RECENT EVENTS LOG", (w - 420, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 80, 255), 2)

    y = 60
    for entry in list(reversed(list(global_log)))[:7]: # Show max 7 events to fit panel
        color = (255, 100, 255) if entry["priority"] >= 3 else \
                (255, 200, 80) if entry["priority"] == 2 else (220, 220, 220)
        text = f"[{entry['time']}] {entry['msg']}"
        draw_text_with_shadow(frame, text, (w - 420, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)
        y += 22


def draw_memory_panel(frame, memory_bank, visible_uids):
    h, w = frame.shape[:2]
    # Guard: skip panel if frame is too small
    if w < 450 or h < 230:
        return
    # Draw translucent memory panel backbox
    sub_img = frame[10:210, 10:430]
    black_rect = np.zeros_like(sub_img)
    black_rect[:] = (15, 15, 15)
    cv2.addWeighted(black_rect, 0.75, sub_img, 0.25, 0, sub_img)
    cv2.rectangle(frame, (10, 10), (430, 210), (0, 255, 255), 1)

    draw_text_with_shadow(frame, "SYSTEM MEMORY", (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
    
    y = 60
    for uid, mem in list(memory_bank.items())[:7]: # Show max 7 items to fit panel
        if mem.uid in visible_uids:
            zone = mem.stable_zone if mem.stable_zone != "unknown" else "?"
            text = f"[LIVE] {mem.display_name} - {zone} ({mem.state})"
            color = (50, 255, 50) # Bright neon green
        else:
            sm = int(mem.seconds_missing())
            conf = memory_confidence(sm)
            if conf == 0:
                text = f"[GONE] {mem.display_name} - expired"
                color = (150, 150, 150)
            else:
                zone = mem.last_seen_zone if mem.last_seen_zone != "unknown" else "?"
                text = f"[MEM]  {mem.display_name} - {zone}, {sm}s ago [{conf}%]"
                color = (0, 200, 255) # Neon sky blue
        draw_text_with_shadow(frame, text, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)
        y += 22


def draw_voice_ui(frame, voice_state, recognized_text, last_answer, wrapped_lines, typed_text=""):
    h, w = frame.shape[:2]
    # Guard: skip bottom panel if frame is too small
    if h < 140:
        return
    font = cv2.FONT_HERSHEY_SIMPLEX

    state_colors = {
        "idle":      (200, 200, 200),
        "typing":    (255, 100, 255),
        "deleting":  (100, 100, 255),
    }
    indicator_labels = {
        "idle":      "[ i ] Type | [ d ] Delete | [ z ] Zone | [ q ] Quit",
        "typing":    "[ TYP ] Type your question & press Enter (Esc to cancel)",
        "deleting":  "[ DEL ] Click inside a zone to delete it (Esc to cancel)",
    }

    color = state_colors.get(voice_state, (200, 200, 200))
    label = indicator_labels.get(voice_state, "")

    # Draw bottom panel backdrop (120px tall)
    sub_img = frame[h - 120:h, 0:w]
    black_rect = np.zeros_like(sub_img)
    black_rect[:] = (10, 10, 10)
    cv2.addWeighted(black_rect, 0.8, sub_img, 0.2, 0, sub_img)
    cv2.line(frame, (0, h - 120), (w, h - 120), (255, 255, 255), 1)

    # Status indicator circle
    if voice_state in ("typing", "deleting"):
        pulse_r = int(9 + 5 * abs(math.sin(time.time() * 4)))
        cv2.circle(frame, (20, h - 20), pulse_r, color, -1)
    else:
        cv2.circle(frame, (20, h - 20), 9, color, -1)

    draw_text_with_shadow(frame, label, (38, h - 14), font, 0.52, color, 1)

    # Display Query Question
    display_q = ""
    if voice_state == "typing":
        display_q = f"QUERY INPUT: {typed_text}_"
        draw_text_with_shadow(frame, display_q, (20, h - 90), font, 0.55, (255, 255, 255), 2)
    elif recognized_text:
        display_q = f"QUERY: \"{recognized_text}\""
        draw_text_with_shadow(frame, display_q, (20, h - 90), font, 0.55, (255, 200, 100), 2)

    # Display Query Answer
    if wrapped_lines:
        lines = wrapped_lines
        base_y = h - 60 if display_q else h - 80
        for i, l in enumerate(lines[-2:]): # Draw up to 2 wrapped lines of response
            draw_text_with_shadow(frame, l, (20, base_y + i * 22), font, 0.52, (100, 255, 255), 1)


def print_object_details(mem):
    print("=" * 50)
    print(f" DETAILS FOR: {mem.label.upper()} ")
    print("=" * 50)
    print(f"Current State : {mem.state}")
    print(f"Stable Zone   : {mem.stable_zone}")
    print(f"Last Position : ({mem.last_x}, {mem.last_y})")
    print(f"Last Seen At  : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mem.last_seen_time))}")
    print("-" * 50)
    print("EVENT LOG HISTORY:")
    if not mem.event_log:
        print("  No event history recorded.")
    else:
        for event in mem.event_log:
            print(f"  [{event['time_str']}] {event['event'].capitalize()} in {event['zone']}")
    print("=" * 50)
    print()


def main():
    print("Cognitive Memory Engine — Starting")
    print("Shortcuts:")
    print("  [i] : Ask a question by typing (Text Mode)")
    print("  [d] : Delete a custom spatial zone (Delete Mode)")
    print("  [z] : Draw a new spatial zone (Mouse drag)")
    print("  [q] : Quit")

    # Initialize persistent database schema and load dynamic data
    init_db()
    load_zones()

    from ultralytics import YOLO
    model = YOLO("yolov8n.pt")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] Could not open webcam. Check your camera connection.")
        return

    # Load previously tracked object states and movement histories from MySQL database
    memory_bank = load_memory_bank()
    orphan_positions = {}
    frame_count = 0


    query_engine = QueryEngine(memory_bank)

    voice_state = "idle"
    recognized_text = ""
    last_answer = ""
    wrapped_lines = []
    typed_text = ""
    visible_uids_snapshot = set()

    cv2.namedWindow("Cognitive Memory Engine")
    cv2.setMouseCallback("Cognitive Memory Engine", mouse_callback)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        now = time.time()

        # Prune dead orphans (prevent memory leak)
        orphan_positions = {k: v for k, v in orphan_positions.items() if now - v[2] < 10.0}

        # Prune expired memories (confidence = 0) to prevent memory bank bloat and UI overflow
        expired_uids = [uid for uid, mem in list(memory_bank.items()) if not mem.visible and mem.seconds_missing() > 600]
        for uid in expired_uids:
            memory_bank.pop(uid, None)
            delete_object_state(uid)  # Delete expired states from database

        draw_zones(frame)

        results = model.track(
            frame,
            persist=True,
            conf=0.5,
            iou=0.5,
            tracker="bytetrack.yaml",
            verbose=False
        )

        visible_uids = set()
        frame_objects = {}

        if results and results[0].boxes is not None:
            # Keep only the highest confidence box per class (one object of a kind)
            best_boxes = {}
            for box in results[0].boxes:
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                
                # Failsafe if YOLO model classes mismatch
                if cls >= len(model.names): continue
                label = model.names[cls]

                threshold = CONF_THRESHOLDS.get(label, 0.60)
                if conf < threshold or label not in VALID_CLASSES:
                    continue

                if label not in best_boxes or conf > float(best_boxes[label].conf[0]):
                    best_boxes[label] = box

            for label, box in best_boxes.items():
                conf = float(box.conf[0])
                uid = label

                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                frame_objects[uid] = (cx, cy, label)

                if uid not in memory_bank:
                    memory_bank[uid] = ObjectMemory(label)

                visible_uids.add(uid)
                mem = memory_bank[uid]
                mem.visible = True
                mem.last_seen_time = now
                # Update last_seen_zone from stable_zone when valid, or from
                # current raw zone on first appearance so it's never left as "unknown"
                if mem.stable_zone != "unknown":
                    mem.last_seen_zone = mem.stable_zone
                elif mem.last_seen_zone == "unknown":
                    zone_check = get_zone(cx, cy)
                    if zone_check != "unknown":
                        mem.last_seen_zone = zone_check

                zone_now = get_zone(cx, cy)
                if zone_now == mem.raw_zone:
                    mem.zone_strike += 1
                else:
                    mem.raw_zone = zone_now
                    mem.zone_strike = 1

                if mem.zone_strike >= mem.STABILITY_FRAMES and \
                   mem.stable_zone != zone_now and \
                   now - mem.first_seen_time > 1.0:
                    prev = mem.stable_zone
                    mem.stable_zone = zone_now
                    mem.zone_entry_time = now
                    mem.still_since = None

                    if zone_now == "unknown" and prev != "unknown":
                        add_log(f"{mem.display_name} left {prev}", priority=3)
                        mem.remember("removed", prev)
                        mem.state = "removed"
                    elif zone_now != "unknown":
                        add_log(f"{mem.display_name} -> {zone_now}", priority=1)
                        mem.remember("moved", zone_now)

                if mem.last_x is not None and now - mem.first_seen_time > 1.0:
                    mem.speed = dist(cx, cy, mem.last_x, mem.last_y)

                    if mem.speed > 15:
                        prev_state = mem.state
                        mem.state = "moving"
                        mem.still_since = None
                        if prev_state == "placed":
                            msg = f"{mem.display_name} picked up from {mem.stable_zone}"
                            if mem.remember("picked up", mem.stable_zone, cooldown=3.0):
                                add_log(msg, priority=2)

                    elif mem.speed < 2:
                        if mem.still_since is None:
                            mem.still_since = now
                        still_dur = now - mem.still_since
                        if still_dur >= mem.placement_duration_required and \
                           mem.stable_zone != "unknown" and mem.state != "placed":
                            mem.state = "placed"
                            msg = f"{mem.display_name} placed in {mem.stable_zone}"
                            if mem.remember("placed", mem.stable_zone, cooldown=5.0):
                                add_log(msg, priority=3)
                        elif still_dur < mem.placement_duration_required and mem.state == "moving":
                            mem.state = "idle"

                mem.last_x = cx
                mem.last_y = cy

                # Sync object state to database (throttled: every 30 frames to reduce DB load)
                if frame_count % 30 == 0:
                    save_object_state(mem)

                nearby = [
                    olabel for ouid, (ox, oy, olabel) in frame_objects.items()
                    if ouid != uid and dist(cx, cy, ox, oy) < 120
                ]

                state_color = {
                    "placed":    (0, 255, 0),
                    "moving":    (0, 255, 255),
                    "picked up": (0, 165, 255),
                    "removed":   (0, 0, 255),
                }.get(mem.state, (180, 180, 180))

                cv2.rectangle(frame, (x1, y1), (x2, y2), state_color, 2)
                cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
                zone_label = mem.stable_zone if mem.stable_zone != "unknown" else "?"
                tag = f"{mem.display_name} [{zone_label}] {mem.state}"
                if nearby:
                    tag += f" near {nearby[0]}"
                draw_text_with_shadow(frame, tag, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.52, state_color, 2)
                cv2.rectangle(frame, (x1, y2 + 4), (x1 + int(conf * 100), y2 + 12), state_color, -1)

        visible_uids_snapshot = set(visible_uids)

        for uid, mem in memory_bank.items():
            if uid not in visible_uids:
                if mem.visible:
                    mem.visible = False
                    # Sync state update on visibility loss
                    save_object_state(mem)
                if mem.last_x is not None:
                    orphan_positions[uid] = (mem.last_x, mem.last_y, mem.last_seen_time)





        # Sync voice_state with delete_mode state from mouse callback
        if voice_state == "deleting" and not drawing_state.get("delete_mode", False):
            voice_state = "idle"

        draw_memory_panel(frame, memory_bank, visible_uids)
        draw_event_log(frame)
        draw_voice_ui(frame, voice_state, recognized_text, last_answer, wrapped_lines, typed_text)

        if drawing_state["active"] and drawing_state["start"] and drawing_state["current"]:
            sx, sy = drawing_state["start"]
            ex, ey = drawing_state["current"]
            cv2.rectangle(frame, (sx, sy), (ex, ey), (0, 255, 0), 2)

        cv2.imshow("Cognitive Memory Engine", frame)

        # Keyboard Control
        key = cv2.waitKey(1) & 0xFF

        # Handle keyboard shortcuts and modes
        if voice_state == "typing":
            if key == 13 or key == 10: # Enter Key
                if typed_text.strip():
                    recognized_text = typed_text.strip()
                    answer = query_engine.query(recognized_text, visible_uids_snapshot)
                    last_answer = answer
                    wrapped_lines = wrap_text(answer, cv2.FONT_HERSHEY_SIMPLEX, frame.shape[1] - 40)
                    print(f"\nText Q: {recognized_text}\nAnswer: {answer}\n")
                    
                    # Print details to the console window also
                    label = query_engine.resolve_label(recognized_text)
                    if label and label in memory_bank:
                        print_object_details(memory_bank[label])
                        
                    voice_state = "idle"
                else:
                    voice_state = "idle"
                typed_text = ""
            elif key == 8 or key == 127: # Backspace Key
                typed_text = typed_text[:-1]
            elif key == 27: # Esc Key (Cancel)
                voice_state = "idle"
                typed_text = ""
            elif 32 <= key <= 126: # Valid ASCII characters
                typed_text += chr(key)
        elif voice_state == "deleting":
            if key == 27: # Esc Key (Cancel delete mode)
                drawing_state["delete_mode"] = False
                voice_state = "idle"
        else:
            if key == ord('q') or key == 27: # Quit on 'q' or 'Esc'
                break

            elif key == ord('i') and voice_state == "idle":
                voice_state = "typing"
                typed_text = ""
                recognized_text = ""
                last_answer = ""
            elif key == ord('d') and voice_state == "idle":
                drawing_state["delete_mode"] = True
                voice_state = "deleting"
                print("Delete Mode Activated. Click inside any zone on the video feed to delete it.")
            elif key == ord('z') and voice_state == "idle":
                drawing_state["drawing_mode"] = True
                print("Drawing Mode: Click and drag on the video to define a new zone.")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
