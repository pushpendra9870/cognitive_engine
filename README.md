# Cognitive Event-Memory Engine

A real-time object tracking, spatial zone reasoning, and natural language query system powered by **YOLOv8** and **OpenCV**, with persistent state and event tracking saved to a **MySQL** database.

The application captures video frames (from a camera or video source), runs object detection, tracks object positions, maps them to dynamic spatial zones, detects event triggers (e.g., placing, picking up, or moving objects), and supports natural language queries (like *"where is my phone?"* or *"history of laptop"*) to find objects in real-time.

---

## 🛠️ Technology Stack & Tools

* **Programming Language**: Python 3
* **Computer Vision**: 
  * **OpenCV**: Handles video capture, high-contrast HUD drawing, dynamic spatial zone interaction, and query/keyboard interfaces.
  * **YOLOv8 (Ultralytics)**: Performs high-accuracy, real-time object detection and tracking.
* **Database Backend**: 
  * **MySQL**: Persists spatial zone definitions, object kinematic states, and event log history. Uses `mysql-connector-python` for native SQL integration.
* **Key Algorithmic Components**:
  * **Kinematic State Engine**: Infers object states (`initialized`, `idle`, `moving`, `placed`, `removed`) based on spatial stabilization and velocity.
  * **Proximity-Based Re-ID Healer**: Prevents "ghost IDs" caused by camera noise or occlusion by mapping new tracking IDs to recently lost objects in proximity.
  * **Natural Language Query Engine**: Parses text queries in real-time and retrieves answers from current tracking states and history logs.

---

## 📋 Database Schema

The database `cognitive_engine` consists of three primary tables:
1. **`zones`**: Stores the coordinate bounds (`x1, y1, x2, y2`) of spatial zones (`Drawer`, `Table`, `Shelf`, etc.).
2. **`object_states`**: Maintains the current kinematic state, last coordinates, and timestamp details of active/tracked objects.
3. **`object_history`**: A transaction/audit log storing a history of state transitions (e.g., when an object is placed, moved, or picked up) for timeline analysis.

---

## 🚀 Installation & Setup

### 1. Prerequisites
Ensure you have Python 3.10+ and a MySQL Server running on your system.

### 2. Clone the Repository
```bash
git clone https://github.com/pushpendra9870/camera.git
cd "final project"
```

### 3. Create a Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install opencv-python numpy ultralytics mysql-connector-python
```

### 5. Database Configuration
Make sure your MySQL server is running. Copy the `.env.example` file to `.env` and fill in your database credentials:
```bash
cp .env.example .env
```
Open `.env` and configure:
* **DB_HOST**: `localhost`
* **DB_USER**: `root`
* **DB_PASSWORD**: `your_mysql_password`
* **DB_DATABASE**: `cognitive_engine` (automatically created on first startup if it doesn't exist)

---

## 🎮 How to Run & Control Guide

Start the engine:
```bash
python app.py
```

### Keyboard Shortcuts
* **`[i]`**: Enter query mode. Type natural queries (e.g., *"where is my phone"* or *"history of book"*) in the on-screen console and press **Enter** to get instant answers. Press **Esc** to exit query mode.
* **`[z]`**: Toggle custom zone drawing mode. Click and drag with your mouse on the frame to draw a new bounding zone, and assign it a name.
* **`[q]` or `[Esc]`**: Exit/Quit the application.
