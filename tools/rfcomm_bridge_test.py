"""Exercise a real ObjC -> Python callback using a local buffer; no radio."""
import ctypes
import objc
import IOBluetooth  # registers the formal protocol
from Foundation import NSObject
from rfcomm_probe import read_callback_data, REQUEST


class CP002BufferProbe(NSObject, protocols=[objc.protocolNamed("IOBluetoothRFCOMMChannelDelegate")]):
    def rfcommChannelData_data_length_(self, channel, data, length):
        try:
            self.received = read_callback_data(data, length)
            self.error = None
            self.pointer_type = type(data).__name__
        except Exception as exc:
            self.error = repr(exc)


def main():
    target = CP002BufferProbe.alloc().init()
    library = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    library.sel_registerName.argtypes = [ctypes.c_char_p]
    library.sel_registerName.restype = ctypes.c_void_p
    library.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_ulong]
    library.objc_msgSend.restype = None
    selector = library.sel_registerName(b"rfcommChannelData:data:length:")
    buffer = ctypes.create_string_buffer(REQUEST)
    library.objc_msgSend(objc.pyobjc_id(target), selector, None,
                         ctypes.addressof(buffer), len(REQUEST))
    assert target.error is None, target.error
    assert target.received == REQUEST
    assert read_callback_data(REQUEST, len(REQUEST)) == REQUEST
    for data, length in ((0, 1), (0, len(REQUEST) + 1), (0, -1)):
        try:
            read_callback_data(data, length)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid pointer/length accepted")
    print(f"PASS: native callback ({target.pointer_type}), buffer copy and invalid lengths; no Bluetooth tested")


if __name__ == "__main__":
    main()
