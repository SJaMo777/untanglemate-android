"""On-disk format for .smmap files.

Encrypts the JSON payload with a hard-coded app-wide Fernet key so
files aren't readable by simple `cat` / text-search. Any install of
the app can open any other install's map, by design — competitors who
inspect the binary can recover the key, so this is obfuscation, not
security. Documented tradeoff: stops casual reading + indexing tools;
not a defence against determined attackers.

Wire format
-----------
    [4-byte magic header] [gzip-compressed Fernet token]

Magic header `SMM1` marks the file as encrypted. `load_bytes` sniffs
the first 4 bytes — anything else is treated as a legacy JSON file
and decoded as UTF-8 plain text, so existing .smmap files keep
loading without conversion. The next time the user saves, the file
is rewritten in the new format.

Gzip first then encrypt: compressing AFTER encryption is useless
(ciphertext is incompressible by design), and JSON-with-lots-of-
repeated-keys squeezes by ~70%. Net result: encrypted .smmap files
are typically smaller than the plaintext they replaced.
"""
from __future__ import annotations

import gzip
import os
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


# App-wide Fernet key. Same for every install so any user can open
# any other user's map. Generated once; do NOT rotate without
# providing a migration path for files already in the wild.
_APP_KEY = b"YGJpQqvNkXcEofcU3wG_47jE6jc_-i7vWdEzqu0gW1k="

# 4-byte signature at the start of every encrypted file. Versioned so
# the format can evolve without ambiguity — `SMM2` would mean "new
# layout, see the loader for details" while still distinguishing from
# legacy JSON (which starts with `{`) and from random binary.
MAGIC_V1 = b"SMM1"

_fernet = Fernet(_APP_KEY)


def is_encrypted(data: bytes) -> bool:
    """True when `data` starts with a known magic header."""
    return data.startswith(MAGIC_V1)


def encrypt_text(payload: str) -> bytes:
    """Encode `payload` (the JSON string a map serializes to) as the
    on-disk binary blob. Gzip-compresses first, then encrypts, then
    prepends the magic header."""
    compressed = gzip.compress(payload.encode("utf-8"), compresslevel=6)
    token = _fernet.encrypt(compressed)
    return MAGIC_V1 + token


def decrypt_to_text(data: bytes) -> str:
    """Reverse of `encrypt_text`. Caller MUST have checked
    `is_encrypted(data)` first."""
    if not is_encrypted(data):
        raise ValueError("decrypt_to_text called on non-encrypted bytes")
    token = data[len(MAGIC_V1):]
    try:
        compressed = _fernet.decrypt(token)
    except InvalidToken as e:
        raise ValueError(
            "Map file is corrupted or was written with a different "
            "app key — cannot decrypt."
        ) from e
    return gzip.decompress(compressed).decode("utf-8")


def read_map_text(path: str | Path) -> str:
    """Open a .smmap file and return its JSON text regardless of
    on-disk format. Encrypted blobs are decrypted; legacy plaintext
    files come back as-is. Lets `document.load` stay format-agnostic."""
    raw = Path(path).read_bytes()
    if is_encrypted(raw):
        return decrypt_to_text(raw)
    # Legacy plaintext .smmap — pre-encryption files. Treat as UTF-8
    # JSON. The same map will be re-saved in encrypted form the next
    # time the user hits Save.
    return raw.decode("utf-8")


def write_map_text(path: str | Path, payload: str) -> None:
    """Write `payload` (the JSON text) to disk in the encrypted
    on-disk format. Caller passes the JSON they would have written
    directly in the old plaintext era.

    Written to a sibling temp file and then `os.replace`d into place,
    which is atomic on the same volume. Writing straight onto the live
    file meant a several-second encrypt-and-write on a big map left a
    window where the .smmap on disk was neither the old map nor the new
    one — and a crash, a power cut, or a sync client uploading mid-write
    landed a truncated file where the user's map used to be. With the
    replace, a reader sees either the whole old file or the whole new
    one; there is no partial state to observe or to upload.

    The temp file is a sibling because `os.replace` is only atomic
    within one filesystem — via the system temp dir it would degrade to
    a copy, reintroducing exactly the window this closes. The pid in the
    name keeps two processes (or two machines writing into the same
    synced folder) from colliding on it.
    """
    target = Path(path)
    data = encrypt_text(payload)
    tmp = target.with_name(".%s.%d.tmp" % (target.name, os.getpid()))
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            # Get it onto the platter before the rename. Without this the
            # rename can be durable while the contents it points at are
            # still in the cache, which is the corrupt-file case again
            # with extra steps.
            os.fsync(fh.fileno())
        _replace_with_retry(tmp, target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _replace_with_retry(
    tmp: Path, target: Path, *, attempts: int = 15, delay: float = 0.1,
    max_delay: float = 0.5,
) -> None:
    """`os.replace(tmp, target)`, retried on Windows sharing violations.

    Windows refuses to replace a file another process holds open, and a
    map in a Dropbox / Drive folder is opened constantly by the sync
    client and by antivirus. Those handles are held for a moment, not a
    session, so a short retry turns a spurious "save failed" into a
    save. The last attempt is allowed to raise — a lock that outlives
    the whole retry budget is a real problem the user needs to be told
    about.

    User-reported 2026-09: still hit "Save failed" (WinError 5) closing
    and reopening the same map twice in quick succession on a slow
    connection — plausibly Dropbox still uploading the FIRST close's
    save when the second one starts. The original 10 attempts x a flat
    0.1s (~1s total) was tuned for a brief AV/indexer touch, not a sync
    client that is actually mid-upload over a slow line, which can hold
    the handle for several seconds. Delay now grows (0.1s -> 0.5s) up to
    ~6s of total budget across the same number-ish of attempts, and the
    catch is OSError rather than only PermissionError — a Windows
    sharing violation (WinError 32) doesn't always surface as the
    latter, and the whole point of retrying here is "something else
    briefly has this file," not "specifically PermissionError."
    """
    for remaining in range(attempts - 1, -1, -1):
        try:
            os.replace(tmp, target)
            return
        except OSError:
            if not remaining:
                raise
            time.sleep(delay)
            delay = min(delay + 0.1, max_delay)
