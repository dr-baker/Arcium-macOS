"""Read recent console activity without observing apps, windows or input data."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import ctypes
from functools import lru_cache
import math
import sys
import time


@dataclass(frozen=True)
class Activity:
    observed_at: float
    observed_monotonic: float
    idle_seconds: float | None = None
    on_console: bool | None = None
    login_done: bool | None = None
    display_asleep: bool | None = None
    locked_hint: bool | None = None
    error: str | None = None

    def status(self, cutoff=300, *, now=None):
        age = (time.monotonic() if now is None else now) - self.observed_monotonic
        if not math.isfinite(age) or age < 0 or age > 10:
            return 'unknown', 'activity reading is stale'
        if self.error or any(type(v) is not bool for v in
                             (self.on_console, self.login_done, self.display_asleep)):
            return 'unknown', self.error or 'activity sensor unavailable'
        if not self.on_console or not self.login_done:
            return 'away', 'no active console session'
        if self.display_asleep:
            return 'away', 'display is asleep'
        if self.locked_hint is True:
            return 'away', 'screen-lock hint is set'
        if (type(self.idle_seconds) not in (int, float) or
                not math.isfinite(self.idle_seconds) or self.idle_seconds < 0):
            return 'unknown', 'input idle time unavailable'
        if self.idle_seconds >= cutoff:
            return 'idle', 'no recent console input'
        return 'active', 'recent console input and an awake display'

    def record(self, cutoff=300):
        state, reason = self.status(cutoff)
        return {**asdict(self), 'state': state, 'reason': reason,
                'age_seconds': time.monotonic() - self.observed_monotonic,
                'idle_cutoff_seconds': cutoff,
                'lock_hint_available': self.locked_hint is not None,
                'scope': 'recent-input heuristic; no apps, windows or input contents collected'}


@lru_cache(maxsize=1)
def _native():
    cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cg.CGEventSourceSecondsSinceLastEventType.argtypes = [ctypes.c_int32, ctypes.c_uint32]
    cg.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
    cg.CGSessionCopyCurrentDictionary.argtypes = []
    cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
    cg.CGMainDisplayID.argtypes = []
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    cg.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]
    cg.CGDisplayIsAsleep.restype = ctypes.c_uint32
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFDictionaryGetValueIfPresent.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.POINTER(ctypes.c_void_p)]
    cf.CFDictionaryGetValueIfPresent.restype = ctypes.c_ubyte
    cf.CFGetTypeID.argtypes = [ctypes.c_void_p]
    cf.CFGetTypeID.restype = ctypes.c_ulong
    cf.CFBooleanGetTypeID.argtypes = []
    cf.CFBooleanGetTypeID.restype = ctypes.c_ulong
    cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
    cf.CFBooleanGetValue.restype = ctypes.c_ubyte
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFRelease.restype = None
    return cg, cf


def _boolean(cf, dictionary, name):
    key = cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)
    if not key:
        return None
    try:
        value = ctypes.c_void_p()
        if not cf.CFDictionaryGetValueIfPresent(dictionary, key, ctypes.byref(value)) or not value.value:
            return None
        if cf.CFGetTypeID(value) != cf.CFBooleanGetTypeID():
            return None
        return bool(cf.CFBooleanGetValue(value))
    finally:
        cf.CFRelease(key)


def sample():
    observed = dict(observed_at=time.time(), observed_monotonic=time.monotonic())
    if sys.platform != 'darwin':
        return Activity(**observed, error='console activity is supported on macOS only')
    try:
        cg, cf = _native()
        dictionary = cg.CGSessionCopyCurrentDictionary()
        if not dictionary:
            return Activity(**observed, error='no visible GUI session')
        try:
            display = cg.CGMainDisplayID()
            return Activity(**observed,
                idle_seconds=cg.CGEventSourceSecondsSinceLastEventType(0, 0xffffffff),
                on_console=_boolean(cf, dictionary, 'kCGSSessionOnConsoleKey'),
                login_done=_boolean(cf, dictionary, 'kCGSessionLoginDoneKey'),
                display_asleep=bool(cg.CGDisplayIsAsleep(display)) if display else None,
                # Undocumented supplementary veto. Absence is unknown, never false.
                locked_hint=_boolean(cf, dictionary, 'CGSSessionScreenIsLocked'))
        finally:
            cf.CFRelease(dictionary)
    except (OSError, AttributeError, ValueError):
        return Activity(**observed, error='native console activity query failed')
