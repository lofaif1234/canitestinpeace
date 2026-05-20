#!/usr/bin/env lua
--[[
================================================================================
NOKA.lua — Advanced Roblox Instance Manager for Termux v2.0
================================================================================

SETUP INSTRUCTIONS FOR TERMUX:
1. Install Termux from F-Droid (not Play Store version)
2. Run: pkg update && pkg install lua54 curl netcat-openbsd
3. Place this file in ~/NOKA.lua
4. Make executable: chmod +x ~/NOKA.lua
5. Run: lua ~/NOKA.lua

FEATURES:
- Auto-detect and manage multiple Roblox app instances
- Live dashboard with ANSI in-place updates
- Crash detection via heartbeat system
- Discord webhook notifications
- Scheduled automation rules
- Full configuration wizard

HEARTBEAT SYSTEM:
This script spawns a netcat listener on localhost:25565. Inject the companion
NOKA_Heartbeat.luau script into Roblox via your executor to enable monitoring.

================================================================================
--]]

-- =============================================================================
-- INLINE JSON LIBRARY (pure Lua, zero dependencies)
-- =============================================================================
local json = {}

local function encode_string(s)
    return string.format("%q", s)
end

local function is_array(t)
    local max = 0
    local count = 0
    for k, v in pairs(t) do
        if type(k) ~= "number" then return false end
        if k < 1 then return false end
        if k > max then max = k end
        count = count + 1
    end
    return max == count
end

local encode

encode = function(val, indent)
    indent = indent or 0
    local t = type(val)
    if t == "nil" then
        return "null"
    elseif t == "boolean" then
        return val and "true" or "false"
    elseif t == "number" then
        return tostring(val)
    elseif t == "string" then
        return encode_string(val)
    elseif t == "table" then
        local items = {}
        local indent_str = string.rep("  ", indent + 1)
        local close_str = string.rep("  ", indent)
        if is_array(val) then
            for i, v in ipairs(val) do
                table.insert(items, encode(v, indent + 1))
            end
            return "[\n" .. indent_str .. table.concat(items, ",\n" .. indent_str) .. "\n" .. close_str .. "]"
        else
            for k, v in pairs(val) do
                table.insert(items, encode_string(k) .. ": " .. encode(v, indent + 1))
            end
            return "{\n" .. indent_str .. table.concat(items, ",\n" .. indent_str) .. "\n" .. close_str .. "}"
        end
    else
        return "null"
    end
end

json.encode = encode

local function decode(s)
    -- Minimal JSON parser for the config format we use
    -- This handles simple structures, not full JSON spec
    local result, err = load("return " .. s, nil, nil, {})
    if result then
        local ok, val = pcall(result)
        if ok then
            -- Convert to numbers where appropriate
            local function convert_numbers(t)
                if type(t) ~= "table" then return t end
                for k, v in pairs(t) do
                    if type(v) == "table" then
                        convert_numbers(v)
                    elseif type(v) == "string" and tonumber(v) then
                        if not (k == "url" or k:find("id") or k:find("name")) then
                            t[k] = tonumber(v)
                        end
                    end
                end
                return t
            end
            return convert_numbers(val)
        end
    end
    return nil, err
end

json.decode = decode

-- =============================================================================
-- MODULE: M_Log
-- =============================================================================
local M_Log = {}
M_Log.log_path = os.getenv("HOME") .. "/NOKA/noka.log"
M_Log.max_lines = 1000

function M_Log.init()
    local dir = os.getenv("HOME") .. "/NOKA"
    os.execute("mkdir -p " .. dir .. "/heartbeat")
    os.execute("mkdir -p " .. dir .. "/screenshots")
    os.execute("mkdir -p " .. dir .. "/profiles")
end

function M_Log.write(level, msg, instance)
    local timestamp = os.date("%Y-%m-%d %H:%M:%S")
    local instance_tag = instance and (" [" .. instance .. "]") or ""
    local line = string.format("[%s] [%s]%s %s", timestamp, level:upper(), instance_tag, msg)
    
    -- Append to log file
    local f = io.open(M_Log.log_path, "a")
    if f then
        f:write(line .. "\n")
        f:close()
    end
end

function M_Log.tail(n)
    n = n or 50
    local f = io.popen("tail -n " .. n .. " " .. M_Log.log_path .. " 2>/dev/null")
    if f then
        local content = f:read("*a")
        f:close()
        return content
    end
    return "No logs available"
end

function M_Log.clear()
    os.remove(M_Log.log_path)
end

-- =============================================================================
-- MODULE: M_Shell
-- =============================================================================
local M_Shell = {}

function M_Shell.sanitize(input)
    -- Remove shell metacharacters
    return input:gsub("[;|&$`\\\"'<>(){}[]]", "")
end

function M_Shell.exec(cmd, timeout)
    timeout = timeout or 30
    local stdout_file = os.tmpname()
    local stderr_file = os.tmpname()
    
    -- Execute with timeout using a subshell
    local full_cmd = string.format("timeout %d %s > %s 2> %s; echo $? > %s.exit",
        timeout, cmd, stdout_file, stderr_file, stdout_file)
    
    os.execute(full_cmd)
    
    -- Read exit code
    local exit_f = io.open(stdout_file .. ".exit", "r")
    local exit_code = 1
    if exit_f then
        exit_code = tonumber(exit_f:read("*l")) or 1
        exit_f:close()
    end
    
    -- Read stdout
    local stdout = ""
    local f = io.open(stdout_file, "r")
    if f then
        stdout = f:read("*a") or ""
        f:close()
    end
    
    -- Read stderr
    local stderr = ""
    local f2 = io.open(stderr_file, "r")
    if f2 then
        stderr = f2:read("*a") or ""
        f2:close()
    end
    
    -- Cleanup
    os.remove(stdout_file)
    os.remove(stdout_file .. ".exit")
    os.remove(stderr_file)
    
    return stdout, stderr, exit_code
end

function M_Shell.check_tool(tool)
    local _, _, code = M_Shell.exec("which " .. tool)
    return code == 0
end

-- =============================================================================
-- ROOT MODULE (requires M_Shell.exec to be defined above)
-- =============================================================================
local ROOT = {}
ROOT._available = nil

function ROOT.check()
    if ROOT._available ~= nil then return ROOT._available end
    local f = io.popen("su -c 'echo ROOT_OK' 2>/dev/null")
    local result = ""
    if f then
        result = f:read("*l") or ""
        f:close()
    end
    ROOT._available = (result:find("ROOT_OK") ~= nil)
    return ROOT._available
end

function ROOT.exec(cmd, timeout)
    local su_cmd = string.format("su -c %q", cmd)
    return M_Shell.exec(su_cmd, timeout or 30)
end

function M_Shell.get_package_list()
    local stdout, _, code = ROOT.exec("pm list packages | grep -E '^package:com\\.roblo'")
    if code == 0 then
        local packages = {}
        for line in stdout:gmatch("package:([^\n]+)") do
            table.insert(packages, line)
        end
        return packages
    end
    return {}
end

function M_Shell.get_all_game_clients()
    local stdout, _, code = ROOT.exec("pm list packages | grep -E '(roblo|minecraft)'")
    if code == 0 then
        local packages = {}
        for line in stdout:gmatch("package:([^\n]+)") do
            table.insert(packages, line)
        end
        return packages
    end
    return {}
end

function M_Shell.validate_package(pkg)
    local _, _, code = M_Shell.exec("pm path " .. pkg)
    return code == 0
end

function M_Shell.kill_app(pkg)
    M_Shell.exec("am force-stop " .. pkg)
    M_Log.write("info", "Killed " .. pkg)
end

function M_Shell.launch_app(pkg, place_id)
    local url = string.format("roblox://placeId=%s", place_id)
    local cmd = string.format("am start -a android.intent.action.VIEW -d '%s' %s", url, pkg)
    M_Shell.exec(cmd)
    M_Log.write("info", "Launched " .. pkg .. " with placeId " .. place_id, pkg)
end

function M_Shell.take_screenshot(path)
    M_Shell.exec("screencap -p " .. path)
end

-- =============================================================================
-- MODULE: M_Config
-- =============================================================================
local M_Config = {}
M_Config.path = os.getenv("HOME") .. "/NOKA/config.json"
M_Config.data = nil

M_Config.defaults = {
    version = "2.0",
    packages = {},
    game_url = "",
    fallback_url = "",
    place_id = "",
    launch_interval = 120,
    launch_interval_random = false,
    launch_interval_min = 90,
    launch_interval_max = 150,
    restart_policy = "crash_only",
    restart_interval_minutes = 60,
    restart_action = "full_restart",
    crash_sensitivity = "standard",
    heartbeat_timeout = 30,
    webhook = {
        enabled = false,
        url = "",
        interval = 300,
        events = {"startup", "crash", "restart"}
    },
    screenshots = {
        enabled = false,
        interval_minutes = 10
    },
    logging = {
        verbosity = "standard",
        max_lines = 1000
    },
    scheduler = {},
    created_at = "",
    updated_at = ""
}

function M_Config.load()
    local f = io.open(M_Config.path, "r")
    if f then
        local content = f:read("*a")
        f:close()
        local data, err = json.decode(content)
        if data then
            M_Config.data = data
            -- Merge with defaults for any missing fields
            for k, v in pairs(M_Config.defaults) do
                if M_Config.data[k] == nil then
                    M_Config.data[k] = v
                end
            end
            return true
        else
            M_Log.write("error", "Failed to parse config: " .. tostring(err))
        end
    end
    M_Config.data = {}
    for k, v in pairs(M_Config.defaults) do
        M_Config.data[k] = v
    end
    return false
end

function M_Config.save()
    M_Config.data.updated_at = os.date("%Y-%m-%d %H:%M:%S")
    if M_Config.data.created_at == "" then
        M_Config.data.created_at = M_Config.data.updated_at
    end
    local content = json.encode(M_Config.data)
    local f = io.open(M_Config.path, "w")
    if f then
        f:write(content)
        f:close()
        return true
    end
    return false
end

function M_Config.get(key)
    return M_Config.data and M_Config.data[key] or M_Config.defaults[key]
end

function M_Config.set(key, value)
    if M_Config.data then
        M_Config.data[key] = value
    end
end

function M_Config.extract_place_id(url)
    if not url then return nil end
    -- Check if it's already a number
    if tonumber(url) then return url end
    -- Extract from Roblox URL
    local place_id = url:match("roblox%.com/games/(%d+)")
    if place_id then return place_id end
    -- Try other patterns
    place_id = url:match("placeId=(%d+)")
    if place_id then return place_id end
    return nil
end

function M_Config.validate_url(url)
    if not url then return false end
    if tonumber(url) then return true end
    if url:match("^https?://www%.roblox%.com/games/%d+") then return true end
    if url:match("roblox://placeId=%d+") then return true end
    return false
end

-- =============================================================================
-- MODULE: M_UI
-- =============================================================================
local M_UI = {}

-- ANSI color codes
M_UI.colors = {
    reset = "\27[0m",
    bold = "\27[1m",
    cyan = "\27[36m",
    green = "\27[32m",
    yellow = "\27[33m",
    red = "\27[31m",
    magenta = "\27[35m",
    white = "\27[37m"
}

function M_UI.clear()
    io.write("\27[2J\27[H")
    io.flush()
end

function M_UI.set_cursor(row, col)
    io.write(string.format("\27[%d;%dH", row, col))
    io.flush()
end

function M_UI.color(name, text)
    return M_UI.colors[name] .. text .. M_UI.colors.reset
end

function M_UI.banner()
    local lines = {
        "███╗   ██╗ ██████╗ ██╗  ██╗ █████╗ ",
        "████╗  ██║██╔═══██╗██║ ██╔╝██╔══██╗",
        "██╔██╗ ██║██║   ██║█████╔╝ ███████║",
        "██║╚██╗██║██║   ██║██╔═██╗ ██╔══██║",
        "██║ ╚████║╚██████╔╝██║  ██╗██║  ██║",
        "╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝",
        "     Roblox Instance Manager v2.0"
    }
    
    for i = 1, 6 do
        print(M_UI.color("cyan", M_UI.color("bold", lines[i])))
    end
    print(M_UI.color("magenta", lines[7]))
    print()
end

function M_UI.status_bar()
    local packages = M_Config.get("packages") or {}
    local active_count = 0
    for _, pkg in ipairs(packages) do
        if pkg.enabled then active_count = active_count + 1 end
    end
    
    local webhook = M_Config.get("webhook") or {enabled = false}
    local webhook_status = webhook.enabled and M_UI.color("green", "ON") or M_UI.color("red", "OFF")
    
    local config_status = (io.open(M_Config.path, "r") ~= nil) and 
        M_UI.color("green", "loaded") or M_UI.color("yellow", "missing")
    
    local line = string.format("[Instances: %d active]  [Webhook: %s]  [Config: %s]",
        active_count, webhook_status, config_status)
    print(line)
    print()
end

function M_UI.header()
    M_UI.clear()
    M_UI.banner()
    M_UI.status_bar()
end

-- TTY handle: reopen /dev/tty so input always comes from the real terminal
-- even when the script is piped via: curl ... | luajit -
local _tty = io.open("/dev/tty", "r+")
if not _tty then
    _tty = io.stdin
end

function M_UI.read_line()
    io.flush()
    local line = _tty:read("*l")
    return line
end

function M_UI.main_menu()
    M_UI.header()
    print(M_UI.color("bold", M_UI.color("cyan", "=== MAIN MENU ===")))
    print()
    print("1) First-time configuration wizard")
    print("2) Start auto-rejoin / monitoring")
    print("3) Webhook & notifications")
    print("4) Update game URL")
    print("5) Instance profiles")
    print("6) Diagnostics & logs")
    print("7) Scheduler")
    print("8) Export / Import config")
    print("9) About & help")
    print("0) Exit")
    print()
    io.write("Enter choice: ")
    local choice = M_UI.read_line()
    return choice or ""
end

function M_UI.prompt(text)
    io.write(text .. " ")
    return M_UI.read_line() or ""
end

function M_UI.confirm(text)
    local resp = M_UI.prompt(text .. " [y/N]: ")
    return resp:lower() == "y"
end

function M_UI.show_table(headers, rows)
    local col_widths = {}
    for i, h in ipairs(headers) do
        col_widths[i] = #h
    end
    
    for _, row in ipairs(rows) do
        for i, cell in ipairs(row) do
            if #tostring(cell) > (col_widths[i] or 0) then
                col_widths[i] = #tostring(cell)
            end
        end
    end
    
    -- Print headers
    local header_line = ""
    for i, h in ipairs(headers) do
        header_line = header_line .. string.format(" %%-%ds ", col_widths[i] + 2):format(h)
    end
    print(M_UI.color("bold", header_line))
    
    -- Separator
    local sep = ""
    for i = 1, #headers do
        sep = sep .. string.rep("-", col_widths[i] + 4)
    end
    print(sep)
    
    -- Rows
    for _, row in ipairs(rows) do
        local line = ""
        for i, cell in ipairs(row) do
            line = line .. string.format(" %%-%ds ", col_widths[i] + 2):format(tostring(cell))
        end
        print(line)
    end
end

function M_UI.wizard_step(step_num, total, title)
    M_UI.header()
    print(M_UI.color("cyan", string.format("Step %d of %d: %s", step_num, total, title)))
    print(string.rep("-", 40))
    print()
end

function M_UI.success(msg)
    print(M_UI.color("green", "[OK] " .. msg))
end

function M_UI.error(msg)
    print(M_UI.color("red", "[ERROR] " .. msg))
end

function M_UI.warning(msg)
    print(M_UI.color("yellow", "[WARN] " .. msg))
end

function M_UI.pause()
    M_UI.prompt("\nPress Enter to continue...")
end

-- =============================================================================
-- MODULE: M_Webhook
-- =============================================================================
local M_Webhook = {}
M_Webhook.history = {}
M_Webhook.history_file = os.getenv("HOME") .. "/NOKA/webhook_history.json"

function M_Webhook.load_history()
    local f = io.open(M_Webhook.history_file, "r")
    if f then
        local content = f:read("*a")
        f:close()
        local data = json.decode(content)
        if data and type(data) == "table" then
            M_Webhook.history = data
        end
    end
end

function M_Webhook.save_history()
    local f = io.open(M_Webhook.history_file, "w")
    if f then
        f:write(json.encode(M_Webhook.history))
        f:close()
    end
end

function M_Webhook.add_history(event, status, timestamp)
    table.insert(M_Webhook.history, 1, {
        event = event,
        status = status,
        time = timestamp or os.date("%Y-%m-%d %H:%M:%S")
    })
    -- Keep only last 20
    while #M_Webhook.history > 20 do
        table.remove(M_Webhook.history)
    end
    M_Webhook.save_history()
end

function M_Webhook.send(event, instance, status, uptime, screenshot_path)
    local config = M_Config.get("webhook")
    if not config or not config.enabled or config.url == "" then
        return false, "Webhook disabled"
    end
    
    -- Check if this event type should be sent
    local events = config.events or {}
    local should_send = false
    for _, e in ipairs(events) do
        if e == "all" or e == event then
            should_send = true
            break
        end
    end
    if not should_send then
        return false, "Event type not enabled"
    end
    
    -- Determine color
    local colors = {startup = 3447003, crash = 15158332, restart = 15844367, heartbeat = 3066993}
    local color = colors[event] or 0
    
    -- Build embed
    local embed = {
        title = "NOKA Status Report",
        color = color,
        fields = {
            {name = "Instance", value = instance or "Unknown", inline = true},
            {name = "Event", value = event, inline = true},
            {name = "Status", value = status or "N/A", inline = true},
            {name = "Uptime", value = uptime or "--:--:--", inline = true},
            {name = "Time", value = os.date("%Y-%m-%d %H:%M:%S"), inline = true}
        },
        footer = {text = "NOKA v2.0"}
    }
    
    local payload = json.encode({embeds = {embed}})
    
    -- Send via curl
    local cmd = string.format("curl -s -X POST -H 'Content-Type: application/json' -d '%s' '%s'",
        payload:gsub("'", "'\"'\"'"), config.url)
    
    local stdout, stderr, code = M_Shell.exec(cmd, 10)
    
    if code == 0 then
        M_Webhook.add_history(event, "success")
        M_Log.write("info", "Webhook sent: " .. event)
        return true
    else
        M_Webhook.add_history(event, "failed")
        M_Log.write("error", "Webhook failed: " .. event .. " - " .. stderr)
        return false, stderr
    end
end

function M_Webhook.test()
    return M_Webhook.send("startup", "Test Instance", "Testing", "00:00:00")
end

function M_Webhook.mask_url(url)
    if not url or #url < 35 then return url or "" end
    return url:sub(1, 30) .. "***"
end

-- =============================================================================
-- MODULE: M_Monitor
-- =============================================================================
local M_Monitor = {}
M_Monitor.instances = {}
M_Monitor.running = false
M_Monitor.start_time = nil
M_Monitor.total_restarts = 0
M_Monitor.webhooks_sent = 0

function M_Monitor.get_heartbeat_path(pkg_id)
    return os.getenv("HOME") .. "/NOKA/heartbeat/" .. pkg_id:gsub("%.", "_") .. ".hb"
end

function M_Monitor.read_heartbeat(pkg_id)
    local path = M_Monitor.get_heartbeat_path(pkg_id)
    local f = io.open(path, "r")
    if f then
        local content = f:read("*a")
        f:close()
        local data = json.decode(content)
        if data and data.ts then
            return data.ts, data.status or "alive"
        end
    end
    return nil, nil
end

function M_Monitor.write_heartbeat(pkg_id, data)
    local path = M_Monitor.get_heartbeat_path(pkg_id)
    local f = io.open(path, "w")
    if f then
        f:write(json.encode(data))
        f:close()
    end
end

function M_Monitor.check_heartbeat(pkg_id)
    local ts, status = M_Monitor.read_heartbeat(pkg_id)
    if not ts then
        return "missing", nil
    end
    
    local timeout = M_Config.get("heartbeat_timeout") or 30
    local now = os.time()
    local elapsed = now - ts
    
    if elapsed > timeout * 2 then
        return "crashed", elapsed
    elseif elapsed > timeout then
        return "slow", elapsed
    else
        return "alive", elapsed
    end
end

function M_Monitor.format_uptime(seconds)
    if not seconds or seconds < 0 then return "--:--:--" end
    local h = math.floor(seconds / 3600)
    local m = math.floor((seconds % 3600) / 60)
    local s = seconds % 60
    return string.format("%02d:%02d:%02d", h, m, s)
end

function M_Monitor.get_instance_status(pkg)
    local status, elapsed = M_Monitor.check_heartbeat(pkg.id)
    local symbol = "?"
    local label = "Unknown"
    
    local states = {
        alive = {symbol = "LIVE", label = "Live"},
        launching = {symbol = "LAUNCH", label = "Launching"},
        slow = {symbol = "SLOW", label = "Slow"},
        crashed = {symbol = "CRASH", label = "Crashed"},
        restarting = {symbol = "RESTART", label = "Restarting"},
        paused = {symbol = "PAUSE", label = "Paused"},
        missing = {symbol = "MISS", label = "No Signal"}
    }
    
    if states[status] then
        symbol = states[status].symbol
        label = states[status].label
    end
    
    local instance = M_Monitor.instances[pkg.id] or {}
    local uptime = 0
    if instance.start_time then
        uptime = os.time() - instance.start_time
    end
    
    return {
        pkg = pkg,
        status = status,
        status_symbol = symbol,
        status_label = label,
        uptime = uptime,
        elapsed = elapsed
    }
end

function M_Monitor.launch_all()
    local packages = M_Config.get("packages") or {}
    local place_id = M_Config.get("place_id")
    
    if not place_id or place_id == "" then
        M_UI.error("No Place ID configured. Run configuration wizard first.")
        return false
    end
    
    for _, pkg in ipairs(packages) do
        if pkg.enabled then
            M_Monitor.instances[pkg.id] = {
                start_time = os.time(),
                restarts = 0,
                paused = false
            }
            
            M_UI.info("Launching " .. pkg.nickname .. "...")
            M_Shell.kill_app(pkg.id)
            os.execute("sleep 2")
            M_Shell.launch_app(pkg.id, place_id)
            
            -- Wait interval before next launch
            local interval = M_Config.get("launch_interval") or 120
            if M_Config.get("launch_interval_random") then
                local min = M_Config.get("launch_interval_min") or 90
                local max = M_Config.get("launch_interval_max") or 150
                interval = math.random(min, max)
            end
            
            if _ < #packages then
                M_UI.info("Waiting " .. interval .. "s before next launch...")
                os.execute("sleep " .. interval)
            end
        end
    end
    
    M_Monitor.start_time = os.time()
    M_Webhook.send("startup", "All Instances", "Started", "00:00:00")
    return true
end

function M_Monitor.stop_all()
    local packages = M_Config.get("packages") or {}
    for _, pkg in ipairs(packages) do
        M_Shell.kill_app(pkg.id)
    end
    M_Monitor.running = false
    M_UI.success("All instances stopped")
end

function M_Monitor.restart_instance(pkg)
    local place_id = M_Config.get("place_id")
    M_Shell.kill_app(pkg.id)
    os.execute("sleep 2")
    M_Shell.launch_app(pkg.id, place_id)
    
    if M_Monitor.instances[pkg.id] then
        M_Monitor.instances[pkg.id].start_time = os.time()
        M_Monitor.instances[pkg.id].restarts = (M_Monitor.instances[pkg.id].restarts or 0) + 1
    end
    
    M_Monitor.total_restarts = M_Monitor.total_restarts + 1
    M_Webhook.send("restart", pkg.nickname, "Restarted", M_Monitor.format_uptime(0))
end

function M_Monitor.handle_crashed(pkg)
    M_UI.error("Crash detected: " .. pkg.nickname)
    M_Log.write("error", "Crash detected, restarting " .. pkg.id, pkg.nickname)
    
    local policy = M_Config.get("restart_policy")
    if policy == "crash_only" or policy == "scheduled" then
        M_Monitor.restart_instance(pkg)
    end
end

M_UI.info = function(msg) print(M_UI.color("cyan", "[INFO] " .. msg)) end

-- =============================================================================
-- MODULE: M_Scheduler
-- =============================================================================
local M_Scheduler = {}

function M_Scheduler.add_rule(rule_type, params)
    local scheduler = M_Config.get("scheduler") or {}
    table.insert(scheduler, {
        type = rule_type,
        params = params,
        enabled = true,
        created = os.date("%Y-%m-%d %H:%M:%S")
    })
    M_Config.set("scheduler", scheduler)
    M_Config.save()
    return true
end

function M_Scheduler.delete_rule(index)
    local scheduler = M_Config.get("scheduler") or {}
    if scheduler[index] then
        table.remove(scheduler, index)
        M_Config.set("scheduler", scheduler)
        M_Config.save()
        return true
    end
    return false
end

function M_Scheduler.list_rules()
    return M_Config.get("scheduler") or {}
end

function M_Scheduler.check_rules()
    local rules = M_Scheduler.list_rules()
    local now = os.date("%H:%M")
    local triggered = {}
    
    for i, rule in ipairs(rules) do
        if rule.enabled then
            if rule.type == "START_ALL" and rule.params.time == now then
                table.insert(triggered, rule)
            elseif rule.type == "STOP_ALL" and rule.params.time == now then
                table.insert(triggered, rule)
            elseif rule.type == "RESTART_ALL" then
                -- Check if interval elapsed
                if rule.params.last_triggered then
                    local elapsed = os.time() - rule.params.last_triggered
                    if elapsed >= (rule.params.interval or 60) * 60 then
                        table.insert(triggered, rule)
                        rule.params.last_triggered = os.time()
                    end
                else
                    rule.params.last_triggered = os.time()
                end
            elseif rule.type == "SCREENSHOT" then
                if rule.params.last_triggered then
                    local elapsed = os.time() - rule.params.last_triggered
                    if elapsed >= (rule.params.interval or 10) * 60 then
                        table.insert(triggered, rule)
                        rule.params.last_triggered = os.time()
                    end
                else
                    rule.params.last_triggered = os.time()
                end
            end
        end
    end
    
    return triggered
end

function M_Scheduler.execute_rule(rule)
    if rule.type == "START_ALL" then
        M_Monitor.launch_all()
    elseif rule.type == "STOP_ALL" then
        M_Monitor.stop_all()
    elseif rule.type == "RESTART_ALL" then
        M_Monitor.stop_all()
        os.execute("sleep 3")
        M_Monitor.launch_all()
    elseif rule.type == "SCREENSHOT" then
        local path = os.getenv("HOME") .. "/NOKA/screenshots/cap_" .. os.date("%Y%m%d_%H%M%S") .. ".png"
        M_Shell.take_screenshot(path)
    end
end

-- =============================================================================
-- LIVE DASHBOARD
-- =============================================================================
local M_Dashboard = {}

function M_Dashboard.render()
    M_UI.header()
    print(M_UI.color("bold", M_UI.color("cyan", "NOKA Live Monitor")))
    print(M_UI.color("white", "Press Q to stop, R to restart all, P to pause, S for screenshot, L for logs"))
    print()
    
    local packages = M_Config.get("packages") or {}
    local rows = {}
    
    for i, pkg in ipairs(packages) do
        if pkg.enabled then
            local status = M_Monitor.get_instance_status(pkg)
            local color = "white"
            if status.status == "alive" then color = "green"
            elseif status.status == "slow" then color = "yellow"
            elseif status.status == "crashed" or status.status == "missing" then color = "red"
            elseif status.status == "restarting" then color = "cyan"
            end
            
            table.insert(rows, {
                tostring(i),
                pkg.nickname,
                M_UI.color(color, status.status_symbol),
                M_Monitor.format_uptime(status.uptime),
                tostring(status.elapsed or "N/A")
            })
        end
    end
    
    if #rows > 0 then
        M_UI.show_table({"#", "Package", "Status", "Uptime", "Last HB"}, rows)
    else
        print("No active instances.")
    end
    
    print()
    local global_uptime = 0
    if M_Monitor.start_time then
        global_uptime = os.time() - M_Monitor.start_time
    end
    print(string.format("[Global uptime: %s]  [Total restarts: %d]  [Webhooks sent: %d]",
        M_Monitor.format_uptime(global_uptime), M_Monitor.total_restarts, M_Monitor.webhooks_sent))
end

function M_Dashboard.run_heartbeat_server()
    -- Start a background netcat listener
    local cmd = "while true; do echo '{\"status\":\"ok\"}' | nc -l -p 25565 2>/dev/null; done &"
    os.execute(cmd)
end

function M_Dashboard.start()
    M_Monitor.running = true
    M_Monitor.launch_all()
    
    -- Start heartbeat server
    M_Dashboard.run_heartbeat_server()
    
    local last_check = 0
    local last_scheduler = 0
    
    while M_Monitor.running do
        M_Dashboard.render()
        
        -- Non-blocking input check (using read with timeout)
        local cmd = "read -t 5 -n 1 key; echo $key"
        local f = io.popen(cmd)
        local key = ""
        if f then
            key = (f:read("*l") or ""):gsub("%s", "")
            f:close()
        end
        
        if key:lower() == "q" then
            M_Monitor.running = false
            M_Monitor.stop_all()
            break
        elseif key:lower() == "r" then
            M_UI.info("Restarting all instances...")
            M_Monitor.stop_all()
            os.execute("sleep 3")
            M_Monitor.launch_all()
        elseif key:lower() == "s" then
            local path = os.getenv("HOME") .. "/NOKA/screenshots/cap_" .. os.date("%Y%m%d_%H%M%S") .. ".png"
            M_Shell.take_screenshot(path)
            M_UI.success("Screenshot saved: " .. path)
            os.execute("sleep 2")
        elseif key:lower() == "l" then
            print()
            print(M_Log.tail(20))
            os.execute("sleep 3")
        elseif key:lower() == "p" then
            io.write("Instance number to pause/resume: ")
            io.flush()
            local num = tonumber(io.read())
            if num then
                local pkgs = M_Config.get("packages") or {}
                if pkgs[num] then
                    local inst = M_Monitor.instances[pkgs[num].id]
                    if inst then
                        inst.paused = not (inst.paused or false)
                        M_UI.success((inst.paused and "Paused " or "Resumed ") .. pkgs[num].nickname)
                    end
                end
            end
            os.execute("sleep 2")
        end
        
        -- Check heartbeats every 20 seconds
        local now = os.time()
        if now - last_check >= 20 then
            for _, pkg in ipairs(M_Config.get("packages") or {}) do
                if pkg.enabled then
                    local status = M_Monitor.get_instance_status(pkg)
                    if status.status == "crashed" or status.status == "missing" then
                        M_Monitor.handle_crashed(pkg)
                    elseif status.status == "slow" then
                        M_Log.write("warn", "Missed heartbeat (1/2) " .. pkg.id, pkg.nickname)
                    end
                end
            end
            last_check = now
        end
        
        -- Run scheduler every 60 seconds
        if now - last_scheduler >= 60 then
            local rules = M_Scheduler.check_rules()
            for _, rule in ipairs(rules) do
                M_Scheduler.execute_rule(rule)
            end
            last_scheduler = now
        end
    end
end

-- =============================================================================
-- MENU HANDLERS
-- =============================================================================
local MenuHandlers = {}

-- Option 1: Configuration Wizard
function MenuHandlers.config_wizard()
    local total_steps = 8
    
    -- Step 1: Package Detection
    M_UI.wizard_step(1, total_steps, "Package Detection")
    print("1) Automatic (detect Roblox packages)")
    print("2) Manual (enter package name)")
    print("3) Scan all game clients")
    local choice = M_UI.prompt("Choice:")
    
    local detected_packages = {}
    if choice == "1" then
        detected_packages = M_Shell.get_package_list()
    elseif choice == "2" then
        local pkg = M_UI.prompt("Enter exact package name (e.g., com.roblox.client):")
        if M_Shell.validate_package(pkg) then
            table.insert(detected_packages, pkg)
        else
            M_UI.error("Invalid package")
            M_UI.pause()
            return
        end
    elseif choice == "3" then
        detected_packages = M_Shell.get_all_game_clients()
    end
    
    if #detected_packages == 0 then
        M_UI.error("No packages detected")
        M_UI.pause()
        return
    end
    
    print()
    print("Detected packages:")
    for i, pkg in ipairs(detected_packages) do
        print(i .. ") " .. pkg)
    end
    M_UI.pause()
    
    -- Step 2: Package Selection
    M_UI.wizard_step(2, total_steps, "Package Selection")
    print("1) Use all detected packages")
    print("2) Select specific packages")
    local sel_choice = M_UI.prompt("Choice:")
    
    local selected = {}
    if sel_choice == "1" then
        selected = detected_packages
    else
        local nums = M_UI.prompt("Enter package numbers (comma-separated):")
        for n in nums:gmatch("%d+") do
            local idx = tonumber(n)
            if idx and detected_packages[idx] then
                table.insert(selected, detected_packages[idx])
            end
        end
    end
    
    -- Assign nicknames
    local packages = {}
    for _, pkg in ipairs(selected) do
        local nickname = M_UI.prompt("Nickname for " .. pkg .. " (default: " .. pkg .. "):")
        if nickname == "" then nickname = pkg end
        table.insert(packages, {id = pkg, nickname = nickname, enabled = true})
    end
    M_Config.set("packages", packages)
    
    -- Step 3: Game URL
    M_UI.wizard_step(3, total_steps, "Game URL")
    local url = M_UI.prompt("Enter Roblox game URL or Place ID:")
    while not M_Config.validate_url(url) do
        M_UI.error("Invalid URL format")
        url = M_UI.prompt("Enter valid Roblox URL or Place ID:")
    end
    
    local place_id = M_Config.extract_place_id(url)
    M_Config.set("game_url", url)
    M_Config.set("place_id", place_id)
    
    local has_fallback = M_UI.confirm("Set a fallback URL?")
    if has_fallback then
        local fallback = M_UI.prompt("Fallback URL:")
        M_Config.set("fallback_url", fallback)
    end
    
    -- Step 4: Webhook Setup
    M_UI.wizard_step(4, total_steps, "Webhook Setup")
    print("1) Discord webhook")
    print("2) Skip")
    local webhook_choice = M_UI.prompt("Choice:")
    
    if webhook_choice == "1" then
        local webhook_url = M_UI.prompt("Enter Discord webhook URL:")
        M_Config.set("webhook", {
            enabled = true,
            url = webhook_url,
            interval = 300,
            events = {"startup", "crash", "restart"}
        })
        M_UI.success("Webhook configured (test on save)")
    else
        M_Config.set("webhook", {enabled = false, url = "", interval = 300, events = {}})
    end
    
    -- Step 5: Launch Interval
    M_UI.wizard_step(5, total_steps, "Launch Interval")
    print("1) Custom interval (seconds)")
    print("2) Default (120 seconds)")
    print("3) Random range")
    local interval_choice = M_UI.prompt("Choice:")
    
    if interval_choice == "1" then
        local interval = tonumber(M_UI.prompt("Interval in seconds:")) or 120
        M_Config.set("launch_interval", interval)
    elseif interval_choice == "2" then
        M_Config.set("launch_interval", 120)
    elseif interval_choice == "3" then
        M_Config.set("launch_interval_random", true)
        local min = tonumber(M_UI.prompt("Minimum interval:")) or 90
        local max = tonumber(M_UI.prompt("Maximum interval:")) or 150
        M_Config.set("launch_interval_min", min)
        M_Config.set("launch_interval_max", max)
    end
    
    -- Step 6: Restart Policy
    M_UI.wizard_step(6, total_steps, "Restart Policy")
    print("1) No auto-restart")
    print("2) Restart on crash only")
    print("3) Scheduled restart")
    local restart_choice = M_UI.prompt("Choice:")
    
    local policies = {"none", "crash_only", "scheduled"}
    M_Config.set("restart_policy", policies[tonumber(restart_choice) or 2])
    
    if restart_choice == "3" then
        local interval = tonumber(M_UI.prompt("Restart interval (minutes):")) or 60
        M_Config.set("restart_interval_minutes", interval)
        print("a) Full app restart")
        print("b) Server rejoin (deep-link)")
        local action = M_UI.prompt("Action:")
        M_Config.set("restart_action", action == "b" and "deep_link" or "full_restart")
    end
    
    -- Step 7: Crash Detection
    M_UI.wizard_step(7, total_steps, "Crash Detection Sensitivity")
    print("1) Standard (30 second timeout)")
    print("2) Strict (15 second timeout)")
    print("3) Lenient (60 second timeout)")
    local sens = M_UI.prompt("Choice:")
    
    local timeouts = {standard = 30, strict = 15, lenient = 60}
    local sens_map = {standard = "standard", strict = "strict", lenient = "lenient"}
    local choice_map = {[1] = "standard", [2] = "strict", [3] = "lenient"}
    local choice_key = choice_map[tonumber(sens)] or "standard"
    
    M_Config.set("crash_sensitivity", choice_key)
    M_Config.set("heartbeat_timeout", timeouts[choice_key])
    
    -- Step 8: Screenshots & Logging
    M_UI.wizard_step(8, total_steps, "Screenshots & Logging")
    local screenshots = M_UI.confirm("Enable periodic screenshots?")
    M_Config.set("screenshots", {enabled = screenshots, interval_minutes = 10})
    if screenshots then
        local interval = tonumber(M_UI.prompt("Screenshot interval (minutes):")) or 10
        M_Config.set("screenshots", {enabled = true, interval_minutes = interval})
    end
    
    print()
    print("1) Minimal logging")
    print("2) Standard logging")
    print("3) Verbose logging")
    local log_choice = M_UI.prompt("Choice:")
    local levels = {"minimal", "standard", "verbose"}
    M_Config.set("logging", {verbosity = levels[tonumber(log_choice) or 2], max_lines = 1000})
    
    -- Save config
    M_Config.save()
    
    M_UI.header()
    M_UI.success("Configuration saved!")
    print()
    print("Summary:")
    print("- Packages: " .. #packages)
    print("- Place ID: " .. (M_Config.get("place_id") or "N/A"))
    print("- Webhook: " .. (M_Config.get("webhook").enabled and "Enabled" or "Disabled"))
    print("- Launch interval: " .. M_Config.get("launch_interval") .. "s")
    M_UI.pause()
end

-- Option 2: Start monitoring
function MenuHandlers.start_monitoring()
    M_UI.header()
    print(M_UI.color("cyan", "Starting auto-rejoin / monitoring..."))
    print()
    
    local packages = M_Config.get("packages") or {}
    if #packages == 0 then
        M_UI.error("No packages configured. Run configuration wizard first.")
        M_UI.pause()
        return
    end
    
    local place_id = M_Config.get("place_id")
    if not place_id or place_id == "" then
        M_UI.error("No Place ID configured. Run configuration wizard first.")
        M_UI.pause()
        return
    end
    
    M_Dashboard.start()
end

-- Option 3: Webhook & notifications
function MenuHandlers.webhook_menu()
    while true do
        M_UI.header()
        print(M_UI.color("cyan", "=== WEBHOOK & NOTIFICATIONS ==="))
        print()
        
        local webhook = M_Config.get("webhook") or {enabled = false, url = ""}
        print("Current webhook: " .. M_Webhook.mask_url(webhook.url))
        print("Status: " .. (webhook.enabled and "Enabled" or "Disabled"))
        print()
        print("1) Change webhook URL")
        print("2) Change heartbeat interval")
        print("3) Configure notification events")
        print("4) Send test embed now")
        print("5) View webhook send history (last 20)")
        print("6) Disable webhook")
        print("7) Back")
        print()
        
        local choice = M_UI.prompt("Choice:")
        
        if choice == "1" then
            local url = M_UI.prompt("New webhook URL:")
            webhook.url = url
            M_Config.set("webhook", webhook)
            M_Config.save()
            M_UI.success("Webhook URL updated")
            M_UI.pause()
        elseif choice == "2" then
            local interval = tonumber(M_UI.prompt("Heartbeat interval (seconds):")) or 300
            webhook.interval = interval
            M_Config.set("webhook", webhook)
            M_Config.save()
            M_UI.success("Interval updated")
            M_UI.pause()
        elseif choice == "3" then
            print("Enter events (comma-separated): startup, crash, restart, heartbeat, all")
            local events_str = M_UI.prompt("Events:")
            local events = {}
            for e in events_str:gmatch("[%w_]+") do
                table.insert(events, e)
            end
            webhook.events = events
            M_Config.set("webhook", webhook)
            M_Config.save()
            M_UI.success("Events updated")
            M_UI.pause()
        elseif choice == "4" then
            M_UI.info("Sending test webhook...")
            local ok, err = M_Webhook.test()
            if ok then
                M_UI.success("Test sent successfully")
            else
                M_UI.error("Failed: " .. tostring(err))
            end
            M_UI.pause()
        elseif choice == "5" then
            print()
            print(M_UI.color("bold", "Recent webhook history:"))
            print()
            for i, entry in ipairs(M_Webhook.history) do
                print(string.format("%d) [%s] %s - %s", i, entry.time, entry.event, entry.status))
            end
            if #M_Webhook.history == 0 then
                print("No history yet")
            end
            M_UI.pause()
        elseif choice == "6" then
            webhook.enabled = false
            M_Config.set("webhook", webhook)
            M_Config.save()
            M_UI.success("Webhook disabled")
            M_UI.pause()
        elseif choice == "7" then
            break
        end
    end
end

-- Option 4: Update game URL
function MenuHandlers.update_url()
    M_UI.header()
    print(M_UI.color("cyan", "=== UPDATE GAME URL ==="))
    print()
    print("Current URL: " .. (M_Config.get("game_url") or "None"))
    print("Current Place ID: " .. (M_Config.get("place_id") or "None"))
    print()
    
    local url = M_UI.prompt("New Roblox URL or Place ID:")
    while not M_Config.validate_url(url) do
        M_UI.error("Invalid URL format")
        url = M_UI.prompt("Enter valid URL:")
    end
    
    local place_id = M_Config.extract_place_id(url)
    M_Config.set("game_url", url)
    M_Config.set("place_id", place_id)
    
    if M_UI.confirm("Update fallback URL too?") then
        local fallback = M_UI.prompt("Fallback URL:")
        M_Config.set("fallback_url", fallback)
    end
    
    M_Config.save()
    M_UI.success("URL updated")
    M_UI.pause()
end

-- Option 5: Instance profiles
function MenuHandlers.profiles_menu()
    while true do
        M_UI.header()
        print(M_UI.color("cyan", "=== INSTANCE PROFILES ==="))
        print()
        print("1) Save current config as profile")
        print("2) Load a profile")
        print("3) List all profiles")
        print("4) Delete a profile")
        print("5) Back")
        print()
        
        local choice = M_UI.prompt("Choice:")
        
        if choice == "1" then
            local name = M_UI.prompt("Profile name:")
            if name and name ~= "" then
                local path = os.getenv("HOME") .. "/NOKA/profiles/" .. name .. ".json"
                local content = json.encode(M_Config.data)
                local f = io.open(path, "w")
                if f then
                    f:write(content)
                    f:close()
                    M_UI.success("Profile saved: " .. name)
                else
                    M_UI.error("Failed to save profile")
                end
            end
            M_UI.pause()
        elseif choice == "2" then
            local name = M_UI.prompt("Profile name to load:")
            local path = os.getenv("HOME") .. "/NOKA/profiles/" .. name .. ".json"
            local f = io.open(path, "r")
            if f then
                local content = f:read("*a")
                f:close()
                local data = json.decode(content)
                if data then
                    print()
                    print("Loading profile will replace current config. Continue?")
                    if M_UI.confirm("Load profile") then
                        M_Config.data = data
                        M_Config.save()
                        M_UI.success("Profile loaded")
                    end
                else
                    M_UI.error("Invalid profile file")
                end
            else
                M_UI.error("Profile not found")
            end
            M_UI.pause()
        elseif choice == "3" then
            print()
            print(M_UI.color("bold", "Available profiles:"))
            local cmd = "ls " .. os.getenv("HOME") .. "/NOKA/profiles/*.json 2>/dev/null"
            local f = io.popen(cmd)
            if f then
                local found = false
                for line in f:lines() do
                    found = true
                    local name = line:match("([^/]+)%.json$")
                    if name then
                        print("- " .. name)
                    end
                end
                f:close()
                if not found then
                    print("No profiles saved yet")
                end
            end
            M_UI.pause()
        elseif choice == "4" then
            local name = M_UI.prompt("Profile name to delete:")
            local path = os.getenv("HOME") .. "/NOKA/profiles/" .. name .. ".json"
            if os.remove(path) then
                M_UI.success("Profile deleted")
            else
                M_UI.error("Failed to delete profile")
            end
            M_UI.pause()
        elseif choice == "5" then
            break
        end
    end
end

-- Device health for diagnostics
function MenuHandlers.show_device_health()
    M_UI.header()
    print(M_UI.color("cyan", "=== DEVICE HEALTH ==="))
    print()
    
    -- RAM
    local stdout = M_Shell.exec("free -m | grep Mem")
    if stdout then
        print(M_UI.color("bold", "RAM Usage:"))
        local total, used, free = stdout:match("(%d+)%s+(%d+)%s+(%d+)")
        if total then
            local pct = math.floor(used / total * 100)
            local bar = string.rep("#", pct / 5) .. string.rep("-", 20 - pct / 5)
            print(string.format("[%s] %d%% (%d/%d MB)", bar, pct, used, total))
        end
        print()
    end
    
    -- CPU
    stdout = M_Shell.exec("top -bn1 | grep 'Cpu(s)' 2>/dev/null || echo 'N/A'")
    if stdout then
        print(M_UI.color("bold", "CPU Usage:"))
        local usage = stdout:match("(%d+[%.,]?%d*)%%?%s*us")
        if usage then
            usage = tonumber(usage:gsub(",", ".")) or 0
            local bar = string.rep("#", usage / 5) .. string.rep("-", 20 - usage / 5)
            print(string.format("[%s] %.1f%%", bar, usage))
        else
            print("Unable to read CPU usage")
        end
        print()
    end
    
    -- Battery
    stdout = M_Shell.exec("termux-battery-status 2>/dev/null || echo '{}'")
    if stdout and stdout ~= "{}" then
        local batt = json.decode(stdout)
        if batt and batt.percentage then
            print(M_UI.color("bold", "Battery:"))
            local pct = tonumber(batt.percentage) or 0
            local bar = string.rep("#", pct / 5) .. string.rep("-", 20 - pct / 5)
            local status = batt.status or "unknown"
            local plugged = batt.plugged or "UNPLUGGED"
            print(string.format("[%s] %d%% (%s, %s)", bar, pct, status, plugged))
            print()
        end
    end
    
    -- Storage
    stdout = M_Shell.exec("df -h ~/NOKA | tail -1")
    if stdout then
        print(M_UI.color("bold", "Storage (~/NOKA):"))
        local size, used, avail, pct = stdout:match("(%S+)%s+(%S+)%s+(%S+)%s+(%d+)%%")
        if pct then
            local p = tonumber(pct) or 0
            local bar = string.rep("#", p / 5) .. string.rep("-", 20 - p / 5)
            print(string.format("[%s] %s%% used (%s free)", bar, pct, avail))
        end
    end
    
    M_UI.pause()
end

-- Option 6: Diagnostics & logs
function MenuHandlers.diagnostics_menu()
    while true do
        M_UI.header()
        print(M_UI.color("cyan", "=== DIAGNOSTICS & LOGS ==="))
        print()
        print("1) View live log (tail -f)")
        print("2) View last 50 log entries")
        print("3) Check device health")
        print("4) Test package launch (dry run)")
        print("5) Test webhook connectivity")
        print("6) Check heartbeat file status")
        print("7) Clear logs")
        print("8) Back")
        print()
        
        local choice = M_UI.prompt("Choice:")
        
        if choice == "1" then
            M_UI.clear()
            print(M_UI.color("yellow", "Live log - Press Ctrl+C to exit"))
            print()
            os.execute("tail -f " .. M_Log.log_path .. " 2>/dev/null || echo 'No log file'")
        elseif choice == "2" then
            print()
            print(M_Log.tail(50))
            M_UI.pause()
        elseif choice == "3" then
            MenuHandlers.show_device_health()
        elseif choice == "4" then
            local packages = M_Config.get("packages") or {}
            if #packages > 0 then
                print()
                print("Dry run - would launch these packages:")
                for _, pkg in ipairs(packages) do
                    if pkg.enabled then
                        print("- " .. pkg.nickname .. " (" .. pkg.id .. ")")
                    end
                end
            else
                M_UI.error("No packages configured")
            end
            M_UI.pause()
        elseif choice == "5" then
            M_UI.info("Testing webhook...")
            local ok, err = M_Webhook.test()
            if ok then
                M_UI.success("Webhook test successful")
            else
                M_UI.error("Test failed: " .. tostring(err))
            end
            M_UI.pause()
        elseif choice == "6" then
            print()
            print(M_UI.color("bold", "Heartbeat file status:"))
            local packages = M_Config.get("packages") or {}
            for _, pkg in ipairs(packages) do
                if pkg.enabled then
                    local ts = M_Monitor.read_heartbeat(pkg.id)
                    local status = ts and "OK (" .. ts .. ")" or "MISSING"
                    print("- " .. pkg.nickname .. ": " .. status)
                end
            end
            M_UI.pause()
        elseif choice == "7" then
            if M_UI.confirm("Clear all logs?") then
                M_Log.clear()
                M_UI.success("Logs cleared")
            end
            M_UI.pause()
        elseif choice == "8" then
            break
        end
    end
end

-- Option 7: Scheduler
function MenuHandlers.scheduler_menu()
    while true do
        M_UI.header()
        print(M_UI.color("cyan", "=== SCHEDULER ==="))
        print()
        print("1) Add schedule rule")
        print("2) View active rules")
        print("3) Delete a rule")
        print("4) Back")
        print()
        
        local choice = M_UI.prompt("Choice:")
        
        if choice == "1" then
            print()
            print("Rule types:")
            print("1) START_ALL - Launch all at HH:MM")
            print("2) STOP_ALL - Kill all at HH:MM")
            print("3) RESTART_ALL - Restart every X minutes")
            print("4) SCREENSHOT - Capture every X minutes")
            local rtype = M_UI.prompt("Rule type:")
            
            local type_map = {["1"] = "START_ALL", ["2"] = "STOP_ALL", ["3"] = "RESTART_ALL", ["4"] = "SCREENSHOT"}
            local rule_type = type_map[rtype]
            
            if rule_type then
                local params = {}
                if rule_type == "START_ALL" or rule_type == "STOP_ALL" then
                    params.time = M_UI.prompt("Time (HH:MM, 24-hour format):")
                else
                    params.interval = tonumber(M_UI.prompt("Interval in minutes:")) or 60
                end
                
                M_Scheduler.add_rule(rule_type, params)
                M_UI.success("Rule added")
            else
                M_UI.error("Invalid rule type")
            end
            M_UI.pause()
        elseif choice == "2" then
            print()
            print(M_UI.color("bold", "Active rules:"))
            local rules = M_Scheduler.list_rules()
            for i, rule in ipairs(rules) do
                local details = ""
                if rule.params.time then
                    details = "at " .. rule.params.time
                elseif rule.params.interval then
                    details = "every " .. rule.params.interval .. " min"
                end
                local status = rule.enabled and "Enabled" or "Disabled"
                print(string.format("%d) %s %s [%s]", i, rule.type, details, status))
            end
            if #rules == 0 then
                print("No rules configured")
            end
            M_UI.pause()
        elseif choice == "3" then
            local rules = M_Scheduler.list_rules()
            for i, rule in ipairs(rules) do
                print(i .. ") " .. rule.type)
            end
            local idx = tonumber(M_UI.prompt("Rule number to delete:"))
            if idx then
                if M_Scheduler.delete_rule(idx) then
                    M_UI.success("Rule deleted")
                else
                    M_UI.error("Invalid rule number")
                end
            end
            M_UI.pause()
        elseif choice == "4" then
            break
        end
    end
end

-- Option 8: Export / Import
function MenuHandlers.export_import_menu()
    while true do
        M_UI.header()
        print(M_UI.color("cyan", "=== EXPORT / IMPORT CONFIG ==="))
        print()
        print("1) Export config.json to custom path")
        print("2) Export all profiles")
        print("3) Import config from path")
        print("4) Import profile from path")
        print("5) Back")
        print()
        
        local choice = M_UI.prompt("Choice:")
        
        if choice == "1" then
            local path = M_UI.prompt("Export path:")
            local content = json.encode(M_Config.data)
            local f = io.open(path, "w")
            if f then
                f:write(content)
                f:close()
                M_UI.success("Config exported to " .. path)
            else
                M_UI.error("Failed to export")
            end
            M_UI.pause()
        elseif choice == "2" then
            local dest = M_UI.prompt("Destination directory:")
            os.execute("mkdir -p " .. dest)
            os.execute("cp -r " .. os.getenv("HOME") .. "/NOKA/profiles " .. dest .. "/")
            M_UI.success("Profiles exported")
            M_UI.pause()
        elseif choice == "3" then
            local path = M_UI.prompt("Config path to import:")
            local f = io.open(path, "r")
            if f then
                local content = f:read("*a")
                f:close()
                local data = json.decode(content)
                if data then
                    if M_UI.confirm("Import will replace current config. Continue?") then
                        M_Config.data = data
                        M_Config.save()
                        M_UI.success("Config imported")
                    end
                else
                    M_UI.error("Invalid JSON")
                end
            else
                M_UI.error("File not found")
            end
            M_UI.pause()
        elseif choice == "4" then
            local path = M_UI.prompt("Profile path to import:")
            local name = M_UI.prompt("Profile name:")
            local dest = os.getenv("HOME") .. "/NOKA/profiles/" .. name .. ".json"
            os.execute("cp " .. path .. " " .. dest)
            M_UI.success("Profile imported")
            M_UI.pause()
        elseif choice == "5" then
            break
        end
    end
end

-- Option 9: About & Help
function MenuHandlers.about_help()
    M_UI.header()
    print(M_UI.color("cyan", "=== ABOUT & HELP ==="))
    print()
    print(M_UI.color("bold", "NOKA - Roblox Instance Manager v2.0"))
    print()
    print("A complete Termux automation tool for managing multiple")
    print("Roblox instances with crash detection, webhooks, and scheduling.")
    print()
    print(M_UI.color("bold", "Quick Start:"))
    print("1. Run 'First-time configuration wizard' to set up")
    print("2. Start monitoring to launch instances")
    print("3. Inject NOKA_Heartbeat.luau into Roblox via your executor")
    print()
    print(M_UI.color("bold", "Keybindings (during monitoring):"))
    print("Q - Stop monitoring and return to menu")
    print("R - Restart all instances")
    print("P - Pause/resume a specific instance")
    print("S - Take screenshot")
    print("L - View recent logs")
    print()
    print(M_UI.color("bold", "Requirements:"))
    print("- Termux with: lua54, curl, netcat-openbsd")
    print("- Android with Roblox installed")
    print("- Roblox script executor for heartbeat script")
    print()
    print("Lua version: " .. _VERSION)
    M_UI.pause()
end

-- =============================================================================
-- MAIN PROGRAM
-- =============================================================================
local function check_requirements()
    M_UI.header()
    print(M_UI.color("cyan", "Checking requirements..."))
    print()
    
    local tools = {"am", "pm", "screencap", "nc", "curl"}
    local all_ok = true
    
    for _, tool in ipairs(tools) do
        if M_Shell.check_tool(tool) then
            print("  " .. M_UI.color("green", "[OK]") .. " " .. tool)
        else
            print("  " .. M_UI.color("red", "[MISSING]") .. " " .. tool)
            all_ok = false
        end
    end
    
    print()
    if not all_ok then
        M_UI.warning("Some tools are missing. Install with: pkg install curl netcat-openbsd")
    end
    
    return all_ok
end

local function main()
    -- Initialize
    M_Log.init()
    M_Config.load()
    M_Webhook.load_history()
    
    -- Check for debug flag
    local debug_mode = false
    for _, arg in ipairs(arg or {}) do
        if arg == "--debug" then
            debug_mode = true
        end
    end
    
    if debug_mode then
        print(M_UI.color("yellow", "DEBUG MODE ENABLED"))
    end
    
    -- Check requirements on first run
    check_requirements()
    
    -- Main menu loop
    local running = true
    while running do
        local choice = M_UI.main_menu()
        
        if choice == "1" then
            MenuHandlers.config_wizard()
        elseif choice == "2" then
            MenuHandlers.start_monitoring()
        elseif choice == "3" then
            MenuHandlers.webhook_menu()
        elseif choice == "4" then
            MenuHandlers.update_url()
        elseif choice == "5" then
            MenuHandlers.profiles_menu()
        elseif choice == "6" then
            MenuHandlers.diagnostics_menu()
        elseif choice == "7" then
            MenuHandlers.scheduler_menu()
        elseif choice == "8" then
            MenuHandlers.export_import_menu()
        elseif choice == "9" then
            MenuHandlers.about_help()
        elseif choice == "0" then
            running = false
            print()
            print(M_UI.color("green", "Goodbye!"))
        else
            M_UI.error("Invalid choice")
            os.execute("sleep 1")
        end
    end
end


main()






