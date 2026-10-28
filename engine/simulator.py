# -*- coding: utf-8 -*-
"""
simulator.py - Fausse GoXLR Mini pour coder et tester sans le materiel (projet GoXLR Mini).

Remplace la DLL Thesycon (goxlr_audioapi_x64.dll) : memes fonctions TUSBAUDIO_*,
memes arguments ctypes, memes codes d'erreur. Le moteur goxlrctl.py tourne donc
avec exactement son code protocole (en-tete 16 octets, index 16 bits, STALL
quand on lit trop tot, vidange a l'activation).

Pieges reproduits volontairement :
  - EnumerateDevices() avec un handle ouvert invalide TOUS les handles ;
  - debranchement : TSTATUS_INVALID_HANDLE sur le handle en cours ;
  - pilote bloque : la prochaine requete dort N secondes ;
  - longueurs de corps fausses (routage, carte couleurs...) notees dans errors.

Utilisation : goxlrctl.py daemon --simulate [--port 14566]
"""
import ctypes
import math
import random
import struct
import threading
import time
from collections import deque

TSTATUS_SUCCESS = 0
TSTATUS_INVALID_HANDLE = 3992977480
TSTATUS_DEVICE_STATE = 3992977495
TSTATUS_NO_DEVICE = 3992977484
TSTATUS_STALL = 4009754628
CODES = {
    TSTATUS_SUCCESS: b"TSTATUS_SUCCESS",
    TSTATUS_INVALID_HANDLE: b"TSTATUS_INVALID_HANDLE",
    TSTATUS_DEVICE_STATE: b"TSTATUS_INVALID_DEVICE_STATE",
    TSTATUS_NO_DEVICE: b"TSTATUS_NO_DEVICES",
    TSTATUS_STALL: b"TSTATUS_USBD_STATUS_STALL_PID",
}

FAKE_APPS = set()      # processus simules pour les scenes automatiques

CHANNELS = ["Mic", "LineIn", "Console", "System", "Game", "Chat", "Sample",
            "Music", "Headphones", "MicMonitor", "LineOut"]
BUTTON_BITS = {"Fader1Mute": 4, "Fader2Mute": 9, "Fader3Mute": 14, "Fader4Mute": 19,
               "Bleep": 22, "MicrophoneMute": 23}
INPUT_IDS = {0x02: "Microphone", 0x03: "Microphone", 0x04: "LineIn", 0x05: "LineIn", 0x06: "Console",
             0x07: "Console", 0x08: "System", 0x09: "System", 0x0A: "Game", 0x0B: "Game", 0x0C: "Chat",
             0x0D: "Chat", 0x0E: "Music", 0x0F: "Music", 0x10: "Samples", 0x11: "Samples"}
OUTPUT_POS = {"Headphones": 1, "BroadcastMix": 5, "ChatMic": 9, "Sampler": 13, "LineOut": 17, "StreamMix2": 21}


class FakeDevice:
    """Ce que le firmware de la Mini a recu et applique."""

    # sensibilite de chaque micro par rapport a un dynamique (dB) : un statique sort bien plus fort
    SENSITIVITY = {"dynamic": 0.0, "condenser": 18.0, "jack": 8.0}

    def __init__(self, firmware=(1, 2, 1, 49), serial="SIM-GOXLR-MINI"):
        self.firmware = firmware
        self.serial = serial
        self.volumes = [0] * 11
        self.muted = [False] * 11
        self.faders = [0, 7, 5, 3]          # index de voie par fader
        self.routing = {}                   # id d'entree (gauche/droite) -> octets
        self.colour_map = bytes(520)
        self.button_states = bytes(24)
        self.mic_params = {}
        self.effects = {}
        self.fader_display = {}
        self.animation = None
        self.phantom = False
        self.monitored_mix = None           # sous-mixages : etat d'origine tant que rien n'est envoye
        self.channel_mixes = None
        self.mic_type = "dynamic"
        self.gains = {"dynamic": 0, "condenser": 0, "jack": 0}
        self.fader_pos = [128, 128, 128, 128]
        self.held = set()
        self.timed = {}                     # bouton -> fin de l'appui (monotonic)
        self.mic_input = "dynamic"          # micro branche : dynamic, condenser, jack ou None
        self.talking = False
        self.voice_db = -30.0               # crete de la voix a 40 dB de gain (micro dynamique)
        self.noise_db = -66.0               # bruit de la piece a 40 dB de gain (micro dynamique)
        self.errors = []
        self.commands = 0
        self.index_resets = 0
        self.max_index = 0
        self.last_index = None
        self.counter = 0                    # compteur interne de la Mini (elle repond avec lui, vu le 23/10/2026)
        self.index_mismatches = 0
        self.history = deque(maxlen=400)
        self.rng = random.Random(42)

    @property
    def mix2(self):
        return tuple(self.firmware[:2]) >= (1, 3)

    def mask(self):
        now = time.monotonic()
        m = 0
        for b in self.held:
            m |= 1 << BUTTON_BITS[b]
        for b, until in list(self.timed.items()):
            if now < until:
                m |= 1 << BUTTON_BITS[b]
            else:
                del self.timed[b]
        return m

    def mic_db(self):
        """Niveau micro selon le micro branche, l'entree choisie et le gain. La voix varie d'une syllabe a l'autre
        (jusqu'a 24 dB sous ses cretes) ; le bruit de la piece monte avec le gain, comme la voix."""
        t = self.mic_input
        typ = self.mic_type
        if t is None:
            return None
        xlr_ok = t in ("dynamic", "condenser") and typ in ("dynamic", "condenser")
        if t == "condenser" and not (typ == "condenser" and self.phantom):
            xlr_ok = False
        if not (xlr_ok or (t == "jack" and typ == "jack")):
            return None
        gain = self.gains[typ] - 40 + self.SENSITIVITY[t]
        if self.talking:
            db = self.voice_db + gain - self.rng.random() ** 2 * 24
        else:
            db = self.noise_db + gain + self.rng.random() * 1.5
        return max(-72.0, min(0.0, db))

    def mic_raw(self):
        db = self.mic_db()
        if db is None:
            return 0
        return max(0, min(65535, int(round(10 ** ((db + 72.2) / 20)))))

    def execute(self, cid, body, idx):
        self.commands += 1
        self.history.append((cid, len(body), idx))
        if cid == 0:
            self.index_resets += 1
            self.last_index = 0
            self.counter = 0
            return b""
        if idx > 0xFFFF:
            self.errors.append(f"index {idx} hors 16 bits")
        self.counter = (self.counter + 1) & 0xFFFF
        if idx != self.counter:
            self.index_mismatches += 1
        self.max_index = max(self.max_index, idx)
        self.last_index = idx
        cmd, sub = cid >> 12, cid & 0xFFF
        if cmd == 0x80F:
            if sub == 1:
                return self.serial.encode().ljust(24, b"\x00") + b"2021-03-09".ljust(16, b"\x00")
            p = (self.firmware[0] << 12) | (self.firmware[1] << 8) | self.firmware[2]
            return struct.pack("<IIII", p, self.firmware[3], 0, 1)
        if cmd == 0x806:
            if sub < 16:
                self.volumes[sub] = body[0]
            return b""
        if cmd == 0x809:
            self.muted[sub] = bool(body[0])
            return b""
        if cmd == 0x805:
            self.faders[sub] = body[0]
            return b""
        if cmd == 0x804:
            want = 26 if self.mix2 else 22
            if len(body) != want:
                self.errors.append(f"routage {len(body)} octets au lieu de {want}")
            self.routing[sub] = bytes(body)
            return b""
        if cmd == 0x803:
            if len(body) != 520:
                self.errors.append(f"carte couleurs {len(body)} octets")
            self.colour_map = bytes(body)
            return b""
        if cmd == 0x808:
            if len(body) != 24:
                self.errors.append(f"etat des boutons {len(body)} octets")
            self.button_states = bytes(body)
            return b""
        if cmd == 0x800:
            enc = bytes(4)
            return struct.pack("<I", self.mask()) + enc + bytes(self.fader_pos) + bytes(4)
        if cmd == 0x80C:
            return struct.pack("<H", self.mic_raw())
        if cmd == 0x80B:
            for off in range(0, len(body) - 7, 8):
                key = struct.unpack_from("<I", body, off)[0]
                val = bytes(body[off + 4:off + 8])
                self.mic_params[key] = val
                if key == 0x000:
                    self.phantom = val[0] == 1
                elif key in (1, 2, 3):
                    self.mic_type = {1: "dynamic", 2: "condenser", 3: "jack"}[key]
                    self.gains[self.mic_type] = struct.unpack_from("<H", val, 2)[0]
            return b""
        if cmd == 0x801:
            for off in range(0, len(body) - 7, 8):
                key, val = struct.unpack_from("<Ii", body, off)
                self.effects[key] = val
            return b""
        if cmd == 0x814:
            self.fader_display[sub] = tuple(body)
            return b""
        if cmd == 0x816:
            self.animation = tuple(body)
            return b""
        if cmd == 0x818:
            self.monitored_mix = body[0]
            return b""
        if cmd == 0x817:
            want = 10 if self.mix2 else 8
            if len(body) != want:
                self.errors.append(f"sous-mixages {len(body)} octets au lieu de {want}")
            self.channel_mixes = bytes(body)
            return b""
        self.errors.append(f"commande inconnue {cid:#x}")
        return b""

    # -- lecture de l'etat "firmware" pour les tests --
    def route_on(self, inp, out):
        left = [k for k, v in INPUT_IDS.items() if v == inp][0]
        data = self.routing.get(left)
        return bool(data and data[OUTPUT_POS[out]] == 0x20)

    def colour(self, index):
        b = self.colour_map[index * 4:index * 4 + 4]
        return "%02X%02X%02X" % (b[2], b[1], b[0])


class FakeTusb:
    """Remplace goxlr_audioapi_x64.dll (memes noms, memes arguments)."""
    _shared = None

    @classmethod
    def shared(cls):
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    @classmethod
    def reset_shared(cls, **kw):
        cls._shared = cls(**kw)
        return cls._shared

    def __init__(self, firmware=(1, 2, 1, 49)):
        self.lock = threading.RLock()
        self.dev = FakeDevice(firmware=firmware)
        self.plugged = True
        self.handles = {}
        self.next_h = 100
        self.pending = deque()
        self.latency = 0.003
        self.hang_s = 0.0
        self.fail_next = []
        self.stall_rate = 0.0
        self.enumerate_calls = 0
        self.enumerate_violations = 0
        self.rng = random.Random(7)
        self.unplugged_usb = "none"         # ce que « Windows » voit debranche : "none" (cable qui ne fait que charger), "failed"...

    # -- commandes du banc de test --
    def usb_scan(self):
        """Equivalent simule de goxlrctl.usb_scan() : la liste des appareils USB vue par Windows."""
        return "mini" if self.plugged else self.unplugged_usb

    def unplug(self):
        with self.lock:
            self.plugged = False
            for h in self.handles:
                self.handles[h] = False
            self.pending.clear()

    def plug(self):
        with self.lock:
            self.plugged = True

    def hang(self, seconds):
        self.hang_s = float(seconds)

    def press(self, button, ms=150):
        with self.lock:
            self.dev.timed[button] = time.monotonic() + max(60, ms) / 1000.0

    def button_down(self, button):
        with self.lock:
            self.dev.held.add(button)

    def button_up(self, button):
        with self.lock:
            self.dev.held.discard(button)

    def move_fader(self, index, value):
        with self.lock:
            v = max(0, min(255, int(value)))
            self.dev.fader_pos[index] = v
            self.dev.volumes[self.dev.faders[index]] = v      # comme le vrai : le fader regle le volume

    def describe(self):
        d = self.dev
        with self.lock:
            return {"plugged": self.plugged, "firmware": ".".join(map(str, d.firmware)), "commands": d.commands,
                    "index_resets": d.index_resets, "max_index": d.max_index, "enumerate_violations": self.enumerate_violations,
                    "errors": d.errors[-20:], "volumes": dict(zip(CHANNELS, d.volumes)),
                    "muted": dict(zip(CHANNELS, d.muted)), "faders": [CHANNELS[i] for i in d.faders],
                    "button_states": list(d.button_states), "fader_pos": d.fader_pos, "mic_type": d.mic_type,
                    "gains": d.gains, "phantom": d.phantom, "mic_input": d.mic_input, "talking": d.talking,
                    "apps": sorted(FAKE_APPS)}

    # -- API Thesycon --
    def _maybe_hang(self):
        if self.hang_s > 0:
            s, self.hang_s = self.hang_s, 0.0
            time.sleep(s)

    def _bad_handle(self, h):
        if not self.handles.get(h):
            return TSTATUS_INVALID_HANDLE
        if self.fail_next:
            return self.fail_next.pop(0)
        return 0

    def TUSBAUDIO_EnumerateDevices(self):
        with self.lock:
            self.enumerate_calls += 1
            live = [h for h, ok in self.handles.items() if ok]
            if live:
                self.enumerate_violations += 1      # le vrai pilote tue alors tous les handles
                for h in live:
                    self.handles[h] = False
            return 0

    def TUSBAUDIO_GetDeviceCount(self):
        return 1 if self.plugged else 0

    def TUSBAUDIO_OpenDeviceByIndex(self, idx, ph):
        with self.lock:
            if not self.plugged or idx != 0:
                return TSTATUS_NO_DEVICE
            h = self.next_h
            self.next_h += 1
            self.handles[h] = True
            ph._obj.value = h
            return 0

    def TUSBAUDIO_GetDeviceInstanceIdString(self, h, buf, n):
        s = "USB\\VID_1220&PID_8FE4\\SIM"
        for i, ch in enumerate(s[:n - 1]):
            buf[i] = ord(ch)
        buf[min(len(s), n - 1)] = 0
        return 0

    def TUSBAUDIO_CloseDevice(self, h):
        with self.lock:
            self.handles.pop(h, None)
        return 0

    def TUSBAUDIO_StatusCodeStringA(self, code):
        return CODES.get(code, b"TSTATUS_" + str(code).encode())

    def TUSBAUDIO_ClassVendorRequestOut(self, h, _a, _b, request, _c, _d, length, data, meta, metalen):
        self._maybe_hang()
        with self.lock:
            err = self._bad_handle(h)
            if err:
                return err
            payload = bytes(data)[:length]
            if request == 1:
                self.pending.clear()
                self.dev.counter = 0
                return 0
            if request == 2:
                cid, blen, idx = struct.unpack_from("<IHH", payload)
                resp = self.dev.execute(cid, payload[16:16 + blen], idx)
                frame = struct.pack("<IHH", cid, len(resp), self.dev.counter) + bytes(8) + resp
                self.pending.append((time.monotonic() + self.latency, frame))
            return 0

    def TUSBAUDIO_ClassVendorRequestIn(self, h, _a, _b, request, _c, _d, length, buf, meta, metalen):
        self._maybe_hang()
        with self.lock:
            err = self._bad_handle(h)
            if err:
                return err
            if request == 0:
                out = bytes(24)
            elif request == 3:
                ready = self.pending and self.pending[0][0] <= time.monotonic()
                if not ready or (self.stall_rate and self.rng.random() < self.stall_rate):
                    return TSTATUS_STALL
                out = self.pending.popleft()[1]
            else:
                out = b""
            n = min(len(out), length)
            if n:
                ctypes.memmove(buf, out, n)
            meta[0:4] = list(struct.pack("<I", n))
            return 0
