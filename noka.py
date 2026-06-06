#!/usr/bin/env python3
"""
NOKA - Roblox Instance Manager v2.0 (Python Version)
A complete Termux automation tool for managing multiple Roblox instances
with crash detection, webhooks, and scheduling.
BUILD: 20250606-1529
"""

import os
import sys
import json
import time
import subprocess
import signal
import threading
import requests
import hashlib
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# =============================================================================
# MODULE: M_SuShell (Persistent root shell — ONE su grant, zero toast spam)
# =============================================================================
class M_SuShell:
    """Keeps a single long-lived 'su' process open.
    Every root command is written to its stdin so Magisk/KernelSU only shows
    the 'Termux was granted Superuser rights' toast ONCE at startup instead of
    once per su invocation."""

    _proc   = None
    _lock   = threading.Lock()
    _ready  = False
    _FENCE  = "__NOKA_DONE__"

    @classmethod
    def _start(cls):
        """Launch the persistent su shell (called once)."""
        try:
            cls._proc = subprocess.Popen(
                ["su"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # suppress ALL grant banners
                text=True,
                bufsize=1,
            )
            out = cls._run_raw("echo alive", timeout=5)
            cls._ready = "alive" in out
        except Exception:
            cls._proc  = None
            cls._ready = False

    @classmethod
    def _run_raw(cls, cmd: str, timeout: float = 15) -> str:
        """Send one command; collect output until sentinel line."""
        if cls._proc is None or cls._proc.poll() is not None:
            return ""
        try:
            cls._proc.stdin.write(f"{cmd}\necho {cls._FENCE}\n")
            cls._proc.stdin.flush()
            lines = []
            import select as _select
            deadline = time.time() + timeout
            while time.time() < deadline:
                ready, _, _ = _select.select([cls._proc.stdout], [], [], 0.1)
                if ready:
                    line = cls._proc.stdout.readline()
                    if not line:
                        break
                    line = line.rstrip("\r\n")
                    if line == cls._FENCE:
                        break
                    lines.append(line)
            return "\n".join(lines)
        except Exception:
            return ""

    @classmethod
    def run(cls, cmd: str, timeout: float = 15) -> str:
        """Run a shell command as root; return stdout. '' if root unavailable."""
        with cls._lock:
            if not cls._ready:
                cls._start()
            if not cls._ready:
                return ""
            return cls._run_raw(cmd, timeout=timeout)

    @classmethod
    def available(cls) -> bool:
        """True if a working root shell is open."""
        with cls._lock:
            if not cls._ready:
                cls._start()
            return cls._ready

    @classmethod
    def close(cls):
        """Shut down the persistent shell on program exit."""
        try:
            if cls._proc and cls._proc.poll() is None:
                cls._proc.stdin.write("exit\n")
                cls._proc.stdin.flush()
                cls._proc.wait(timeout=2)
        except Exception:
            pass
        finally:
            cls._proc  = None
            cls._ready = False


# =============================================================================
# MODULE: M_UI (User Interface)
# =============================================================================
class M_UI:
    """UI module with colors and terminal control"""
    
    # ANSI color codes
    COLORS = {
        'reset': '\033[0m',
        'bold': '\033[1m',
        'cyan': '\033[36m',
        'green': '\033[32m',
        'red': '\033[31m',
        'yellow': '\033[33m',
        'magenta': '\033[35m',
        'white': '\033[37m',
        'blue': '\033[34m'
    }
    
    @staticmethod
    def clear():
        """Clear screen and scrollback buffer"""
        print('\033[2J\033[3J\033[H', end='', flush=True)
    
    @staticmethod
    def color(color_name: str, text: str) -> str:
        """Apply color to text"""
        return f"{M_UI.COLORS.get(color_name, '')}{text}{M_UI.COLORS['reset']}"
    
    @staticmethod
    def banner():
        """Display NOKA banner"""
        lines = [
            "███╗   ██╗ ██████╗ ██╗  ██╗ █████╗ ",
            "████╗  ██║██╔═══██╗██║ ██╔╝██╔══██╗",
            "██╔██╗ ██║██║   ██║█████╔╝ ███████║",
            "██║╚██╗██║██║   ██║██╔═██╗ ██╔══██║",
            "██║ ╚████║╚██████╔╝██║  ██╗███████║",
            "╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝",
            "     Roblox Instance Manager v2.0"
        ]
        
        for i in range(6):
            print(M_UI.color('cyan', M_UI.color('bold', lines[i])))
        print(M_UI.color('magenta', lines[6]))
        print()
    
    @staticmethod
    def status_bar():
        """Show status bar with system info"""
        config = M_Config.get()
        packages = config.get('packages', [])
        active_count = sum(1 for p in packages if p.get('enabled', False))
        
        webhook = config.get('webhook', {})
        webhook_status = M_UI.color('green', 'ON') if webhook.get('enabled') else M_UI.color('red', 'OFF')
        
        config_status = M_UI.color('green', 'loaded') if os.path.exists(M_Config.PATH) else M_UI.color('yellow', 'missing')
        
        line = f"[Instances: {active_count} active]  [Webhook: {webhook_status}]  [Config: {config_status}]"
        print(M_UI.color('bold', line))
        print()
    
    @staticmethod
    def header():
        """Display header with banner and status"""
        M_UI.clear()
        M_UI.banner()
        M_UI.status_bar()
    
    @staticmethod
    def read_line() -> str:
        """Read input from user with proper handling"""
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            return input().strip()
        except:
            return ""
    
    @staticmethod
    def prompt(text: str) -> str:
        """Prompt user for input"""
        print(f"{text} ", end='', flush=True)
        return M_UI.read_line()
    
    @staticmethod
    def confirm(text: str) -> bool:
        """Ask user yes/no question"""
        resp = M_UI.prompt(f"{text} [y/N]: ").lower()
        return resp == 'y'
    
    @staticmethod
    def success(msg: str):
        """Print success message"""
        print(M_UI.color('green', f"[OK] {msg}"))
    
    @staticmethod
    def error(msg: str):
        """Print error message"""
        print(M_UI.color('red', f"[ERROR] {msg}"))
    
    @staticmethod
    def warning(msg: str):
        """Print warning message"""
        print(M_UI.color('yellow', f"[WARN] {msg}"))
    
    @staticmethod
    def info(msg: str):
        """Print info message"""
        print(M_UI.color('cyan', f"[INFO] {msg}"))
    
    @staticmethod
    def pause():
        """Pause for user input"""
        M_UI.prompt("\nPress Enter to continue...")
    
    @staticmethod
    def wizard_step(step: int, total: int, title: str):
        """Display wizard step header"""
        M_UI.header()
        print(M_UI.color('cyan', f"Step {step} of {total}: {title}"))
        print("-" * 40)
        print()
    
    @staticmethod
    def main_menu() -> str:
        """Display main menu and get choice"""
        M_UI.header()
        print(M_UI.color('bold', M_UI.color('cyan', "=== MAIN MENU ===")))
        print()
        print("1) First-time configuration wizard")
        print("2) Start auto-rejoin / monitoring")
        print("3) Webhook & notifications")
        print("4) Update game URL")
        print("5) Instance profiles")
        print("6) Diagnostics & logs")
        print("7) Scheduler")
        print("8) Export / Import")
        print("9) About & Help")
        print("L) License information")
        print("0) Exit")
        print()
        
        choice = M_UI.prompt("Enter choice:")
        return choice or ""

# =============================================================================
# MODULE: M_Shell (Shell Commands)
# =============================================================================
class M_Shell:
    """Shell command execution module"""
    
    _root_cached = None
    _active_procs = []  # Track subprocesses for cleanup on exit
    
    @staticmethod
    def exec(cmd: str, timeout: int = 30) -> Tuple[str, str, int]:
        """Execute shell command with timeout"""
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True
            )
            M_Shell._active_procs.append(proc)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                stdout = stdout.replace('\r', '') if stdout else ""
                stderr = stderr.replace('\r', '') if stderr else ""
                return stdout, stderr, proc.returncode
            finally:
                if proc in M_Shell._active_procs:
                    M_Shell._active_procs.remove(proc)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except:
                pass
            return "", "Command timed out", 124
        except Exception as e:
            return "", str(e), 1
    
    @staticmethod
    def cleanup():
        """Kill all active subprocesses on exit"""
        import signal
        for proc in list(M_Shell._active_procs):
            try:
                proc.kill()
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except:
                pass
        M_Shell._active_procs.clear()
    
    @staticmethod
    def sanitize_input(input_str: str) -> str:
        """Sanitize user input to prevent command injection"""
        return re.sub(r'[;|&$`\\"\'<>(){}[\]]', '', input_str)
    
    @staticmethod
    def kill_app(package: str) -> bool:
        """Kill app by package name"""
        stdout, stderr, code = M_Shell.exec(f"am force-stop {package}")
        return code == 0
    
    @staticmethod
    def clear_app_cache(package: str) -> bool:
        """Clear only app cache files, NOT login data"""
        has_root = M_Shell.has_root()

        # Method 1: Android builtin command (Android 8+)
        if has_root:
            out = M_SuShell.run(f"cmd activity clear-app-cache {package}; echo __EXIT__$?", timeout=10)
            code = 0 if any(l.strip() == "__EXIT__0" for l in out.splitlines()) else 1
        else:
            _, _, code = M_Shell.exec(f"cmd activity clear-app-cache {package}")
        if code == 0:
            return True

        # Method 2: Delete only cache directory with root (preserves login)
        if has_root:
            cache_paths = [
                f"/data/data/{package}/cache/*",
                f"/data/data/{package}/code_cache/*",
                f"/sdcard/Android/data/{package}/cache/*"
            ]
            for path in cache_paths:
                M_SuShell.run(f"rm -rf {path}", timeout=10)
            return True

        return False
    
    # Background CPU sampling state
    _cpu_sample_lock    = threading.Lock()
    _cpu_last_percent   = 0.0
    _cpu_thread_started = False
    _cpu_first_sample   = threading.Event()   # set when first result is ready

    @staticmethod
    def _sample_cpu_fields():
        """Read /proc/stat aggregate CPU line; return list of int jiffie fields."""
        try:
            with open('/proc/stat', 'r') as f:
                line = f.readline()
            tokens = line.split()
            if tokens and tokens[0].startswith('cpu'):
                return list(map(int, tokens[1:]))
        except Exception:
            pass
        return []

    @staticmethod
    def _update_cpu_background():
        """Background daemon: keeps _cpu_last_percent fresh every ~1.5 s."""
        while True:
            try:
                f1 = M_Shell._sample_cpu_fields()
                time.sleep(1.0)
                f2 = M_Shell._sample_cpu_fields()
                if f1 and f2 and len(f1) == len(f2):
                    total_diff = sum(f2) - sum(f1)
                    idle_diff  = f2[3]  - f1[3]
                    if total_diff > 0:
                        pct = 100.0 * (1.0 - idle_diff / total_diff)
                        with M_Shell._cpu_sample_lock:
                            M_Shell._cpu_last_percent = round(pct, 1)
                        M_Shell._cpu_first_sample.set()   # signal that data is ready
            except Exception:
                pass
            time.sleep(0.5)

    @staticmethod
    def _ensure_cpu_thread():
        """Start the background thread once and wait (max 2.5 s) for first sample."""
        if M_Shell._cpu_thread_started:
            return
        M_Shell._cpu_thread_started = True
        t = threading.Thread(target=M_Shell._update_cpu_background, daemon=True)
        t.start()
        # Block until the first real sample arrives (or 2.5 s timeout)
        M_Shell._cpu_first_sample.wait(timeout=2.5)

    @staticmethod
    def get_system_stats():
        """Get real CPU and RAM usage. CPU comes from a background sampler so
        this call never blocks. RAM is read directly from /proc/meminfo."""
        M_Shell._ensure_cpu_thread()

        # --- CPU: from background thread cache ---
        with M_Shell._cpu_sample_lock:
            cpu_percent = M_Shell._cpu_last_percent

        # --- RAM: /proc/meminfo (direct, no su needed) ---
        ram_used_gb  = 0.0
        ram_total_gb = 0.0
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo_raw = f.read()
            meminfo = {}
            for line in meminfo_raw.splitlines():
                if ':' in line:
                    key, val = line.split(':', 1)
                    digits = ''.join(c for c in val if c.isdigit())
                    if digits:
                        meminfo[key.strip()] = int(digits)

            total_raw     = meminfo.get('MemTotal', 0)
            available_raw = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
            used_raw      = total_raw - available_raw

            # /proc/meminfo values are in kB on every Android kernel
            ram_total_gb = total_raw / (1024.0 ** 2)
            ram_used_gb  = used_raw  / (1024.0 ** 2)

            # Safety: if kernel reports in bytes instead of kB
            if ram_total_gb > 1024:
                ram_total_gb = total_raw / (1024.0 ** 3)
                ram_used_gb  = used_raw  / (1024.0 ** 3)
        except Exception:
            pass

        return cpu_percent, ram_used_gb, ram_total_gb
    
    @staticmethod
    def detect_screen_size():
        """Auto-detect screen size using wm size"""
        try:
            if M_Shell.has_root():
                stdout = M_SuShell.run("wm size", timeout=5)
            else:
                stdout, _, _ = M_Shell.exec("wm size")
            if stdout:
                match = re.search(r'(\d+)x(\d+)', stdout)
                if match:
                    return int(match.group(1)), int(match.group(2))
        except Exception:
            pass
        return 1080, 1920  # Default fallback
    
    @staticmethod
    def get_package_stats(package: str) -> dict:
        """Get CPU and memory stats for a specific package using the persistent root shell."""
        if not M_SuShell.available():
            return {"cpu": "0.0", "mem": "0.0"}

        # Get PID — take the first numeric token to skip any stray output
        pid_out = M_SuShell.run(f"pidof {package}", timeout=5)
        pid = next((t for t in pid_out.split() if t.isdigit()), "")
        if not pid:
            return {"cpu": "0.0", "mem": "0.0"}

        try:
            # Sample 1: proc/stat for this pid + global cpu in one shell line
            raw1 = M_SuShell.run(f"cat /proc/{pid}/stat; echo ---; cat /proc/stat | head -1; echo ---; grep VmRSS /proc/{pid}/status", timeout=5)
            sections1 = raw1.split("---")
            if len(sections1) < 3:
                return {"cpu": "0.0", "mem": "0.0"}

            pstat1  = sections1[0].strip().split()
            cpuraw1 = sections1[1].strip().split()
            memraw1 = sections1[2].strip()

            proc_jif1  = int(pstat1[13]) + int(pstat1[14])
            total_jif1 = sum(map(int, cpuraw1[1:]))   # skip "cpu" label

            mem_mb = 0.0
            for line in memraw1.splitlines():
                if "VmRSS" in line:
                    mem_mb = float(line.split()[1]) / 1024.0
                    break

            time.sleep(0.5)

            # Sample 2
            raw2 = M_SuShell.run(f"cat /proc/{pid}/stat; echo ---; cat /proc/stat | head -1", timeout=5)
            sections2 = raw2.split("---")
            if len(sections2) < 2:
                return {"cpu": "0.0", "mem": "0.0"}

            pstat2  = sections2[0].strip().split()
            cpuraw2 = sections2[1].strip().split()

            proc_jif2  = int(pstat2[13]) + int(pstat2[14])
            total_jif2 = sum(map(int, cpuraw2[1:]))

            delta_proc  = proc_jif2  - proc_jif1
            delta_total = total_jif2 - total_jif1
            cpu_pct = 100.0 * (delta_proc / delta_total) if delta_total > 0 else 0.0

            return {"cpu": f"{cpu_pct:.1f}", "mem": f"{mem_mb:.1f}"}
        except Exception:
            pass

        return {"cpu": "0.0", "mem": "0.0"}
    
    @staticmethod
    def has_root() -> bool:
        """Check if root is available via the persistent su shell (cached, toast-free)."""
        if M_Shell._root_cached is not None:
            return M_Shell._root_cached
        M_Shell._root_cached = M_SuShell.available()
        return M_Shell._root_cached
    
    @staticmethod
    def resize_window_after_launch(package: str, bounds: str):
        """Resize window after launch using wm commands (requires root) - silent"""
        if not bounds:
            return

        time.sleep(3)

        try:
            left, top, right, bottom = map(int, bounds.split(','))
            width  = right - left
            height = bottom - top
        except Exception:
            return

        if not M_Shell.has_root():
            return

        # Method 1: Try am resize-task -1 (most recent task)
        out = M_SuShell.run(f"am resize-task -1 {width} {height}; echo __EXIT__$?", timeout=5)
        if any(l.strip() == "__EXIT__0" for l in out.splitlines()):
            return

        # Method 2: Find task ID from dumpsys
        out = M_SuShell.run(
            f"dumpsys activity activities | grep -B 2 {package} | grep taskId", timeout=10
        )
        match = re.search(r'taskId=(\d+)', out)
        if match:
            task_id = match.group(1)
            res = M_SuShell.run(f"am resize-task {task_id} {width} {height}; echo __EXIT__$?", timeout=5)
            if any(l.strip() == "__EXIT__0" for l in res.splitlines()):
                return

        # Method 3: wm stack resize
        M_SuShell.run(f"wm stack id resize {left} {top} {right} {bottom}", timeout=5)
    
    @staticmethod
    def get_window_bounds(index: int, total: int = 1) -> str:
        """Calculate window bounds for grid layout - 2x2 grid with 5th in center"""
        screen_w, screen_h = M_Shell.detect_screen_size()
        margin = 20
        
        # Status bar offset (for Android status bar)
        status_bar = 80
        
        if total == 1:
            # Single instance - centered large
            cell_w = screen_w - 100
            cell_h = screen_h - 250
            left = (screen_w - cell_w) // 2
            top = status_bar + 20
        elif total == 2:
            # Side by side (horizontal split)
            cell_w = (screen_w - margin * 3) // 2
            cell_h = screen_h - 200
            col = index - 1
            left = margin + col * (cell_w + margin)
            top = status_bar + 20
        elif total == 3:
            # 2 on top, 1 centered below
            cell_w = (screen_w - margin * 3) // 2
            cell_h = (screen_h - margin * 4) // 2
            if index <= 2:
                # Top row
                col = index - 1
                left = margin + col * (cell_w + margin)
                top = status_bar + 20
            else:
                # 3rd in center bottom
                left = (screen_w - cell_w) // 2
                top = status_bar + 20 + cell_h + margin
        elif total == 4:
            # 2x2 grid
            cell_w = (screen_w - margin * 3) // 2
            cell_h = (screen_h - margin * 4) // 2
            col = (index - 1) % 2
            row = (index - 1) // 2
            left = margin + col * (cell_w + margin)
            top = status_bar + 20 + row * (cell_h + margin)
        else:
            # 5+ instances: 2x2 with extras in middle
            # First 4 in 2x2 grid
            cell_w = (screen_w - margin * 3) // 2
            cell_h = (screen_h - margin * 4) // 2
            
            if index <= 4:
                col = (index - 1) % 2
                row = (index - 1) // 2
                left = margin + col * (cell_w + margin)
                top = status_bar + 20 + row * (cell_h + margin)
            else:
                # 5th and beyond - smaller in center
                cell_w = (screen_w - margin * 3) // 2 - 50
                cell_h = (screen_h - margin * 4) // 2 - 50
                left = (screen_w - cell_w) // 2
                top = (screen_h - cell_h) // 2
        
        right = left + cell_w
        bottom = top + cell_h
        return f"{left},{top},{right},{bottom}"
    
    @staticmethod
    def launch_app(package: str, place_id: str, window_bounds: str = "") -> bool:
        """Launch app with cache clear, separate task, and auto-resize"""
        if not package or not place_id:
            M_UI.error("Package and place_id required")
            return False

        has_root = M_Shell.has_root()

        # Step 1: Clear cache before launch
        M_UI.info("Clearing app cache...")
        M_Shell.clear_app_cache(package)
        time.sleep(1)

        # Step 2: Force-stop to ensure clean start
        M_Shell.kill_app(package)
        time.sleep(1)

        # Step 3: Check if package is installed
        M_UI.info("Checking package...")
        if has_root:
            stdout = M_SuShell.run(f"pm path {package}", timeout=10)
        else:
            stdout, _, _ = M_Shell.exec(f"pm path {package}")

        if not stdout or "package:" not in stdout:
            M_UI.error(f"Package not installed: {package}")
            return False

        url = f"roblox://placeId={place_id}"

        # Build launch commands — root ones go through persistent shell, no new su spawn
        def try_root_cmd(shell_cmd: str) -> bool:
            # Run command, then echo exit code with a unique tag so we can find it
            # among am start's multi-line output
            out = M_SuShell.run(f"{shell_cmd}; echo __EXIT__$?", timeout=15)
            for line in out.splitlines():
                if line.startswith("__EXIT__"):
                    return line.strip() == "__EXIT__0"
            return False

        def try_normal_cmd(shell_cmd: str) -> bool:
            _, _, code = M_Shell.exec(shell_cmd)
            return code == 0

        methods = []

        if window_bounds:
            methods.append((
                f"am start -a android.intent.action.VIEW -d \"{url}\" -f 0x10008000 --windowingMode 5 --windowBounds {window_bounds} {package}",
                "Freeform clear-task", has_root
            ))
            methods.append((
                f"am start -a android.intent.action.VIEW -d \"{url}\" -f 0x10008000 --windowingMode 4 --windowBounds {window_bounds} {package}",
                "Freeform alt mode", has_root
            ))

        methods.append((
            f"am start -a android.intent.action.VIEW -d \"{url}\" -f 0x10008000 {package}",
            "Standard clear-task", has_root
        ))
        methods.append((
            f"am start -n {package}/com.roblox.client.Activity -f 0x10008000",
            "Simple clear-task", has_root
        ))

        for shell_cmd, name, use_root in methods:
            ok = try_root_cmd(shell_cmd) if use_root else try_normal_cmd(shell_cmd)
            if ok:
                if window_bounds:
                    M_Shell.resize_window_after_launch(package, window_bounds)
                return True

        return False

# =============================================================================
# MODULE: M_Config (Configuration Management)
# =============================================================================
class M_Config:
    """Configuration management module"""
    
    PATH = os.path.expanduser("~/NOKA/config.json")
    data = None
    
    DEFAULTS = {
        "version": "2.0",
        "packages": [],
        "game_url": "",
        "fallback_url": "",
        "place_id": "",
        "webhook": {
            "enabled": False,
            "url": "",
            "events": ["startup", "crash", "restart", "shutdown", "status"],
            "interval": 300,
            "ping_everyone": False,
            "screenshot": False
        },
        "launch_interval": 120,
        "launch_interval_random": False,
        "launch_interval_min": 90,
        "launch_interval_max": 150,
        "restart_policy": "crash_only",
        "scheduler": [],
        "auth": {
            "license_key": "",
            "hwid": "",
            "api_url": "http://localhost:5000",
            "api_secret": "",
            "validated": False,
            "last_validation": ""
        }
    }
    
    @staticmethod
    def load():
        """Load configuration from file"""
        try:
            if os.path.exists(M_Config.PATH):
                with open(M_Config.PATH, 'r') as f:
                    M_Config.data = json.load(f)
            else:
                M_Config.data = M_Config.DEFAULTS.copy()
                M_Config.save()
        except Exception as e:
            M_UI.error(f"Failed to load config: {e}")
            M_Config.data = M_Config.DEFAULTS.copy()
    
    @staticmethod
    def save():
        """Save configuration to file"""
        try:
            os.makedirs(os.path.dirname(M_Config.PATH), exist_ok=True)
            with open(M_Config.PATH, 'w') as f:
                json.dump(M_Config.data, f, indent=2)
        except Exception as e:
            M_UI.error(f"Failed to save config: {e}")
    
    @staticmethod
    def get(key: str = None, default: Any = None) -> Any:
        """Get configuration value with optional default"""
        if not M_Config.data:
            M_Config.load()
        
        if key:
            return M_Config.data.get(key, default)
        return M_Config.data
    
    @staticmethod
    def set(key: str, value: Any):
        """Set configuration value"""
        if not M_Config.data:
            M_Config.load()
        M_Config.data[key] = value
        M_Config.save()
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate Roblox URL or place ID"""
        if not url:
            return False
        
        # Check if it's a place ID
        if url.isdigit():
            return True
        
        # Check if it's a roblox URL
        if "roblox.com/games/" in url:
            return True
        
        return False

# =============================================================================
# MODULE: M_Log (Logging)
# =============================================================================
class M_Log:
    """Logging module"""
    
    LOG_DIR = os.path.expanduser("~/NOKA")
    LOG_FILE = os.path.join(LOG_DIR, "noka.log")
    
    @staticmethod
    def init():
        """Initialize logging"""
        os.makedirs(M_Log.LOG_DIR, exist_ok=True)
    
    @staticmethod
    def write(level: str, message: str, context: str = ""):
        """Write log entry"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        context_str = f" [{context}]" if context else ""
        log_entry = f"[{timestamp}] {level.upper()}{context_str}: {message}\n"
        
        try:
            with open(M_Log.LOG_FILE, 'a') as f:
                f.write(log_entry)
        except Exception:
            pass  # Fail silently for log writes
    
    @staticmethod
    def clear():
        """Clear log file"""
        try:
            if os.path.exists(M_Log.LOG_FILE):
                os.remove(M_Log.LOG_FILE)
            M_UI.success("Log cleared")
        except Exception as e:
            M_UI.error(f"Failed to clear log: {e}")

# =============================================================================
# MODULE: M_Auth (Authentication)
# =============================================================================
class M_Auth:
    """Authentication module with HWID locking"""
    
    configured = False
    
    @staticmethod
    def generate_hwid() -> str:
        """Generate hardware ID from device fingerprint"""
        hwid_parts = []
        
        # Get Android ID
        try:
            stdout, stderr, code = M_Shell.exec("settings get secure android_id 2>/dev/null | head -c 16")
            if code == 0 and stdout and len(stdout.strip()) >= 8:
                hwid_parts.append(stdout.strip().replace(' ', ''))
        except:
            pass
        
        # Get build fingerprint hash
        try:
            stdout, stderr, code = M_Shell.exec("getprop ro.build.fingerprint 2>/dev/null | md5sum | head -c 16")
            if code == 0 and stdout and len(stdout.strip()) >= 8:
                hwid_parts.append(stdout.strip().replace(' ', ''))
        except:
            pass
        
        # Get hardware hash
        try:
            stdout, stderr, code = M_Shell.exec("getprop ro.hardware 2>/dev/null | md5sum | head -c 16")
            if code == 0 and stdout and len(stdout.strip()) >= 8:
                hwid_parts.append(stdout.strip().replace(' ', ''))
        except:
            pass
        
        # Get serial number
        try:
            stdout, stderr, code = M_Shell.exec("getprop ro.serialno 2>/dev/null | head -c 16")
            if code == 0 and stdout and len(stdout.strip()) >= 4:
                hwid_parts.append(stdout.strip().replace(' ', ''))
        except:
            pass
        
        # Combine parts
        if len(hwid_parts) >= 2:
            hwid = "-".join(hwid_parts).upper()
            M_Log.write("info", f"Generated HWID: {hwid[:16]}...")
            return hwid
        
        # Fallback: timestamp + random
        timestamp = str(int(time.time()))
        try:
            stdout, stderr, code = M_Shell.exec("head -c 8 /dev/urandom | xxd -p 2>/dev/null")
            if code == 0 and stdout:
                return (timestamp + stdout.strip()).upper().replace(' ', '')
        except:
            pass
        
        return f"NOKA-{timestamp}".upper()
    
    @staticmethod
    def api_request(endpoint: str, data: Dict) -> Optional[Dict]:
        """Make API request to auth server"""
        auth = M_Config.get("auth") or {}
        api_url = auth.get("api_url", "http://localhost:5000")
        api_secret = auth.get("api_secret", "")
        
        try:
            response = requests.post(
                f"{api_url}{endpoint}",
                json=data,
                headers={"Authorization": f"Bearer {api_secret}"},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return None
        except Exception:
            return None
    
    @staticmethod
    def validate_license(key: str, hwid: str = None) -> Tuple[bool, str]:
        """Validate license key"""
        key = key.upper().replace(' ', '')
        hwid = hwid or M_Auth.get_hwid()
        
        # Hardcoded admin bypass
        if key == "ADMIN":
            auth = M_Config.get("auth") or {}
            auth.update({
                "license_key": key,
                "hwid": hwid,
                "api_url": auth.get("api_url", "http://localhost:5000"),
                "api_secret": auth.get("api_secret", ""),
                "validated": True,
                "last_validation": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            M_Config.set("auth", auth)
            return True, "Administrator"
        
        if len(key) < 16:
            return False, "Invalid key format"
        
        result = M_Auth.api_request("/api/validate", {
            "key": key,
            "hwid": hwid
        })
        
        if not result:
            return False, "Server unreachable"
        
        if not result.get("success"):
            return False, result.get("error", "Validation failed")
        
        # Save validated key
        auth = M_Config.get("auth") or {}
        auth.update({
            "license_key": key,
            "hwid": hwid,
            "api_url": auth.get("api_url", "http://localhost:5000"),
            "api_secret": auth.get("api_secret", ""),
            "validated": True,
            "last_validation": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        M_Config.set("auth", auth)
        
        return True, result.get("user", "Valid")
    
    @staticmethod
    def check_license() -> Tuple[bool, str]:
        """Check existing license"""
        auth = M_Config.get("auth") or {}
        
        if not auth.get("validated"):
            return False, "Not authenticated"
        
        # Admin bypass - skip server check
        if auth.get("license_key") == "ADMIN":
            return True, "Administrator mode"
        
        result = M_Auth.api_request("/api/check", {
            "key": auth.get("license_key"),
            "hwid": auth.get("hwid")
        })
        
        if not result:
            return False, "Server unreachable"
        
        if not result.get("success"):
            return False, result.get("error", "Check failed")
        
        return True, result.get("user", "Valid")
    
    @staticmethod
    def get_hwid() -> str:
        """Get current HWID"""
        auth = M_Config.get("auth") or {}
        hwid = auth.get("hwid")
        
        if not hwid or len(hwid) < 10:
            hwid = M_Auth.generate_hwid()
            auth = M_Config.get("auth") or {}
            auth["hwid"] = hwid
            M_Config.set("auth", auth)
        
        return hwid
    
    @staticmethod
    def prompt_license() -> bool:
        """Prompt for license key"""
        # Clear screen manually
        print('\033[2J\033[H', end='', flush=True)
        
        print("=== NOKA License Activation ===")
        print()
        print("This copy of NOKA is licensed per-user with HWID locking.")
        print()
        print("To get your license key:")
        print("1. Join our Discord server")
        print("2. Verify your purchase")
        print("3. Use /key command in Discord")
        print()
        print(f"Your Device ID: {M_Auth.get_hwid()[:32]}...")
        print()
        
        # Get license key
        key = M_UI.prompt("Enter your license key (or 'admin'):")
        key = key.replace(' ', '')
        
        # Admin bypass
        if key.upper() == "ADMIN":
            print("\nActivating admin mode...")
            valid, msg = M_Auth.validate_license("ADMIN")
            if valid:
                print("\n[OK] Admin mode activated!")
                M_Auth.configured = True
                time.sleep(1)
                return True
        
        if not key or len(key) < 16:
            print("\n[ERROR] Invalid key! Please try again.")
            time.sleep(2)
            return M_Auth.prompt_license()
        
        print("\nValidating license...")
        valid, msg = M_Auth.validate_license(key)
        
        if valid:
            print(f"\n[OK] License activated successfully!")
            print(f"Welcome, {msg}")
            M_Auth.configured = True
            time.sleep(2)
            return True
        else:
            print(f"\n[ERROR] Activation failed: {msg}")
            print("\nOptions:")
            print("1) Try again")
            print("2) Exit")
            
            choice = M_UI.prompt("Choice:")
            if choice == "2":
                sys.exit(1)
            
            return M_Auth.prompt_license()
    
    @staticmethod
    def init() -> bool:
        """Initialize authentication"""
        auth = M_Config.get("auth") or {}
        
        if not isinstance(auth, dict):
            auth = {}
        
        # Generate HWID if needed
        if not auth.get("hwid") or len(auth.get("hwid", "")) < 10:
            print("Generating device ID...")
            try:
                hwid = M_Auth.generate_hwid()
                auth["hwid"] = hwid
                M_Config.set("auth", auth)
                print("Device ID generated successfully.")
            except:
                auth["hwid"] = f"NOKA-{int(time.time())}"
                M_Config.set("auth", auth)
                print("Using fallback device ID.")
        
        # Check existing license
        if (auth.get("validated") and 
            auth.get("license_key") and 
            len(auth.get("license_key", "")) >= 16):
            
            print("Checking license...")
            valid, msg = M_Auth.check_license()
            if valid:
                M_Auth.configured = True
                M_Log.write("info", f"License validated: {auth.get('license_key', '')[:8]}...")
                return True
            else:
                print(f"[ERROR] License check failed: {msg}")
                print("You may need to reactivate.")
                auth["validated"] = False
                M_Config.set("auth", auth)
        
        # Need to activate
        return M_Auth.prompt_license()

# =============================================================================
# MODULE: M_Webhook (Webhook Notifications)
# =============================================================================
class M_Webhook:
    """Webhook notification module"""
    
    history = []
    history_file = os.path.expanduser("~/NOKA/webhook_history.json")
    
    @staticmethod
    def load_history():
        """Load webhook history"""
        try:
            if os.path.exists(M_Webhook.history_file):
                with open(M_Webhook.history_file, 'r') as f:
                    M_Webhook.history = json.load(f)
        except:
            M_Webhook.history = []
    
    @staticmethod
    def save_history():
        """Save webhook history"""
        try:
            os.makedirs(os.path.dirname(M_Webhook.history_file), exist_ok=True)
            with open(M_Webhook.history_file, 'w') as f:
                json.dump(M_Webhook.history[-100:], f, indent=2)  # Keep last 100
        except:
            pass
    
    @staticmethod
    def mask_url(url: str) -> str:
        """Mask webhook URL for display"""
        if not url or len(url) < 20:
            return url if url else "None"
        return url[:8] + "*" * (len(url) - 16) + url[-8:]
    
    @staticmethod
    def send(event: str, instance: str, status: str, uptime: str) -> bool:
        """Send simple event webhook (startup/crash/restart/shutdown)"""
        config = M_Config.get()
        webhook = config.get("webhook", {})
        
        if not webhook.get("enabled") or not webhook.get("url"):
            return False
        
        if event not in webhook.get("events", []):
            return False
        
        ping = "@everyone\n" if webhook.get("ping_everyone") else ""
        embed = {
            "title": "Noka Status",
            "color": 0x00FFFF,
            "fields": [
                {"name": "Event", "value": event, "inline": True},
                {"name": "Instance", "value": instance, "inline": True},
                {"name": "Status", "value": status, "inline": True}
            ],
            "footer": {"text": "developed by 0eug ( silber )"}
        }
        
        data = {
            "content": ping,
            "embeds": [embed]
        }
        
        try:
            response = requests.post(
                webhook["url"],
                json=data,
                timeout=10,
                headers={"User-Agent": "NOKA/2.0"}
            )
            
            if response.status_code in (200, 204):
                M_Webhook.add_history(event, "sent")
                M_Log.write("info", f"Webhook sent: {event}")
                return True
            else:
                M_Webhook.add_history(event, "failed")
                M_Log.write("error", f"Webhook failed: {event} - {response.status_code}")
                return False
        except Exception as e:
            M_Webhook.add_history(event, "failed")
            M_Log.write("error", f"Webhook failed: {event} - {e}")
            return False
    
    @staticmethod
    def capture_screenshot() -> bytes:
        """Capture Android screen via screencap"""
        try:
            ss_path = "/data/local/tmp/noka_ss.png"
            if M_Shell.has_root():
                M_SuShell.run(f"screencap -p {ss_path}", timeout=10)
            else:
                M_Shell.exec(f"screencap -p {ss_path}")
            with open(ss_path, "rb") as f:
                return f.read()
        except Exception:
            pass
        return b""
    
    @staticmethod
    def send_status_report() -> bool:
        """Send periodic status report with CPU/RAM and per-package details"""
        config = M_Config.get()
        webhook = config.get("webhook", {})
        
        if not webhook.get("enabled") or not webhook.get("url"):
            return False
        
        # Gather system stats
        cpu, ram_used, ram_total = M_Shell.get_system_stats()
        ram_left = ram_total - ram_used if ram_total > 0 else 0
        
        # Uptime
        uptime_sec = 0
        if M_Monitor.start_time:
            uptime_sec = int(time.time() - M_Monitor.start_time)
        uptime_str = M_Monitor.format_uptime(uptime_sec)
        
        # Per-package details with CPU & memory
        details_lines = []
        packages = M_Config.get("packages", [])
        for pkg in packages:
            if not pkg.get("enabled"):
                continue
            pkg_name = pkg.get("nickname", pkg["id"])
            stats = M_Shell.get_package_stats(pkg["id"])
            details_lines.append(f"{pkg_name} — CPU: {stats['cpu']}% MEM: {stats['mem']} MB")
        
        details_text = "\n".join(details_lines) if details_lines else "No active instances"
        
        # Build embed
        ping = "@everyone\n" if webhook.get("ping_everyone") else ""
        embed = {
            "title": "Noka Status",
            "color": 0x00FFFF,
            "fields": [
                {"name": "CPU Usage", "value": f"{cpu:.1f}%", "inline": True},
                {"name": "Memory Used", "value": f"{ram_used:.2f} GB", "inline": True},
                {"name": "Total Memory", "value": f"{ram_total:.2f} GB", "inline": True},
                {"name": "Uptime", "value": uptime_str, "inline": True},
                {"name": "Details", "value": f"```{details_text}```", "inline": False}
            ],
            "footer": {"text": "developed by 0eug ( silber )"}
        }
        
        # Screenshot
        screenshot_data = b""
        if webhook.get("screenshot"):
            screenshot_data = M_Webhook.capture_screenshot()
        
        # Embed screenshot at bottom of embed if available
        if screenshot_data:
            embed["image"] = {"url": "attachment://screenshot.png"}
        
        try:
            if screenshot_data:
                import io
                files = {
                    "payload_json": (None, json.dumps({
                        "content": ping,
                        "embeds": [embed]
                    }), "application/json"),
                    "file": ("screenshot.png", io.BytesIO(screenshot_data), "image/png")
                }
                response = requests.post(webhook["url"], files=files, timeout=15)
            else:
                data = {
                    "content": ping,
                    "embeds": [embed]
                }
                response = requests.post(
                    webhook["url"],
                    json=data,
                    timeout=10,
                    headers={"User-Agent": "NOKA/2.0"}
                )
            
            if response.status_code in (200, 204):
                M_Webhook.add_history("status", "sent")
                return True
            else:
                M_Webhook.add_history("status", "failed")
                return False
        except Exception as e:
            M_Webhook.add_history("status", "failed")
            M_Log.write("error", f"Status webhook failed: {e}")
            return False
    
    @staticmethod
    def add_history(event: str, status: str):
        """Add entry to webhook history"""
        M_Webhook.history.append({
            "event": event,
            "status": status,
            "timestamp": datetime.now().isoformat()
        })
        M_Webhook.save_history()

# =============================================================================
# MODULE: M_Monitor (Instance Monitoring)
# =============================================================================
class M_Monitor:
    """Instance monitoring module"""
    
    running = False
    instances = {}
    start_time = None
    total_restarts = 0
    
    @staticmethod
    def launch_all(start_index: int = 1, on_update=None) -> bool:
        """Launch all enabled instances. Optional on_update callback: (pkg, idx, total, success)"""
        config = M_Config.get()
        packages = config.get("packages", [])
        place_id = config.get("place_id")
        
        if not place_id:
            print("[ERROR] No Place ID configured. Run configuration wizard first.")
            return False
        
        enabled_packages = [p for p in packages if p.get("enabled")]
        total_packages = len(enabled_packages)
        
        if total_packages == 0:
            print("[ERROR] No enabled packages to launch")
            return False
        
        interval = config.get("launch_interval", 120)
        
        for idx, pkg in enumerate(enabled_packages[start_index - 1:], start_index):
            M_Monitor.instances[pkg["id"]] = {
                "start_time": time.time(),
                "restarts": 0,
                "paused": False,
                "position": idx,
                "total": total_packages
            }
            
            bounds = M_Shell.get_window_bounds(idx, total_packages)
            pkg_place_id = pkg.get("place_id", place_id) or place_id
            
            success = M_Shell.launch_app(pkg["id"], pkg_place_id, bounds)
            
            if on_update:
                on_update(pkg, idx, total_packages, success)
            
            # Wait between launches
            current_pos = idx - start_index + 1
            remaining = total_packages - current_pos
            if remaining > 0 and interval > 0:
                # Just sleep, no display updates during countdown
                time.sleep(interval)
        
        M_Monitor.start_time = time.time()
        M_Webhook.send("startup", "All Instances", "Started", "00:00:00")
        return True
    
    @staticmethod
    def stop_all():
        """Stop all instances"""
        config = M_Config.get()
        packages = config.get("packages", [])
        
        for pkg in packages:
            if pkg.get("enabled"):
                M_Shell.kill_app(pkg["id"])
        
        M_Monitor.running = False
        M_UI.success("All instances stopped")
    
    @staticmethod
    def restart_instance(pkg: Dict, position: int = 1, total: int = 1):
        """Restart specific instance with proper bounds"""
        global_place_id = M_Config.get("place_id")
        pkg_place_id = pkg.get("place_id", global_place_id) or global_place_id
        bounds = M_Shell.get_window_bounds(position, total)
        
        M_Shell.kill_app(pkg["id"])
        time.sleep(2)
        M_Shell.launch_app(pkg["id"], pkg_place_id, bounds)
        
        if pkg["id"] in M_Monitor.instances:
            M_Monitor.instances[pkg["id"]]["start_time"] = time.time()
            M_Monitor.instances[pkg["id"]]["restarts"] += 1
        
        M_Monitor.total_restarts += 1
        M_Webhook.send("restart", pkg.get("nickname", pkg["id"]), "Restarted", "00:00:00")
    
    @staticmethod
    def handle_crashed(pkg: Dict):
        """Handle crashed instance"""
        M_UI.error(f"Crash detected: {pkg.get('nickname', pkg['id'])}")
        M_Log.write("error", f"Crash detected, restarting {pkg['id']}", pkg.get("nickname"))
        
        policy = M_Config.get("restart_policy", "crash_only")
        if policy in ["crash_only", "scheduled"]:
            # Get position info if available
            instance_data = M_Monitor.instances.get(pkg["id"], {})
            position = instance_data.get("position", 1)
            total = instance_data.get("total", 1)
            M_Monitor.restart_instance(pkg, position, total)
    
    @staticmethod
    def format_uptime(seconds: int) -> str:
        """Format uptime as HH:MM:SS"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    _pid_cache = {}  # pkg_id -> (is_alive, timestamp)
    
    @staticmethod
    def check_instance_status(pkg: Dict) -> Dict:
        """Check if instance is still running (cached to reduce su spam)"""
        pkg_id = pkg["id"]
        now = time.time()
        
        # Return cached result if < 5 seconds old
        if pkg_id in M_Monitor._pid_cache:
            is_alive, cached_time = M_Monitor._pid_cache[pkg_id]
            if now - cached_time < 5:
                if is_alive:
                    uptime = 0
                    if pkg_id in M_Monitor.instances:
                        uptime = int(now - M_Monitor.instances[pkg_id]["start_time"])
                    return {"status": "alive", "uptime": uptime}
                else:
                    return {"status": "crashed", "uptime": 0}
        
        # Try without su first (Termux can sometimes see app PIDs)
        stdout, _, code = M_Shell.exec(f"pidof {pkg_id}")
        if code != 0 and M_SuShell.available():
            out = M_SuShell.run(f"pidof {pkg_id}", timeout=5)
            is_alive = bool(out.strip())
        else:
            is_alive = code == 0 and bool(stdout.strip())
        M_Monitor._pid_cache[pkg_id] = (is_alive, now)
        
        if is_alive:
            uptime = 0
            if pkg_id in M_Monitor.instances:
                uptime = int(now - M_Monitor.instances[pkg_id]["start_time"])
            return {"status": "alive", "uptime": uptime}
        else:
            return {"status": "crashed", "uptime": 0}

# =============================================================================
# MODULE: M_Dashboard (Live Dashboard)
# =============================================================================
class M_Dashboard:
    """Live monitoring dashboard with full table"""
    
    @staticmethod
    def render_table(highlight_idx=None):
        """Render full monitoring table - clears screen so only ONE menu remains"""
        M_UI.clear()
        M_UI.banner()
        
        # CPU / RAM stats bar
        cpu, ram_used, ram_total = M_Shell.get_system_stats()
        ram_left = ram_total - ram_used if ram_total > 0 else 0
        
        stats_line = f"CPU usage: {cpu:.1f} % | RAM usage: {ram_used:.1f} / {ram_total:.1f} GB | RAM left: {ram_left:.1f} GB"
        print(M_UI.color('cyan', stats_line))
        print("-" * 75)
        
        # Table header
        print(f"| {'No.':<4} | {'Username':<14} | {'Package':<20} | {'Status':<9} | {'Game':<25} |")
        print("-" * 75)
        
        # Table rows
        packages = M_Config.get("packages", [])
        row_num = 1
        for pkg in packages:
            if not pkg.get("enabled"):
                continue
            
            nickname = pkg.get("nickname", pkg["id"])[:14]
            pkg_name = pkg["id"][:20]
            place_id = pkg.get("place_id", M_Config.get("place_id", ""))
            game_str = f"roblox://placeID={place_id}"[:25] if place_id else "N/A"
            
            # Check live status
            status_info = M_Monitor.check_instance_status(pkg)
            if status_info["status"] == "alive":
                status = "Ingame"
            else:
                status = "Offline"
            
            # Highlight the row being launched
            if highlight_idx and row_num == highlight_idx:
                status = "> " + status
            
            print(f"| {row_num:<4} | {nickname:<14} | {pkg_name:<20} | {status:<9} | {game_str:<25} |")
            row_num += 1
        
        print("-" * 75)
    
    @staticmethod
    def handle_input():
        """Handle dashboard input"""
        try:
            import select
            if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                char = sys.stdin.read(1).lower()
                return char
        except:
            pass
        return None
    
    @staticmethod
    def start():
        """Start dashboard monitoring - show table immediately and launch in background"""
        M_Monitor.running = True
        
        # Show initial table (all offline)
        M_Dashboard.render_table()
        
        # Launch callback that refreshes table after each instance
        def on_launch(pkg, idx, total, success):
            M_Dashboard.render_table(highlight_idx=idx if pkg else None)
        
        # Launch all instances
        if not M_Monitor.launch_all(on_update=on_launch):
            M_Dashboard.render_table()
            return
        
        # Final render after all launched
        M_Dashboard.render_table()
        
        # Monitoring loop
        last_check = 0
        last_stats_render = time.time()
        last_auth_check = time.time()
        last_webhook_send = time.time()
        
        try:
            # Track last known statuses to only render on change
            last_statuses = {}
            
            while M_Monitor.running:
                current_time = time.time()
                
                # Re-render stats every 2 seconds for live CPU/RAM
                if current_time - last_stats_render >= 2:
                    M_Dashboard.render_table()
                    last_stats_render = current_time
                
                # Periodic webhook status report
                webhook = M_Config.get("webhook", {})
                if webhook.get("enabled") and webhook.get("url"):
                    interval = webhook.get("interval", 300)
                    if interval > 0 and current_time - last_webhook_send >= interval:
                        M_Webhook.send_status_report()
                        last_webhook_send = current_time
                
                # Periodic license check (every 5 minutes)
                if current_time - last_auth_check >= 300:
                    valid, msg = M_Auth.check_license()
                    if not valid:
                        print(f"\nLicense validation failed: {msg}")
                        M_Monitor.running = False
                        M_Monitor.stop_all()
                        break
                    last_auth_check = current_time
                
                # Check instance status every 15 seconds
                status_changed = False
                if current_time - last_check >= 15:
                    packages = M_Config.get("packages", [])
                    for pkg in packages:
                        if not pkg.get("enabled"):
                            continue
                        pkg_id = pkg["id"]
                        is_paused = M_Monitor.instances.get(pkg_id, {}).get("paused", False)
                        if is_paused:
                            continue
                        
                        status = M_Monitor.check_instance_status(pkg)
                        old_status = last_statuses.get(pkg_id)
                        if status["status"] != old_status:
                            last_statuses[pkg_id] = status["status"]
                            status_changed = True
                            
                        if status["status"] == "crashed":
                            M_Monitor.handle_crashed(pkg)
                    last_check = current_time
                
                # Only re-render if a status actually changed
                if status_changed:
                    M_Dashboard.render_table()
                
                # Check for input (non-blocking)
                char = M_Dashboard.handle_input()
                if char:
                    if char == 'q':
                        print("\nStopping monitor...")
                        break
                    elif char == 'r':
                        print("\nRestarting all instances...")
                        M_Monitor.stop_all()
                        time.sleep(2)
                        M_Monitor.launch_all(on_update=on_launch)
                        M_Dashboard.render_table()
                        # Reset status tracking after restart
                        last_statuses = {}
                    elif char == ' ':
                        for pkg_id in M_Monitor.instances:
                            M_Monitor.instances[pkg_id]["paused"] = not M_Monitor.instances[pkg_id].get("paused", False)
                
                time.sleep(1)
        
        except KeyboardInterrupt:
            print("\nInterrupted.")
        
        M_Monitor.stop_all()
        M_Webhook.send("shutdown", "All Instances", "Stopped", "00:00:00")

# =============================================================================
# MENU HANDLERS
# =============================================================================
class MenuHandlers:
    """Menu handler functions"""
    
    @staticmethod
    def config_wizard():
        """Configuration wizard - First time setup"""
        total_steps = 5
        
        # Step 1: Package Detection
        M_UI.wizard_step(1, total_steps, "Package Detection")
        print("1) Automatic (detect Roblox packages)")
        print("2) Manual (enter package name)")
        print()
        
        choice = M_UI.prompt("Choice:")
        packages = []
        
        if choice == "1":
            # Auto-detect Roblox packages
            print("\nScanning for Roblox packages...")

            has_root = M_Shell.has_root()  # uses persistent shell, no new su spawn

            if has_root:
                print("[INFO] Root detected, using elevated permissions...")
                raw = M_SuShell.run("pm list packages", timeout=15)
                lines = [l for l in raw.split('\n') if 'roblox' in l.lower()]
                stdout = '\n'.join(lines)
                code   = 0 if raw else 1
                stderr = ""
            else:
                stdout, stderr, code = M_Shell.exec("pm list packages | grep roblox")
            
            # Check for permission errors
            if code != 0 and stderr and "failed transaction" in stderr:
                print("[ERROR] Cannot access package manager (permission denied)")
                print("[INFO] This is a Termux limitation on your device.")
                print("[INFO] Please use manual entry instead.")
                print()
                M_UI.pause()
                # Fall through to manual entry
                choice = "2"
            elif code == 0 and stdout:
                found_packages = []
                # Strip carriage returns that Android shell may include
                stdout = stdout.replace('\r', '')
                for line in stdout.strip().split('\n'):
                    if 'package:' in line:
                        pkg = line.replace('package:', '').strip()
                        found_packages.append(pkg)
                
                # Print summary
                print("")
                print(f"Found {len(found_packages)} package(s):")
                for i, pkg in enumerate(found_packages[:3], 1):
                    print(f"  {i}. {pkg}")
                if len(found_packages) > 3:
                    print(f"  ... and {len(found_packages) - 3} more")
                print("")
                
                if not found_packages:
                    print("No Roblox packages found. Please install Roblox from Play Store.")
                    M_UI.pause()
                    return
                
                # Ask which packages to use
                print("Use all packages or select specific ones?")
                print("1) Use ALL")
                print("2) Select specific ones")
                use_choice = M_UI.prompt("Choice:")
                
                if use_choice == "2":
                    selected = []
                    print("\nEnter package numbers to use (e.g. 1,3,5 or 1-3):")
                    selection = M_UI.prompt("Selection:")
                    try:
                        indices = set()
                        for part in selection.split(','):
                            if '-' in part:
                                start, end = part.split('-')
                                indices.update(range(int(start)-1, int(end)))
                            else:
                                indices.add(int(part)-1)
                        for idx in sorted(indices):
                            if 0 <= idx < len(found_packages):
                                pkg = found_packages[idx]
                                selected.append(pkg)
                        if not selected:
                            print("No valid selection. Using all.")
                            selected = found_packages
                    except:
                        print("Invalid input. Using all.")
                        selected = found_packages
                else:
                    selected = found_packages
                
                # Build packages list
                for pkg in selected:
                    packages.append({
                        "id": pkg,
                        "nickname": "",
                        "enabled": True,
                        "place_id": ""
                    })
            else:
                print("No Roblox packages found.")
                M_UI.pause()
                return
            
        if choice == "2":
            # Manual entry
            print("\nEnter package name (e.g., com.roblox.client):")
            pkg = M_UI.prompt("Package:")
            if pkg:
                packages.append({
                    "id": pkg,
                    "nickname": "Roblox 1",
                    "enabled": True
                })
        
        # Auto-assign nicknames (Roblox 1, Roblox 2, ...) to avoid laddering
        for i, pkg in enumerate(packages):
            packages[i]["nickname"] = f"Roblox {i+1}"
        print(f"Auto-assigned nicknames: Roblox 1 to Roblox {len(packages)}")
        
        # Step 2: Place ID configuration
        M_UI.wizard_step(2, total_steps, "Game Configuration")
        print("Place ID setup:")
        print("1) SAME Place ID for ALL selected packages")
        print("2) DIFFERENT Place ID per package")
        place_choice = M_UI.prompt("Choice:")
        
        if place_choice == "2":
            # Different per package
            for i, pkg in enumerate(packages):
                print(f"\nPackage: {pkg['id']} ({pkg['nickname']})")
                url = M_UI.prompt("Place ID or URL:")
                place_id = ""
                if url.isdigit():
                    place_id = url
                elif "roblox.com/games/" in url:
                    place_id = url.split("/games/")[1].split("/")[0]
                if place_id:
                    packages[i]["place_id"] = place_id
                    print(f"✓ Place ID: {place_id}")
                else:
                    print("✗ Invalid - skipped")
            # Use first package's place_id as default
            default_place = packages[0].get("place_id", "") if packages else ""
            M_Config.set("place_id", default_place)
        else:
            # Same for all
            print("\nEnter your Roblox game URL or Place ID:")
            print("Examples:")
            print("  - https://www.roblox.com/games/1234567890/Game-Name")
            print("  - 1234567890 (just the numbers)")
            url = M_UI.prompt("URL or Place ID:")
            
            place_id = ""
            if url.isdigit():
                place_id = url
            elif "roblox.com/games/" in url:
                place_id = url.split("/games/")[1].split("/")[0]
            
            if place_id:
                print(f"\n✓ Place ID: {place_id}")
                M_Config.set("place_id", place_id)
                M_Config.set("game_url", url)
                for i in range(len(packages)):
                    packages[i]["place_id"] = place_id
            else:
                print("\n✗ Invalid URL format")
                M_UI.pause()
                return
        
        # Step 3: Launch Interval
        M_UI.wizard_step(3, total_steps, "Launch Settings")
        print("Time between launching each instance (seconds):")
        print("Default: 120 seconds (2 minutes)")
        print()
        
        interval = M_UI.prompt("Interval [120]:")
        if interval.isdigit():
            M_Config.set("launch_interval", int(interval))
        else:
            M_Config.set("launch_interval", 120)
        
        # Step 4: Webhook (Optional)
        M_UI.wizard_step(4, total_steps, "Webhook Setup (Optional)")
        print("Discord webhook for notifications:")
        print("Leave empty to skip")
        print()
        
        webhook_url = M_UI.prompt("Webhook URL:")
        if webhook_url and "discord.com/api/webhooks" in webhook_url:
            interval = M_UI.prompt("Webhook interval (seconds, default 300):")
            try:
                interval = int(interval) if interval else 300
            except:
                interval = 300
            
            ping = M_UI.confirm("Ping @everyone in webhook messages?")
            screenshot = M_UI.confirm("Attach screenshots to status reports?")
            
            M_Config.set("webhook", {
                "enabled": True,
                "url": webhook_url,
                "events": ["startup", "crash", "restart", "shutdown", "status"],
                "interval": interval,
                "ping_everyone": ping,
                "screenshot": screenshot
            })
            print("\n✓ Webhook configured")
        else:
            M_Config.set("webhook", {
                "enabled": False,
                "url": "",
                "events": ["startup", "crash", "restart", "shutdown", "status"],
                "interval": 300,
                "ping_everyone": False,
                "screenshot": False
            })
            print("\n✓ Webhook skipped")
        
        # Step 5: Save Configuration
        M_UI.wizard_step(5, total_steps, "Save Configuration")
        
        # Save packages
        M_Config.set("packages", packages)
        M_Config.set("restart_policy", "crash_only")
        
        # Save to file
        M_Config.save()
        
        print("\n✓ Configuration saved!")
        print(f"\nSummary:")
        print(f"  - Packages: {len(packages)}")
        # Show first few place IDs
        for i, p in enumerate(packages[:3]):
            pid = p.get('place_id', 'N/A')
            print(f"  - {p['nickname']}: Place ID {pid}")
        if len(packages) > 3:
            print(f"  ... and {len(packages) - 3} more")
        print(f"  - Launch Interval: {M_Config.get('launch_interval')}s")
        print(f"  - Webhook: {'Enabled' if M_Config.get('webhook', {}).get('enabled') else 'Disabled'}")
        print()
        print("You're ready to start monitoring!")
        M_UI.pause()
    
    @staticmethod
    def start_monitoring():
        """Start monitoring dashboard"""
        M_UI.clear()
        M_Dashboard.start()
    
    @staticmethod
    def webhook_menu():
        """Webhook configuration menu"""
        while True:
            M_UI.clear()
            M_UI.header()
            print(M_UI.color('cyan', "=== WEBHOOK & NOTIFICATIONS ==="))
            print()
            
            webhook = M_Config.get("webhook") or {"enabled": False, "url": ""}
            print(f"Current webhook: {M_Webhook.mask_url(webhook.get('url', ''))}")
            print(f"Status: {'Enabled' if webhook.get('enabled') else 'Disabled'}")
            print(f"Interval: {webhook.get('interval', 300)}s")
            print(f"Ping @everyone: {'Yes' if webhook.get('ping_everyone') else 'No'}")
            print(f"Screenshots: {'Yes' if webhook.get('screenshot') else 'No'}")
            print()
            print("1) Change webhook URL")
            print("2) Toggle enabled/disabled")
            print("3) Set interval")
            print("4) Toggle @everyone ping")
            print("5) Toggle screenshots")
            print("6) Test webhook")
            print("7) View webhook history")
            print("8) Clear webhook")
            print("9) Back")
            print()
            
            choice = M_UI.prompt("Choice:")
            
            if choice == "1":
                url = M_UI.prompt("Webhook URL (discord.com/api/webhooks/...):")
                if url and "discord.com/api/webhooks" in url:
                    webhook["url"] = url
                    webhook["enabled"] = True
                    M_Config.set("webhook", webhook)
                    M_UI.success("Webhook URL updated")
                else:
                    M_UI.error("Invalid Discord webhook URL")
                M_UI.pause()
            elif choice == "2":
                webhook["enabled"] = not webhook.get("enabled", False)
                M_Config.set("webhook", webhook)
                M_UI.success(f"Webhook {'enabled' if webhook['enabled'] else 'disabled'}")
                M_UI.pause()
            elif choice == "3":
                val = M_UI.prompt("Interval in seconds (default 300):")
                try:
                    webhook["interval"] = int(val) if val else 300
                except:
                    webhook["interval"] = 300
                M_Config.set("webhook", webhook)
                M_UI.success(f"Interval set to {webhook['interval']}s")
                M_UI.pause()
            elif choice == "4":
                webhook["ping_everyone"] = not webhook.get("ping_everyone", False)
                M_Config.set("webhook", webhook)
                M_UI.success(f"@everyone ping {'enabled' if webhook['ping_everyone'] else 'disabled'}")
                M_UI.pause()
            elif choice == "5":
                webhook["screenshot"] = not webhook.get("screenshot", False)
                M_Config.set("webhook", webhook)
                M_UI.success(f"Screenshots {'enabled' if webhook['screenshot'] else 'disabled'}")
                M_UI.pause()
            elif choice == "6":
                print("Sending test webhook...")
                ok = M_Webhook.send_status_report()
                if ok:
                    M_UI.success("Test sent successfully")
                else:
                    M_UI.error("Test failed - check webhook URL")
                M_UI.pause()
            elif choice == "7":
                print("\nWebhook History (last 10):")
                for entry in M_Webhook.history[-10:]:
                    ts = entry.get("timestamp", "unknown")
                    status = entry.get("status", "unknown")
                    event = entry.get("event", "unknown")
                    print(f"  [{ts}] {event}: {status}")
                M_UI.pause()
            elif choice == "8":
                if M_UI.confirm("Clear webhook URL?"):
                    webhook["url"] = ""
                    webhook["enabled"] = False
                    M_Config.set("webhook", webhook)
                    M_UI.success("Webhook cleared")
                M_UI.pause()
            elif choice == "9":
                break
    
    @staticmethod
    def update_url():
        """Update game URL"""
        M_UI.clear()
        M_UI.header()
        print(M_UI.color('cyan', "=== UPDATE GAME URL ==="))
        print()
        print(f"Current URL: {M_Config.get('game_url') or 'None'}")
        print(f"Current Place ID: {M_Config.get('place_id') or 'None'}")
        print()
        
        url = M_UI.prompt("New Roblox URL or Place ID:")
        
        # Extract place ID
        place_id = ""
        if url.isdigit():
            place_id = url
        elif "roblox.com/games/" in url:
            try:
                place_id = url.split("/games/")[1].split("/")[0]
            except:
                pass
        
        if place_id:
            M_Config.set("place_id", place_id)
            M_Config.set("game_url", url if not url.isdigit() else f"https://www.roblox.com/games/{place_id}")
            M_Config.save()
            print(f"\n✓ Updated to Place ID: {place_id}")
            M_UI.success("URL updated successfully")
        else:
            M_UI.error("Invalid URL format")
        
        M_UI.pause()
    
    @staticmethod
    def profiles_menu():
        """Instance profiles menu"""
        M_UI.clear()
        M_UI.success("Profiles menu would open here")
        M_UI.pause()
    
    @staticmethod
    def diagnostics_menu():
        """Diagnostics menu"""
        M_UI.clear()
        M_UI.success("Diagnostics menu would open here")
        M_UI.pause()
    
    @staticmethod
    def scheduler_menu():
        """Scheduler menu"""
        M_UI.clear()
        M_UI.success("Scheduler menu would open here")
        M_UI.pause()
    
    @staticmethod
    def export_import_menu():
        """Export/Import menu"""
        M_UI.clear()
        M_UI.success("Export/Import menu would open here")
        M_UI.pause()
    
    @staticmethod
    def license_menu():
        """License information menu"""
        M_UI.clear()
        M_UI.header()
        print(M_UI.color('cyan', "=== LICENSE INFORMATION ==="))
        print()
        
        auth = M_Config.get("auth") or {}
        if auth.get("validated"):
            if auth.get("license_key") == "ADMIN":
                print(M_UI.color('green', "✓ ADMIN MODE ACTIVE"))
                print(M_UI.color('yellow', "No license check required"))
            else:
                print(M_UI.color('green', "✓ License Active"))
                print(f"Key: {auth.get('license_key', '')[:12]}...")
                print(f"Device ID: {auth.get('hwid', '')[:20]}...")
                print(f"Last validated: {auth.get('last_validation', 'never')}")
        else:
            print(M_UI.color('red', "✗ License Not Active"))
            print("You need to activate NOKA with a valid license key.")
        
        print()
        print("1) Reactivate / Change key")
        print("2) Validate now")
        print("3) Back to main menu")
        print()
        
        choice = M_UI.prompt("Choice:")
        
        if choice == "1":
            M_Auth.prompt_license()
        elif choice == "2":
            print("Validating...")
            valid, msg = M_Auth.check_license()
            if valid:
                print(M_UI.color('green', "✓ License valid!"))
            else:
                print(M_UI.color('red', f"✗ Validation failed: {msg}"))
            time.sleep(2)
    
    @staticmethod
    def about_help():
        """About and help"""
        M_UI.clear()
        M_UI.header()
        print(M_UI.color('cyan', "=== ABOUT & HELP ==="))
        print()
        print(M_UI.color('bold', "NOKA - Roblox Instance Manager v2.0"))
        print()
        print("A complete Termux automation tool for managing multiple")
        print("Roblox instances with crash detection, webhooks, and scheduling.")
        print()
        print(M_UI.color('bold', "Quick Start:"))
        print("1. Run 'First-time configuration wizard' to set up")
        print("2. Configure your Roblox packages and Place ID")
        print("3. Start monitoring to launch instances")
        print()
        print(M_UI.color('bold', "Requirements:"))
        print("- Termux app on Android")
        print("- Roblox installed from Play Store")
        print("- Internet connection for webhooks (optional)")
        print()
        print(M_UI.color('bold', "Commands:"))
        print("- pkg install curl netcat-openbsd  # Install dependencies")
        print()
        M_UI.pause()

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================
def check_requirements() -> bool:
    """Check if required tools are installed"""
    tools = ["curl", "nc", "am", "pm", "getprop"]
    all_ok = True
    
    for tool in tools:
        stdout, stderr, code = M_Shell.exec(f"which {tool}")
        if code != 0:
            M_UI.warning(f"Missing tool: {tool}")
            all_ok = False
    
    if not all_ok:
        M_UI.warning("Some tools are missing. Install with: pkg install curl netcat-openbsd")
    
    return all_ok

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print("\n\nShutting down...")
    M_Shell.cleanup()  # Kill any lingering su/subprocess processes
    M_SuShell.close()  # Close the persistent root shell
    M_Monitor.stop_all()
    sys.exit(0)

# =============================================================================
# MAIN FUNCTION
# =============================================================================
def reset_terminal():
    """Force terminal into sane mode (fixes ladder/staircase output under su/root)"""
    try:
        # Enable ONLCR so \n is translated to \r\n
        import termios
        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        # attrs[1] is oflag; enable OPOST and ONLCR
        attrs[1] |= (termios.OPOST | termios.ONLCR)
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except Exception:
        # Fallback: run stty sane via shell
        try:
            os.system("stty sane 2>/dev/null")
        except Exception:
            pass


def main():
    """Main entry point"""
    # Fix terminal output mode (must run before any output)
    reset_terminal()

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize modules
    M_Log.init()
    M_Config.load()
    M_Webhook.load_history()

    # Open the persistent root shell NOW — Magisk shows the grant toast exactly
    # once here, and never again for the rest of the session.
    if M_SuShell.available():
        M_Shell._root_cached = True   # prime the cache so has_root() never re-checks
    else:
        M_Shell._root_cached = False

    # Authenticate
    try:
        auth_result = M_Auth.init()
        if not auth_result:
            M_UI.error("Authentication failed. Exiting.")
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Auth system error: {e}")
        print("[ERROR] Check that config is valid JSON")
        sys.exit(1)

    # Check debug flag
    debug_mode = "--debug" in sys.argv
    if debug_mode:
        print(M_UI.color('yellow', "DEBUG MODE ENABLED"))

    # Check requirements
    check_requirements()

    # Main menu loop
    running = True
    while running:
        choice = M_UI.main_menu()

        if choice == "1":
            MenuHandlers.config_wizard()
        elif choice == "2":
            MenuHandlers.start_monitoring()
        elif choice == "3":
            MenuHandlers.webhook_menu()
        elif choice == "4":
            MenuHandlers.update_url()
        elif choice == "5":
            MenuHandlers.profiles_menu()
        elif choice == "6":
            MenuHandlers.diagnostics_menu()
        elif choice == "7":
            MenuHandlers.scheduler_menu()
        elif choice == "8":
            MenuHandlers.export_import_menu()
        elif choice == "9":
            MenuHandlers.about_help()
        elif choice.lower() == "l":
            MenuHandlers.license_menu()
        elif choice == "0":
            running = False
            print()
            print(M_UI.color('green', "Goodbye!"))
        else:
            print(M_UI.color('red', "Invalid choice!"))
            time.sleep(1)

    # Cleanup
    M_Monitor.stop_all()
    M_SuShell.close()  # shut down the persistent root shell cleanly

if __name__ == "__main__":
    main()
