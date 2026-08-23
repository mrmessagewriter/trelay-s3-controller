# ============================================================
# Sprinklers1 firmware ZIP loader
#
# Deploy this file once as /main.py on the ESP32.
# Firmware upgrades replace only /main.zip.
#
# main.zip is mounted read-only at /firmware and is never
# extracted. Python modules and static files are read directly
# from the uncompressed ZIP archive through MicroPython's VFS.
# ============================================================

import os
import sys
import gc
import io
import json
import struct
import hashlib
import binascii

FIRMWARE_ZIP = "/main.zip"
FIRMWARE_MOUNT = "/firmware"
FIRMWARE_ENTRY = "/firmware/main.py"
PACKAGED_CONFIG = "/firmware/config.json"
DEVICE_CONFIG = "/config.json"
FIRMWARE_INFO_NAME = "firmware_info.json"

FILE_MODE = 0x8000
DIR_MODE = 0x4000


class ZipEntryFile(io.IOBase):
    def __init__(self, vfs, name, binary):
        self.vfs = vfs
        self.name = name
        self.binary = binary
        self.entry = vfs.entries[name]
        self.size = self.entry[2]
        self.pos = 0
        self.file = open(vfs.archive_path, "rb")
        self.data_offset = vfs._entry_data_offset(name)
        self.file.seek(self.data_offset)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def close(self):
        if self.file is not None:
            try:
                self.file.close()
            except:
                pass
            self.file = None

    def flush(self):
        pass

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        if whence == 0:
            new_pos = offset
        elif whence == 1:
            new_pos = self.pos + offset
        elif whence == 2:
            new_pos = self.size + offset
        else:
            raise OSError(22)

        if new_pos < 0:
            raise OSError(22)
        if new_pos > self.size:
            new_pos = self.size

        self.pos = new_pos
        self.file.seek(self.data_offset + self.pos)
        return self.pos

    def read(self, n=-1):
        if self.file is None:
            raise OSError(9)

        remaining = self.size - self.pos
        if n is None or n < 0 or n > remaining:
            n = remaining

        if n <= 0:
            return b"" if self.binary else ""

        data = self.file.read(n)
        self.pos += len(data)

        if self.binary:
            return data
        return data.decode("utf-8")

    def readinto(self, buf):
        if self.file is None:
            raise OSError(9)

        remaining = self.size - self.pos
        n = len(buf)
        if n > remaining:
            n = remaining

        if n <= 0:
            return 0

        data = self.file.read(n)
        count = len(data)
        buf[:count] = data
        self.pos += count
        return count

    def readline(self):
        if self.file is None:
            raise OSError(9)

        if self.pos >= self.size:
            return b"" if self.binary else ""

        out = bytearray()
        while self.pos < self.size:
            b = self.file.read(1)
            if not b:
                break
            self.pos += 1
            out.extend(b)
            if b == b"\n":
                break

        data = bytes(out)
        if self.binary:
            return data
        return data.decode("utf-8")

    def readlines(self):
        result = []
        while True:
            line = self.readline()
            if not line:
                return result
            result.append(line)

    def ioctl(self, request, arg):
        # MicroPython stream protocol.
        if request == 1:       # MP_STREAM_FLUSH
            self.flush()
            return 0
        if request == 4:       # MP_STREAM_CLOSE
            self.close()
            return 0
        if request == 11:      # MP_STREAM_GET_BUFFER_SIZE
            return 512
        if request == 2:       # MP_STREAM_SEEK
            try:
                import machine
                offset = machine.mem32[arg]
                whence = machine.mem32[arg + 4]
                machine.mem32[arg] = self.seek(offset, whence)
                return 0
            except:
                return -1
        return -1


class ZipVFS:
    """Read-only VFS for ZIP_STORED archives."""

    def __init__(self, archive_path):
        self.archive_path = archive_path
        self.path = "/"
        self.entries = {}
        self.directories = {""}
        self._data_offsets = {}
        self._load_directory()

    def mount(self, readonly, mkfs):
        if not readonly:
            raise OSError(30)

    def umount(self):
        pass

    def _normalize(self, path):
        if path is None or path == "":
            path = self.path
        elif not path.startswith("/"):
            path = self.path + path

        parts = []
        for part in path.split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        return "/".join(parts)

    def _load_directory(self):
        with open(self.archive_path, "rb") as f:
            f.seek(0, 2)
            archive_size = f.tell()
            tail_size = min(archive_size, 65557)
            f.seek(archive_size - tail_size)
            tail = f.read(tail_size)

            marker = tail.rfind(b"PK\x05\x06")
            if marker < 0:
                raise OSError("ZIP end directory not found")

            eocd = tail[marker:marker + 22]
            if len(eocd) < 22:
                raise OSError("Invalid ZIP end directory")

            values = struct.unpack("<4s4H2IH", eocd)
            total_entries = values[4]
            central_offset = values[6]

            f.seek(central_offset)

            for _ in range(total_entries):
                header = f.read(46)
                if len(header) != 46 or header[:4] != b"PK\x01\x02":
                    raise OSError("Invalid ZIP central directory")

                values = struct.unpack("<4s6H3I5H2I", header)
                flags = values[3]
                compression = values[4]
                crc32 = values[7]
                compressed_size = values[8]
                uncompressed_size = values[9]
                name_len = values[10]
                extra_len = values[11]
                comment_len = values[12]
                local_offset = values[16]

                name_bytes = f.read(name_len)
                f.seek(extra_len + comment_len, 1)
                name = name_bytes.decode("utf-8").replace("\\", "/")

                if flags & 1:
                    raise OSError("Encrypted ZIP entries are not supported")
                if compression != 0:
                    raise OSError("Firmware ZIP must use no compression")

                if name.endswith("/"):
                    self.directories.add(name.rstrip("/"))
                    continue

                if compressed_size != uncompressed_size:
                    raise OSError("Stored ZIP entry size mismatch")

                self.entries[name] = (
                    local_offset,
                    compressed_size,
                    uncompressed_size,
                    crc32,
                )

                pieces = name.split("/")[:-1]
                current = ""
                for piece in pieces:
                    current = piece if not current else current + "/" + piece
                    self.directories.add(current)

    def _entry_data_offset(self, name):
        if name in self._data_offsets:
            return self._data_offsets[name]

        local_offset = self.entries[name][0]
        with open(self.archive_path, "rb") as f:
            f.seek(local_offset)
            header = f.read(30)

        if len(header) != 30 or header[:4] != b"PK\x03\x04":
            raise OSError("Invalid ZIP local header")

        values = struct.unpack("<4s5H3I2H", header)
        name_len = values[9]
        extra_len = values[10]
        offset = local_offset + 30 + name_len + extra_len
        self._data_offsets[name] = offset
        return offset

    def chdir(self, path):
        normalized = self._normalize(path)
        if normalized not in self.directories:
            raise OSError(2)
        self.path = "/" + normalized + ("/" if normalized else "")

    def getcwd(self):
        return self.path

    def stat(self, path):
        name = self._normalize(path)
        if name in self.entries:
            size = self.entries[name][2]
            return (FILE_MODE, 0, 0, 0, 0, 0, size, 0, 0, 0)
        if name in self.directories:
            return (DIR_MODE, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        raise OSError(2)

    def statvfs(self, path):
        return (1, 1, 0, 0, 0, 0, 0, 0, 0, 255)

    def ilistdir(self, path):
        directory = self._normalize(path)
        if directory not in self.directories:
            raise OSError(2)

        prefix = directory + "/" if directory else ""
        children = {}

        for name in self.entries:
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix):]
            first = rest.split("/", 1)[0]
            if "/" in rest:
                children[first] = (DIR_MODE, 0)
            else:
                children[first] = (FILE_MODE, self.entries[name][2])

        for dirname in self.directories:
            if not dirname.startswith(prefix) or dirname == directory:
                continue
            rest = dirname[len(prefix):]
            if rest and "/" not in rest:
                children[rest] = (DIR_MODE, 0)

        def iterator():
            for name in sorted(children):
                mode, size = children[name]
                yield (name, mode, 0, size)
        return iterator()

    def open(self, path, mode="r"):
        if "w" in mode or "a" in mode or "+" in mode or "x" in mode:
            raise OSError(30)

        name = self._normalize(path)
        if name not in self.entries:
            raise OSError(2)

        return ZipEntryFile(self, name, "b" in mode)

    def read_bytes(self, name):
        name = self._normalize(name)
        with self.open(name, "rb") as f:
            return f.read()

    def names(self):
        return list(self.entries.keys())



def checksum_archive(archive):
    """Hash all files except firmware_info.json using a canonical stream."""
    hasher = hashlib.sha256()

    for name in sorted(archive.names()):
        if name == FIRMWARE_INFO_NAME:
            continue

        size = archive.entries[name][2]
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(str(size).encode("ascii"))
        hasher.update(b"\x00")

        with archive.open(name, "rb") as f:
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break
                hasher.update(chunk)

        hasher.update(b"\x00")

    return binascii.hexlify(hasher.digest()).decode("ascii")



def verify_firmware(archive):
    try:
        info = json.loads(archive.read_bytes(FIRMWARE_INFO_NAME).decode("utf-8"))
    except Exception as e:
        raise OSError("Unable to read firmware_info.json: {}".format(e))

    expected = str(info.get("checksum", "")).lower()
    actual = checksum_archive(archive).lower()

    if not expected or expected != actual:
        raise OSError(
            "Firmware checksum mismatch: expected {}, calculated {}".format(
                expected, actual
            )
        )

    return info



def mount_firmware(archive):
    # Soft reboots normally remove dynamic mounts, but tolerate a stale one.
    try:
        try:
            import vfs
            vfs.umount(FIRMWARE_MOUNT)
        except:
            os.umount(FIRMWARE_MOUNT)
    except:
        pass

    try:
        import vfs
        vfs.mount(archive, FIRMWARE_MOUNT, readonly=True)
    except ImportError:
        os.mount(archive, FIRMWARE_MOUNT, readonly=True)

    if FIRMWARE_MOUNT + "/lib" not in sys.path:
        sys.path.insert(0, FIRMWARE_MOUNT + "/lib")
    if FIRMWARE_MOUNT not in sys.path:
        sys.path.insert(0, FIRMWARE_MOUNT)



def ensure_device_config():
    try:
        with open(DEVICE_CONFIG, "rb"):
            return
    except:
        pass

    print("No persistent config.json found; creating it from firmware defaults.")

    with open(PACKAGED_CONFIG, "rb") as source:
        with open(DEVICE_CONFIG + ".tmp", "wb") as target:
            while True:
                chunk = source.read(512)
                if not chunk:
                    break
                target.write(chunk)

    try:
        os.remove(DEVICE_CONFIG)
    except:
        pass
    os.rename(DEVICE_CONFIG + ".tmp", DEVICE_CONFIG)



def run_firmware():
    print()
    print("============================")
    print("Sprinklers1 Firmware Loader")
    print("============================")

    gc.collect()

    try:
        archive = ZipVFS(FIRMWARE_ZIP)
        info = verify_firmware(archive)

        print("Firmware:", info.get("name", "Unknown"))
        print("Version:", info.get("version", "Unknown"))
        print("Build date:", info.get("date", "Unknown"))
        print("Checksum: OK")

        mount_firmware(archive)
        ensure_device_config()

        gc.collect()
        print("Free memory before application:", gc.mem_free())

        with open(FIRMWARE_ENTRY, "r") as f:
            source = f.read()

        globals()["__file__"] = FIRMWARE_ENTRY
        exec(source, globals(), globals())

    except Exception as e:
        print()
        print("============================")
        print("FIRMWARE LOAD FAILED")
        print("============================")
        print(repr(e))
        raise


run_firmware()
