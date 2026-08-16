"""
service.py

PrivacyGate Windows Background Service.
Starts api.py (FastAPI) silently on Windows boot.
No console window. No user interaction needed.

Two ways to use:

  1. INSTALL as Windows service (runs on boot, survives logout):
       python service.py install
       python service.py start

  2. RUN directly (for development/testing):
       python service.py run

  3. STOP + REMOVE:
       python service.py stop
       python service.py remove

Requirements:
  pip install pywin32
  After install: python Scripts/pywin32_postinstall.py -install

How it works:
  - Uses pywin32 to register as a real Windows service
  - On start: launches uvicorn serving api.py on 127.0.0.1:8000
  - On stop: gracefully shuts down uvicorn
  - Logs to C:\ProgramData\PrivacyGate\service.log
"""

import os
import sys
import time
import signal
import logging
import subprocess
from pathlib import Path

# ─────────────────────────────────────────────────────────
# LOGGING — writes to C:\ProgramData\PrivacyGate\service.log
# ─────────────────────────────────────────────────────────

LOG_DIR  = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "PrivacyGate"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "service.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
    ]
)
log = logging.getLogger("PrivacyGate")

# ─────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────

BASE_DIR   = Path(__file__).resolve().parent
API_PATH   = BASE_DIR / "api.py"
PYTHON_EXE = sys.executable   # same Python that runs this script
PORT       = 8000
HOST       = "127.0.0.1"

# ─────────────────────────────────────────────────────────
# UVICORN PROCESS MANAGER
# ─────────────────────────────────────────────────────────

_uvicorn_proc = None


def _start_uvicorn():
    """Launch uvicorn as a subprocess. Returns the Popen object."""
    global _uvicorn_proc

    cmd = [
        PYTHON_EXE, "-m", "uvicorn",
        "api:app",
        "--host", HOST,
        "--port", str(PORT),
        "--log-level", "error",
        "--no-access-log",
    ]

    # CREATE_NO_WINDOW = 0x08000000
    # Prevents a console window from appearing on Windows
    CREATE_NO_WINDOW = 0x08000000

    _uvicorn_proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    log.info(f"PrivacyGate API started — PID {_uvicorn_proc.pid} — {HOST}:{PORT}")
    return _uvicorn_proc


def _stop_uvicorn():
    """Gracefully stop the uvicorn subprocess."""
    global _uvicorn_proc

    if _uvicorn_proc is None:
        return

    try:
        _uvicorn_proc.terminate()
        _uvicorn_proc.wait(timeout=10)
        log.info("PrivacyGate API stopped.")
    except subprocess.TimeoutExpired:
        _uvicorn_proc.kill()
        log.warning("PrivacyGate API force-killed.")
    except Exception as e:
        log.error(f"Error stopping API: {e}")
    finally:
        _uvicorn_proc = None


# ─────────────────────────────────────────────────────────
# WINDOWS SERVICE  (pywin32)
# ─────────────────────────────────────────────────────────

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


if HAS_WIN32:

    class PrivacyGateService(win32serviceutil.ServiceFramework):
        _svc_name_        = "PrivacyGate"
        _svc_display_name_ = "PrivacyGate Privacy Service"
        _svc_description_  = (
            "PrivacyGate local privacy scanning service. "
            "Scans files and text for PII before they reach AI tools. "
            "Required for the PrivacyGate Chrome extension."
        )

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)

        def SvcStop(self):
            """Called by Windows when the service is stopped."""
            log.info("Service stop requested.")
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            _stop_uvicorn()
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):
            """Main service loop — called when service starts."""
            log.info("PrivacyGate service starting.")
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, "")
            )

            _start_uvicorn()

            # Wait until stop is requested
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
            log.info("PrivacyGate service stopped.")


# ─────────────────────────────────────────────────────────
# DIRECT RUN MODE  (for development / testing)
# Runs the API directly in this process without Windows service.
# Press Ctrl+C to stop.
# ─────────────────────────────────────────────────────────

def run_direct():
    """Run the API directly — for development and testing."""
    import uvicorn

    log.info(f"PrivacyGate running directly on {HOST}:{PORT}")
    print(f"\n  PrivacyGate API running at http://{HOST}:{PORT}")
    print(f"  Press Ctrl+C to stop.\n")

    uvicorn.run(
        "api:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )


# ─────────────────────────────────────────────────────────
# STARTUP ENTRY  — called by installer to register autostart
# ─────────────────────────────────────────────────────────

def add_to_startup():
    """
    Add PrivacyGate to Windows startup via registry.
    This is a fallback if Windows service install fails.
    Runs service.py on login with a hidden window.
    """
    try:
        import winreg

        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE
        )

        # pythonw.exe runs without a console window
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        if not pythonw.exists():
            pythonw = sys.executable  # fallback

        cmd = f'"{pythonw}" "{BASE_DIR / "service.py"}" run'
        winreg.SetValueEx(key, "PrivacyGate", 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)

        log.info(f"Added to startup registry: {cmd}")
        print(f"  PrivacyGate added to Windows startup.")
        return True

    except Exception as e:
        log.error(f"Could not add to startup: {e}")
        print(f"  Warning: Could not add to startup: {e}")
        return False


def remove_from_startup():
    """Remove PrivacyGate from Windows startup registry."""
    try:
        import winreg
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, "PrivacyGate")
        winreg.CloseKey(key)
        print("  PrivacyGate removed from Windows startup.")
    except FileNotFoundError:
        pass  # Not in startup — that's fine
    except Exception as e:
        print(f"  Warning: {e}")


# ─────────────────────────────────────────────────────────
# MAIN — command line interface
# ─────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args:
        print("""
PrivacyGate Service Manager

Usage:
  python service.py run          Run directly (development mode)
  python service.py install      Install as Windows service
  python service.py start        Start the Windows service
  python service.py stop         Stop the Windows service
  python service.py remove       Remove the Windows service
  python service.py startup      Add to Windows startup (registry)
  python service.py nostartup    Remove from Windows startup
        """)
        return

    command = args[0].lower()

    if command == "run":
        run_direct()
        return

    if command == "startup":
        add_to_startup()
        return

    if command == "nostartup":
        remove_from_startup()
        return

    # Windows service commands — need pywin32
    if not HAS_WIN32:
        print("Error: pywin32 not installed.")
        print("Install: pip install pywin32")
        print("Then run: python Scripts/pywin32_postinstall.py -install")
        sys.exit(1)

    if command == "install":
        win32serviceutil.InstallService(
            PrivacyGateService._svc_reg_class_,
            PrivacyGateService._svc_name_,
            PrivacyGateService._svc_display_name_,
            startType=win32service.SERVICE_AUTO_START,
            description=PrivacyGateService._svc_description_,
        )
        print("  PrivacyGate service installed.")
        print("  Run: python service.py start")

    elif command == "start":
        win32serviceutil.StartService(PrivacyGateService._svc_name_)
        print("  PrivacyGate service started.")

    elif command == "stop":
        win32serviceutil.StopService(PrivacyGateService._svc_name_)
        print("  PrivacyGate service stopped.")

    elif command == "remove":
        try:
            win32serviceutil.StopService(PrivacyGateService._svc_name_)
        except Exception:
            pass
        win32serviceutil.RemoveService(PrivacyGateService._svc_name_)
        print("  PrivacyGate service removed.")

    else:
        # Pass unknown commands to pywin32 handler
        # (handles 'debug', 'restart', etc.)
        win32serviceutil.HandleCommandLine(PrivacyGateService)


if __name__ == "__main__":
    # If called by Windows SCM directly — handle as service
    if len(sys.argv) == 1 and HAS_WIN32:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(PrivacyGateService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        main()