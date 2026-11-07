"""Race-resistant Windows workspace operations using handle-relative NT opens.

All child paths are opened relative to an already-open directory handle with
FILE_OPEN_REPARSE_POINT. Reparse points are rejected after opening the object,
so path traversal never follows a substituted junction or symbolic link.
"""
from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes
from pathlib import Path

MAX_FILE_BYTES = 200_000
MAX_LIST_ENTRIES = 100

FILE_LIST_DIRECTORY = 0x0001
FILE_READ_DATA = 0x0001
FILE_WRITE_DATA = 0x0002
FILE_READ_ATTRIBUTES = 0x0080
SYNCHRONIZE = 0x00100000
FILE_SHARE_ALL = 0x00000007
FILE_OPEN = 0x00000001
FILE_CREATE = 0x00000002
FILE_DIRECTORY_FILE = 0x00000001
FILE_NON_DIRECTORY_FILE = 0x00000040
FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
FILE_OPEN_REPARSE_POINT = 0x00200000
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
FILE_DIRECTORY_INFORMATION_CLASS = 1
STATUS_NO_MORE_FILES = 0x80000006
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]

class OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(UNICODE_STRING)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", wintypes.LPVOID),
        ("SecurityQualityOfService", wintypes.LPVOID),
    ]

class IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

class FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
    _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetFileInformationByHandleEx.argtypes = [
    wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
]
kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
kernel32.ReadFile.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
]
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = [
    wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
]
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.SetFilePointerEx.argtypes = [
    wintypes.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD,
]
kernel32.SetFilePointerEx.restype = wintypes.BOOL
kernel32.SetEndOfFile.argtypes = [wintypes.HANDLE]
kernel32.SetEndOfFile.restype = wintypes.BOOL
ntdll.NtCreateFile.restype = ctypes.c_long
ntdll.NtQueryDirectoryFile.restype = ctypes.c_long
ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG

def _raise_last_error(message: str) -> None:
    code = ctypes.get_last_error()
    raise OSError(code, f"{message}: {ctypes.FormatError(code).strip()}")

def _raise_status(status: int, message: str) -> None:
    code = int(ntdll.RtlNtStatusToDosError(status))
    raise OSError(code, f"{message}: {ctypes.FormatError(code).strip()}")

def _close(handle) -> None:
    if handle and handle != INVALID_HANDLE_VALUE:
        kernel32.CloseHandle(handle)

def _tag_info(handle) -> FILE_ATTRIBUTE_TAG_INFO:
    info = FILE_ATTRIBUTE_TAG_INFO()
    if not kernel32.GetFileInformationByHandleEx(
        handle, FILE_ATTRIBUTE_TAG_INFO_CLASS, ctypes.byref(info), ctypes.sizeof(info)
    ):
        _raise_last_error("Could not inspect workspace object attributes")
    if info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError("Reparse-point workspace access is denied")
    return info

class WindowsWorkspaceBackend:
    """Pinned-root, handle-relative file backend for Windows."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve(strict=True)
        flags = 0x02000000 | 0x00200000  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        handle = kernel32.CreateFileW(
            str(self.root), FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
            FILE_SHARE_ALL, None, 3, flags, None,
        )
        if handle == INVALID_HANDLE_VALUE:
            _raise_last_error("Could not pin workspace root")
        try:
            info = _tag_info(handle)
            if not info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY:
                raise OSError("Workspace root is not a directory")
            self._root = handle
        except Exception:
            _close(handle)
            raise

    def close(self) -> None:
        if getattr(self, "_root", None):
            _close(self._root)
            self._root = None

    def _open_relative(self, parent, name: str, *, directory: bool, create: bool = False, access: int | None = None):
        name_buffer = ctypes.create_unicode_buffer(name)
        unicode_name = UNICODE_STRING(
            len(name.encode("utf-16-le")),
            len(name.encode("utf-16-le")) + 2,
            ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        object_name = ctypes.pointer(unicode_name)
        attributes = OBJECT_ATTRIBUTES(
            ctypes.sizeof(OBJECT_ATTRIBUTES), parent, object_name, 0x40, None, None
        )
        iosb = IO_STATUS_BLOCK()
        handle = wintypes.HANDLE()
        desired = access if access is not None else (
            (FILE_LIST_DIRECTORY if directory else FILE_READ_DATA)
            | FILE_READ_ATTRIBUTES | SYNCHRONIZE
        )
        options = FILE_OPEN_REPARSE_POINT | FILE_SYNCHRONOUS_IO_NONALERT
        options |= FILE_DIRECTORY_FILE if directory else FILE_NON_DIRECTORY_FILE
        status = ntdll.NtCreateFile(
            ctypes.byref(handle), desired, ctypes.byref(attributes),
            ctypes.byref(iosb), None,
            FILE_ATTRIBUTE_DIRECTORY if directory else FILE_ATTRIBUTE_NORMAL,
            FILE_SHARE_ALL, FILE_CREATE if create else FILE_OPEN,
            options, None, 0,
        )
        if status < 0:
            _raise_status(status, "Could not open workspace path component")
        result = handle.value
        try:
            info = _tag_info(result)
            is_directory = bool(info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            if is_directory != directory:
                raise OSError("Workspace object has an unexpected type")
            return result
        except Exception:
            _close(result)
            raise

    def _parent(self, parts: tuple[str, ...], *, create: bool = False):
        current = self._root
        owned = []
        try:
            for part in parts:
                child = self._open_relative(
                    current, part, directory=True, create=create,
                    access=FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
                )
                owned.append(child)
                current = child
            return current, owned
        except Exception:
            for handle in reversed(owned):
                _close(handle)
            raise

    @staticmethod
    def _read_handle(handle) -> bytes:
        chunks = []
        total = 0
        while True:
            buffer = ctypes.create_string_buffer(min(65536, MAX_FILE_BYTES + 1 - total))
            read = wintypes.DWORD()
            if not kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None):
                _raise_last_error("Could not read workspace file")
            if read.value == 0:
                break
            total += read.value
            if total > MAX_FILE_BYTES:
                raise OSError("File exceeds the configured read limit")
            chunks.append(buffer.raw[:read.value])
        return b"".join(chunks)

    @staticmethod
    def _write_handle(handle, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + 65536]
            buffer = ctypes.create_string_buffer(chunk)
            written = wintypes.DWORD()
            if not kernel32.WriteFile(handle, buffer, len(chunk), ctypes.byref(written), None):
                _raise_last_error("Could not write workspace file")
            if written.value == 0:
                raise OSError("Workspace file write made no progress")
            offset += written.value

    def read_file(self, parts: tuple[str, ...]) -> str:
        if not parts:
            raise OSError("A file path is required")
        parent, owned = self._parent(parts[:-1])
        handle = None
        try:
            handle = self._open_relative(parent, parts[-1], directory=False)
            return self._read_handle(handle).decode("utf-8")
        finally:
            _close(handle)
            for item in reversed(owned):
                _close(item)

    def write_file(self, parts: tuple[str, ...], content: str) -> None:
        if not parts:
            raise OSError("A file path is required")
        data = content.encode("utf-8")
        if len(data) > 100_000:
            raise OSError("Content exceeds the configured write limit")
        parent, owned = self._parent(parts[:-1], create=True)
        handle = None
        try:
            handle = self._open_relative(
                parent, parts[-1], directory=False, create=True,
                access=FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
            )
            self._write_handle(handle, data)
        finally:
            _close(handle)
            for item in reversed(owned):
                _close(item)

    def replace_text(self, parts: tuple[str, ...], old_text: str, new_text: str) -> None:
        if not parts or not old_text:
            raise OSError("A file path and non-empty old text are required")
        parent, owned = self._parent(parts[:-1])
        handle = None
        try:
            handle = self._open_relative(
                parent, parts[-1], directory=False,
                access=FILE_READ_DATA | FILE_WRITE_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
            )
            original = self._read_handle(handle).decode("utf-8")
            if original.count(old_text) != 1:
                raise OSError("Exact-match edit requires one occurrence; no change made")
            updated = original.replace(old_text, new_text, 1).encode("utf-8")
            if len(updated) > MAX_FILE_BYTES:
                raise OSError("Edited file exceeds the configured size limit")
            position = ctypes.c_longlong()
            if not kernel32.SetFilePointerEx(handle, 0, ctypes.byref(position), 0):
                _raise_last_error("Could not seek workspace file")
            if not kernel32.SetEndOfFile(handle):
                _raise_last_error("Could not truncate workspace file")
            self._write_handle(handle, updated)
        finally:
            _close(handle)
            for item in reversed(owned):
                _close(item)

    def list_files(self, parts: tuple[str, ...], denied_parts: set[str], denied_suffixes: set[str]) -> str:
        parent, owned = self._parent(parts)
        try:
            buffer = ctypes.create_string_buffer(65536)
            iosb = IO_STATUS_BLOCK()
            status = ntdll.NtQueryDirectoryFile(
                parent, None, None, None, ctypes.byref(iosb),
                ctypes.byref(buffer), len(buffer),
                FILE_DIRECTORY_INFORMATION_CLASS, False, None, True,
            )
            if status == STATUS_NO_MORE_FILES:
                return "(directory is empty or contains only excluded entries)"
            if status < 0:
                _raise_status(status, "Could not list workspace directory")
            raw = buffer.raw
            entries = []
            offset = 0
            while True:
                next_offset, _index = struct.unpack_from("<II", raw, offset)
                attrs = struct.unpack_from("<I", raw, offset + 56)[0]
                name_len = struct.unpack_from("<I", raw, offset + 60)[0]
                name = raw[offset + 64:offset + 64 + name_len].decode("utf-16-le")
                lowered = name.lower()
                if name not in {".", ".."} and lowered not in denied_parts and not lowered.startswith(".env") and not any(word in lowered for word in ("secret", "credential", "access-token", "refresh-token")) and Path(name).suffix.lower() not in denied_suffixes:
                    if not attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                        kind = "dir" if attrs & FILE_ATTRIBUTE_DIRECTORY else "file"
                        entries.append(f"{kind} {name}")
                        if len(entries) >= MAX_LIST_ENTRIES:
                            break
                if next_offset == 0:
                    break
                offset += next_offset
            suffix = "\n[listing capped at 100 entries]" if len(entries) >= MAX_LIST_ENTRIES else ""
            return "\n".join(entries) + suffix if entries else "(directory is empty or contains only excluded entries)"
        finally:
            for item in reversed(owned):
                _close(item)
