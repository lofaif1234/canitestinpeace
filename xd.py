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
# Config
# ──────────────────────────────────────────────────────────────────────────────
PLACE_ID        = ""
DELAY_BETWEEN   = 5
STATUS_BAR_H    = 80
NAV_BAR_H       = 0
MARGIN          = 12


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
    pkgs = []

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

    out4 = SuShell.run("cmd package list packages | grep -i roblox", timeout=15)
    print(f"  [DEBUG] cmd package list output: {repr(out4[:300]) if out4 else '(empty)'}")
    for line in out4.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            pkg = line.replace("package:", "").strip()
            if re.match(r'^com\.roblox\..+$', pkg, re.IGNORECASE):
                pkgs.append(pkg)

    return list(dict.fromkeys(pkgs))


def package_installed(pkg: str) -> bool:
    out = SuShell.run(f"pm path {pkg}", timeout=8)
    return "package:" in out


# ──────────────────────────────────────────────────────────────────────────────
# Get task ID for a package
# ──────────────────────────────────────────────────────────────────────────────
def get_task_id(pkg: str) -> str | None:
    """Try multiple methods to find the task ID for a running package."""

    # Method A: dumpsys activity tasks (modern Android)
    out = SuShell.run("dumpsys activity tasks", timeout=10)
    # Look for a task block that contains our package name
    task_id = None
    current_task = None
    for line in out.splitlines():
        m = re.search(r'Task[Id\s#=:]+(\d+)', line)
        if m:
            current_task = m.group(1)
        if pkg in line and current_task:
            task_id = current_task
            break
    if task_id:
        print(f"  [DEBUG] Found task ID via dumpsys tasks: {task_id}")
        return task_id

    # Method B: dumpsys activity activities
    out2 = SuShell.run("dumpsys activity activities", timeout=10)
    current_task = None
    for line in out2.splitlines():
        m = re.search(r'taskId=(\d+)', line)
        if m:
            current_task = m.group(1)
        if pkg in line and current_task:
            task_id = current_task
            break
    if task_id:
        print(f"  [DEBUG] Found task ID via dumpsys activities: {task_id}")
        return task_id

    # Method C: grep shortcut
    out3 = SuShell.run(
        f"dumpsys activity activities | grep -B10 '{pkg}' | grep 'taskId=' | tail -1",
        timeout=10
    )
    m = re.search(r'taskId=(\d+)', out3)
    if m:
        print(f"  [DEBUG] Found task ID via grep: {m.group(1)}")
        return m.group(1)

    print(f"  [DEBUG] Could not find task ID for {pkg}")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Resize a task into exact bounds
# ──────────────────────────────────────────────────────────────────────────────
def resize_task(pkg: str, left: int, top: int, right: int, bottom: int):
    w = right - left
    h = bottom - top
    tid = get_task_id(pkg)

    if tid:
        # Try am task resize with explicit bounds (works on many freeform ROMs)
        r1 = SuShell.run(
            f"am task resize {tid} {left} {top} {right} {bottom}",
            timeout=8
        )
        print(f"  [DEBUG] am task resize: {repr(r1[:100])}")

        # Also try the older resize-task syntax
        r2 = SuShell.run(
            f"am resize-task {tid} {left} {top} {right} {bottom}",
            timeout=8
        )
        print(f"  [DEBUG] am resize-task: {repr(r2[:100])}")

        # wm stack resize targeting freeform stack (stack 5)
        r3 = SuShell.run(
            f"wm stack resize 5 {left} {top} {right} {bottom}",
            timeout=8
        )
        print(f"  [DEBUG] wm stack resize: {repr(r3[:100])}")

        # Move task into freeform stack then resize
        r4 = SuShell.run(
            f"am stack move-task {tid} 5 true",
            timeout=8
        )
        print(f"  [DEBUG] am stack move-task: {repr(r4[:100])}")

        r5 = SuShell.run(
            f"wm stack resize 5 {left} {top} {right} {bottom}",
            timeout=8
        )
        print(f"  [DEBUG] wm stack resize after move: {repr(r5[:100])}")

    # Fallback: input swipe to drag the window (crude but works on some setups)
    # This is a last-resort only — skipped unless nothing else works


# ──────────────────────────────────────────────────────────────────────────────
# Launch one instance
# ──────────────────────────────────────────────────────────────────────────────
def launch_instance(pkg: str, place_id: str, bounds: tuple, index: int):
    left, top, right, bottom = bounds
    url = f"roblox://placeId={place_id}"
    tag = f"[#{index}] {pkg}"

    print(f"  {tag} — stopping...")
    SuShell.run(f"am force-stop {pkg}", timeout=8)
    time.sleep(1)

    launched = False

    # Attempt 1: launch directly into freeform with explicit bounds
    for mode in (5, 4):
        cmd = (
            f"am start -a android.intent.action.VIEW "
            f"-d \"{url}\" "
            f"--windowingMode {mode} "
            f"--windowBounds {left},{top},{right},{bottom} "
            f"-f 0x10008000 "
            f"{pkg}"
        )
        out = SuShell.run(cmd + "; echo __EXIT__$?", timeout=15)
        print(f"  [DEBUG] launch mode {mode}: {repr(out[:200])}")
        if "Error" not in out and "Exception" not in out:
            launched = True
            break

    if not launched:
        # Attempt 2: plain launch, resize after
        SuShell.run(
            f"am start -a android.intent.action.VIEW -d \"{url}\" "
            f"-f 0x10008000 {pkg}",
            timeout=15,
        )
        launched = True

    if launched:
        print(f"  {tag} — launched, waiting 5s before resize...")
        time.sleep(5)
        resize_task(pkg, left, top, right, bottom)
        print(f"  {tag} — done  ({left},{top},{right},{bottom})")
    else:
        print(f"  {tag} — FAILED to launch")

    return launched


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
            print("[ERROR] No Roblox packages found (com.roblox.*)")
            print("\n[INFO] All installed packages:")
            all_pkgs = SuShell.run("pm list packages", timeout=20)
            print(all_pkgs if all_pkgs else "  (no output)")
            print("\nTip: python3 roblox_launch.py com.roblox.yourpackagename")
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
        print(f"\n[WARN] Skipping not-installed: {skipped}")
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
    print("Planned layout:")
    for i, (b, p) in enumerate(zip(bounds_list, packages), 1):
        print(f"  #{i} {p}: left={b[0]} top={b[1]} right={b[2]} bottom={b[3]}")
    print()

    for i, (pkg, bounds) in enumerate(zip(packages, bounds_list), 1):
        launch_instance(pkg, place_id, bounds, i)
        if i < total:
            print(f"  Waiting {DELAY_BETWEEN}s before next launch...\n")
            time.sleep(DELAY_BETWEEN)

    print("\n[OK] All instances launched.")
    SuShell.close()


if __name__ == "__main__":
    main()
