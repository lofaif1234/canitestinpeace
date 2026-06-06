#!/usr/bin/env python3
"""
roblox_launch.py — Floating Roblox instance launcher
Launches multiple Roblox packages as floating windows arranged in a grid.
Requires root (Magisk/KernelSU). Only ONE superuser grant toast shown at startup.

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
# Persistent root shell  (one grant toast, ever)
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
                stderr=subprocess.DEVNULL,
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
                    if not line:
                        break
                    if line == cls._FENCE:
                        break
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
# Config — edit these to match your setup
# ──────────────────────────────────────────────────────────────────────────────
PLACE_ID        = ""          # set your Roblox place ID here, e.g. "15376909"
DELAY_BETWEEN   = 5           # seconds to wait between launching each instance
STATUS_BAR_H    = 80          # Android status bar height in px
NAV_BAR_H       = 0           # navigation bar height (0 if gesture nav)
MARGIN          = 12          # gap between windows in px


# ──────────────────────────────────────────────────────────────────────────────
# Screen detection
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
    """Return list of (left, top, right, bottom) tuples, one per instance."""
    W, H = get_screen_size()
    usable_h = H - STATUS_BAR_H - NAV_BAR_H

    def row_bounds(cols, row_idx, rows, items_in_row, start_col=0):
        cell_w = (W - MARGIN * (cols + 1)) // cols
        cell_h = (usable_h - MARGIN * (rows + 1)) // rows
        result = []
        for col in range(items_in_row):
            left   = MARGIN + col * (cell_w + MARGIN)
            top    = STATUS_BAR_H + MARGIN + row_idx * (cell_h + MARGIN)
            right  = left + cell_w
            bottom = top + cell_h
            result.append((left, top, right, bottom))
        return result

    if total == 1:
        pad = 60
        return [(pad, STATUS_BAR_H + pad, W - pad, H - NAV_BAR_H - pad)]

    if total == 2:
        cell_w = (W - MARGIN * 3) // 2
        cell_h = usable_h - MARGIN * 2
        top = STATUS_BAR_H + MARGIN
        return [
            (MARGIN,              top, MARGIN + cell_w,              top + cell_h),
            (MARGIN * 2 + cell_w, top, MARGIN * 2 + cell_w * 2,     top + cell_h),
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
    top_cols = top_count
    bot_cols = bottom_count
    top_h  = (usable_h - MARGIN * 3) * 2 // 5
    bot_h  = usable_h - top_h - MARGIN * 3
    bounds = []

    for col in range(top_count):
        cell_w = (W - MARGIN * (top_cols + 1)) // top_cols
        left   = MARGIN + col * (cell_w + MARGIN)
        top    = STATUS_BAR_H + MARGIN
        bounds.append((left, top, left + cell_w, top + top_h))

    for col in range(bottom_count):
        cell_w = (W - MARGIN * (bot_cols + 1)) // bot_cols
        left   = MARGIN + col * (cell_w + MARGIN)
        top    = STATUS_BAR_H + MARGIN * 2 + top_h
        bounds.append((left, top, left + cell_w, top + bot_h))

    return bounds


# ──────────────────────────────────────────────────────────────────────────────
# Package helpers
# ──────────────────────────────────────────────────────────────────────────────
def find_roblox_packages():
    pkgs = []

    # Method 1: pm list packages filtered directly (fastest)
    out = SuShell.run("pm list packages | grep -i roblox", timeout=15)
    print(f"  [DEBUG] pm list grep output: {repr(out[:300]) if out else '(empty)'}")
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            pkg = line.replace("package:", "").strip()
            if re.match(r'^com\.roblox\..+$', pkg, re.IGNORECASE):
                pkgs.append(pkg)

    if pkgs:
        return pkgs

    # Method 2: full pm list packages scan (in case grep isn't available)
    out2 = SuShell.run("pm list packages", timeout=20)
    print(f"  [DEBUG] pm list packages returned {len(out2.splitlines())} lines")
    for line in out2.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            pkg = line.replace("package:", "").strip()
            if re.match(r'^com\.roblox\..+$', pkg, re.IGNORECASE):
                pkgs.append(pkg)

    if pkgs:
        return pkgs

    # Method 3: pm list packages -3 (third-party only, sometimes more reliable)
    out3 = SuShell.run("pm list packages -3 | grep -i roblox", timeout=15)
    print(f"  [DEBUG] pm list -3 grep output: {repr(out3[:300]) if out3 else '(empty)'}")
    for line in out3.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            pkg = line.replace("package:", "").strip()
            if re.match(r'^com\.roblox\..+$', pkg, re.IGNORECASE):
                pkgs.append(pkg)

    if pkgs:
        return pkgs

    # Method 4: cmd package list packages (alternative on some ROMs)
    out4 = SuShell.run("cmd package list packages | grep -i roblox", timeout=15)
    print(f"  [DEBUG] cmd package list output: {repr(out4[:300]) if out4 else '(empty)'}")
    for line in out4.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            pkg = line.replace("package:", "").strip()
            if re.match(r'^com\.roblox\..+$', pkg, re.IGNORECASE):
                pkgs.append(pkg)

    return list(dict.fromkeys(pkgs))  # deduplicate, preserve order


def package_installed(pkg: str) -> bool:
    out = SuShell.run(f"pm path {pkg}", timeout=8)
    return "package:" in out


# ──────────────────────────────────────────────────────────────────────────────
# Launch + resize one instance
# ──────────────────────────────────────────────────────────────────────────────
def launch_instance(pkg: str, place_id: str, bounds: tuple, index: int):
    left, top, right, bottom = bounds
    width  = right - left
    height = bottom - top
    url    = f"roblox://placeId={place_id}"
    tag    = f"[#{index}] {pkg}"

    print(f"  {tag} — stopping...")
    SuShell.run(f"am force-stop {pkg}", timeout=8)
    time.sleep(1)

    launched = False
    for mode in (5, 4):
        cmd = (
            f"am start -a android.intent.action.VIEW "
            f"-d \"{url}\" "
            f"-f 0x10008000 "
            f"--windowingMode {mode} "
            f"--windowBounds {left},{top},{right},{bottom} "
            f"{pkg}; echo __EXIT__$?"
        )
        out = SuShell.run(cmd, timeout=15)
        if any(l.strip() == "__EXIT__0" for l in out.splitlines()):
            launched = True
            break

    if not launched:
        SuShell.run(
            f"am start -a android.intent.action.VIEW -d \"{url}\" "
            f"-f 0x10008000 {pkg}",
            timeout=15,
        )
        launched = True

    if launched:
        print(f"  {tag} — launched, resizing in 4 s...")
        time.sleep(4)
        _resize(pkg, left, top, right, bottom)
        print(f"  {tag} — done  ({left},{top},{right},{bottom})")
    else:
        print(f"  {tag} — FAILED to launch")

    return launched


def _resize(pkg: str, left: int, top: int, right: int, bottom: int):
    w = right - left
    h = bottom - top

    out = SuShell.run(f"am resize-task -1 {w} {h}; echo __EXIT__$?", timeout=6)
    if any(l.strip() == "__EXIT__0" for l in out.splitlines()):
        return

    dumpsys = SuShell.run(
        f"dumpsys activity activities | grep -B5 {pkg} | grep taskId",
        timeout=10,
    )
    m = re.search(r'taskId=(\d+)', dumpsys)
    if m:
        tid = m.group(1)
        out = SuShell.run(f"am resize-task {tid} {w} {h}; echo __EXIT__$?", timeout=6)
        if any(l.strip() == "__EXIT__0" for l in out.splitlines()):
            return

    SuShell.run(
        f"wm stack move-task -1 5 true; "
        f"wm stack resize 5 {left} {top} {right} {bottom}",
        timeout=6,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("=== Roblox Floating Launcher ===\n")

    print("Requesting root access (one-time grant)...")
    if not SuShell.ok():
        print("[ERROR] Root not available. Make sure Magisk/KernelSU is installed.")
        sys.exit(1)
    print("[OK] Root shell ready.\n")

    if len(sys.argv) > 1:
        packages = sys.argv[1:]
        print(f"Using packages from arguments: {packages}")
    else:
        print("Auto-detecting Roblox packages...")
        packages = find_roblox_packages()
        if not packages:
            # Print all packages so user can see what's installed and pass manually
            print("[ERROR] No Roblox packages found (com.roblox.*)")
            print("\n[INFO] Dumping ALL installed packages so you can identify yours:")
            all_pkgs = SuShell.run("pm list packages", timeout=20)
            print(all_pkgs if all_pkgs else "  (no output — root shell may have failed)")
            print("\nTip: Run again with your package name as an argument:")
            print("  python3 roblox_launch.py com.roblox.yourpackagename")
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
    skipped = set(packages) - set(valid)
    if skipped:
        print(f"\n[WARN] Skipping not-installed packages: {skipped}")
    if not valid:
        print("[ERROR] None of the packages are installed.")
        SuShell.close()
        sys.exit(1)

    packages = valid
    total    = len(packages)

    bounds_list = compute_bounds(total)
    W, H = get_screen_size()
    print(f"\nScreen: {W}x{H}")
    print(f"Launching {total} instance(s) in grid layout...\n")

    for i, (pkg, bounds) in enumerate(zip(packages, bounds_list), 1):
        launch_instance(pkg, place_id, bounds, i)
        if i < total:
            print(f"  Waiting {DELAY_BETWEEN}s before next launch...\n")
            time.sleep(DELAY_BETWEEN)

    print("\n[OK] All instances launched.")
    SuShell.close()


if __name__ == "__main__":
    main()
