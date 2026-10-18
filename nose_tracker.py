#!/usr/bin/env python3
"""
nose_tracker.py - A lightweight desktop tool to detect aircraft noses in a
fixed‑camera runway livestream, draw persistent trails, and display
real‑time status.

Features
--------
* Select capture region (drag rectangle) on a frozen screenshot.
* Optional detection ROI (press 'r' to draw, 'c' to clear).
* Background subtraction with running average (learning rate 0.02).
* Motion mask cleaning, blob detection, velocity tracking, nose point.
* Exponential smoothing on nose position.
* Persistent overlay for trails (never fades).
* Keyboard controls for threshold, smoothing, trail presets, line width,
  pause/resume, screenshot saving, quit, etc.
* Optional CLI flags:
    --record out.mp4          save annotated video
    --save-trails trails.npy  persist overlay between runs
    --load-trails trails.npy  load persisted overlay
    --fps N                 cap processing rate (default 30)
    --source file.mp4        use video file instead of screen capture
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import cv2
import mss
import numpy as np

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #
def _resize_frame(frame: np.ndarray, target_width: int = 640) -> np.ndarray:
    """Resize frame while keeping aspect ratio."""
    if frame.shape[1] <= target_width:
        return frame
    scale = target_width / frame.shape[1]
    return cv2.resize(frame, (target_width, int(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)


def _draw_overlay(frame: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    """Blend overlay onto frame (overlay is BGR, same size)."""
    return cv2.addWeighted(frame, 1.0, overlay, 0.7, 0)


# --------------------------------------------------------------------------- #
# Capture class – handles region selection and continuous capture
# --------------------------------------------------------------------------- #
class Capture:
    """Capture a user‑selected rectangular region from the screen."""

    def __init__(self, downscale_width: int = 640):
        self.downscale_width = downscale_width
        self.region: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h) in screen coords
        self._first_frame: Optional[np.ndarray] = None
        self._screen_monitor = 1  # primary monitor; can be changed if needed

    def select_region(self) -> Tuple[int, int, int, int]:
        """Open cv2 window, let user drag a rectangle, return (x, y, w, h)."""
        with mss.mss() as sct:
            # Grab a full screenshot to let cv2.selectROI work
            sct_img = sct.grab(sct.monitors[self._screen_monitor])
            img_np = np.array(sct_img)
            # Convert BGR (OpenCV) from BGRA
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
            cv2.namedWindow("Select capture region – press ENTER when done", cv2.WINDOW_NORMAL)
            roi = cv2.selectROI("Select capture region – press ENTER when done", img_bgr, False, False)
            cv2.destroyAllWindows()
            if roi == (0, 0, 0, 0):
                raise RuntimeError("Region selection cancelled.")
            x, y, w, h = roi
            self.region = (x, y, w, h)
            return self.region

    def grab(self) -> Tuple[np.ndarray, int, int]:
        """
        Grab the selected region, downscale it, and return:
        (frame, full_width, full_height)
        The frame is already resized to `downscale_width`.
        """
        if self.region is None:
            raise RuntimeError("Capture region not selected yet.")
        x, y, w, h = self.region
        with mss.mss() as sct:
            sct_img = sct.grab({"top": y, "left": x, "width": w, "height": h})
            img_np = np.array(sct_img)
            frame = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
            frame = _resize_frame(frame, self.downscale_width)
            h_full, w_full = frame.shape[:2]
            return frame, w_full, h_full

    def get_first_frame(self) -> np.ndarray:
        """Return the first captured frame (used for ROI selection)."""
        if self._first_frame is None:
            frame, _, _ = self.grab()
            self._first_frame = frame
        return self._first_frame


# --------------------------------------------------------------------------- #
# Detector class – pure logic, no UI
# --------------------------------------------------------------------------- #
class Detector:
    """
    Detect aircraft noses in a frame.

    Parameters
    ----------
    learning_rate : float
        How fast the background model adapts (default 0.02).
    motion_thresh : int
        Absolute difference threshold for motion mask (default 22).
    min_area : int
        Minimum blob area (in down‑scaled pixels) to keep (default 16).
    max_bg_change_frac : float
        Fraction of mask that must be active to consider a scene change
        (default 0.30).
    roi : Tuple[int, int, int, int] | None
        Optional detection region (x, y, w, h) in down‑scaled coordinates.
        If None, whole frame is used.
    """

    def __init__(
        self,
        learning_rate: float = 0.02,
        motion_thresh: int = 22,
        min_area: int = 16,
        max_bg_change_frac: float = 0.30,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ):
        self.learning_rate = learning_rate
        self.motion_thresh = motion_thresh
        self.min_area = min_area
        self.max_bg_change_frac = max_bg_change_frac
        self.roi = roi
        self.bg_model: Optional[np.ndarray] = None  # running average (float32)
        self._prev_centroid: Optional[Tuple[int, int]] = None
        self._prev_frame: Optional[np.ndarray] = None

    def _maybe_reset_bg(self, mask: np.ndarray) -> bool:
        """If > max_bg_change_frac of mask is active, reset background and return True."""
        if self.bg_model is None:
            self.bg_model = mask.astype(np.float32)
            return False
        if np.count_nonzero(mask) > self.max_bg_change_frac * mask.size:
            self.bg_model = mask.astype(np.float32)
            return True
        return False

    def update(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Process a down‑scaled frame.

        Returns a dict with keys:
            'nose'        : (x, y) in full‑resolution coordinates
            'speed'       : scalar speed (pixels/frame)
            'mask'        : binary motion mask (down‑scaled)
            'status'      : 'tracking', 'scene_change', 'no_detection', etc.
        """
        if self.bg_model is None:
            self.bg_model = frame.astype(np.float32)

        # Motion mask
        diff = cv2.absdiff(self.bg_model.astype(np.uint8), frame)
        _, mask = cv2.threshold(diff, self.motion_thresh, 255, cv2.THRESH_BINARY)

        # Scene change detection
        if self._maybe_reset_bg(mask):
            self.bg_model = mask.astype(np.float32)
            return {"nose": None, "speed": 0.0, "mask": mask, "status": "scene_change"}

        # Apply ROI mask if requested
        if self.roi is not None:
            x, y, w, h = self.roi
            mask = mask[y : y + h, x : x + w]
            # Also mask the frame for consistency
            frame = frame[y : y + h, x : x + w]

        # Morphological cleaning
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        # Find largest component above min_area
        n_components, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n_components <= 1:
            # No foreground pixels
            self._prev_centroid = None
            self._prev_frame = None
            return {"nose": None, "speed": 0.0, "mask": mask, "status": "no_detection"}

        # Extract stats for each component (ignore background = 0)
        areas = stats[1:, cv2.CC_STAT_AREA]
        if areas.size == 0:
            self._prev_centroid = None
            self._prev_frame = None
            return {"nose": None, "speed": 0.0, "mask": mask, "status": "no_detection"}

        max_idx = int(np.argmax(areas))
        max_area = areas[max_idx]
        if max_area < self.min_area:
            self._prev_centroid = None
            self._prev_frame = None
            return {"nose": None, "speed": 0.0, "mask": mask, "status": "no_detection"}

        # Centroid of the largest component
        centroid_idx = np.argmax(labels == max_idx)
        y, x = np.where(labels == max_idx)
        cx, cy = int(np.mean(x)), int(np.mean(y))

        # Velocity estimation
        speed = 0.0
        if self._prev_centroid is not None:
            dx = cx - self._prev_centroid[0]
            dy = cy - self._prev_centroid[1]
            speed = np.hypot(dx, dy)

        # Update previous state
        self._prev_centroid = (cx, cy)
        self._prev_frame = frame.copy()

        # Determine nose point
        if speed >= 0.15:
            # Use contour point farthest along velocity direction
            # Get contour of the selected component
            contour = np.where(labels == max_idx)[0][0]  # first index of max component
            cnt = contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
            # Find point with max dot product with velocity vector
            vel_vec = np.array([dx, dy], dtype=np.float32)
            if np.linalg.norm(vel_vec) == 0:
                nose = (cx, cy)
            else:
                vel_unit = vel_vec / np.linalg.norm(vel_vec)
                # Compute dot product for each contour point
                dot_products = cnt[:, 0, :].flatten() @ vel_unit
                # Pick point with max dot product
                max_idx_pt = int(np.argmax(dot_products))
                nose_pt = cnt[max_idx_pt][0]
                nose = (nose_pt[0], nose_pt[1])
        else:
            nose = (cx, cy)

        # Convert back to full‑resolution coordinates
        if self.roi is not None:
            x, y, w, h = self.roi
            nose_full = (int(nose[0] * w_full / w) + x, int(nose[1] * h_full / h) + y)
        else:
            nose_full = (int(nose[0] * self._first_frame.shape[1] / frame.shape[1]), int(nose[1] * self._first_frame.shape[0] / frame.shape[0]))

        return {
            "nose": nose_full,
            "speed": float(speed),
            "mask": mask.copy(),
            "status": "tracking",
        }

    # ------------------------------------------------------------------- #
    # Utility for testing – reset internal state
    # ------------------------------------------------------------------- #
    def reset(self):
        self.bg_model = None
        self._prev_centroid = None
        self._prev_frame = None


# --------------------------------------------------------------------------- #
# TrailLayer class – persistent overlay for trails
# --------------------------------------------------------------------------- #
class TrailLayer:
    """
    Holds a BGR image that stores all drawn trails.
    Provides methods to draw lines, markers, and composite with the live frame.
    """

    def __init__(self, size: Tuple[int, int]):
        self.size = size  # (height, width)
        self.overlay = np.zeros((height, width, 3), dtype=np.uint8)  # black background

    def draw_line(self, pt1: Tuple[int, int], pt2: Tuple[int, int], color: Tuple[int, int, int], thickness: int = 2):
        cv2.line(self.overlay, pt1, pt2, color, thickness)

    def draw_circle(self, center: Tuple[int, int], radius: int, color: Tuple[int, int, int], thickness: int = -1):
        cv2.circle(self.overlay, center, radius, color, thickness)

    def composite(self, frame: np.ndarray) -> np.ndarray:
        """Blend overlay onto frame and return the result."""
        return _draw_overlay(frame, self.overlay)


# --------------------------------------------------------------------------- #
# Tracker class – manages paths, smoothing, and trail drawing
# --------------------------------------------------------------------------- #
class Tracker:
    """
    Track aircraft noses across frames, manage multiple paths, and draw trails.

    Parameters
    ----------
    smoothing_alpha : float
        Exponential smoothing factor for nose position (0 < α ≤ 1). Default 0.3.
    trail_color : Tuple[int, int, int]
        BGR color for the trail lines (default white = (255, 255, 255)).
    marker_radius : int
        Radius of the nose marker circle.
    marker_thickness : int
        Thickness of the marker circle (‑1 = filled).
    """

    def __init__(
        self,
        smoothing_alpha: float = 0.3,
        trail_color: Tuple[int, int, int] = (255, 255, 255),
        marker_radius: int = 5,
        marker_thickness: int = -1,
    ):
        self.smoothing_alpha = smoothing_alpha
        self.trail_color = trail_color
        self.marker_radius = marker_radius
        self.marker_thickness = marker_thickness
        self.paths: List[List[Tuple[int, int]]] = []  # each path is list of nose points
        self.current_path: List[Tuple[int, int]] = []
        self.last_nose: Optional[Tuple[int, int]] = None
        self.last_speed: float = 0.0
        self.frame_counter = 0
        self.no_detection_counter = 0

    def update(self, nose: Optional[Tuple[int, int]], speed: float, frame_shape: Tuple[int, int]) -> List[Tuple[int, int]]:
        """
        Feed a detected nose (or None) and its speed to the tracker.

        Returns the list of points for the current nose (for drawing the marker).
        """
        self.frame_counter += 1

        if nose is None:
            # No detection – increase gap counter
            self.no_detection_counter += 1
            if self.no_detection_counter > 45:
                # End current path and start a new one after reset
                if self.current_path:
                    self.paths.append(self.current_path)
                    self.current_path = []
                self.no_detection_counter = 0
            return []  # no marker

        # Reset gap counter
        self.no_detection_counter = 0

        # Smooth nose position
        if self.last_nose is None:
            smoothed_nose = nose
        else:
            # Exponential smoothing: new = α * current + (1-α) * previous
            smoothed_nose = (
                int(self.smoothing_alpha * nose[0] + (1 - self.smoothing_alpha) * self.last_nose[0]),
                int(self.smoothing_alpha * nose[1] + (1 - self.smoothing_alpha) * self.last_nose[1]),
            )
        self.last_nose = smoothed_nose

        # Add point to current path
        self.current_path.append(smoothed_nose)

        # If we have enough points, draw a line segment onto the trail layer (handled elsewhere)
        return [smoothed_nose]

    def new_path(self):
        """Start a fresh path (called when a gap >45 frames occurs)."""
        if self.current_path:
            self.paths.append(self.current_path)
        self.current_path = []

    def get_all_paths(self) -> List[List[Tuple[int, int]]]:
        """Return a deep copy of all stored paths."""
        return [list(p) for p in self.paths]

    def draw(self, overlay: TrailLayer):
        """Draw all stored paths onto the overlay."""
        for path in self.paths:
            if len(path) < 2:
                continue
            for i in range(len(path) - 1):
                cv2.line(overlay.overlay, path[i], path[i + 1], self.trail_color, 2)

        # Draw current nose marker
        if self.last_nose is not None:
            cv2.circle(overlay.overlay, self.last_nose, self.marker_radius, (0, 0, 255), self.marker_thickness)  # red marker


# --------------------------------------------------------------------------- #
# UI class – handles OpenCV window, key bindings, and overlay display
# --------------------------------------------------------------------------- #
class UI:
    """
    Main interactive loop.

    Parameters
    ----------
    capture : Capture
    detector : Detector
    tracker : Tracker
    trail_layer : TrailLayer
    fps_cap : int | None
        If set, processing will be limited to this many frames per second.
    """

    def __init__(
        self,
        capture: Capture,
        detector: Detector,
        tracker: Tracker,
        trail_layer: TrailLayer,
        fps_cap: Optional[int] = None,
    ):
        self.capture = capture
        self.detector = detector
        self.tracker = tracker
        self.trail_layer = trail_layer
        self.fps_cap = fps_cap
        self.running = True
        self.paused = False
        self.last_time = time.time()

    def _draw_text(self, img: np.ndarray, pos: Tuple[int, int], text: str, color: Tuple[int, int, int] = (255, 255, 255)):
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

    def _handle_key(self, key: int):
        if key == ord("q") or key == 27:  # ESC or q
            self.running = False
        elif key == ord("p"):
            self.paused = not self.paused
        elif key == ord("r"):
            # Draw detection ROI
            frame, w_full, h_full = self.capture.grab()
            # Use the full frame for ROI selection (unscaled)
            roi = cv2.selectROI("Detection ROI – press ENTER when done", frame, False, False)
            cv2.destroyAllWindows()
            if roi != (0, 0, 0, 0):
                x, y, w, h = roi
                # Convert to down‑scaled coordinates
                self.detector.roi = (
                    int(x * self.capture.downscale_width / w_full),
                    int(y * self.capture.downscale_width / h_full),
                    int(w * self.capture.downscale_width / w_full),
                    int(h * self.capture.downscale_width / h_full),
                )
        elif key == ord("c"):
            self.detector.roi = None
        elif key == ord("+"):
            self.detector.motion_thresh = np.clip(self.detector.motion_thresh + 5, 0, 255)
        elif key == ord("-"):
            self.detector.motion_thresh = np.clip(self.detector.motion_thresh - 5, 0, 255)
        elif key == ord("[") :
            self.detector.motion_thresh = np.clip(self.detector.motion_thresh - 1, 0, 255)
        elif key == ord("]"):
            self.detector.motion_thresh = np.clip(self.detector.motion_thresh + 1, 0, 255)
        elif key == 49:  # '1'
            self.tracker.trail_color = (0, 0, 255)  # red
        elif key == 50:  # '2'
            self.tracker.trail_color = (0, 255, 0)  # green
        elif key == 51:  # '3'
            self.tracker.trail_color = (255, 0, 0)  # blue
        elif key == 52:  # '4'
            self.tracker.trail_color = (255, 255, 0)  # yellow
        elif key == 53:  # '5'
            self.tracker.trail_color = (255, 0, 255)  # magenta
        elif key == 54:  # '6'
            self.tracker.trail_color = (0, 255, 255)  # cyan
        elif key == 55:  # '7'
            self.tracker.trail_color = (255, 165, 0)  # orange
        elif key == 56:  # '8'
            self.tracker.trail_color = (128, 0, 128)  # purple
        elif key == 57:  # '9'
            self.tracker.trail_color = (200, 200, 200)  # light gray
        elif key == 45:  # '-'
            self.tracker.trail_color = (0, 0, 0)  # black (no trail)
        elif key == 95:  # '_' (line width down)
            self.tracker.trail_color = (self.tracker.trail_color[0], max(1, self.tracker.trail_color[1] - 1), self.tracker.trail_color[2])
        elif key == 61:  # '=' (line width up)
            self.tracker.trail_color = (min(255, self.tracker.trail_color[0] + 1), self.tracker.trail_color[1], self.tracker.trail_color[2])
        elif key == ord("x"):
            self.tracker.tracker.reset()
            self.trail_layer.overlay[:] = 0
        elif key == ord("w"):
            # increase line width (handled via '=' key)
            pass
        elif key == ord("s"):
            # decrease line width (handled via '-' key)
            pass

    def run(self):
        """Main loop – capture, detect, track, draw."""
        cv2.namedWindow("Nose Tracker", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Nose Tracker", 1280, 720)

        # Initial UI text
        self._draw_status("Watching", (10, 30))

        while self.running:
            if not self.paused:
                try:
                    frame, w_full, h_full = self.capture.grab()
                except Exception as e:
                    print(f"Capture error: {e}", file=sys.stderr)
                    break

                # Detect
                det = self.detector.update(frame)

                # Update tracker
                nose_points = self.tracker.update(det["nose"], det["speed"], (h_full, w_full))

                # Draw overlay
                self.trail_layer.draw()
                self.tracker.draw(self.trail_layer)

                # Composite final frame
                final_frame = self.trail_layer.composite(frame)

                # UI overlay text
                status = "Tracking" if det["status"] == "tracking" else "Watching"
                self._draw_status(f"{status} | FPS: {self.fps_cap or int(1/(time.time() - self.last_time))}", (10, 70))

                # Show frame
                cv2.imshow("Nose Tracker", final_frame)
                self.last_time = time.time()

                # Frame rate limiting
                if self.fps_cap:
                    elapsed = time.time() - self.last_time
                    if elapsed < 1.0 / self.fps_cap:
                        time.sleep(1.0 / self.fps_cap - elapsed)

                # Key handling
                key = cv2.waitKey(1) & 0xFF
                self._handle_key(key)

        cv2.destroyAllWindows()

    def _draw_status(self, text: str, pos: Tuple[int, int]):
        """Utility to draw a small status line."""
        frame = self.trail_layer.composite(np.zeros_like(self.trail_layer.overlay))
        self._draw_text(frame, pos, text)
        # Show on the real frame
        final_frame = self.trail_layer.composite(np.zeros_like(final_frame))
        # Actually we just re‑draw on the current frame:
        final_frame = self.trail_layer.composite(frame)
        self._draw_text(final_frame, pos, text)


# --------------------------------------------------------------------------- #
# Main entry point – parse args, initialise components, run UI
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Nose Tracker – detect aircraft noses in a runway livestream.")
    parser.add_argument("--record", type=str, help="Output video file (e.g., out.mp4).")
    parser.add_argument("--save-trails", type=str, help="Path to .npy file to save the overlay layer.")
    parser.add_argument("--load-trails", type=str, help="Path to .npy file to load the overlay layer.")
    parser.add_argument("--fps", type=int, default=30, help="Maximum processing frames per second (default 30).")
    parser.add_argument("--source", type=str, help="Video file to process instead of screen capture.")
    args = parser.parse_args()

    # ------------------------------------------------------------------- #
    # Capture setup
    # ------------------------------------------------------------------- #
    if args.source:
        # Video source
        cap = cv2.VideoCapture(args.source)
        if not cap.isOpened():
            print(f"Error: cannot open video file {args.source}", file=sys.stderr)
            sys.exit(1)

        # We need a first frame to select capture region; use the first frame of the video.
        ret, first_frame = cap.read()
        if not ret:
            print("Error: cannot read first frame from video.", file=sys.stderr)
            sys.exit(1)

        # Convert to a format that allows region selection
        # For simplicity, we reuse the same UI flow but with a static region.
        # Create a temporary Capture that works on the first frame.
        temp_capture = Capture(downscale_width=640)
        # Manually set region to full frame (so user can't change it)
        temp_capture.region = (0, 0, first_frame.shape[1], first_frame.shape[0])
        # Grab the first frame to let UI reuse the same code path
        _, _, _ = temp_capture.grab()
        # Use the same detection ROI logic later.
        capture = temp_capture
        # We'll treat the video frames as captured frames later.
        video_mode = True
    else:
        capture = Capture(downscale_width=640)
        capture.select_region()  # let user choose region
        video_mode = False

    # ------------------------------------------------------------------- #
    # Detector setup
    # ------------------------------------------------------------------- #
    detector = Detector(
        learning_rate=0.02,
        motion_thresh=22,
        min_area=16,
        max_bg_change_frac=0.30,
        roi=None,
    )

    # ------------------------------------------------------------------- #
    # Tracker setup
    # ------------------------------------------------------------------- #
    tracker = Tracker(smoothing_alpha=0.3, trail_color=(255, 255, 255), marker_radius=5, marker_thickness=-1)

    # ------------------------------------------------------------------- #
    # TrailLayer setup
    # ------------------------------------------------------------------- #
    # We'll get the full resolution size after the first capture.
    first_frame, w_full, h_full = capture.grab()
    trail_layer = TrailLayer((h_full, w_full))

    # If we need to load persisted trails:
    if args.load_trails:
        trail_path = Path(args.load_trails)
        if trail_path.is_file():
            data = np.load(trail_path)
            if data.shape == trail_layer.size:
                trail_layer.overlay = data.astype(np.uint8)
                print(f"Loaded persisted trails from {args.load_trails}")

    # ------------------------------------------------------------------- #
    # Optional video mode handling
    # ------------------------------------------------------------------- #
    if video_mode:
        # We'll reuse the same capture logic but pull frames from the video.
        # For simplicity, we treat each video frame as a captured frame.
        # The UI will still use the same capture.grab() method, but we need to
        # modify it to read from the VideoCapture instead of mss.
        # To avoid rewriting, we create a small wrapper class.
        class VideoCaptureWrapper:
            def __init__(self, cap: cv2.VideoCapture):
                self.cap = cap
                self.region = (0, 0, 0, 0)  # dummy, not used

            def grab(self):
                ret, frame = self.cap.read()
                if not ret:
                    raise RuntimeError("End of video or read error.")
                # Resize to downscale width
                frame = _resize_frame(frame, 640)
                h_full, w_full = frame.shape[:2]
                return frame, w_full, h_full

            def select_region(self):
                # Not used in video mode – raise error if called.
                raise RuntimeError("Region selection not supported for video source.")

        capture = VideoCaptureWrapper(cap)

    # ------------------------------------------------------------------- #
    # UI run loop
    # ------------------------------------------------------------------- #
    ui = UI(capture, detector, tracker, trail_layer, fps_cap=args.fps)
    try:
        ui.run()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        print(f"Error in UI loop: {e}", file=sys.stderr)

    # ------------------------------------------------------------------- #
    # Optional video recording
    # ------------------------------------------------------------------- #
    if args.record:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out_width = w_full
        out_height = h_full
        out = cv2.VideoWriter(args.record, fourcc, args.fps, (out_width, out_height))
        if not out.isOpened():
            print(f"Error: cannot open video writer for {args.record}", file=sys.stderr)
        else:
            # Re‑run the capture loop to record – we reuse the UI logic but without showing the window.
            # For brevity, we just capture frames and write them.
            while ui.running:
                if not ui.paused:
                    frame, _, _ = capture.grab()
                    det = detector.update(frame)
                    ui.tracker.update(det["nose"], det["speed"], (h_full, w_full))
                    ui.trail_layer.draw()
                    ui.tracker.draw(ui.trail_layer)
                    final_frame = ui.trail_layer.composite(frame)
                    out.write(final_frame)
                else:
                    time.sleep(0.01)

            out.release()
            print(f"Video saved to {args.record}")

    # ------------------------------------------------------------------- #
    # Optional trail persistence
    # ------------------------------------------------------------------- #
    if args.save_trails:
        trail_path = Path(args.save_trails)
        np.save(trail_path, trail_layer.overlay)
        print(f"Trail overlay saved to {args.save_trails}")


if __name__ == "__main__":
    main()