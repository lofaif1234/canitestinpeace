#!/usr/bin/env python3
"""
roblox_launch.py — Floating Roblox instance launcher
Launches multiple Roblox packages as floating windows arranged in a grid.
Requires root (Magisk/KernelSU).

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
                stderr=subprocess.STDOUT,   # capture stderr too
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
STATUS_BAR_H  = 80
NAV_BAR_H     = 0
MARGIN        = 12
LAUNCH_WAIT   = 8   # seconds to wait for app to fully start before resizing


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
    for cmd in [
        "pm list packages | grep -i roblox",
        "pm list packages",
        "pm list packages -3",
        "cmd package list packages | grep -i roblox",
    ]:
        out = SuShell.run(cmd, timeout=20)
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


def wait_for_launch(pkg: str, max_wait: int = 15) -> bool:
    """Poll dumpsys until the package appears as a running activity."""
    print(f"  Waiting for {pkg} to appear in activity stack", end="", flush=True)
    for _ in range(max_wait):
        out = SuShell.run("dumpsys activity activities", timeout=5)
        if pkg in out:
            print(" ✓")
            return True
        print(".", end="", flush=True)
        time.sleep(1)
    print(" (timed out)")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Task ID detection
# ──────────────────────────────────────────────────────────────────────────────
def get_task_id(pkg: str) -> str | None:
    # Grab the full activities dump and walk it line by line.
    # We track the most-recently-seen taskId and check if pkg appears nearby.
    out = SuShell.run("dumpsys activity activities", timeout=12)
    lines = out.splitlines()
    last_task = None
    for i, line in enumerate(lines):
        m = re.search(r'[Tt]ask[Id#\s=:]+(\d+)', line)
        if m:
            last_task = m.group(1)
        if pkg in line and last_task:
            print(f"  [DEBUG] Task ID for {pkg}: {last_task}")
            return last_task

    # Fallback: grep nearby lines around the package name
    for i, line in enumerate(lines):
        if pkg in line:
            # search surrounding 20 lines for a taskId
            window = lines[max(0, i-20):i+5]
            for wl in reversed(window):
                m = re.search(r'[Tt]ask[Id#\s=:]+(\d+)', wl)
                if m:
                    print(f"  [DEBUG] Task ID (window search) for {pkg}: {m.group(1)}")
                    return m.group(1)

    print(f"  [DEBUG] Could not find task ID for {pkg}")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Resize — try every known method
# ──────────────────────────────────────────────────────────────────────────────
def resize_task(pkg: str, left: int, top: int, right: int, bottom: int):
    w = right - left
    h = bottom - top
    tid = get_task_id(pkg)

    results = {}

    if tid:
        # 1. Modern: am task resize with bounds
        results['am_task_resize'] = SuShell.run(
            f"am task resize {tid} {left} {top} {right} {bottom}", timeout=8)

        # 2. Move into freeform stack (5), then resize that stack
        results['stack_move'] = SuShell.run(
            f"am stack move-task {tid} 5 true", timeout=8)
        results['stack_resize'] = SuShell.run(
            f"wm stack resize 5 {left} {top} {right} {bottom}", timeout=8)

        # 3. Legacy resize-task with just width/height
        results['resize_wh'] = SuShell.run(
            f"am resize-task {tid} {w} {h}", timeout=8)

        # 4. Legacy resize-task with full bounds
        results['resize_bounds'] = SuShell.run(
            f"am resize-task {tid} {left} {top} {right} {bottom}", timeout=8)

    # 5. Resize the most-recent task (no task ID needed)
    results['resize_last_wh'] = SuShell.run(
        f"am resize-task -1 {w} {h}", timeout=8)

    # 6. Resize freeform stack directly
    results['wm_stack_5'] = SuShell.run(
        f"wm stack resize 5 {left} {top} {right} {bottom}", timeout=8)

    for k, v in results.items():
        if v.strip():
            print(f"  [DEBUG] {k}: {repr(v.strip()[:120])}")
        else:
            print(f"  [DEBUG] {k}: (no output / ok)")


# ──────────────────────────────────────────────────────────────────────────────
# Launch one instance — plain am start, no windowing flags
# ──────────────────────────────────────────────────────────────────────────────
def launch_instance(pkg: str, place_id: str, bounds: tuple, index: int):
    left, top, right, bottom = bounds
    url = f"roblox://placeId={place_id}"
    tag = f"[#{index}] {pkg}"

    print(f"\n  {tag} — force-stopping...")
    SuShell.run(f"am force-stop {pkg}", timeout=8)
    time.sleep(1)

    # Plain launch — no --windowingMode or --windowBounds (those broke it)
    out = SuShell.run(
        f"am start -a android.intent.action.VIEW -d \"{url}\" "
        f"-f 0x10008000 {pkg}; echo __LAUNCH_EXIT__$?",
        timeout=15,
    )
    print(f"  [DEBUG] am start output: {repr(out[:200])}")

    launched = "__LAUNCH_EXIT__0" in out or "Starting:" in out
    if not launched:
        # Try without the package name (let Android resolve the intent)
        out2 = SuShell.run(
            f"am start -a android.intent.action.VIEW -d \"{url}\" "
            f"-f 0x10008000; echo __LAUNCH_EXIT__$?",
            timeout=15,
        )
        print(f"  [DEBUG] am start (no pkg) output: {repr(out2[:200])}")
        launched = "__LAUNCH_EXIT__0" in out2 or "Starting:" in out2

    if not launched:
        print(f"  {tag} — WARNING: launch may have failed, continuing anyway...")

    # Wait until the app actually appears in the activity stack
    appeared = wait_for_launch(pkg, max_wait=LAUNCH_WAIT + 5)
    if not appeared:
        print(f"  {tag} — app did not appear in stack, skipping resize")
        return False

    # Give it an extra second to settle
    time.sleep(2)

    print(f"  {tag} — resizing to ({left},{top},{right},{bottom})...")
    resize_task(pkg, left, top, right, bottom)
    print(f"  {tag} — done")
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
        print(f"  #{i} {p}: left={b[0]} top={b[1]} right={b[2]} bottom={b[3]}")
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
