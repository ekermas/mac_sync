"""CP002 throwaway RFCOMM probe. Exchanges fixed data only, never user files."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BLOCK = bytes(range(256)) * 16
DIGEST = hashlib.sha256(BLOCK).hexdigest()
REQUEST = b"MACSYNC-CP002\n" + BLOCK
ACK = b"SHA256 " + DIGEST.encode() + b"\n"


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("role", choices=["listen", "connect", "self-test"])
    p.add_argument("--machine", choices=["local-arm64", "peer-intel"])
    p.add_argument("--address", help="listener Bluetooth address; never saved in report")
    p.add_argument("--channel", type=int, default=7)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()
    if not 1 <= args.channel <= 30 or not 5 <= args.timeout <= 600:
        p.error("channel must be 1..30; timeout 5..600 seconds")
    if args.role != "self-test":
        if platform.system() != "Darwin":
            p.error("macOS required")
        expected = {"local-arm64": "arm64", "peer-intel": "x86_64"}
        if args.machine not in expected or platform.machine() != expected[args.machine]:
            p.error("--machine must match this Mac architecture")
        if args.role == "connect" and not re.fullmatch(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", args.address or ""):
            p.error("connect requires --address AA:BB:CC:DD:EE:FF")
    return args


class Receiver:
    """Bounded parser that accepts arbitrary RFCOMM fragmentation."""
    def __init__(self, expected):
        self.expected = expected
        self.data = bytearray()

    def feed(self, data):
        self.data.extend(data)
        if len(self.data) > len(self.expected) or self.data != self.expected[:len(self.data)]:
            raise ValueError("unexpected_test_data")
        return len(self.data) == len(self.expected)


def self_test():
    for message in (REQUEST, ACK):
        for size in (1, 17, 127, 1024, len(message)):
            receiver = Receiver(message)
            for offset in range(0, len(message), size):
                complete = receiver.feed(message[offset:offset + size])
            assert complete
        for invalid in (b"!", message + b"!"):
            try:
                Receiver(message).feed(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("corruption was accepted")
    print("PASS: request/ACK fragmentation, corruption and length bounds; no Bluetooth tested")


def run_worker(args):
    import objc
    import IOBluetooth as B
    from Foundation import NSObject, NSRunLoop, NSDate, NSDefaultRunLoopMode, NSData

    class Delegate(NSObject, protocols=[objc.protocolNamed("IOBluetoothRFCOMMChannelDelegate")]):
        def init(self):
            self = objc.super(Delegate, self).init()
            if self is not None:
                self.channel = None
                self.queue = []
                self.pending = None
                self.done = False
                self.error = None
                self.verified = False
                self.receiver = Receiver(REQUEST if args.role == "listen" else ACK)
            return self

        @objc.python_method
        def send(self, payload):
            mtu = int(self.channel.getMTU())
            if mtu <= 0:
                self.error = "invalid_mtu"
                return
            self.queue = [payload[i:i + mtu] for i in range(0, len(payload), mtu)]
            self.next_write()

        @objc.python_method
        def next_write(self):
            if not self.queue:
                self.pending = None
                if args.role == "listen" and self.verified:
                    self.done = True
                return
            self.pending = self.queue.pop(0)
            status = self.channel.writeAsync_length_refcon_(self.pending, len(self.pending), None)
            if status:
                self.error = f"write_start:{int(status)}"

        def incoming_channel_(self, notification, channel):
            if self.channel is not None:
                channel.closeChannel()
                return
            self.channel = channel
            status = channel.setDelegate_(self)
            if status:
                self.error = f"set_delegate:{int(status)}"
            print("CONNECTED incoming", flush=True)

        incoming_channel_ = objc.selector(incoming_channel_, signature=b"v@:@@")

        def rfcommChannelOpenComplete_status_(self, channel, status):
            if status:
                self.error = f"open_complete:{int(status)}"
                return
            self.channel = channel
            print("CONNECTED outgoing", flush=True)
            self.send(REQUEST)

        def rfcommChannelData_data_length_(self, channel, data, length):
            try:
                if self.receiver.feed(bytes(data[:length])):
                    if args.role == "listen":
                        payload = bytes(self.receiver.data)[len(b"MACSYNC-CP002\n"):]
                        if hashlib.sha256(payload).hexdigest() != DIGEST:
                            raise ValueError("sha256_mismatch")
                        self.verified = True
                        self.send(ACK)
                    else:
                        self.verified = True
                        self.done = True
            except Exception as exc:
                self.error = f"receive:{type(exc).__name__}"

        def rfcommChannelWriteComplete_refcon_status_(self, channel, refcon, status):
            if status:
                self.error = f"write_complete:{int(status)}"
            else:
                self.next_write()

        def rfcommChannelClosed_(self, channel):
            if not self.done:
                self.error = "channel_closed_before_completion"

    delegate = Delegate.alloc().init()
    record = notification = None
    result = {"status": "failed", "sha256_verified": False}
    try:
        if args.role == "listen":
            uuid = lambda value: NSData.dataWithBytes_length_(value, len(value))
            service = {
                "0001 - ServiceClassIDList": [uuid(bytes.fromhex("e875e684b8034a429332b7a8ad092c02"))],
                "0004 - ProtocolDescriptorList": [
                    [uuid(b"\x01\x00")],
                    [uuid(b"\x00\x03"), {"DataElementType": 1, "DataElementSize": 1,
                                               "DataElementValue": args.channel}],
                ],
                "0100 - ServiceName": "mac_sync CP002",
                "LocalAttributes": {"Persistent": False},
            }
            record = B.IOBluetoothSDPServiceRecord.publishedServiceRecordWithDictionary_(service)
            if record is None:
                raise RuntimeError("publish_service_failed")
            status, channel_id = record.getRFCOMMChannelID_(None)
            if status:
                raise RuntimeError(f"get_channel:{int(status)}")
            notification = B.IOBluetoothRFCOMMChannel.registerForChannelOpenNotifications_selector_withChannelID_direction_(
                delegate, b"incoming:channel:", channel_id,
                B.kIOBluetoothUserNotificationChannelDirectionIncoming)
            if notification is None:
                raise RuntimeError("register_notification_failed")
            result["channel"] = int(channel_id)
            print(f"READY channel={channel_id}; waiting {args.timeout}s", flush=True)
        else:
            device = B.IOBluetoothDevice.deviceWithAddressString_(args.address.replace(":", "-"))
            if device is None:
                raise RuntimeError("invalid_device")
            status, channel = device.openRFCOMMChannelAsync_withChannelID_delegate_(None, args.channel, delegate)
            delegate.channel = channel
            if status:
                raise RuntimeError(f"open_start:{int(status)}")
            print("CONNECTING", flush=True)
        deadline = time.monotonic() + args.timeout
        while not delegate.done and not delegate.error and time.monotonic() < deadline:
            NSRunLoop.currentRunLoop().runMode_beforeDate_(
                NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.05))
        result.update(status="passed" if delegate.done and not delegate.error else "failed",
                      sha256_verified=delegate.verified,
                      reason=delegate.error or (None if delegate.done else "timeout"))
    except Exception as exc:
        result.update(reason=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
    finally:
        if delegate.channel is not None:
            delegate.channel.setDelegate_(None)
            delegate.channel.closeChannel()
        if notification is not None:
            notification.unregister()
        if record is not None:
            result["service_removal_status"] = int(record.removeServiceRecord())
    return result


def main():
    args = arguments()
    if args.role == "self-test":
        self_test()
        return
    if args.worker:
        try:
            result = run_worker(args)
        except Exception as exc:
            result = {"status": "failed", "reason": type(exc).__name__, "sha256_verified": False}
        print("RESULT " + json.dumps(result), flush=True)
        return
    # A hard deadline also covers native calls that might block the run loop.
    process = subprocess.Popen([sys.executable, __file__, *sys.argv[1:], "--worker"],
                               stdout=subprocess.PIPE, text=True)
    import threading
    result = {"status": "failed", "reason": "worker_exited_without_result", "sha256_verified": False}
    def collect():
        nonlocal result
        for line in process.stdout:
            print(line, end="", flush=True)
            if line.startswith("RESULT "):
                result = json.loads(line[7:])
    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    try:
        process.wait(timeout=args.timeout + 10)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        process.kill()
        process.wait()
        result = {"status": "failed", "reason": type(exc).__name__, "sha256_verified": False}
    reader.join(timeout=2)
    now = datetime.datetime.now(datetime.timezone.utc)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    report = {"checkpoint": "CP002", "machine": args.machine, "role": args.role,
              "timestamp_utc": now.isoformat(), "macos": platform.mac_ver()[0],
              "architecture": platform.machine(), "python": platform.python_version(),
              "revision": revision.stdout.strip(), "working_tree_dirty": bool(dirty.stdout.strip()),
              "worker_returncode": process.returncode, "block_bytes": len(BLOCK),
              "expected_sha256": DIGEST, **result}
    path = ROOT / "reports" / f"cp002-{args.machine}-{args.role}-{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Report: {path}", flush=True)
    sys.exit(0 if result["status"] == "passed" and process.returncode == 0 else 1)


if __name__ == "__main__":
    main()
