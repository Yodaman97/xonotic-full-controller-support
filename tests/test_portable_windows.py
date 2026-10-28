"""Test PE dependency inspection against a controlled PE32+ fixture."""
import importlib.util
from pathlib import Path
import struct
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "misc/tools/package-controller-windows.py"
spec = importlib.util.spec_from_file_location("portable_package", SCRIPT)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def pe_fixture():
    data = bytearray(2048)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, 0x8664)
    struct.pack_into("<H", data, 134, 1)
    struct.pack_into("<H", data, 148, 240)
    struct.pack_into("<H", data, 152, 0x20b)
    struct.pack_into("<I", data, 272, 0x1000)
    struct.pack_into("<IIII", data, 400, 1024, 0x1000, 1024, 512)
    struct.pack_into("<I", data, 524, 0x1100)
    data[768:777] = b"SDL2.dll\0"
    return bytes(data)


class PortableTests(unittest.TestCase):
    def test_pe_rva_resolves_dll_name(self):
        self.assertEqual(package.pe_imports(pe_fixture()), ["sdl2.dll"])

    def test_reject_32_bit_binary(self):
        data = bytearray(pe_fixture())
        struct.pack_into("<H", data, 132, 0x14c)
        with self.assertRaisesRegex(ValueError, "x64"):
            package.pe_imports(data)

    def test_reject_invalid_import_pointer(self):
        data = bytearray(pe_fixture())
        struct.pack_into("<I", data, 272, 0x9000)
        with self.assertRaisesRegex(ValueError, "RVA"):
            package.pe_imports(data)

    def test_non_system_runtime_must_be_bundled(self):
        self.assertTrue(package.is_system("kernel32.dll"))
        self.assertTrue(package.is_system("api-ms-win-core-file-l1-1-0.dll"))
        self.assertFalse(package.is_system("sdl2.dll"))
        self.assertFalse(package.is_system("libvorbisfile.dll"))


if __name__ == "__main__":
    unittest.main()
