"""
jarvis_actions.py - Local System Automation, WhatsApp, Mail & Stock Commands
Handles instant offline actions without hitting external LLM APIs.
"""

import base64
import ctypes
import subprocess
import re
import urllib.parse
import datetime
import os
import glob
import sys
import json
import threading
import time
import webbrowser
import shutil
import jarvis_market
import difflib
import queue
from contextlib import contextmanager
from contextvars import ContextVar
from email.message import EmailMessage
from email.utils import parseaddr
from html.parser import HTMLParser

SITES = {
    "youtube": "https://www.youtube.com",
    "whatsapp": "https://web.whatsapp.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "maps": "https://maps.google.com",
    "calendar": "https://calendar.google.com",
    "drive": "https://drive.google.com",
    "twitter": "https://twitter.com",
    "self studys": "https://www.selfstudys.com",
    "selfstudys": "https://www.selfstudys.com",
    "self study": "https://www.selfstudys.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "tiktok": "https://www.tiktok.com",
    "reddit": "https://www.reddit.com",
    "discord": "https://discord.com",
    "slack": "https://slack.com",
    "zoom": "https://zoom.us",
    "teams": "https://teams.microsoft.com",
    "notion": "https://www.notion.so",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "perplexity": "https://www.perplexity.ai",
    "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.com",
    "chrome": "https://www.google.com/chrome",
    "word": "https://www.microsoft365.com",
    "excel": "https://www.microsoft365.com",
    "powerpoint": "https://www.microsoft365.com",
    "microsoft word": "https://www.microsoft365.com",
    "microsoft excel": "https://www.microsoft365.com",
    "microsoft powerpoint": "https://www.microsoft365.com",
    "google chrome": "https://www.google.com/chrome",
    "code": "https://code.visualstudio.com",
    "vs code": "https://code.visualstudio.com",
    "visual studio code": "https://code.visualstudio.com",
}

ALIASES = {
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
    "chrome": "Google Chrome",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "settings": "System Settings",
    "system preferences": "System Settings",
    "terminal": "Terminal",
    "spotify": "Spotify",
    "perplexity": "Perplexity",
}

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_gmail_service_cache = None
_calendar_service_cache = None
_pending_email = None
_pending_social = None
_whatsapp_jobs = queue.Queue()
_whatsapp_worker_thread = None
_whatsapp_worker_lock = threading.Lock()
_background_mode = ContextVar("jarvis_background_mode", default=False)
_WINDOW_SHOW_MINNOACTIVE = 7


@contextmanager
def background_command(query):
    """Expose a trailing background request to launch helpers for the full command."""
    match = re.search(
        r"\s+in\s+(?:the\s+)?background\s*[.!?]*$",
        query,
        re.IGNORECASE,
    )
    command = query[:match.start()].rstrip(" ,.!?") if match else query
    token = _background_mode.set(_background_mode.get() or bool(match))
    try:
        yield command
    finally:
        _background_mode.reset(token)


def _launch_response(message):
    if _background_mode.get():
        return message + " I requested a minimized launch."
    return message


def _startfile(target):
    if _background_mode.get() and sys.platform == "win32":
        os.startfile(target, show_cmd=_WINDOW_SHOW_MINNOACTIVE)
    else:
        os.startfile(target)


def _open(args):
    if sys.platform == "darwin":
        return subprocess.run(["open"] + args, capture_output=True).returncode == 0
    if sys.platform == "win32" and args and args[0] == "-a":
        return False
    if len(args) == 1:
        if _background_mode.get() and sys.platform == "win32":
            try:
                _startfile(args[0])
                return True
            except OSError as exc:
                print(f"[Background launch error] Could not open {args[0]} minimized: {exc}")
                return False
        return webbrowser.open(args[0])
    return False


def _app_names_match(query, candidates):
    query = re.sub(r"\b(application|app)\b", "", query.lower()).strip()
    query = re.sub(r"[^a-z0-9]+", " ", query).strip()
    if not query or not candidates:
        return None

    for name in candidates:
        candidate = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
        if query == candidate:
            return name, True
    return None


def _normalized_name(name):
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _find_local_path(name):
    requested = _normalized_name(name)
    if not requested:
        return None

    home = os.path.expanduser("~")
    roots = [
        os.getcwd(),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        os.environ.get("OneDrive", ""),
        home,
    ]
    excluded_dirs = {
        "appdata",
        "__pycache__",
        "node_modules",
        "$recycle.bin",
        ".git",
        ".venv",
        "venv",
        "application data",
        "cookies",
        "local settings",
        "my documents",
        "my music",
        "my pictures",
        "my videos",
        "nethood",
        "printhood",
        "recent",
        "sendto",
        "start menu",
        "templates",
    }
    visited_dirs = set()

    def report_walk_error(error):
        print(f"[Local item search notice] Could not search {error.filename}: {error}")

    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        root = os.path.abspath(root)
        for current_dir, directories, filenames in os.walk(root, onerror=report_walk_error):
            current_key = os.path.normcase(os.path.abspath(current_dir))
            if current_key in visited_dirs:
                directories[:] = []
                continue
            visited_dirs.add(current_key)
            directories[:] = [
                directory for directory in directories
                if directory.lower() not in excluded_dirs
                and not directory.startswith(".")
            ]

            for entry in directories:
                if _normalized_name(entry) == requested:
                    return os.path.join(current_dir, entry)
            for entry in filenames:
                if (
                    _normalized_name(entry) == requested
                    or _normalized_name(os.path.splitext(entry)[0]) == requested
                ):
                    return os.path.join(current_dir, entry)
    return None


def _open_local_path(path):
    try:
        if sys.platform == "win32":
            _startfile(path)
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, path])
        return True
    except OSError as exc:
        print(f"[Local item launch error] Could not open {path}: {exc}")
        return False


def _website_for(name):
    normalized_name = name.lower().strip()
    site = SITES.get(normalized_name)
    if site is None:
        alias_target = ALIASES.get(normalized_name)
        if alias_target:
            site = SITES.get(alias_target.lower())
    if site:
        return site
    domain = _normalized_name(name)
    return f"https://{domain}.com" if domain else None


def _spotify_playback_powershell_script(query, minimize=False):
    encoded_query_argument = base64.b64encode(query.encode("utf-8")).decode("ascii")
    return r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$query = [Text.Encoding]::UTF8.GetString(
    [Convert]::FromBase64String('__QUERY__')
)
$deadline = [DateTime]::UtcNow.AddSeconds(12)
$window = $null
$matchingTrack = $null
while ([DateTime]::UtcNow -lt $deadline) {
    $spotifyProcess = Get-Process -Name Spotify -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
        Select-Object -First 1
    if ($spotifyProcess) {
        $window = [System.Windows.Automation.AutomationElement]::FromHandle(
            $spotifyProcess.MainWindowHandle
        )
        if ($window) {
            $itemCondition = [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                [System.Windows.Automation.ControlType]::DataItem
            )
            $items = $window.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                $itemCondition
            )
            foreach ($item in $items) {
                if (-not $item.Current.Name.Contains(
                    $query, [StringComparison]::OrdinalIgnoreCase
                )) {
                    continue
                }
                $buttonCondition = [System.Windows.Automation.PropertyCondition]::new(
                    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                    [System.Windows.Automation.ControlType]::Button
                )
                $buttons = $item.FindAll(
                    [System.Windows.Automation.TreeScope]::Descendants,
                    $buttonCondition
                )
                foreach ($button in $buttons) {
                    if ($button.Current.Name -notmatch '(?i)^play(?:\s|$)') {
                        continue
                    }
                    try {
                        $pattern = $button.GetCurrentPattern(
                            [System.Windows.Automation.InvokePattern]::Pattern
                        )
                        $matchingTrack = $button
                        break
                    } catch [System.InvalidOperationException] {
                        continue
                    }
                }
                if ($matchingTrack) { break }
            }
        }
    }
    if ($matchingTrack) { break }
    Start-Sleep -Milliseconds 400
}
if (-not $matchingTrack) {
    [Console]::Error.WriteLine('Could not find a matching Spotify track Play button.')
    exit 2
}
try {
    $pattern = $matchingTrack.GetCurrentPattern(
        [System.Windows.Automation.InvokePattern]::Pattern
    )
    $pattern.Invoke()
    if (__MINIMIZE__) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class JarvisWindowMinimizer {
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr handle, int command);
}
'@
        [JarvisWindowMinimizer]::ShowWindowAsync(
            $spotifyProcess.MainWindowHandle, 7
        ) | Out-Null
    }
    exit 0
} catch {
    [Console]::Error.WriteLine("Could not start Spotify playback: $_")
    exit 3
}
""".replace("__QUERY__", encoded_query_argument).replace(
        "__MINIMIZE__", "$true" if minimize else "$false"
    )


def _play_spotify_search(query):
    encoded_query = urllib.parse.quote(query, safe="")
    spotify_uri = f"spotify:search:{encoded_query}"
    try:
        if sys.platform != "win32":
            print("[Spotify playback error] Automatic Spotify playback currently requires Windows.")
            return False
        _startfile(spotify_uri)
        powershell_script = _spotify_playback_powershell_script(
            query, minimize=_background_mode.get()
        )
        encoded_script = base64.b64encode(powershell_script.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded_script,
            ],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            return True
        error = result.stderr.strip() or result.stdout.strip()
        print(f"[Spotify playback error] {error or 'Spotify could not start playback.'}")
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[Spotify playback error] Could not start Spotify playback: {exc}")
        return False


def _osa(script):
    subprocess.run(["osascript", "-e", script])


def _run_powershell(script, timeout=15):
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-OutputFormat", "Text", "-EncodedCommand", encoded_script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[System control error] PowerShell command failed: {exc}")
        return False, str(exc)
    if result.returncode:
        error = result.stderr.strip() or result.stdout.strip()
        print(f"[System control error] {error}")
        return False, error
    return True, result.stdout.strip()


def _close_window(target):
    if sys.platform != "win32":
        return False, "Closing a named window is currently supported on Windows."

    encoded_target = base64.b64encode(target.encode("utf-8")).decode("ascii")
    script = r"""
$target = [Text.Encoding]::UTF8.GetString(
    [Convert]::FromBase64String('__TARGET__')
)
$source = @'
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
public static class JarvisWindowCloser {
    private delegate bool EnumWindowsProc(IntPtr handle, IntPtr state);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr state);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr handle);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr handle, StringBuilder text, int length);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr handle, uint message, IntPtr wParam, IntPtr lParam);
    public static string Close(string target) {
        string closed = null;
        EnumWindows((handle, state) => {
            if (!IsWindowVisible(handle)) return true;
            var title = new StringBuilder(512);
            GetWindowText(handle, title, title.Capacity);
            uint processId;
            GetWindowThreadProcessId(handle, out processId);
            string processName = "";
            try { processName = Process.GetProcessById((int)processId).ProcessName; }
            catch (ArgumentException) { return true; }
            if (title.ToString().IndexOf(target, StringComparison.OrdinalIgnoreCase) < 0 &&
                processName.IndexOf(target, StringComparison.OrdinalIgnoreCase) < 0) return true;
            if (PostMessage(handle, 0x0010, IntPtr.Zero, IntPtr.Zero)) {
                closed = title.Length > 0 ? title.ToString() : processName;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return closed;
    }
}
'@
Add-Type -TypeDefinition $source
$closed = [JarvisWindowCloser]::Close($target)
if ($closed) { Write-Output $closed; exit 0 }
[Console]::Error.WriteLine("No open window matched '$target'.")
exit 2
""".replace("__TARGET__", encoded_target)
    return _run_powershell(script)


def _set_brightness(value):
    if sys.platform != "win32":
        return False, "Brightness controls are currently supported on Windows."
    value = max(0, min(100, int(value)))
    script = f"""
$ErrorActionPreference = 'Stop'
$methods = @(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)
if ($methods.Count -eq 0) {{ throw 'No brightness-controllable display was found.' }}
foreach ($monitor in $methods) {{
    $null = Invoke-CimMethod -InputObject $monitor -MethodName WmiSetBrightness `
        -Arguments @{{ Timeout = 1; Brightness = {value} }} -ErrorAction Stop
}}
"""
    return _run_powershell(script)


def _press_media_key(key_code):
    if sys.platform != "win32":
        return False
    try:
        keybd_event = ctypes.windll.user32.keybd_event
        keybd_event(key_code, 0, 0, 0)
        keybd_event(key_code, 0, 2, 0)
        return True
    except (AttributeError, OSError) as exc:
        print(f"[Media control error] Could not send media key: {exc}")
        return False


def _set_volume(level):
    level = max(0.0, min(1.0, level))
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["osascript", "-e", f"set volume output volume {round(level * 100)}"],
                capture_output=True,
            )
        except OSError as exc:
            print(f"[Volume control error] Could not set system volume: {exc}")
            return False
        return result.returncode == 0
    if sys.platform.startswith("linux") and shutil.which("pactl"):
        try:
            result = subprocess.run(
                [
                    "pactl", "set-sink-volume", "@DEFAULT_SINK@",
                    f"{round(level * 100)}%",
                ],
                capture_output=True,
            )
        except OSError as exc:
            print(f"[Volume control error] Could not set system volume: {exc}")
            return False
        return result.returncode == 0
    if sys.platform != "win32":
        return False
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:
        print(f"[Volume control error] Missing Windows audio dependency: {exc}")
        return False

    comtypes.CoInitialize()
    try:
        endpoint = AudioUtilities.GetSpeakers().EndpointVolume
        endpoint.SetMute(0, None)
        endpoint.SetMasterVolumeLevelScalar(max(0.0, min(1.0, level)), None)
        return True
    except (OSError, comtypes.COMError) as exc:
        print(f"[Volume control error] Could not set system volume: {exc}")
        return False
    finally:
        comtypes.CoUninitialize()


def _adjust_volume(action):
    if sys.platform == "win32":
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
        except ImportError as exc:
            print(f"[Volume control error] Missing Windows audio dependency: {exc}")
            return False

        comtypes.CoInitialize()
        try:
            volume = AudioUtilities.GetSpeakers().EndpointVolume
            if action == "mute":
                volume.SetMute(1, None)
            elif action == "unmute":
                volume.SetMute(0, None)
            else:
                current = volume.GetMasterVolumeLevelScalar()
                change = 0.1 if action == "up" else -0.1
                volume.SetMute(0, None)
                volume.SetMasterVolumeLevelScalar(
                    max(0.0, min(1.0, current + change)), None
                )
            return True
        except (OSError, comtypes.COMError) as exc:
            print(f"[Volume control error] Could not change system volume: {exc}")
            return False
        finally:
            comtypes.CoUninitialize()
    if sys.platform == "darwin":
        scripts = {
            "up": "set volume output volume ((output volume of (get volume settings)) + 10)",
            "down": "set volume output volume ((output volume of (get volume settings)) - 10)",
            "mute": "set volume with output muted",
            "unmute": "set volume without output muted",
        }
        try:
            result = subprocess.run(["osascript", "-e", scripts[action]], capture_output=True)
        except OSError as exc:
            print(f"[Volume control error] {exc}")
            return False
        return result.returncode == 0
    if sys.platform.startswith("linux") and shutil.which("pactl"):
        commands = {
            "up": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
            "down": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
            "mute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
            "unmute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
        }
        try:
            return subprocess.run(commands[action], capture_output=True).returncode == 0
        except OSError as exc:
            print(f"[Volume control error] {exc}")
            return False
    return False


def _stop_music():
    if sys.platform == "win32":
        if _press_media_key(0xB2):
            return True
    elif sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["osascript", "-e", 'tell application "Spotify" to pause'],
                capture_output=True,
            )
            return result.returncode == 0
        except OSError as exc:
            print(f"[Media control error] {exc}")
    elif sys.platform.startswith("linux") and shutil.which("playerctl"):
        try:
            return subprocess.run(["playerctl", "stop"], capture_output=True).returncode == 0
        except OSError as exc:
            print(f"[Media control error] {exc}")
    return False


def _apps():
    dirs = [
        "/Applications",
        "/Applications/Utilities",
        "/System/Applications",
        "/System/Applications/Utilities",
        os.path.expanduser("~/Applications"),
    ]
    apps = {}
    for d in dirs:
        for path in glob.glob(d + "/*.app"):
            n = os.path.basename(path)[:-4]
            apps[n.lower()] = n
    return apps


_WINDOWS_APPS_CACHE_TTL = 300
_windows_apps_cache = None
_windows_apps_cache_time = 0.0
_windows_apps_cache_lock = threading.Lock()


def _load_windows_apps():
    apps = {}
    command = (
        "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 and result.stdout.strip():
            entries = json.loads(result.stdout)
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                if entry.get("Name") and entry.get("AppID"):
                    apps.setdefault(entry["Name"], ("packaged", entry["AppID"]))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"[Application search notice] Could not query Windows Start apps: {exc}")

    start_menu_dirs = [
        os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
        ),
        os.path.join(
            os.environ.get("PROGRAMDATA", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
        ),
    ]
    for root in start_menu_dirs:
        if not os.path.isdir(root):
            continue
        for current_dir, _subdirs, files in os.walk(root):
            for filename in files:
                if filename.lower().endswith((".lnk", ".url")):
                    name = os.path.splitext(filename)[0]
                    apps.setdefault(name, ("shortcut", os.path.join(current_dir, filename)))

    try:
        import winreg

        app_paths = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                root_key = winreg.OpenKey(hive, app_paths)
            except OSError:
                continue
            with root_key:
                for index in range(winreg.QueryInfoKey(root_key)[0]):
                    executable_name = winreg.EnumKey(root_key, index)
                    try:
                        with winreg.OpenKey(root_key, executable_name) as app_key:
                            executable_path = os.path.expandvars(
                                winreg.QueryValue(app_key, None)
                            ).strip('"')
                    except OSError:
                        continue
                    if os.path.isfile(executable_path):
                        name = os.path.splitext(executable_name)[0]
                        apps.setdefault(name, ("executable", executable_path))
    except ImportError:
        pass

    return apps


def _windows_apps():
    global _windows_apps_cache, _windows_apps_cache_time
    now = time.monotonic()
    if (
        _windows_apps_cache is not None
        and now - _windows_apps_cache_time < _WINDOWS_APPS_CACHE_TTL
    ):
        return _windows_apps_cache

    with _windows_apps_cache_lock:
        now = time.monotonic()
        if (
            _windows_apps_cache is None
            or now - _windows_apps_cache_time >= _WINDOWS_APPS_CACHE_TTL
        ):
            _windows_apps_cache = _load_windows_apps()
            _windows_apps_cache_time = now
    return _windows_apps_cache


if sys.platform == "win32":
    threading.Thread(
        target=_windows_apps,
        name="jarvis-app-cache",
        daemon=True,
    ).start()


def find_app(name):
    requested = ALIASES.get(name.lower().strip(), name).strip()
    apps = _windows_apps() if sys.platform == "win32" else _apps()
    match = _app_names_match(requested, apps)
    if match is None:
        return None
    return match[0]


def _launch_app(name):
    requested = ALIASES.get(name.lower().strip(), name).strip()
    if sys.platform == "win32":
        apps = _windows_apps()
        match = _app_names_match(requested, apps)
        if match is None:
            return None
        app_name, exact = match
        launch_type, target = apps[app_name]
        try:
            if launch_type == "packaged":
                startupinfo = None
                if _background_mode.get():
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = _WINDOW_SHOW_MINNOACTIVE
                subprocess.Popen(
                    ["explorer.exe", f"shell:AppsFolder\\{target}"],
                    startupinfo=startupinfo,
                )
            elif launch_type == "shortcut":
                _startfile(target)
            else:
                _startfile(target)
        except OSError as exc:
            print(f"[Application launch error] Could not open {app_name}: {exc}")
            return False
        return app_name, exact

    apps = _apps()
    match = _app_names_match(requested, apps)
    if match:
        app_name, exact = match
        if _open(["-a", app_name]):
            return app_name, exact
    return None


def send_whatsapp_message(contact_name, message="Hello from Jarvis"):
    return draft_social_message("whatsapp", contact_name, message)


def _jarvis_profile_path(filename):
    profile_root = os.environ.get("APPDATA")
    if profile_root:
        profile_root = os.path.join(profile_root, "OpenJarvis")
    else:
        profile_root = os.path.expanduser("~/.openjarvis")
    os.makedirs(profile_root, exist_ok=True)
    return os.path.join(profile_root, filename)


def _get_gmail_service():
    global _gmail_service_cache
    if _gmail_service_cache is not None:
        return _gmail_service_cache, None

    try:
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        print(f"[Gmail error] Gmail API dependencies are unavailable: {exc}")
        return None, "Gmail support is not installed. Reinstall Jarvis dependencies."

    client_file = _jarvis_profile_path("gmail_client_secret.json")
    token_file = _jarvis_profile_path("gmail_token.json")
    if not os.path.isfile(client_file):
        return None, (
            "Gmail is not connected yet. Set up Gmail API access by placing your "
            "Google OAuth desktop-app file at "
            f"{client_file}, then ask me to read or compose email again."
        )

    try:
        credentials = None
        if os.path.isfile(token_file):
            credentials = Credentials.from_authorized_user_file(
                token_file, scopes=GMAIL_SCOPES
            )
        if credentials and credentials.has_scopes(GMAIL_SCOPES):
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
        else:
            credentials = None

        if not credentials or not credentials.valid:
            if _background_mode.get():
                return None, (
                    "Google sign-in needs an interactive browser. Repeat this "
                    "command without 'in background' once; later commands can "
                    "run in the background."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                client_file, scopes=GMAIL_SCOPES
            )
            credentials = flow.run_local_server(port=0, open_browser=True)

        with open(token_file, "w", encoding="utf-8") as token:
            token.write(credentials.to_json())
        _gmail_service_cache = build(
            "gmail", "v1", credentials=credentials, cache_discovery=False
        )
        return _gmail_service_cache, None
    except (OSError, ValueError, GoogleAuthError) as exc:
        print(f"[Gmail authentication error] {exc}")
        return None, (
            "I couldn't connect to Gmail. Check your local OAuth file and "
            "complete the Google sign-in prompt."
        )


def _get_calendar_service():
    global _calendar_service_cache
    if _calendar_service_cache is not None:
        return _calendar_service_cache, None

    try:
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        print(f"[Calendar error] Google Calendar dependencies are unavailable: {exc}")
        return None, "Google Calendar support is not installed. Reinstall Jarvis dependencies."

    client_file = _jarvis_profile_path("calendar_client_secret.json")
    if not os.path.isfile(client_file):
        client_file = _jarvis_profile_path("gmail_client_secret.json")
    token_file = _jarvis_profile_path("calendar_token.json")
    if not os.path.isfile(client_file):
        return None, (
            "Google Calendar is not connected yet. Place your Google OAuth "
            f"desktop-app file at {client_file}, then try again."
        )

    try:
        credentials = None
        if os.path.isfile(token_file):
            credentials = Credentials.from_authorized_user_file(
                token_file, scopes=CALENDAR_SCOPES
            )
        if credentials and credentials.has_scopes(CALENDAR_SCOPES):
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
        else:
            credentials = None

        if not credentials or not credentials.valid:
            if _background_mode.get():
                return None, (
                    "Google sign-in needs an interactive browser. Repeat this "
                    "command without 'in background' once; later commands can "
                    "run in the background."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                client_file, scopes=CALENDAR_SCOPES
            )
            credentials = flow.run_local_server(port=0, open_browser=True)

        with open(token_file, "w", encoding="utf-8") as token:
            token.write(credentials.to_json())
        _calendar_service_cache = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        )
        return _calendar_service_cache, None
    except (OSError, ValueError, GoogleAuthError) as exc:
        print(f"[Calendar authentication error] {exc}")
        return None, (
            "I couldn't connect to Google Calendar. Check your local OAuth "
            "file and complete the Google sign-in prompt."
        )


def configure_google_calendar(client_id, client_secret):
    global _calendar_service_cache
    client_id = client_id.strip()
    client_secret = client_secret.strip()
    if (
        len(client_id) > 500
        or not re.fullmatch(r"[^@\s]+\.apps\.googleusercontent\.com", client_id)
    ):
        return "Enter the OAuth client ID ending in .apps.googleusercontent.com."
    if not client_secret or len(client_secret) > 500 or re.search(r"\s", client_secret):
        return "Enter a valid Google OAuth client secret."

    client_file = _jarvis_profile_path("calendar_client_secret.json")
    token_file = _jarvis_profile_path("calendar_token.json")
    installed = {
        "client_id": client_id,
        "project_id": "openjarvis-local",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_secret": client_secret,
        "redirect_uris": ["http://localhost"],
    }

    try:
        old_client_id = None
        old_client_secret = None
        if os.path.isfile(client_file):
            with open(client_file, encoding="utf-8") as existing_file:
                old_config = json.load(existing_file)
            old_installed = (
                old_config.get("installed", {})
                if isinstance(old_config, dict)
                else {}
            )
            if not isinstance(old_installed, dict):
                old_installed = {}
            old_client_id = old_installed.get("client_id")
            old_client_secret = old_installed.get("client_secret")
        with open(client_file, "w", encoding="utf-8") as client_config:
            json.dump({"installed": installed}, client_config)
        if (
            (old_client_id != client_id or old_client_secret != client_secret)
            and os.path.isfile(token_file)
        ):
            os.remove(token_file)
    except (OSError, ValueError) as exc:
        print(f"[Calendar setup error] Could not save OAuth configuration: {exc}")
        return "I couldn't save the Google Calendar details to your local Jarvis profile."

    _calendar_service_cache = None
    service, error = _get_calendar_service()
    if error:
        return error

    from googleapiclient.errors import HttpError

    now = datetime.datetime.now().astimezone()
    try:
        service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=(now + datetime.timedelta(minutes=1)).isoformat(),
            maxResults=1,
        ).execute()
    except HttpError as exc:
        print(f"[Calendar connection test error] {exc}")
        return (
            "Google sign-in finished, but Calendar access failed. Check that "
            "the Google Calendar API is enabled and Calendar access was allowed."
        )
    return "Google Calendar connected. You can now ask Jarvis to read or update your schedule."


_CALENDAR_WEEKDAYS = {
    name.casefold(): index
    for index, name in enumerate(
        ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    )
}


def _parse_calendar_date(value):
    text = re.sub(r"\s+", " ", value.strip().strip(".,!?"))
    text = re.sub(r"^(?:on|for)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:at|from)\b.*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s+for\s+\d+\s+(?:hours?|hrs?|minutes?|mins?).*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:the\s+)?", "", text, flags=re.IGNORECASE).strip(" ,")

    today = datetime.datetime.now().astimezone().date()
    lowered = text.casefold()
    if lowered == "today":
        return today
    if lowered == "yesterday":
        return today - datetime.timedelta(days=1)
    if lowered == "tomorrow":
        return today + datetime.timedelta(days=1)
    if lowered in ("day after tomorrow", "the day after tomorrow"):
        return today + datetime.timedelta(days=2)

    weekday_match = re.fullmatch(
        r"(?:next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        lowered,
    )
    if weekday_match:
        target = _CALENDAR_WEEKDAYS[weekday_match.group(1)]
        delta = (target - today.weekday()) % 7
        if delta == 0 and lowered.startswith("next "):
            delta = 7
        return today + datetime.timedelta(days=delta)

    formats = (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d",
        "%b %d",
        "%d %B",
        "%d %b",
    )
    for date_format in formats:
        try:
            parsed = datetime.datetime.strptime(text, date_format).date()
        except ValueError:
            continue
        if "%Y" not in date_format:
            parsed = parsed.replace(year=today.year)
            if parsed < today:
                parsed = parsed.replace(year=today.year + 1)
        return parsed
    return None


def _calendar_time_from_text(value):
    match = re.search(
        r"\b(?:at|from)\s+(noon|midnight|"
        r"\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)?)\b",
        value,
        re.IGNORECASE,
    )
    if not match:
        if re.search(r"\b(?:at|from)\s+\d{1,2}\b", value, re.IGNORECASE):
            return None, True
        return None, False

    raw = re.sub(r"\s+", "", match.group(1).lower()).replace(".", "")
    if raw == "noon":
        return datetime.time(12, 0), False
    if raw == "midnight":
        return datetime.time(0, 0), False

    meridiem = raw.endswith(("am", "pm"))
    if meridiem:
        suffix = raw[-2:]
        clock = raw[:-2]
    else:
        suffix = ""
        clock = raw
    try:
        hour_text, separator, minute_text = clock.partition(":")
        hour = int(hour_text)
        minute = int(minute_text) if separator else 0
    except ValueError:
        return None, True
    if minute > 59 or (meridiem and not 1 <= hour <= 12):
        return None, True
    if not meridiem and not separator and 1 <= hour <= 12:
        return None, True
    if not 0 <= hour <= 23:
        return None, True
    if suffix == "pm" and hour != 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0
    return datetime.time(hour, minute), False


def _calendar_schedule_from_text(value):
    event_date = _parse_calendar_date(value)
    if event_date is None:
        return None, None, "Please specify a date such as today, tomorrow, Friday, or November 14, 2026."

    event_time, invalid_time = _calendar_time_from_text(value)
    if invalid_time:
        return None, None, "Please specify an unambiguous time, such as 3:30 PM or 15:30."
    if event_time is None:
        return event_date, None, None

    duration_match = re.search(
        r"\bfor\s+(\d+)\s+(hour|hours|hr|hrs|minute|minutes|min|mins)\b",
        value,
        re.IGNORECASE,
    )
    duration = datetime.timedelta(hours=1)
    if duration_match:
        amount = int(duration_match.group(1))
        unit = duration_match.group(2).casefold()
        duration = datetime.timedelta(
            hours=amount if unit.startswith(("h",)) else 0,
            minutes=amount if unit.startswith(("m",)) else 0,
        )
        if duration <= datetime.timedelta(0) or duration > datetime.timedelta(days=1):
            return None, None, "Calendar event duration must be between 1 minute and 24 hours."
    start = datetime.datetime.combine(event_date, event_time)
    current = datetime.datetime.now().astimezone()
    if event_date == current.date() and start.time() <= current.time():
        if re.search(r"\btoday\b", value, re.IGNORECASE):
            return None, None, "That time has already passed today. Choose a later time or another date."
        weekday = re.search(
            r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            value,
            re.IGNORECASE,
        )
        if weekday:
            event_date += datetime.timedelta(days=7)
            start = datetime.datetime.combine(event_date, event_time)
    end = start + duration
    return start.astimezone(), end.astimezone(), None


def _calendar_day_bounds(day):
    start = datetime.datetime.combine(day, datetime.time.min).astimezone()
    end = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time.min).astimezone()
    return start.isoformat(), end.isoformat()


def _calendar_list_events(service, start, end):
    return service.events().list(
        calendarId="primary",
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy="startTime",
        maxResults=100,
    ).execute().get("items", [])


def _calendar_event_when(event):
    start = event.get("start", {})
    if start.get("dateTime"):
        value = datetime.datetime.fromisoformat(
            start["dateTime"].replace("Z", "+00:00")
        ).astimezone()
        return value.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")
    if start.get("date"):
        value = datetime.date.fromisoformat(start["date"])
        return value.strftime("%A, %B %d").replace(" 0", " ")
    return "time not specified"


def _calendar_match_event(events, title):
    wanted = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    exact = []
    partial = []
    for event in events:
        summary = event.get("summary", "")
        normalized = re.sub(r"[^a-z0-9]+", " ", summary.casefold()).strip()
        if normalized == wanted:
            exact.append(event)
        elif wanted and (wanted in normalized or normalized in wanted):
            partial.append(event)
    matches = exact or partial
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"I couldn't find a calendar event matching {title}."
    choices = "; ".join(
        f"{item.get('summary', 'Untitled')} ({_calendar_event_when(item)})"
        for item in matches[:5]
    )
    return None, f"I found multiple matching events. Include a more specific title or date: {choices}."


def _calendar_find_events(service, title, day=None):
    if day is not None:
        start, end = _calendar_day_bounds(day)
    else:
        now = datetime.datetime.now().astimezone()
        start = (now - datetime.timedelta(days=365)).isoformat()
        end = (now + datetime.timedelta(days=730)).isoformat()
    return _calendar_match_event(_calendar_list_events(service, start, end), title)


def _calendar_read_schedule(query):
    service, error = _get_calendar_service()
    if error:
        return error

    today = datetime.datetime.now().astimezone().date()
    lowered = query.casefold()
    if "next week" in lowered:
        start_day = today + datetime.timedelta(days=(7 - today.weekday()))
        end_day = start_day + datetime.timedelta(days=7)
    elif "this week" in lowered:
        start_day = today - datetime.timedelta(days=today.weekday())
        end_day = start_day + datetime.timedelta(days=7)
    else:
        date_match = re.search(
            r"\b(today|yesterday|tomorrow|day after tomorrow|next\s+"
            r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
            r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
            r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}|"
            r"(?:january|february|march|april|may|june|july|august|"
            r"september|october|november|december|jan|feb|mar|apr|jun|"
            r"jul|aug|sep|oct|nov|dec)\s+\d{1,2}(?:st|nd|rd|th)?"
            r"(?:,\s*\d{4})?)\b",
            lowered,
        )
        start_day = _parse_calendar_date(date_match.group(0)) if date_match else today
        if start_day is None:
            return "I couldn't understand that schedule date. Try a weekday or a date such as November 14, 2026."
        end_day = start_day + datetime.timedelta(days=1)

    start, _ = _calendar_day_bounds(start_day)
    _, end = _calendar_day_bounds(end_day - datetime.timedelta(days=1))
    from googleapiclient.errors import HttpError

    try:
        events = _calendar_list_events(service, start, end)
    except HttpError as exc:
        print(f"[Calendar read error] {exc}")
        return "I couldn't read Google Calendar. Check your connection and account access."

    if not events:
        if end_day - start_day == datetime.timedelta(days=1):
            return f"You have no calendar events on {start_day.strftime('%A, %B %d')}."
        return "You have no calendar events during that period."
    lines = []
    for event in events:
        summary = event.get("summary", "Untitled event")
        if summary.casefold().startswith("task:"):
            summary = "Task: " + summary[5:].strip()
        when = _calendar_event_when(event)
        lines.append(f"{when}: {summary}")
    return "Your Google Calendar schedule: " + ". ".join(lines)


def _calendar_create_event(title, kind, date_spec):
    event_date, event_end, error = _calendar_schedule_from_text(date_spec)
    if error:
        return error
    is_task = kind == "task"
    if is_task:
        summary = f"Task: {title}"
    elif kind in ("meeting", "appointment"):
        prefix = kind.title()
        summary = f"{prefix} {title}" if title.casefold().startswith("with ") else f"{prefix}: {title}"
    else:
        summary = title
    if event_end is None:
        end_date = event_date + datetime.timedelta(days=1)
        event = {
            "summary": summary,
            "start": {"date": event_date.isoformat()},
            "end": {"date": end_date.isoformat()},
        }
    else:
        event = {
            "summary": summary,
            "start": {"dateTime": event_date.isoformat()},
            "end": {"dateTime": event_end.isoformat()},
        }
    service, error = _get_calendar_service()
    if error:
        return error
    from googleapiclient.errors import HttpError

    try:
        service.events().insert(calendarId="primary", body=event).execute()
    except HttpError as exc:
        print(f"[Calendar create error] {exc}")
        return "I couldn't create that Google Calendar entry. Check your connection and calendar access."
    entry_name = f"task {title}" if is_task else summary
    return f"Added {entry_name} to Google Calendar for {_calendar_event_when(event)}."


def _calendar_reschedule_event(title, old_date_spec, new_date_spec):
    old_day = _parse_calendar_date(old_date_spec)
    if old_day is None:
        return "Please specify the current event date so I can find the right calendar entry."
    service, error = _get_calendar_service()
    if error:
        return error
    from googleapiclient.errors import HttpError

    try:
        event, error = _calendar_find_events(service, title, old_day)
        if error:
            return error
        new_start, new_end, error = _calendar_schedule_from_text(new_date_spec)
        if error:
            return error
        if new_end is None:
            end_day = new_start + datetime.timedelta(days=1)
            event.update({
                "start": {"date": new_start.isoformat()},
                "end": {"date": end_day.isoformat()},
            })
        else:
            event.update({
                "start": {"dateTime": new_start.isoformat()},
                "end": {"dateTime": new_end.isoformat()},
            })
        service.events().update(
            calendarId="primary", eventId=event["id"], body=event
        ).execute()
    except HttpError as exc:
        print(f"[Calendar update error] {exc}")
        return "I couldn't update that Google Calendar entry. Check your connection and calendar access."
    return f"Rescheduled {event.get('summary', title)} to {_calendar_event_when(event)}."


def _calendar_rename_event(title, new_title, date_spec):
    day = _parse_calendar_date(date_spec) if date_spec else None
    if date_spec and day is None:
        return "I couldn't understand that event date. Please specify a weekday or a calendar date."
    service, error = _get_calendar_service()
    if error:
        return error
    from googleapiclient.errors import HttpError

    try:
        event, error = _calendar_find_events(service, title, day)
        if error:
            return error
        event["summary"] = new_title
        service.events().update(
            calendarId="primary", eventId=event["id"], body=event
        ).execute()
    except HttpError as exc:
        print(f"[Calendar rename error] {exc}")
        return "I couldn't rename that Google Calendar entry. Check your connection and calendar access."
    return f"Renamed the calendar entry to {new_title}."


def _calendar_set_event_field(title, date_spec, field, value):
    day = _parse_calendar_date(date_spec)
    if day is None:
        return "I couldn't understand that event date. Please specify a weekday or a calendar date."
    service, error = _get_calendar_service()
    if error:
        return error
    from googleapiclient.errors import HttpError

    try:
        event, error = _calendar_find_events(service, title, day)
        if error:
            return error
        service.events().patch(
            calendarId="primary",
            eventId=event["id"],
            body={field: value},
        ).execute()
    except HttpError as exc:
        print(f"[Calendar edit error] {exc}")
        return "I couldn't edit that Google Calendar entry. Check your connection and calendar access."
    return f"Updated the {field} for {event.get('summary', title)}."


def _calendar_delete_event(title, date_spec):
    day = _parse_calendar_date(date_spec) if date_spec else None
    if date_spec and day is None:
        return "I couldn't understand that event date. Please specify a weekday or a calendar date."
    service, error = _get_calendar_service()
    if error:
        return error
    from googleapiclient.errors import HttpError

    try:
        event, error = _calendar_find_events(service, title, day)
        if error:
            return error
        service.events().delete(
            calendarId="primary", eventId=event["id"]
        ).execute()
    except HttpError as exc:
        print(f"[Calendar delete error] {exc}")
        return "I couldn't delete that Google Calendar entry. Check your connection and calendar access."
    return f"Deleted {event.get('summary', title)} from Google Calendar."


def _split_calendar_title_schedule(body):
    for match in re.finditer(r"\s+(?:on|for)\s+", body, re.IGNORECASE):
        title = body[:match.start()].strip(" ,.")
        date_spec = body[match.end():].strip(" ,.")
        if title and _parse_calendar_date(date_spec) is not None:
            return title, date_spec
    date_match = re.search(
        r"\b(?:day after tomorrow|today|tomorrow|next\s+"
        r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}|"
        r"(?:january|february|march|april|may|june|july|august|"
        r"september|october|november|december|jan|feb|mar|apr|jun|"
        r"jul|aug|sep|oct|nov|dec)\s+\d{1,2}(?:st|nd|rd|th)?"
        r"(?:,\s*\d{4})?)\b",
        body,
        re.IGNORECASE,
    )
    if date_match:
        title = body[:date_match.start()].strip(" ,.")
        title = re.sub(r"\b(?:on|for)\s*$", "", title, flags=re.IGNORECASE).strip()
        date_spec = body[date_match.start():].strip(" ,.")
        if title and _parse_calendar_date(date_spec) is not None:
            return title, date_spec
    return None, None


def _handle_calendar_command(query):
    clean = query.strip().strip(" .,!?")
    lowered = clean.casefold()

    create_match = re.fullmatch(
        r"(?:please\s+)?(?:add|create|schedule|book)\s+"
        r"(?:(?:a|an)\s+)?(?:(?P<kind>task|event|meeting|appointment)\s+)?"
        r"(?P<body>.+)",
        clean,
        re.IGNORECASE,
    )
    if create_match:
        title, date_spec = _split_calendar_title_schedule(
            create_match.group("body")
        )
        if title and date_spec:
            kind = (create_match.group("kind") or "event").casefold()
            return _calendar_create_event(title, kind, date_spec)
        if re.search(r"\b(?:task|event|meeting|appointment)\b", clean, re.IGNORECASE):
            return (
                "Tell me the entry name and date, for example: "
                "'add task finish report tomorrow at 3 PM' or "
                "'schedule meeting with Alex on Friday at 2 PM'."
            )

    reschedule_match = re.fullmatch(
        r"(?:please\s+)?(?:reschedule|move|change|edit|update)\s+"
        r"(?:(?:the\s+)?(?:calendar\s+)?(?:event|task|meeting|appointment)\s+)?"
        r"(?P<title>.+?)\s+(?:from|on)\s+(?P<old_date>.+?)\s+to\s+"
        r"(?P<new_date>.+)",
        clean,
        re.IGNORECASE,
    )
    if reschedule_match:
        return _calendar_reschedule_event(
            reschedule_match.group("title").strip(),
            reschedule_match.group("old_date").strip(),
            reschedule_match.group("new_date").strip(),
        )

    rename_match = re.fullmatch(
        r"(?:please\s+)?rename\s+(?:(?:the\s+)?(?:calendar\s+)?"
        r"(?:event|task|meeting)\s+)?(?P<title>.+?)\s+to\s+"
        r"(?P<new_title>.+?)\s+on\s+(?P<date>.+)",
        clean,
        re.IGNORECASE,
    )
    if rename_match:
        return _calendar_rename_event(
            rename_match.group("title").strip(),
            rename_match.group("new_title").strip(),
            rename_match.group("date").strip(),
        )

    field_match = re.fullmatch(
        r"(?:please\s+)?(?:set|change|update|edit)\s+(?:the\s+)?"
        r"(?P<field>location|description)\s+(?:of\s+)?(?:the\s+)?"
        r"(?:calendar\s+)?(?:event|task|meeting|appointment)\s+"
        r"(?P<title>.+?)\s+on\s+(?P<date>.+?)\s+to\s+(?P<value>.+)",
        clean,
        re.IGNORECASE,
    )
    if field_match:
        return _calendar_set_event_field(
            field_match.group("title").strip(),
            field_match.group("date").strip(),
            field_match.group("field").casefold(),
            field_match.group("value").strip(),
        )

    delete_match = re.fullmatch(
        r"(?:please\s+)?(?:delete|remove|cancel)\s+"
        r"(?:(?:the\s+)?(?:calendar\s+)?(?:event|task|meeting|appointment)\s+)"
        r"(?P<title>.+?)(?:\s+on\s+(?P<date>.+))?",
        clean,
        re.IGNORECASE,
    )
    if delete_match:
        return _calendar_delete_event(
            delete_match.group("title").strip(),
            delete_match.group("date"),
        )

    if re.search(r"\b(?:calendar|schedule|agenda|events?|tasks?)\b", lowered) and re.search(
        r"\b(?:what|show|read|check|list|tell|have|schedule|agenda|events?|tasks?)\b",
        lowered,
    ):
        return _calendar_read_schedule(clean)
    return None


class _EmailHTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)


def _decode_email_body(payload):
    plain_parts = []
    html_parts = []
    pending = [payload]
    while pending:
        part = pending.pop()
        body = part.get("body", {})
        data = body.get("data")
        if data:
            try:
                decoded = base64.urlsafe_b64decode(data + "==").decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, TypeError) as exc:
                print(f"[Gmail message notice] Could not decode an email part: {exc}")
                decoded = ""
            if part.get("mimeType") == "text/plain":
                plain_parts.append(decoded)
            elif part.get("mimeType") == "text/html":
                html_parts.append(decoded)
        pending.extend(part.get("parts", []))

    if plain_parts:
        return "\n".join(plain_parts).strip()
    if html_parts:
        parser = _EmailHTMLText()
        for html in html_parts:
            parser.feed(html)
        return "\n".join(parser.parts).strip()
    return ""


def get_mail_brief():
    """Reads recent inbox messages from the connected Gmail account."""
    service, error = _get_gmail_service()
    if error:
        return error

    from googleapiclient.errors import HttpError

    try:
        result = service.users().messages().list(
            userId="me", q="in:inbox", maxResults=3
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return "Your Gmail inbox is empty."

        brief = ["Here are your latest Gmail messages."]
        for index, item in enumerate(messages, start=1):
            message = service.users().messages().get(
                userId="me", id=item["id"], format="full"
            ).execute()
            headers = {
                header["name"].lower(): header["value"]
                for header in message.get("payload", {}).get("headers", [])
            }
            sender = headers.get("from", "Unknown sender")
            subject = headers.get("subject", "No subject")
            body = _decode_email_body(message.get("payload", {}))
            if not body:
                body = message.get("snippet", "")
            body = re.sub(r"\s+", " ", body).strip()[:900]
            brief.append(
                f"Email {index}. From {sender}. Subject: {subject}. "
                f"Message: {body or 'No message text.'}"
            )
        return " ".join(brief)
    except HttpError as exc:
        print(f"[Gmail read error] {exc}")
        return "I couldn't read Gmail. Check your connection and account access."


def _gmail_address(value):
    address = parseaddr(value.strip().strip("<>").strip(".,;:"))[1]
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
        return None
    return address


def _create_gmail_draft(recipient, subject, body):
    global _pending_email
    service, error = _get_gmail_service()
    if error:
        return error

    message = EmailMessage()
    message["To"] = recipient
    if subject:
        message["Subject"] = subject
    message.set_content(body)
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    from googleapiclient.errors import HttpError

    try:
        draft = service.users().drafts().create(
            userId="me", body={"message": {"raw": raw_message}}
        ).execute()
    except HttpError as exc:
        print(f"[Gmail draft error] {exc}")
        return "I couldn't save the Gmail draft. Check your connection and account access."

    _pending_email = {
        "draft_id": draft["id"],
        "recipient": recipient,
        "subject": subject,
    }
    subject_preview = subject or "No subject"
    return (
        f"Draft saved in Gmail to {recipient}. Subject: {subject_preview}. "
        f"Message: {body[:500]}. To send it, say: "
        f"confirm send email to {recipient}. Nothing has been sent yet."
    )


def _confirm_gmail_send(recipient):
    global _pending_email
    if not _pending_email:
        return "There is no prepared Gmail draft to send."
    if not recipient:
        return (
            f"To confirm, say: confirm send email to "
            f"{_pending_email['recipient']}."
        )
    if recipient.lower() != _pending_email["recipient"].lower():
        return (
            f"The prepared draft is addressed to {_pending_email['recipient']}, "
            "so I did not send it. Review or create the correct draft first."
        )

    service, error = _get_gmail_service()
    if error:
        return error

    from googleapiclient.errors import HttpError

    try:
        service.users().drafts().send(
            userId="me", body={"id": _pending_email["draft_id"]}
        ).execute()
    except HttpError as exc:
        print(f"[Gmail send error] {exc}")
        return "Gmail could not send the draft. It remains unsent."

    sent_to = _pending_email["recipient"]
    _pending_email = None
    return f"Email sent to {sent_to}."


def _message_platform_url(platform, contact, message):
    encoded_message = urllib.parse.quote(message, safe="")
    normalized = platform.lower()
    if normalized in ("whatsapp", "whats app"):
        return f"https://web.whatsapp.com/send?text={encoded_message}"
    if normalized in ("telegram",):
        username = contact.strip().lstrip("@")
        if re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            return f"https://t.me/{username}?text={encoded_message}"
        return "https://web.telegram.org/"
    if normalized in ("discord",):
        return "https://discord.com/channels/@me"
    if normalized in ("instagram",):
        return "https://www.instagram.com/direct/inbox/"
    if normalized in ("x", "twitter"):
        return f"https://x.com/messages/compose?text={encoded_message}"
    if normalized in ("facebook", "messenger"):
        return "https://www.messenger.com/"
    if normalized in ("snapchat",):
        return "https://web.snapchat.com/"
    return None


def _copy_message_to_clipboard(message):
    if sys.platform == "win32":
        encoded_message = base64.b64encode(message.encode("utf-8")).decode("ascii")
        succeeded, _detail = _run_powershell(
            "$message = [Text.Encoding]::UTF8.GetString("
            f"[Convert]::FromBase64String('{encoded_message}')); "
            "Set-Clipboard -Value $message"
        )
        return succeeded
    clipboard_command = (
        ["pbcopy"] if sys.platform == "darwin"
        else ["wl-copy"] if shutil.which("wl-copy")
        else ["xclip", "-selection", "clipboard"] if shutil.which("xclip")
        else None
    )
    if not clipboard_command:
        return False
    try:
        result = subprocess.run(
            clipboard_command,
            input=message.encode("utf-8"),
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[Message draft notice] Could not copy message to clipboard: {exc}")
        return False
    return result.returncode == 0


def draft_social_message(platform, contact_name, message):
    """Opens the selected app so the user can choose the recipient and send."""
    url = _message_platform_url(platform, contact_name, message)
    if not url:
        return f"I don't have a message handoff for {platform} yet."
    if not _open([url]):
        return f"I couldn't open {platform}. Your message has not been sent."
    copied = _copy_message_to_clipboard(message)
    clipboard_note = (
        " Your message is copied; paste it after selecting the recipient."
        if copied
        else f" Your draft is: {message}"
    )
    return (
        f"Opened {platform} for {contact_name}."
        f"{' It was requested minimized.' if _background_mode.get() else ''}"
        f"{clipboard_note} Search and "
        "choose the exact or closest matching person in the app, review the "
        "message, and press Send there. Jarvis did not send it."
    )


def _whatsapp_text_key(value):
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _whatsapp_row_name(row, by):
    for selector in ("span[title]", "[title]"):
        for element in row.find_elements(by.CSS_SELECTOR, selector):
            title = element.get_attribute("title")
            if title and title.strip():
                return title.strip()
    text = row.inner_text().strip()
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _send_from_whatsapp_page(page, contact, message):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    search_candidates = page.find_elements(
        By.CSS_SELECTOR,
        'div[contenteditable="true"][data-tab="3"], '
        'div[contenteditable="true"][role="textbox"][aria-label*="Search"]',
    )
    search = next((item for item in search_candidates if item.is_displayed()), None)
    if search is None:
        return {
            "status": "login",
            "message": (
                "WhatsApp Web is open but not signed in. Scan its QR code, "
                "then repeat the message command."
            ),
        }

    search.click()
    search.send_keys(Keys.CONTROL, "a")
    search.send_keys(contact)
    time.sleep(1.2)

    rows = page.find_elements(By.CSS_SELECTOR, '[role="listitem"]')
    if not rows:
        rows = page.find_elements(By.CSS_SELECTOR, '[data-testid="cell-frame-container"]')
    candidates = []
    exact_rows = []
    wanted = _whatsapp_text_key(contact)
    for row in rows[:40]:
        if not row.is_displayed():
            continue
        name = _whatsapp_row_name(row, By)
        if not name:
            continue
        candidates.append(name)
        if _whatsapp_text_key(name) == wanted:
            exact_rows.append((name, row))

    if len(exact_rows) > 1:
        return {
            "status": "match",
            "matches": [name for name, _row in exact_rows[:3]],
        }
    if not exact_rows:
        scores = sorted(
            (
                difflib.SequenceMatcher(
                    None, wanted, _whatsapp_text_key(name)
                ).ratio(),
                name,
            )
            for name in set(candidates)
            if _whatsapp_text_key(name)
        )
        matches = [name for _score, name in reversed(scores[-3:]) if _score >= 0.45]
        if matches:
            return {"status": "match", "matches": matches[:3]}
        return {"status": "not_found", "message": f"I couldn't find {contact} in WhatsApp."}

    matched_name, matched_row = exact_rows[0]
    matched_row.click()
    time.sleep(0.5)
    headers = page.find_elements(By.TAG_NAME, "header")
    header = headers[-1] if headers else None
    if header is None or not header.is_displayed():
        return {
            "status": "error",
            "message": f"I couldn't verify the WhatsApp chat for {matched_name}; nothing was sent.",
        }
    header_text = header.inner_text().strip()
    header_key = _whatsapp_text_key(header_text)
    matched_key = _whatsapp_text_key(matched_name)
    if matched_key not in header_key:
        return {
            "status": "error",
            "message": f"The open chat did not match {matched_name}; nothing was sent.",
        }

    composers = page.find_elements(
        By.CSS_SELECTOR,
        'footer [contenteditable="true"][role="textbox"], '
        'footer [contenteditable="true"]',
    )
    composer = next(
        (item for item in reversed(composers) if item.is_displayed()), None
    )
    if composer is None:
        return {
            "status": "error",
            "message": f"I couldn't find the message box for {matched_name}; nothing was sent.",
        }

    composer.send_keys(message)
    send_buttons = page.find_elements(
        By.CSS_SELECTOR, 'button[aria-label="Send"], [data-testid="send"]'
    )
    send_button = next(
        (item for item in reversed(send_buttons) if item.is_displayed()), None
    )
    if send_button is None:
        composer.send_keys(Keys.CONTROL, "a")
        composer.send_keys(Keys.BACKSPACE)
        return {
            "status": "error",
            "message": f"I couldn't verify the Send button for {matched_name}; nothing was sent.",
        }

    from jarvis_voice import speak

    speak(
        f"Sending this message to {matched_name}: {message}",
        print_output=False,
    )
    send_button.click()
    return {"status": "sent", "contact": matched_name}


def _whatsapp_worker():
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    driver = None
    driver_minimized = False
    while True:
        event, result, contact, message, minimize = _whatsapp_jobs.get()
        try:
            if driver is None:
                options = Options()
                options.add_argument(
                    f"--user-data-dir={_jarvis_profile_path('whatsapp_web_profile')}"
                )
                if minimize:
                    options.add_argument("--start-minimized")
                driver = webdriver.Edge(options=options)
                driver.set_page_load_timeout(30)
            elif driver_minimized and not minimize:
                driver.maximize_window()
                driver_minimized = False
            if not driver.current_url.startswith("https://web.whatsapp.com"):
                driver.get("https://web.whatsapp.com/")
            result["value"] = _send_from_whatsapp_page(
                driver, contact, message
            )
            if minimize:
                driver.minimize_window()
                driver_minimized = True
                if result["value"].get("status") == "login":
                    result["value"]["message"] += (
                        " Restore the minimized Edge window to scan the QR code."
                    )
        except Exception as exc:
            print(f"[WhatsApp automation error] {exc}")
            if driver is not None:
                try:
                    driver.quit()
                except Exception as close_error:
                    print(f"[WhatsApp browser cleanup error] {close_error}")
                driver = None
                driver_minimized = False
            result["value"] = {
                "status": "error",
                "message": (
                    "WhatsApp Web automation failed. Check its Edge window "
                    f"and sign-in status: {exc}"
                ),
            }
        finally:
            event.set()
            _whatsapp_jobs.task_done()


def _send_whatsapp_message(contact, message):
    global _whatsapp_worker_thread
    with _whatsapp_worker_lock:
        if _whatsapp_worker_thread is None or not _whatsapp_worker_thread.is_alive():
            _whatsapp_worker_thread = threading.Thread(
                target=_whatsapp_worker,
                name="jarvis-whatsapp",
                daemon=True,
            )
            _whatsapp_worker_thread.start()

    event = threading.Event()
    result = {}
    _whatsapp_jobs.put(
        (event, result, contact, message, _background_mode.get())
    )
    if not event.wait(timeout=90):
        return {
            "status": "error",
            "message": "WhatsApp is taking too long to respond. Check its Edge window.",
        }
    return result["value"]


def _handle_social_command(query):
    global _pending_social
    clean = query.strip()
    lowered = clean.lower().strip(" .,!?")
    if lowered in ("cancel message", "cancel the message", "discard message"):
        _pending_social = None
        return "Cancelled the message draft. Nothing was sent."

    confirmation = re.fullmatch(
        r"(?:yes|yes send|confirm|confirm send|send it|"
        r"yes send to .+|confirm send to .+)",
        lowered,
    )
    if confirmation and _pending_social and _pending_social.get("awaiting") == "match":
        pending = _pending_social
        named_match = re.fullmatch(
            r"(?:yes send to|confirm send to)\s+(.+)", lowered
        )
        if (
            named_match
            and _whatsapp_text_key(named_match.group(1))
            != _whatsapp_text_key(pending["candidate"])
        ):
            return (
                f"The closest match is {pending['candidate']}. "
                f"Say 'yes send to {pending['candidate']}' to confirm, "
                "or 'cancel message'."
            )
        _pending_social = None
        outcome = _send_whatsapp_message(
            pending["candidate"], pending["message"]
        )
        if outcome["status"] == "sent":
            return f"Sent your message to {outcome['contact']}."
        return outcome["message"]

    if lowered in ("no", "no cancel", "don't send", "do not send") and _pending_social:
        _pending_social = None
        return "Cancelled the message. Nothing was sent."

    patterns = (
        re.compile(
            r"(?:please\s+)?send\s+(?P<body>.+?)\s+to\s+(?P<contact>.+?)"
            r"\s+(?:on|in|via)\s+(?P<platform>whats\s*app|whatsapp|discord|"
            r"instagram|telegram|twitter|x|facebook|messenger|snapchat)"
            r"\s*[.!?]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:please\s+)?(?:send\s+(?:a\s+)?message\s+to|message\s+(?:to\s+)?)"
            r"(?P<contact>.+?)\s+(?:on|in|via)\s+"
            r"(?P<platform>whats\s*app|whatsapp|discord|instagram|telegram|"
            r"twitter|x|facebook|messenger|snapchat)"
            r"(?:\s+(?:saying|that says|message)\s*|:\s*)?(?P<body>.*)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:please\s+)?message\s+(?P<contact>.+?)\s+(?:on|in|via)\s+"
            r"(?P<platform>whats\s*app|whatsapp|discord|instagram|telegram|"
            r"twitter|x|facebook|messenger|snapchat)"
            r"(?:\s+(?:saying|that says)\s+(?P<body>.+))?$",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:please\s+)?(?:send|reply)\s+(?:a\s+)?message\s+(?:on\s+)?"
            r"(?P<platform>whats\s*app|whatsapp)\s+to\s+(?P<contact>.+?)"
            r"(?:\s+(?:saying|that says)\s+(?P<body>.+))?$",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:please\s+)?(?:send|reply)\s+(?P<platform>whats\s*app|whatsapp)"
            r"\s+message\s+to\s+(?P<contact>.+?)"
            r"(?:\s+(?:saying|that says)\s+(?P<body>.+))?$",
            re.IGNORECASE,
        ),
    )
    parsed = None
    for pattern in patterns:
        parsed = pattern.fullmatch(clean)
        if parsed:
            break
    if parsed:
        contact = parsed.group("contact").strip().strip("()[]{}\"'")
        platform = re.sub(r"\s+", "", parsed.group("platform").lower())
        body = (parsed.groupdict().get("body") or "").strip().strip("\"'")
        if not body:
            _pending_social = {"contact": contact, "platform": platform}
            return (
                f"What should the message to {contact} on {platform} say? "
                "Dictate it now, or say 'cancel message'."
            )
        if platform in ("whatsapp",):
            outcome = _send_whatsapp_message(contact, body)
            if outcome["status"] == "sent":
                return f"Sent your message to {outcome['contact']}."
            if outcome["status"] == "match":
                candidate = outcome["matches"][0]
                _pending_social = {
                    "awaiting": "match",
                    "candidate": candidate,
                    "contact": contact,
                    "message": body,
                    "platform": platform,
                }
                return (
                    f"I couldn't find an exact match for {contact}. The closest "
                    f"match is {candidate}. I would send: {body}. Say "
                    f"'yes send to {candidate}' to confirm, or 'cancel message'."
                )
            return outcome["message"]
        return draft_social_message(platform, contact, body)

    if _pending_social and _pending_social.get("awaiting") == "match":
        return (
            f"Please say 'yes send to {_pending_social['candidate']}' to confirm "
            "the closest WhatsApp match, or 'cancel message'."
        )

    if _pending_social:
        if lowered.startswith("message body "):
            clean = clean[len("message body "):].strip()
        pending = _pending_social
        _pending_social = None
        if pending["platform"] == "whatsapp":
            outcome = _send_whatsapp_message(pending["contact"], clean)
            if outcome["status"] == "sent":
                return f"Sent your message to {outcome['contact']}."
            if outcome["status"] == "match":
                candidate = outcome["matches"][0]
                _pending_social = {
                    "awaiting": "match",
                    "candidate": candidate,
                    "contact": pending["contact"],
                    "message": clean,
                    "platform": "whatsapp",
                }
                return (
                    f"I couldn't find an exact match for {pending['contact']}. "
                    f"The closest match is {candidate}. I would send: {clean}. "
                    f"Say 'yes send to {candidate}' to confirm, or 'cancel message'."
                )
            return outcome["message"]
        return draft_social_message(pending["platform"], pending["contact"], clean)

    return None


def _handle_email_command(query):
    global _pending_email
    clean = query.strip()
    lowered = clean.lower().strip(" .,!?")

    if lowered in ("cancel email", "cancel the email", "discard email"):
        _pending_email = None
        return "Cancelled the pending email. Nothing was sent."

    match = re.fullmatch(
        r"(?:please\s+)?confirm\s+send\s+(?:the\s+)?email(?:\s+to\s+(.+))?",
        lowered,
    )
    if match:
        recipient = _gmail_address(match.group(1)) if match.group(1) else None
        return _confirm_gmail_send(recipient)

    match = re.match(
        r"(?:please\s+)?(?:compose|write|draft)\s+(?:an?\s+)?"
        r"(?:email|mail)\s+to\s+(<[^>]+>|[^\s,;]+)(.*)$",
        clean,
        re.IGNORECASE,
    )
    if match:
        recipient = _gmail_address(match.group(1))
        if not recipient:
            return "Please provide a full email address, for example: compose email to tony23@gmail.com."

        tail = match.group(2).strip()
        subject_match = re.search(
            r"\bsubject\s*[:=]?\s*(.+?)(?=\b(?:saying|body|message)\b|$)",
            tail,
            re.IGNORECASE,
        )
        subject = subject_match.group(1).strip(" .,:;") if subject_match else ""
        body_match = re.search(
            r"\b(?:saying|body|message)\s*[:=]?\s*(.+)$",
            tail,
            re.IGNORECASE,
        )
        body = body_match.group(1).strip() if body_match else ""
        if body:
            return _create_gmail_draft(recipient, subject, body)

        _service, error = _get_gmail_service()
        if error:
            return error
        _pending_email = {"recipient": recipient, "subject": subject}
        return (
            f"Ready to compose an email to {recipient}. Dictate the message now, "
            "optionally starting with 'subject ...'. Say 'cancel email' to stop."
        )

    if _pending_email and "draft_id" not in _pending_email:
        if lowered.startswith("subject "):
            subject, separator, body = clean[8:].partition(" body ")
            if separator and body.strip():
                return _create_gmail_draft(
                    _pending_email["recipient"], subject.strip(), body.strip()
                )
            _pending_email["subject"] = subject.strip()
            return "Subject noted. Dictate the email message, or say 'cancel email'."
        if lowered.startswith("email body "):
            clean = clean[len("email body "):].strip()
        return _create_gmail_draft(
            _pending_email["recipient"], _pending_email["subject"], clean
        )
    return None


def try_action(q):
    """Execute an action while sharing background launch intent with its helpers."""
    with background_command(q) as command:
        return _try_action(command)


def _try_action(q):
    """
    Executes instant deterministic actions. Returns response string if handled,
    or None to pass to the AI brain.
    """
    q_clean = q.lower().strip(" .,!?")

    calendar_response = _handle_calendar_command(q)
    if calendar_response is not None:
        return calendar_response

    email_response = _handle_email_command(q)
    if email_response is not None:
        return email_response

    social_response = _handle_social_command(q)
    if social_response is not None:
        return social_response

    # 0. Stop the currently playing media without affecting other open apps.
    if re.fullmatch(
        r"(?:please\s+)?(?:stop|pause)(?:\s+(?:the\s+)?(?:music|song|track|audio|playback))?"
        r"|(?:please\s+)?stop\s+playing(?:\s+music)?",
        q_clean,
    ):
        if _stop_music():
            return "Stopped the music."
        return "I couldn't send a stop command to the active media player."

    # 0a. Close a named application or window without force-terminating it.
    m = re.match(r"(?:please\s+)?(?:close|shut|exit)\s+(.+)", q_clean)
    if m:
        target = re.sub(
            r"^(?:(?:the\s+)?(?:file|folder|window|application|app)\s+(?:named\s+)?)",
            "",
            m.group(1).strip(),
        )
        target = re.sub(r"^(?:the\s+)?|(?:\s+(?:file|folder|window|application|app))$", "", target).strip()
        if target in {
            "it", "this", "that", "file", "folder", "window", "app",
            "application", "current window", "current file",
        }:
            return "Tell me the name of the app, file, or folder you want me to close."
        if not target:
            return "Tell me the name of the app, file, or folder you want me to close."
        closed, detail = _close_window(target)
        if closed:
            return f"Closed {detail}."
        return f"I couldn't close {target}: {detail}"

    if re.fullmatch(
        r"(?:(?:please\s+)?(?:turn|switch)\s+(?:on|off)\s+(?:the\s+)?"
        r"(?:wi-?fi|wireless|bluetooth)|(?:please\s+)?(?:turn|switch)\s+"
        r"(?:the\s+)?(?:wi-?fi|wireless|bluetooth)\s+(?:on|off)|"
        r"(?:please\s+)?(?:enable|disable)\s+(?:the\s+)?"
        r"(?:wi-?fi|wireless|bluetooth)|(?:please\s+)?"
        r"(?:wi-?fi|wireless|bluetooth)\s+(?:on|off))",
        q_clean,
    ):
        return "Wi-Fi and Bluetooth controls are not available. I can change volume and brightness."

    # 0c. Set display brightness or adjust it incrementally.
    m = re.fullmatch(
        r"(?:(?:please\s+)?(?:set|change)\s+(?:the\s+)?)?"
        r"brightness(?:\s+to)?\s+(\d{1,3})\s*%?",
        q_clean,
    )
    if m:
        level = int(m.group(1))
        if not 0 <= level <= 100:
            return "Brightness must be between 0 and 100 percent."
        succeeded, detail = _set_brightness(level)
        if succeeded:
            return f"Brightness set to {level}%."
        return f"I couldn't set the brightness: {detail}"
    if q_clean in ("brightness up", "increase brightness", "brighter"):
        result, detail = _run_powershell(
            "$b = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | "
            "Select-Object -First 1; if (-not $b) { throw 'No brightness-controllable display was found.' }; "
            "Write-Output ([Math]::Min(100, $b.CurrentBrightness + 10))"
        ) if sys.platform == "win32" else (False, "Brightness controls are currently supported on Windows.")
        if result:
            succeeded, detail = _set_brightness(int(detail))
            if succeeded:
                return "Brightness increased."
        return f"I couldn't increase the brightness: {detail}"
    if q_clean in ("brightness down", "decrease brightness", "dimmer"):
        result, detail = _run_powershell(
            "$b = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | "
            "Select-Object -First 1; if (-not $b) { throw 'No brightness-controllable display was found.' }; "
            "Write-Output ([Math]::Max(0, $b.CurrentBrightness - 10))"
        ) if sys.platform == "win32" else (False, "Brightness controls are currently supported on Windows.")
        if result:
            succeeded, detail = _set_brightness(int(detail))
            if succeeded:
                return "Brightness decreased."
        return f"I couldn't decrease the brightness: {detail}"

    # 1. Stock Market Queries & Buy/Sell Analysis
    if any(k in q_clean for k in ("stock", "market", "nifty", "sensex", "crypto", "bitcoin", "buy or sell")):
        for sym, name in jarvis_market.DEFAULT_TICKERS.items():
            if name.lower() in q_clean or sym.lower().replace(".ns", "") in q_clean:
                data = jarvis_market.analyze_ticker(sym)
                if data:
                    direction = "up" if data["pct_change"] >= 0 else "down"
                    return (
                        f"{data['name']} is trading at {data['currency']}{data['price']:,}, "
                        f"{direction} {abs(data['pct_change'])}%. "
                        f"Technical indicator: {data['signal']}. {data['reason']}"
                    )
        return "Here is the market overview: " + jarvis_market.market_briefing()

    # 2. WhatsApp Auto-Message
    if q_clean in ("check whatsapp", "whatsapp"):
        _open([SITES["whatsapp"]])
        return _launch_response("Opening WhatsApp.")

    # 3. Mail Briefing
    if any(k in q_clean for k in (
        "mail brief", "check mail", "read email", "read my email",
        "read my emails", "read emails aloud", "read email aloud",
        "read inbox", "check my email", "inbox summary", "unread email",
    )):
        return get_mail_brief()

    # 4. YouTube Music / Search
    m = re.search(r"(?:play|search|find|open)\s+(.+?)\s+(?:on|in)\s+youtube", q_clean)
    if m:
        query = m.group(1).strip()
        _open(["https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)])
        return _launch_response(f"Playing {query} on YouTube.")

    # 5. Spotify Music Search
    m = re.match(r"(?:please\s+)?play\s+(.+)", q, re.IGNORECASE)
    if m:
        query = re.sub(
            r"\s+(?:on|in)\s+spotify$",
            "",
            m.group(1).strip(),
            flags=re.IGNORECASE,
        ).strip().strip("\"'")
        if query:
            if _play_spotify_search(query):
                return _launch_response(f"Playing {query} on Spotify.")
            return f"I couldn't start playback for {query} on Spotify."

    # 6. Google Search
    m = re.match(r"(?:search|google)(?: for)?\s+(.+)", q_clean)
    if m:
        query = m.group(1).strip()
        _open(["https://www.google.com/search?q=" + urllib.parse.quote(query)])
        return _launch_response(f"Searching Google for {query}.")

    # 7. App Launch
    m = re.match(r"(?:please\s+)?(?:open|launch|start)\s+(.+)", q_clean)
    if m:
        name = re.sub(r"\b(application|app)\b", "", m.group(1)).strip()
        launched = _launch_app(name)
        if launched is False:
            return f"I found {name}, but couldn't open it."
        if launched:
            app, _ = launched
            return _launch_response(f"Opening {app}.")

        local_path = _find_local_path(name)
        if local_path:
            if _open_local_path(local_path):
                return _launch_response(f"Opening {os.path.basename(local_path)}.")
            return f"I found {name}, but couldn't open it."

        website = _website_for(name)
        if website and _open([website]):
            return _launch_response(f"I couldn't find {name} locally; opening {website}.")
        return f"I couldn't find {name} locally or open its website."

    # 8. Volume Controls
    m = re.fullmatch(
        r"(?:please\s+)?(?:(?:turn|set|make)\s+)?(?:the\s+)?volume\s+to\s+(\d{1,3})\s*%?",
        q_clean,
    )
    if m:
        level = int(m.group(1))
        if not 0 <= level <= 100:
            return "Volume must be between 0 and 100 percent."
        if _set_volume(level / 100):
            return f"Volume set to {level}%."
        return "I couldn't set the system volume."
    if q_clean in (
        "volume up", "turn volume up", "turn the volume up",
        "increase volume", "increase the volume", "louder",
    ):
        if _adjust_volume("up"):
            return "Volume increased."
        return "I couldn't increase the system volume."
    if q_clean in (
        "volume down", "turn volume down", "turn the volume down",
        "decrease volume", "decrease the volume", "quieter",
    ):
        if _adjust_volume("down"):
            return "Volume decreased."
        return "I couldn't decrease the system volume."
    if q_clean in ("mute", "mute volume", "mute the volume"):
        if _adjust_volume("mute"):
            return "System audio muted."
        return "I couldn't mute the system audio."
    if q_clean in ("unmute", "unmute volume", "unmute the volume"):
        if _adjust_volume("unmute"):
            return "System audio unmuted."
        return "I couldn't unmute the system audio."

    # 9. Date and Time
    if "time" in q_clean:
        return "It is currently " + datetime.datetime.now().strftime("%I:%M %p")
    if "date" in q_clean or "today" in q_clean:
        return "Today is " + datetime.datetime.now().strftime("%A, %B %d, %Y")

    return None
