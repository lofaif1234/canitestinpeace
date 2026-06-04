#!/usr/bin/env python3
"""
NOKA - Roblox Instance Manager v2.0 (Python Version)
A complete Termux automation tool for managing multiple Roblox instances
with crash detection, webhooks, and scheduling.
"""

import os
import sys
import json
import time
import subprocess
import threading
import requests
import hashlib
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import signal

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
        try:
            # Try to open /dev/tty for direct terminal input
            with open('/dev/tty', 'r') as tty:
                line = tty.readline().strip()
                return line
        except:
            # Fallback to stdin
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
    
    @staticmethod
    def exec(cmd: str, timeout: int = 30) -> Tuple[str, str, int]:
        """Execute shell command with timeout"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", "Command timed out", 124
        except Exception as e:
            return "", str(e), 1
    
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
    def detect_screen_size():
        """Auto-detect screen size using wm size"""
        try:
            stdout, _, code = M_Shell.exec("su -c 'wm size'" if M_Shell.has_root() else "wm size")
            if code == 0 and stdout:
                # Parse output like "Physical size: 1080x1920"
                match = __import__('re').search(r'(\d+)x(\d+)', stdout)
                if match:
                    return int(match.group(1)), int(match.group(2))
        except:
            pass
        return 1080, 1920  # Default fallback
    
    @staticmethod
    def has_root() -> bool:
        """Check if root is available"""
        try:
            stdout, _, code = M_Shell.exec("test -f /system/bin/su && echo yes || echo no")
            return code == 0 and "yes" in stdout
        except:
            return False
    
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
        """Launch app with multiple fallback methods"""
        if not package or not place_id:
            M_UI.error("Package and place_id required")
            return False
        
        # Check if package is installed (with root if available)
        M_UI.info("Checking if package is installed...")
        
        # Try to use root for pm path if available
        root_check, _, root_ok = M_Shell.exec("test -f /system/bin/su && echo yes || echo no")
        has_root = root_ok == 0 and "yes" in root_check
        
        if has_root:
            stdout, stderr, code = M_Shell.exec(f"su -c 'pm path {package}'")
        else:
            stdout, stderr, code = M_Shell.exec(f"pm path {package}")
        
        if code != 0 or not stdout or "package:" not in stdout:
            M_UI.error(f"Package not installed: {package}")
            M_UI.info("Please install Roblox from the Play Store first")
            return False
        
        pkg_path = stdout.split("package:")[1].strip() if "package:" in stdout else stdout.strip()
        M_UI.info(f"✓ Package found: {pkg_path}")
        
        url = f"roblox://placeId={place_id}"
        
        # Try multiple launch methods (with root if available)
        methods = []
        su_prefix = f"su -c '" if has_root else ""
        su_suffix = "'" if has_root else ""
        
        # Method 1: Freeform with bounds
        if window_bounds:
            methods.append({
                "name": "Freeform with bounds",
                "cmd": f"{su_prefix}am start -a android.intent.action.VIEW -d '{url}' -f 0x20000000 --windowingMode 5 --windowBounds {window_bounds} {package}{su_suffix}"
            })
        
        # Method 2: Standard URL launch
        methods.append({
            "name": "Standard URL launch",
            "cmd": f"{su_prefix}am start -a android.intent.action.VIEW -d '{url}' {package}{su_suffix}"
        })
        
        # Method 3: Explicit activity
        methods.append({
            "name": "Package explicit launch",
            "cmd": f"{su_prefix}am start -a android.intent.action.VIEW -d '{url}' -n {package}/com.roblox.client.Activity{su_suffix}"
        })
        
        # Method 4: Simple launch
        methods.append({
            "name": "Simple launch",
            "cmd": f"{su_prefix}am start -n {package}/com.roblox.client.Activity{su_suffix}"
        })
        
        # Try each method
        for i, method in enumerate(methods, 1):
            M_UI.info(f"Trying method {i}: {method['name']}")
            M_UI.info(f"Command: {method['cmd']}")
            
            stdout, stderr, code = M_Shell.exec(method['cmd'])
            
            if code == 0:
                M_UI.success(f"✓ Success with method: {method['name']}")
                return True
            else:
                M_UI.info(f"✗ Method {i} failed (code: {code})")
                if stderr:
                    M_UI.info(f"Error: {stderr[:100]}")
        
        M_UI.error(f"All launch methods failed for {package}")
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
            "events": ["startup", "crash", "restart", "shutdown"]
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
        """Send webhook notification"""
        config = M_Config.get()
        webhook = config.get("webhook", {})
        
        if not webhook.get("enabled") or not webhook.get("url"):
            return False
        
        if event not in webhook.get("events", []):
            return False
        
        data = {
            "event": event,
            "instance": instance,
            "status": status,
            "uptime": uptime,
            "timestamp": datetime.now().isoformat(),
            "hwid": M_Auth.get_hwid()
        }
        
        try:
            response = requests.post(
                webhook["url"],
                json=data,
                timeout=10
            )
            
            if response.status_code == 200:
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
    def launch_all(start_index: int = 1) -> bool:
        """Launch all enabled instances with dashboard countdown"""
        config = M_Config.get()
        packages = config.get("packages", [])
        place_id = config.get("place_id")
        
        if not place_id:
            M_UI.error("No Place ID configured. Run configuration wizard first.")
            return False
        
        # Filter enabled packages
        enabled_packages = [p for p in packages if p.get("enabled")]
        total_packages = len(enabled_packages)
        
        if total_packages == 0:
            M_UI.error("No enabled packages to launch")
            return False
        
        interval = config.get("launch_interval", 120)
        
        # PRE-LAUNCH COUNTDOWN DASHBOARD
        M_UI.clear()
        print(M_UI.color('cyan', "╔══════════════════════════════════════════════════════════╗"))
        print(M_UI.color('cyan', "║           NOKA LAUNCH SEQUENCE - PREPARING               ║"))
        print(M_UI.color('cyan', "╚══════════════════════════════════════════════════════════╝"))
        print()
        print(f"Total instances to launch: {total_packages}")
        print(f"Place ID: {place_id}")
        print(f"Cooldown between launches: {interval}s")
        print()
        print("Layout preview:")
        
        # Show layout preview
        for i in range(1, total_packages + 1):
            pkg = enabled_packages[i - 1]
            bounds = M_Shell.get_window_bounds(i, total_packages)
            print(f"  [{i}] {pkg.get('nickname', pkg['id']):15s} -> Position {bounds}")
        
        print()
        print(M_UI.color('yellow', f"Starting in {interval} seconds..."))
        print(M_UI.color('cyan', "Press Ctrl+C to cancel"))
        print()
        
        # Countdown with dashboard
        for i in range(interval, 0, -1):
            mins, secs = divmod(i, 60)
            timer = f"{mins:02d}:{secs:02d}"
            print(f"\r⏱️  Launching in: {M_UI.color('cyan', timer)}  ", end='', flush=True)
            time.sleep(1)
        print("\r🚀 Launch sequence starting!                ")
        print()
        time.sleep(1)
        
        # LAUNCH SEQUENCE WITH LIVE DASHBOARD
        for idx, pkg in enumerate(enabled_packages[start_index - 1:], start_index):
            M_Monitor.instances[pkg["id"]] = {
                "start_time": time.time(),
                "restarts": 0,
                "paused": False
            }
            
            # Auto-calculate bounds based on position and total
            bounds = M_Shell.get_window_bounds(idx, total_packages)
            
            # Clear and show launch dashboard
            M_UI.clear()
            print(M_UI.color('cyan', "╔══════════════════════════════════════════════════════════╗"))
            print(M_UI.color('cyan', f"║           LAUNCHING INSTANCE {idx}/{total_packages}                      ║"))
            print(M_UI.color('cyan', "╚══════════════════════════════════════════════════════════╝"))
            print()
            
            # Show all instances status
            print("Instance Status:")
            print("-" * 50)
            for i, p in enumerate(enabled_packages, 1):
                status = "🔄 LAUNCHING" if i == idx else ("✅ DONE" if i < idx else "⏳ WAITING")
                if i == idx:
                    print(f"  {M_UI.color('cyan', f'[{i}]')} {p.get('nickname', p['id']):20s} {M_UI.color('cyan', status)}")
                elif i < idx:
                    print(f"  [{i}] {p.get('nickname', p['id']):20s} {M_UI.color('green', status)}")
                else:
                    print(f"  [{i}] {p.get('nickname', p['id']):20s} {M_UI.color('yellow', status)}")
            print("-" * 50)
            print()
            
            # Launch current instance
            print(f"📦 Package: {pkg['id']}")
            print(f"📍 Position: {bounds}")
            print(f"🎯 Place ID: {place_id}")
            print()
            
            print(f"[{idx}/{total_packages}] Launching {pkg.get('nickname', pkg['id'])}...")
            M_Shell.kill_app(pkg["id"])
            time.sleep(1)
            
            success = M_Shell.launch_app(pkg["id"], place_id, bounds)
            
            if success:
                M_UI.success(f"✓ Launched {pkg.get('nickname', pkg['id'])}")
            else:
                M_UI.error(f"✗ Failed to launch {pkg.get('nickname', pkg['id'])}")
            
            # Wait between launches (except for the last one)
            current_pos = idx - start_index + 1
            remaining = total_packages - current_pos
            if remaining > 0 and interval > 0:
                print()
                print(M_UI.color('yellow', f"Waiting {interval}s before next launch..."))
                print(f"({remaining} instance{'s' if remaining > 1 else ''} remaining)")
                print()
                
                for i in range(interval, 0, -1):
                    mins, secs = divmod(i, 60)
                    timer = f"{mins:02d}:{secs:02d}"
                    print(f"\r⏱️  Next launch in: {M_UI.color('cyan', timer)}  ", end='', flush=True)
                    time.sleep(1)
                print("\r" + " " * 40 + "\r", end='')
        
        # Final summary
        M_UI.clear()
        print(M_UI.color('green', "╔══════════════════════════════════════════════════════════╗"))
        print(M_UI.color('green', "║           ALL INSTANCES LAUNCHED SUCCESSFULLY!           ║"))
        print(M_UI.color('green', "╚══════════════════════════════════════════════════════════╝"))
        print()
        print(f"Total launched: {total_packages}")
        print(f"Starting monitoring...")
        time.sleep(2)
        
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
    def restart_instance(pkg: Dict):
        """Restart specific instance"""
        place_id = M_Config.get("place_id")
        M_Shell.kill_app(pkg["id"])
        time.sleep(2)
        M_Shell.launch_app(pkg["id"], place_id)
        
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
            M_Monitor.restart_instance(pkg)
    
    @staticmethod
    def format_uptime(seconds: int) -> str:
        """Format uptime as HH:MM:SS"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    @staticmethod
    def check_instance_status(pkg: Dict) -> Dict:
        """Check if instance is still running"""
        # Use root if available for better process detection
        if M_Shell.has_root():
            stdout, stderr, code = M_Shell.exec(f"su -c 'pidof {pkg['id']}'")
        else:
            stdout, stderr, code = M_Shell.exec(f"pidof {pkg['id']}")
        
        if code == 0 and stdout.strip():
            # Process exists
            uptime = 0
            if pkg["id"] in M_Monitor.instances:
                uptime = int(time.time() - M_Monitor.instances[pkg["id"]]["start_time"])
            
            return {
                "status": "alive",
                "uptime": uptime
            }
        else:
            # Process not found
            return {
                "status": "crashed",
                "uptime": 0
            }

# =============================================================================
# MODULE: M_Dashboard (Live Dashboard)
# =============================================================================
class M_Dashboard:
    """Live monitoring dashboard"""
    
    @staticmethod
    def render():
        """Render dashboard display - simplified to avoid corruption with floating windows"""
        # Move cursor to top instead of full clear (reduces flicker)
        print('\033[H', end='', flush=True)
        
        # Simple header without banner (prevents corruption)
        print(M_UI.color('cyan', "═" * 58))
        print(M_UI.color('cyan', "         NOKA MONITOR - Press Q to stop, R to restart"))
        print(M_UI.color('cyan', "═" * 58))
        
        packages = M_Config.get("packages", [])
        count = 0
        
        print()
        print(f"{'#':<4} {'Package':<18} {'Status':<12} {'Uptime':<10}")
        print("-" * 58)
        
        for pkg in packages:
            if not pkg.get("enabled"):
                continue
            
            count += 1
            status = M_Monitor.check_instance_status(pkg)
            
            # Format status
            if status["status"] == "alive":
                status_display = M_UI.color('green', '● Live')
            elif status["status"] == "slow":
                status_display = M_UI.color('yellow', '◐ Slow')
            else:
                status_display = M_UI.color('red', '❌ Crash')
            
            # Format uptime
            uptime_str = M_Monitor.format_uptime(status["uptime"])
            
            # Package name (truncate)
            name = pkg.get("nickname", pkg["id"])
            if len(name) > 15:
                name = name[:12] + "..."
            
            # Print row (simple format)
            row = f"{count:<4} {name:<18} {status_display:<12} {uptime_str:<10}"
            print(row)
        
        if count == 0:
            print("     No instances running")
        
        print("-" * 58)
        
        # Footer info
        if M_Monitor.start_time:
            total_uptime = M_Monitor.format_uptime(int(time.time() - M_Monitor.start_time))
            print(f"\nTotal uptime: {total_uptime}  |  Restarts: {M_Monitor.total_restarts}")
        
        print("\n[Controls: Q=Quit  R=Restart All  Space=Pause]")
    
    @staticmethod
    def handle_input():
        """Handle dashboard input"""
        try:
            # Non-blocking input check
            import select
            if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                char = sys.stdin.read(1).lower()
                return char
        except:
            pass
        return None
    
    @staticmethod
    def start():
        """Start dashboard monitoring"""
        M_Monitor.running = True
        
        # Show warning about floating windows
        M_UI.clear()
        print(M_UI.color('yellow', "⚠ NOTE: Floating windows may cause display glitches"))
        print(M_UI.color('yellow', "   This is normal - the monitor still works in background"))
        print()
        print("Press Enter to continue...")
        try:
            input()
        except:
            pass
        
        # Launch instances
        if not M_Monitor.launch_all():
            M_UI.error("Failed to launch instances")
            return
        
        # Monitoring loop
        last_check = 0
        last_auth_check = time.time()
        
        # Set up stdin for non-blocking input
        old_settings = None
        try:
            import tty
            import termios
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())
        except:
            pass
        
        try:
            while M_Monitor.running:
                current_time = time.time()
                
                # Periodic license check (every 5 minutes)
                if current_time - last_auth_check >= 300:
                    valid, msg = M_Auth.check_license()
                    if not valid:
                        M_UI.error(f"License validation failed: {msg}")
                        M_UI.error("NOKA will now exit. Please reactivate.")
                        M_Monitor.running = False
                        M_Monitor.stop_all()
                        break
                    last_auth_check = current_time
                
                # Render dashboard
                M_Dashboard.render()
                
                # Check for input
                char = M_Dashboard.handle_input()
                if char:
                    if char == 'q':
                        break
                    elif char == 'r':
                        M_UI.info("Restarting all instances...")
                        M_Monitor.stop_all()
                        time.sleep(2)
                        M_Monitor.launch_all()
                    elif char == ' ':
                        # Pause/resume
                        for pkg_id in M_Monitor.instances:
                            M_Monitor.instances[pkg_id]["paused"] = not M_Monitor.instances[pkg_id].get("paused", False)
                
                # Check instance status
                if current_time - last_check >= 10:  # Check every 10 seconds
                    packages = M_Config.get("packages", [])
                    for pkg in packages:
                        if pkg.get("enabled") and not M_Monitor.instances.get(pkg["id"], {}).get("paused", False):
                            status = M_Monitor.check_instance_status(pkg)
                            if status["status"] == "crashed":
                                M_Monitor.handle_crashed(pkg)
                    last_check = current_time
                
                time.sleep(1)
        
        finally:
            # Restore terminal settings
            if old_settings:
                try:
                    import termios
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                except:
                    pass
        
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
            
            # Check for root access (common locations)
            su_paths = ["/system/bin/su", "/system/xbin/su", "/sbin/su", "/su/bin/su"]
            has_root = False
            su_path = "su"
            
            for path in su_paths:
                stdout, _, code = M_Shell.exec(f"test -f {path} && echo exists")
                if code == 0 and "exists" in stdout:
                    has_root = True
                    su_path = path
                    break
            
            if not has_root:
                # Try which as fallback
                root_stdout, _, root_code = M_Shell.exec("which su 2>/dev/null")
                if root_code == 0 and root_stdout.strip():
                    has_root = True
                    su_path = "su"
            
            if has_root:
                print("[INFO] Root detected, using elevated permissions...")
                # Get all packages then filter in Python (avoid pipe issues)
                stdout, stderr, code = M_Shell.exec(f"{su_path} -c 'pm list packages'")
                if code == 0 and stdout:
                    # Filter for roblox packages in Python
                    lines = [line for line in stdout.split('\n') if 'roblox' in line.lower()]
                    stdout = '\n'.join(lines)
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
                for line in stdout.strip().split('\n'):
                    if 'package:' in line:
                        pkg = line.replace('package:', '').strip()
                        nickname = pkg.replace('com.roblox.client', 'Roblox').replace('.', ' ').title()
                        packages.append({
                            "id": pkg,
                            "nickname": nickname,
                            "enabled": True
                        })
                        print(f"  Found: {pkg}")
                
                if not packages:
                    print("No Roblox packages found. Please install Roblox from Play Store.")
                    M_UI.pause()
                    return
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
        
        # Get nicknames
        for i, pkg in enumerate(packages):
            print(f"\nNickname for {pkg['id']}:")
            nickname = M_UI.prompt(f"Name [default: {pkg['nickname']}]:")
            if nickname:
                packages[i]["nickname"] = nickname
        
        # Step 2: Place ID
        M_UI.wizard_step(2, total_steps, "Game Configuration")
        print("Enter your Roblox game URL or Place ID:")
        print("Examples:")
        print("  - https://www.roblox.com/games/1234567890/Game-Name")
        print("  - 1234567890 (just the numbers)")
        print()
        
        url = M_UI.prompt("URL or Place ID:")
        
        # Extract place ID from URL
        place_id = ""
        if url.isdigit():
            place_id = url
        elif "roblox.com/games/" in url:
            place_id = url.split("/games/")[1].split("/")[0]
        
        if place_id:
            print(f"\n✓ Place ID: {place_id}")
            M_Config.set("place_id", place_id)
            M_Config.set("game_url", url)
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
            M_Config.set("webhook", {
                "enabled": True,
                "url": webhook_url,
                "events": ["startup", "crash", "restart", "shutdown"]
            })
            print("\n✓ Webhook configured")
        else:
            M_Config.set("webhook", {
                "enabled": False,
                "url": "",
                "events": ["startup", "crash", "restart", "shutdown"]
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
        print(f"  - Place ID: {place_id}")
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
            print()
            print("1) Change webhook URL")
            print("2) Toggle enabled/disabled")
            print("3) Test webhook")
            print("4) View webhook history")
            print("5) Clear webhook")
            print("6) Back")
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
                print("Sending test webhook...")
                ok = M_Webhook.send("test", "Test Instance", "Testing", "00:00:00")
                if ok:
                    M_UI.success("Test sent successfully")
                else:
                    M_UI.error("Test failed - check webhook URL")
                M_UI.pause()
            elif choice == "4":
                print("\nWebhook History (last 10):")
                for entry in M_Webhook.history[-10:]:
                    ts = entry.get("timestamp", "unknown")
                    status = entry.get("status", "unknown")
                    event = entry.get("event", "unknown")
                    print(f"  [{ts}] {event}: {status}")
                M_UI.pause()
            elif choice == "5":
                if M_UI.confirm("Clear webhook URL?"):
                    webhook["url"] = ""
                    webhook["enabled"] = False
                    M_Config.set("webhook", webhook)
                    M_UI.success("Webhook cleared")
                M_UI.pause()
            elif choice == "6":
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
    M_Monitor.stop_all()
    sys.exit(0)

# =============================================================================
# MAIN FUNCTION
# =============================================================================
def main():
    """Main entry point"""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize modules
    M_Log.init()
    M_Config.load()
    M_Webhook.load_history()
    
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

if __name__ == "__main__":
    main()
