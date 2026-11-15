"""Throwaway transport diagnostic. No discovery, pairing or file transfers."""
import argparse
import datetime
import importlib.metadata
import json
import platform
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def probe(kind):
    if kind == "classic":
        import IOBluetooth

        controller = IOBluetooth.IOBluetoothHostController.defaultController()
        return {
            "controller_present": controller is not None,
            "rfcomm_class_present": hasattr(IOBluetooth, "IOBluetoothRFCOMMChannel"),
            "connection_tested": False,
        }
    import CoreBluetooth as CB
    from Foundation import NSDate, NSDefaultRunLoopMode, NSRunLoop

    manager = CB.CBCentralManager.alloc().initWithDelegate_queue_options_(None, None, None)
    deadline = time.monotonic() + 5
    while int(manager.state()) in (0, 1) and time.monotonic() < deadline:
        NSRunLoop.currentRunLoop().runMode_beforeDate_(
            NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )
    states = {0: "unknown", 1: "resetting", 2: "unsupported", 3: "unauthorized", 4: "powered_off", 5: "powered_on"}
    state = int(manager.state())
    return {"state": states.get(state, str(state)), "connection_tested": False}


def isolated_probe(kind):
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--internal-probe", kind],
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "connection_tested": False}
    if result.returncode:
        # Native error output can contain identifying information; don't collect it.
        return {"status": "process_failed", "returncode": result.returncode,
                "connection_tested": False}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "invalid_probe_output", "connection_tested": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine", choices=["local-arm64", "peer-intel"])
    parser.add_argument("--probe-bluetooth", action="store_true")
    parser.add_argument("--internal-probe", choices=["classic", "ble"], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.internal_probe:
        try:
            data = {"status": "observed", **probe(args.internal_probe)}
        except Exception as exc:
            data = {"status": "error", "error_type": type(exc).__name__, "connection_tested": False}
        print(json.dumps(data))
        return
    if not args.machine:
        parser.error("--machine is required")
    if platform.system() != "Darwin":
        parser.error("run on macOS")
    expected = {"local-arm64": "arm64", "peer-intel": "x86_64"}[args.machine]
    if platform.machine() != expected:
        parser.error(f"machine label expects {expected}, found {platform.machine()}")
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True)
    dependencies = {}
    for name in ("pyobjc-core", "pyobjc-framework-IOBluetooth", "pyobjc-framework-CoreBluetooth"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    now = datetime.datetime.now(datetime.timezone.utc)
    report = {
        "schema_version": 1, "checkpoint": "CP001", "machine": args.machine,
        "timestamp_utc": now.isoformat(), "macos": platform.mac_ver()[0],
        "architecture": platform.machine(), "python": platform.python_version(),
        "revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "working_tree_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        "dependencies": dependencies,
        "bluetooth": {"status": "not_requested", "connection_tested": False},
    }
    if args.probe_bluetooth:
        report["bluetooth"] = {kind: isolated_probe(kind) for kind in ("classic", "ble")}
    target = ROOT / "reports" / f"{args.machine}-{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Report: {target}")


if __name__ == "__main__":
    main()
