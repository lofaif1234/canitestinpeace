#!/usr/bin/env python3
"""
roblox_launch.py — Floating Roblox instance launcher
Android 10 with custom floating windows. Uses touch simulation to move/resize.

Usage:
  python3 roblox_launch.py                        # auto-detect packages
  python3 roblox_launch.py com.pkg1 com.pkg2 ...  # explicit package list
"""

import sys
import time
import subprocess
import threading
import re
import select

# ──────────────────────────────────────────────────────────────────────────────
# Persistent root shell
# ──────────────────────────────────────────────────────────────────────────────
class SuShell:
    _proc  = None
    _lock  = threading.Lock()
    _ready = False
    _FENCE = "__DONE__"

    @classmethod
    def _start(cls):
        try:
            cls._proc = subprocess.Popen(
                ["su"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            cls._ready = "alive" in cls._send("echo alive", timeout=6)
        except Exception:
            cls._proc  = None
            cls._ready = False

    @classmethod
    def _send(cls, cmd: str, timeout: float = 15) -> str:
        if cls._proc is None or cls._proc.poll() is not None:
            return ""
        try:
            cls._proc.stdin.write(f"{cmd}\necho {cls._FENCE}\n")
            cls._proc.stdin.flush()
            lines, deadline = [], time.time() + timeout
            while time.time() < deadline:
                r, _, _ = select.select([cls._proc.stdout], [], [], 0.1)
                if r:
                    line = cls._proc.stdout.readline().rstrip("\r\n")
                    if line == cls._FENCE:
                        break
                    if line:
                        lines.append(line)
            return "\n".join(lines)
        except Exception:
            return ""

    @classmethod
    def run(cls, cmd: str, timeout: float = 15) -> str:
        with cls._lock:
            if not cls._ready:
                cls._start()
            if not cls._ready:
                return ""
            return cls._send(cmd, timeout)

    @classmethod
    def ok(cls) -> bool:
        with cls._lock:
            if not cls._ready:
                cls._start()
            return cls._ready

    @classmethod
    def close(cls):
        try:
            if cls._proc and cls._proc.poll() is None:
                cls._proc.stdin.write("exit\n")
                cls._proc.stdin.flush()
                cls._proc.wait(timeout=2)
        except Exception:
            pass
        finally:
            cls._proc = None
            cls._ready = False


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
PLACE_ID      = ""
DELAY_BETWEEN = 5
STATUS_BAR_H  = 80        # px — Android status bar
NAV_BAR_H     = 0         # px — set >0 if you have a nav bar
MARGIN        = 12        # px — gap between windows
LAUNCH_WAIT   = 15        # seconds to wait for app to appear in stack

# Floating window chrome sizes (measure on your device if layout is off)
# These describe the window decoration drawn by your ROM's floating window manager
TITLEBAR_H    = 60        # height of the draggable title bar in px
RESIZE_HANDLE = 30        # size of the corner resize handle in px

# Touch swipe speed (ms). Lower = faster drag, but may miss on slow devices
SWIPE_MS      = 400


# ──────────────────────────────────────────────────────────────────────────────
# Screen
# ──────────────────────────────────────────────────────────────────────────────
def get_screen_size():
    out = SuShell.run("wm size", timeout=5)
    m = re.search(r'(\d+)x(\d+)', out)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        return (min(w, h), max(w, h))
    return (1080, 1920)


# ──────────────────────────────────────────────────────────────────────────────
# Layout calculator
# ──────────────────────────────────────────────────────────────────────────────
def compute_bounds(total: int):
    W, H = get_screen_size()
    usable_h = H - STATUS_BAR_H - NAV_BAR_H

    if total == 1:
        pad = 60
        return [(pad, STATUS_BAR_H + pad, W - pad, H - NAV_BAR_H - pad)]

    if total == 2:
        cell_w = (W - MARGIN * 3) // 2
        cell_h = usable_h - MARGIN * 2
        top = STATUS_BAR_H + MARGIN
        return [
            (MARGIN,              top, MARGIN + cell_w,          top + cell_h),
            (MARGIN * 2 + cell_w, top, MARGIN * 2 + cell_w * 2, top + cell_h),
        ]

    if total <= 4:
        cols = 2
        rows = (total + 1) // 2
        bounds = []
        for i in range(total):
            row, col = divmod(i, cols)
            cell_w = (W - MARGIN * (cols + 1)) // cols
            cell_h = (usable_h - MARGIN * (rows + 1)) // rows
            left   = MARGIN + col * (cell_w + MARGIN)
            top    = STATUS_BAR_H + MARGIN + row * (cell_h + MARGIN)
            bounds.append((left, top, left + cell_w, top + cell_h))
        return bounds

    top_count    = (total + 1) // 2
    bottom_count = total - top_count
    top_h  = (usable_h - MARGIN * 3) * 2 // 5
    bot_h  = usable_h - top_h - MARGIN * 3
    bounds = []
    for col in range(top_count):
        cell_w = (W - MARGIN * (top_count + 1)) // top_count
        left   = MARGIN + col * (cell_w + MARGIN)
        top    = STATUS_BAR_H + MARGIN
        bounds.append((left, top, left + cell_w, top + top_h))
    for col in range(bottom_count):
        cell_w = (W - MARGIN * (bottom_count + 1)) // bottom_count
        left   = MARGIN + col * (cell_w + MARGIN)
        top    = STATUS_BAR_H + MARGIN * 2 + top_h
        bounds.append((left, top, left + cell_w, top + bot_h))
    return bounds


# ──────────────────────────────────────────────────────────────────────────────
# Package helpers
# ──────────────────────────────────────────────────────────────────────────────
def find_roblox_packages():
    for cmd in [
        "pm list packages | grep -i roblox",
        "pm list packages",
        "pm list packages -3",
    ]:
        out = SuShell.run(cmd, timeout=20)
        pkgs = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkg = line.replace("package:", "").strip()
                if re.match(r'^com\.roblox\..+$', pkg, re.IGNORECASE):
                    pkgs.append(pkg)
        if pkgs:
            return list(dict.fromkeys(pkgs))
    return []


def package_installed(pkg: str) -> bool:
    return "package:" in SuShell.run(f"pm path {pkg}", timeout=8)


def wait_for_launch(pkg: str, max_wait: int = LAUNCH_WAIT) -> bool:
    print(f"  Waiting for {pkg} to appear in activity stack", end="", flush=True)
    for _ in range(max_wait):
        if pkg in SuShell.run("dumpsys activity activities", timeout=5):
            print(" ✓")
            return True
        print(".", end="", flush=True)
        time.sleep(1)
    print(" (timed out, continuing anyway)")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Get current floating window bounds from dumpsys window
# ──────────────────────────────────────────────────────────────────────────────
def get_window_bounds(pkg: str) -> tuple | None:
    """
    Returns (left, top, right, bottom) of the window's current frame,
    or None if not found.
    """
    out = SuShell.run(f"dumpsys window windows | grep -A 30 '{pkg}'", timeout=10)
    # Look for patterns like: mFrame=[0,0][1080,2244] or Frame: l=0 t=0 r=1080 b=2244
    m = re.search(r'mFrame=\[(\d+),(\d+)\]\[(\d+),(\d+)\]', out)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    m = re.search(r'Frames:.*?cont=\[(\d+),(\d+)\]\[(\d+),(\d+)\]', out)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    # Try mContainingFrame
    m = re.search(r'mContainingFrame=\[(\d+),(\d+)\]\[(\d+),(\d+)\]', out)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Touch-based move & resize
# ──────────────────────────────────────────────────────────────────────────────
def swipe(x1, y1, x2, y2, ms=SWIPE_MS):
    """Simulate a finger drag from (x1,y1) to (x2,y2)."""
    SuShell.run(f"input swipe {x1} {y1} {x2} {y2} {ms}", timeout=ms // 1000 + 5)


def tap(x, y):
    SuShell.run(f"input tap {x} {y}", timeout=5)


def move_window(cur_left, cur_top, cur_right, cur_bottom,
                dst_left, dst_top):
    """
    Drag the title bar from its current centre to position the window
    so its top-left lands at (dst_left, dst_top).
    """
    # Grab point = centre of title bar
    grab_x = (cur_left + cur_right) // 2
    grab_y = cur_top + TITLEBAR_H // 2

    # Delta needed
    dx = dst_left - cur_left
    dy = dst_top  - cur_top

    dst_x = grab_x + dx
    dst_y = grab_y + dy

    print(f"    move: drag ({grab_x},{grab_y}) → ({dst_x},{dst_y})")
    swipe(grab_x, grab_y, dst_x, dst_y, ms=SWIPE_MS)
    time.sleep(0.4)


def resize_window_touch(cur_left, cur_top, cur_right, cur_bottom,
                        dst_right, dst_bottom):
    """
    Drag the bottom-right resize handle to hit (dst_right, dst_bottom).
    """
    # Handle is at the bottom-right corner of the window
    handle_x = cur_right  - RESIZE_HANDLE // 2
    handle_y = cur_bottom - RESIZE_HANDLE // 2

    print(f"    resize: drag ({handle_x},{handle_y}) → ({dst_right},{dst_bottom})")
    swipe(handle_x, handle_y, dst_right, dst_bottom, ms=SWIPE_MS * 2)
    time.sleep(0.4)


def position_window(pkg: str, dst_left: int, dst_top: int,
                    dst_right: int, dst_bottom: int, attempt: int = 1):
    """
    Read the window's current bounds, then move + resize it to the target.
    Retries up to 3 times if needed.
    """
    for try_n in range(1, 4):
        bounds = get_window_bounds(pkg)
        if bounds is None:
            print(f"    [attempt {try_n}] Could not read window bounds, waiting...")
            time.sleep(1)
            continue

        cur_l, cur_t, cur_r, cur_b = bounds
        print(f"    [attempt {try_n}] Current: ({cur_l},{cur_t},{cur_r},{cur_b})")
        print(f"    [attempt {try_n}] Target:  ({dst_left},{dst_top},{dst_right},{dst_bottom})")

        # Step 1 — move (drag title bar to put top-left in right place)
        if abs(cur_l - dst_left) > 5 or abs(cur_t - dst_top) > 5:
            move_window(cur_l, cur_t, cur_r, cur_b, dst_left, dst_top)
            time.sleep(0.5)
            # Re-read after move
            b2 = get_window_bounds(pkg)
            if b2:
                cur_l, cur_t, cur_r, cur_b = b2

        # Step 2 — resize (drag bottom-right corner)
        if abs(cur_r - dst_right) > 5 or abs(cur_b - dst_bottom) > 5:
            resize_window_touch(cur_l, cur_t, cur_r, cur_b, dst_right, dst_bottom)
            time.sleep(0.5)

        # Verify
        final = get_window_bounds(pkg)
        if final:
            fl, ft, fr, fb = final
            ok = (abs(fl - dst_left)   < 20 and
                  abs(ft - dst_top)    < 20 and
                  abs(fr - dst_right)  < 20 and
                  abs(fb - dst_bottom) < 20)
            print(f"    [attempt {try_n}] Final: ({fl},{ft},{fr},{fb}) {'✓ OK' if ok else '✗ off-target, retrying'}")
            if ok:
                return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# Launch one instance
# ──────────────────────────────────────────────────────────────────────────────
def launch_instance(pkg: str, place_id: str, bounds: tuple, index: int):
    left, top, right, bottom = bounds
    url = f"roblox://placeId={place_id}"
    tag = f"[#{index}] {pkg}"

    print(f"\n  {tag} — force-stopping...")
    SuShell.run(f"am force-stop {pkg}", timeout=8)
    time.sleep(1)

    # Plain launch — let the app open in its default floating position
    out = SuShell.run(
        f"am start -a android.intent.action.VIEW -d \"{url}\" "
        f"-f 0x10008000 {pkg}; echo __EXIT__$?",
        timeout=15,
    )
    if "__EXIT__0" not in out and "Starting:" not in out:
        # Fallback: let Android resolve intent without pinning package
        SuShell.run(
            f"am start -a android.intent.action.VIEW -d \"{url}\" "
            f"-f 0x10008000",
            timeout=15,
        )

    # Wait for the activity to appear
    wait_for_launch(pkg)
    time.sleep(2)   # extra settle time

    # Now move & resize via touch
    print(f"  {tag} — positioning to ({left},{top},{right},{bottom})...")
    ok = position_window(pkg, left, top, right, bottom)
    if ok:
        print(f"  {tag} — ✓ positioned correctly")
    else:
        print(f"  {tag} — window positioned (verify visually)")

    return True


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("=== Roblox Floating Launcher ===\n")

    print("Requesting root access (one-time grant)...")
    if not SuShell.ok():
        print("[ERROR] Root not available.")
        sys.exit(1)
    print("[OK] Root shell ready.\n")

    if len(sys.argv) > 1:
        packages = sys.argv[1:]
        print(f"Using packages from arguments: {packages}")
    else:
        print("Auto-detecting Roblox packages...")
        packages = find_roblox_packages()
        if not packages:
            print("[ERROR] No Roblox packages found.")
            all_pkgs = SuShell.run("pm list packages", timeout=20)
            print("[INFO] All installed packages:\n" + (all_pkgs or "  (no output)"))
            SuShell.close()
            sys.exit(1)
        print(f"Found {len(packages)} package(s):")
        for i, p in enumerate(packages, 1):
            print(f"  {i}. {p}")

    print()
    place_id = PLACE_ID.strip()
    if not place_id:
        place_id = input("Enter Roblox Place ID (numbers only): ").strip()
    if not place_id.isdigit():
        print("[ERROR] Invalid Place ID.")
        SuShell.close()
        sys.exit(1)

    valid = [p for p in packages if package_installed(p)]
    if set(packages) - set(valid):
        print(f"[WARN] Skipping not-installed: {set(packages) - set(valid)}")
    if not valid:
        print("[ERROR] None of the packages are installed.")
        SuShell.close()
        sys.exit(1)

    packages = valid
    total    = len(packages)
    bounds_list = compute_bounds(total)
    W, H = get_screen_size()

    print(f"\nScreen: {W}x{H}")
    print(f"Launching {total} instance(s)...\n")
    print("Planned layout:")
    for i, (b, p) in enumerate(zip(bounds_list, packages), 1):
        print(f"  #{i} {p}: ({b[0]},{b[1]}) → ({b[2]},{b[3]})")
    print()

    for i, (pkg, bounds) in enumerate(zip(packages, bounds_list), 1):
        launch_instance(pkg, place_id, bounds, i)
        if i < total:
            print(f"\n  Waiting {DELAY_BETWEEN}s before next launch...")
            time.sleep(DELAY_BETWEEN)

    print("\n[OK] All instances launched.")
    SuShell.close()


if __name__ == "__main__":
    main()
