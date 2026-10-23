#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
goxlrctl.py - Moteur de GoXLR Mini, logiciel libre pour piloter une GoXLR Mini sous Windows.

Parle directement a l'API Thesycon du pilote officiel (goxlr_audioapi_x64.dll)
avec les requetes vendeur du protocole GoXLR (constantes reprises du projet
open source goxlr-utility, licence MIT). Projet non affilie a TC-Helicon ni a Music Tribe.

REGLES D'OR
1. TUSBAUDIO_EnumerateDevices() invalide TOUS les handles ouverts : on ne
   l'appelle que handle ferme, juste avant une (re)ouverture. Le moteur prend
   le port HTTP avant d'ouvrir l'USB : un second moteur s'arrete avant de
   toucher au pilote.
2. L'index de commande est un entier 16 bits. Avant 65535, on envoie la
   commande 0 (remise a zero), comme goxlr-utility. Une version precedente
   l'oubliait : apres 65535 commandes (une heure environ), struct.error a chaque
   commande, plus rien ne partait et les voyants ne bougeaient plus.
3. Un seul fil parle a l'USB. L'API HTTP ne touche jamais l'appareil : elle
   modifie l'etat et marque ce qui doit partir. Elle repond donc toujours,
   meme si le pilote se bloque.
4. Toute erreur pendant un echange USB, attendue ou non, ferme le handle et
   relance une connexion propre qui reapplique l'etat complet.
5. Le superviseur (mode daemon) relance le moteur s'il meurt ou si la boucle
   USB ne donne plus signe de vie.
6. Mises a jour : seulement depuis les releases GitHub du projet, taille et
   empreinte SHA-256 verifiees, retour arriere automatique si la nouvelle
   version ne repond pas.

Commandes :
  goxlrctl.py daemon [--simulate] [--port N]   superviseur + moteur (tache planifiee)
  goxlrctl.py daemon --child                   moteur seul (lance par le superviseur)
  goxlrctl.py ui                               ouvre l'appli
  goxlrctl.py status | health
  goxlrctl.py volume <canal> <0-255|NN%>
  goxlrctl.py mute <canal> <on|off> [all|stream|chat|phones|lineout]
  goxlrctl.py fader <A|B|C|D> <canal>
  goxlrctl.py route <entree> <sortie> <on|off>
  goxlrctl.py colour <cible|global|all> <RRGGBB> [RRGGBB]
  goxlrctl.py mic-gain <dynamic|condenser|jack> <dB 0-72>
  goxlrctl.py scene <nom>                      streaming, gaming, discord, podcast...
  goxlrctl.py mic-preset <nom>                 naturel, radio, stream, podcast...
  goxlrctl.py theme <nom>                      voies, glacier, aurore...
  goxlrctl.py reconnect
  goxlrctl.py apply-profile [fichier.json]
  goxlrctl.py raw <command_id_hex> [body_hex]
  goxlrctl.py update-check                     cherche une nouvelle version
  goxlrctl.py apply-update                     (interne) installe une version preparee
Si le moteur tourne, les commandes passent par lui (HTTP local).
"""
import copy
import ctypes
import hashlib
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "4.1.4"
APP_NAME = "GoXLR Mini"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)          # le Python embarque (._pth) n'ajoute pas le dossier du script
IS_WINDOWS = os.name == "nt"
DLL_PATH = os.environ.get("GOXLR_DLL") or os.path.join(
    os.environ.get("ProgramFiles", r"C:\Program Files"), r"TC-Helicon\GoXLR_Audio_Driver\x64\goxlr_audioapi_x64.dll")
DEFAULT_PROFILE_PATH = os.path.join(BASE_DIR, "profile.json")
UI_PATH = os.path.join(BASE_DIR, "ui.html")
OVERLAY_PATH = os.path.join(BASE_DIR, "overlay.html")
MANIFEST_PATH = os.path.join(BASE_DIR, "manifest.json")
API_HEADER = "X-GoXLR"
TASK_NAME = APP_NAME
APP_EXE = os.path.join(BASE_DIR, "app", APP_NAME + ".exe")
APP_BROWSERS = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"Google\Chrome\Application\chrome.exe"),
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
BOOT_ID = str(int(time.time() * 1000))     # change a chaque demarrage : l'appli recharge son interface
POLL_INTERVAL = 0.015                       # pause entre deux lectures des boutons et faders
WATCHDOG_S = 15.0                           # boucle USB muette plus longtemps : le superviseur relance
EXIT_RESTART, EXIT_PORT_BUSY = 75, 76


def default_data_dir():
    if IS_WINDOWS:
        return os.path.join(os.environ.get("ProgramData") or BASE_DIR, APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".local", "share", "goxlr-mini")


SIMULATE = False
HTTP_PORT = 14565
DATA_DIR = STATE_PATH = LOG_PATH = None


def configure(simulate=None, port=None, data_dir=None):
    """Regle le mode simule, le port et le dossier de donnees (avant de creer le Controller)."""
    global SIMULATE, HTTP_PORT, DATA_DIR, STATE_PATH, LOG_PATH, _lib
    if simulate is not None and bool(simulate) != SIMULATE:
        SIMULATE = bool(simulate)
        _lib = None
    if port is not None:
        HTTP_PORT = int(port)
    if data_dir is not None:
        DATA_DIR = data_dir
    STATE_PATH = os.path.join(DATA_DIR, "state.json")
    LOG_PATH = os.path.join(DATA_DIR, "goxlrctl.log")


configure(simulate=os.environ.get("GOXLR_SIMULATE") == "1",
          port=os.environ.get("GOXLR_PORT") or 14565,
          data_dir=os.environ.get("GOXLR_DATA_DIR") or default_data_dir())


# ---------------- protocole ----------------
CHANNELS = ["Mic", "LineIn", "Console", "System", "Game", "Chat", "Sample",
            "Music", "Headphones", "MicMonitor", "LineOut"]
CHANNEL_LABELS = {"Mic": "Micro", "LineIn": "Entrée ligne", "Console": "Console",
                  "System": "Système", "Game": "Jeu", "Chat": "Chat", "Sample": "Samples",
                  "Music": "Musique", "Headphones": "Casque", "MicMonitor": "Retour micro",
                  "LineOut": "Sortie ligne"}
CHANNEL_COLOURS = {"Mic": "FF453A", "LineIn": "BF5AF2", "Console": "FFD60A", "System": "64D2FF",
                   "Game": "30D158", "Chat": "5E5CE6", "Sample": "FF9F0A", "Music": "FF375F",
                   "Headphones": "F2F2F7", "MicMonitor": "FF6961", "LineOut": "AC8E68"}
FADERS = ["A", "B", "C", "D"]
INPUTS = {  # nom -> (id gauche, id droit)
    "Microphone": (0x02, 0x03), "LineIn": (0x04, 0x05), "Console": (0x06, 0x07),
    "System": (0x08, 0x09), "Game": (0x0A, 0x0B), "Chat": (0x0C, 0x0D),
    "Music": (0x0E, 0x0F), "Samples": (0x10, 0x11),
}
IN_CHANNEL = {"Microphone": "Mic", "LineIn": "LineIn", "Console": "Console", "System": "System",
              "Game": "Game", "Chat": "Chat", "Music": "Music", "Samples": "Sample"}
CHANNEL_INPUT = {v: k for k, v in IN_CHANNEL.items()}
OUTPUTS = {  # nom -> (position gauche, position droite)
    "Headphones": (1, 3), "BroadcastMix": (5, 7), "ChatMic": (9, 11),
    "Sampler": (13, 15), "LineOut": (17, 19), "StreamMix2": (21, 23),
}
# Carte couleurs format >= 1.1.8 sur Mini (520 octets) : cible -> (index de depart, nb couleurs)
COLOUR_TARGETS = {
    "Global": (8, 2), "Accent": (10, 2),
    "Fader1Mute": (12, 2), "Fader2Mute": (14, 2), "Fader3Mute": (16, 2), "Fader4Mute": (18, 2),
    "FadeMeter1": (20, 2), "FadeMeter2": (34, 2), "FadeMeter3": (48, 2), "FadeMeter4": (62, 2),
    "Bleep": (126, 2), "MicrophoneMute": (128, 2),
}
COLOUR_ALIASES = {"global": "Global", "InternalLight": "Global", "LogoX": "Accent", "Cough": "MicrophoneMute"}
BUTTON_BITS = {"Fader1Mute": 4, "Fader2Mute": 9, "Fader3Mute": 14, "Fader4Mute": 19,
               "Bleep": 22, "MicrophoneMute": 23}
FADER_BUTTONS = ["Fader1Mute", "Fader2Mute", "Fader3Mute", "Fader4Mute"]
BTN_ON, BTN_DIM, BTN_FLASH = 0x01, 0x02, 0x03   # ButtonStates goxlr-utility : Colour1 / DimmedColour1 / Flashing
STATUS_STALL = 4009754628             # TSTATUS_USBD_STATUS_STALL_PID : reponse pas encore prete
MIC_TYPES = ["dynamic", "condenser", "jack"]
MIC_GAIN_KEYS = {"dynamic": 0x001, "condenser": 0x002, "jack": 0x003}
# Egaliseur Mini (parametres micro) : frequence -> (cle frequence, cle gain)
EQ_BANDS = {"90": (0x40000, 0x40001), "250": (0x40003, 0x40004), "500": (0x40006, 0x40007),
            "1000": (0x50000, 0x50001), "3000": (0x50003, 0x50004), "8000": (0x50006, 0x50007)}
RATIOS = [1.0, 1.1, 1.2, 1.4, 1.6, 1.8, 2.0, 2.5, 3.2, 4.0, 5.6, 8.0, 16.0, 32.0, 64.0]
GATE_ATTENUATION = [-6, -7, -8, -9, -10, -11, -12, -13, -14, -15, -16, -17, -18, -19, -20, -21,
                    -22, -23, -24, -25, -26, -27, -28, -30, -32, -61]
FADER_STYLES = {"two-colour": (0, 0), "gradient": (1, 0), "meter": (0, 1), "gradient-meter": (1, 1)}
ANIMATIONS = {"none": 5, "retro-rainbow": 0, "rainbow-dark": 1, "rainbow-bright": 2, "simple": 3, "ripple": 4}
WATERFALL = {"down": 0, "up": 1, "off": 2}
RECOMMENDED_GAIN = {"dynamic": 50, "condenser": 30, "jack": 25}
# Mute "vers une sortie" (goxlr-utility MuteFunction) : la voie reste active ailleurs
MUTE_TARGETS = {"all": [], "stream": ["BroadcastMix", "StreamMix2"], "chat": ["ChatMic"],
                "phones": ["Headphones"], "lineout": ["LineOut"]}
MUTE_TARGET_LABELS = {"all": "partout", "stream": "du stream", "chat": "de Discord",
                      "phones": "du casque", "lineout": "des enceintes"}
MIC_BUTTON_MODES = ["toggle", "hold", "ptt"]   # bascule, maintenir pour couper, appuyer pour parler
VOD_MODES = ["off", "no-music"]

# ---------------- preregles ----------------
def _dsp(eq=(0, 0, 0, 0, 0, 0), gate=(True, -55, 40, 0, 19), comp=(-12, 6, 1, 9, 2), deesser=0):
    return {"eq": dict(zip(EQ_BANDS, eq)),
            "gate": dict(zip(("enabled", "threshold", "attenuation", "attack", "release"), gate)),
            "comp": dict(zip(("threshold", "ratio", "attack", "release", "makeup"), comp)),
            "deesser": deesser}

MIC_PRESETS = {
    "naturel": {"label": "Naturel", "desc": "Ta voix telle quelle, juste stabilisée.",
                "dsp": _dsp()},
    "radio": {"label": "Radio", "desc": "Voix pleine et présente, comme à l’antenne.",
              "dsp": _dsp((3, -2, -2, 0, 3, 2), (True, -48, 70, 0, 19), (-22, 9, 1, 9, 6), 30)},
    "stream": {"label": "Stream", "desc": "Claire et régulière, idéale en live.",
               "dsp": _dsp((1, -1, -1, 1, 2, 2), (True, -45, 80, 0, 19), (-18, 8, 1, 9, 4), 20)},
    "podcast": {"label": "Podcast", "desc": "Chaleureuse et posée pour les longues discussions.",
                "dsp": _dsp((2, 0, -1, 0, 1, 1), (True, -50, 50, 0, 19), (-20, 7, 1, 9, 4), 15)},
    "anti-bruit": {"label": "Anti-bruit", "desc": "Coupe le clavier, le ventilo et le bruit de la pièce.",
                   "dsp": _dsp((-3, -1, 0, 1, 2, 1), (True, -35, 100, 0, 15), (-18, 8, 1, 9, 4), 25)},
    "brut": {"label": "Brut", "desc": "Aucun traitement : le son du micro sans retouche.",
             "dsp": _dsp((0, 0, 0, 0, 0, 0), (False, -59, 0, 0, 19), (0, 0, 1, 9, 0), 0)},
}
MIC_TYPE_PRESET = {"dynamic": "radio", "condenser": "anti-bruit", "jack": "stream"}

def _routing(**over):
    on = lambda *outs: {o: o in outs for o in OUTPUTS}
    base = {
        "Microphone": on("Headphones", "BroadcastMix", "ChatMic", "Sampler", "StreamMix2"),
        "Chat": on("Headphones", "BroadcastMix", "LineOut", "StreamMix2"),
        "Music": on("Headphones", "BroadcastMix", "LineOut", "StreamMix2"),
        "Game": on("Headphones", "BroadcastMix", "LineOut", "StreamMix2"),
        "Console": on("Headphones", "BroadcastMix", "LineOut", "StreamMix2"),
        "LineIn": on("Headphones", "BroadcastMix", "LineOut", "StreamMix2"),
        "System": on("Headphones", "LineOut"),
        "Samples": on("Headphones", "BroadcastMix", "ChatMic", "LineOut", "StreamMix2"),
    }
    for inp, outs in over.items():
        base[inp].update(outs)
    return base

SCENES = {
    "streaming": {"label": "Streaming", "desc": "Micro, Discord, musique et jeu. Le stream entend tout sauf tes notifications.",
                  "faders": {"A": "Mic", "B": "Chat", "C": "Music", "D": "Game"},
                  "routing": _routing(), "mic_preset": "stream"},
    "stream-safe": {"label": "Stream sans musique", "desc": "Comme Streaming, mais la musique reste dans ton casque (anti-DMCA).",
                    "faders": {"A": "Mic", "B": "Chat", "C": "Music", "D": "Game"},
                    "routing": _routing(Music={"BroadcastMix": False, "StreamMix2": False}), "mic_preset": "stream"},
    "gaming": {"label": "Gaming", "desc": "Jeu, Discord, musique et système sous la main. Micro sur le bouton de toux.",
               "faders": {"A": "Game", "B": "Chat", "C": "Music", "D": "System"},
               "routing": _routing(), "mic_preset": "anti-bruit"},
    "discord": {"label": "Soirée Discord", "desc": "Tes amis entendent ta musique en plus de ta voix.",
                "faders": {"A": "Mic", "B": "Chat", "C": "Music", "D": "Game"},
                "routing": _routing(Music={"ChatMic": True}), "mic_preset": "naturel"},
    "podcast": {"label": "Podcast", "desc": "Micro, invité à distance, habillage musical et jingles.",
                "faders": {"A": "Mic", "B": "Chat", "C": "Music", "D": "Sample"},
                "routing": _routing(), "mic_preset": "podcast"},
    "ecoute": {"label": "Écoute", "desc": "Musique et films d’abord, le micro reste discret.",
               "faders": {"A": "Music", "B": "System", "C": "Game", "D": "Chat"},
               "routing": _routing(), "mic_preset": None},
}

THEMES = {
    "voies": {"label": "Couleur des voies", "per_channel": True, "accent": "F2F2F7"},
    "glacier": {"label": "Glacier", "top": "00E5FF", "bottom": "00303A", "accent": "00E5FF"},
    "aurore": {"label": "Aurore", "faders": ["00F5D4", "7B61FF", "FF4FD8", "FFB800"], "accent": "7B61FF"},
    "sunset": {"label": "Coucher de soleil", "top": "FF7A00", "bottom": "4A0020", "accent": "FF2D78"},
    "neon": {"label": "Néon", "top": "FF00E5", "bottom": "12003A", "accent": "00FFF0"},
    "blanc": {"label": "Blanc pur", "top": "FFFFFF", "bottom": "2A2A2A", "accent": "FFFFFF"},
    "nuit": {"label": "Nuit", "top": "3A5BFF", "bottom": "00000C", "accent": "1E2E80"},
}

# Applis reconnues pour les scenes automatiques (nom du processus -> nom affiche)
KNOWN_APPS = {
    "obs64.exe": "OBS Studio", "streamlabs obs.exe": "Streamlabs Desktop", "twitchstudio.exe": "Twitch Studio",
    "discord.exe": "Discord", "teamspeak.exe": "TeamSpeak", "ts3client_win64.exe": "TeamSpeak 3",
    "spotify.exe": "Spotify", "vlc.exe": "VLC", "steam.exe": "Steam", "steamwebhelper.exe": "Steam (navigateur)",
    "epicgameslauncher.exe": "Epic Games", "battle.net.exe": "Battle.net", "riotclientservices.exe": "Riot Client",
    "valorant-win64-shipping.exe": "Valorant", "cs2.exe": "Counter-Strike 2", "league of legends.exe": "League of Legends",
    "fortniteclient-win64-shipping.exe": "Fortnite", "r5apex.exe": "Apex Legends", "r5apex_dx12.exe": "Apex Legends",
    "rocketleague.exe": "Rocket League", "gta5.exe": "GTA V", "gta5_enhanced.exe": "GTA V", "minecraft.windows.exe": "Minecraft",
    "javaw.exe": "Minecraft Java", "eldenring.exe": "Elden Ring", "overwatch.exe": "Overwatch",
    "zoom.exe": "Zoom", "ms-teams.exe": "Teams", "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox",
}
SYSTEM_PROCESSES = {
    "[system process]", "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe", "memory compression", "spoolsv.exe", "sihost.exe",
    "taskhostw.exe", "ctfmon.exe", "explorer.exe", "searchhost.exe", "startmenuexperiencehost.exe", "runtimebroker.exe",
    "conhost.exe", "dllhost.exe", "wmiprvse.exe", "audiodg.exe", "securityhealthservice.exe", "msmpeng.exe",
    "nissrv.exe", "smartscreen.exe", "textinputhost.exe", "lockapp.exe", "shellexperiencehost.exe", "sshd.exe",
    "sshd-session.exe", "powershell.exe", "pwsh.exe", "cmd.exe", "python.exe", "pythonw.exe", "goxlr mini.exe",
    "msedgewebview2.exe", "searchindexer.exe", "wudfhost.exe", "useroobebroker.exe", "applicationframehost.exe",
}

# ---------------- journal ----------------
_log_lock = threading.Lock()
_log_last = {"msg": None, "n": 0, "t": 0.0}
RECENT_LOG = deque(maxlen=80)
LOG_PREFIX = ""

def _write_log(line):
    RECENT_LOG.append(line)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 2_000_000:
            for i in (2, 1):
                if os.path.exists(LOG_PATH + "." + str(i)):
                    os.replace(LOG_PATH + "." + str(i), LOG_PATH + "." + str(i + 1))
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass

def log(msg):
    """Journal avec anti-repetition : une erreur en boucle ne noie plus le fichier (v3 : 2 Mo en 6 h)."""
    msg = LOG_PREFIX + str(msg)
    now = time.time()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with _log_lock:
        last = _log_last
        if msg == last["msg"]:
            last["n"] += 1
            if now - last["t"] >= 60:
                _write_log(stamp + " " + msg + " (encore " + str(last["n"]) + " fois depuis la dernière ligne)")
                last["n"], last["t"] = 0, now
            return
        if last["n"]:
            _write_log(stamp + " (ligne précédente répétée " + str(last["n"]) + " fois)")
        last.update(msg=msg, n=0, t=now)
        _write_log(stamp + " " + msg)

# ---------------- couche DLL ----------------
_u32 = ctypes.c_uint32
_lib = None

def _load():
    global _lib
    if _lib is not None:
        return _lib
    if SIMULATE:
        import simulator
        _lib = simulator.FakeTusb.shared()
        return _lib
    assert struct.calcsize("P") == 8, "Python 64-bit requis"
    lib = ctypes.WinDLL(DLL_PATH)
    lib.TUSBAUDIO_EnumerateDevices.restype = _u32
    lib.TUSBAUDIO_GetDeviceCount.restype = _u32
    lib.TUSBAUDIO_OpenDeviceByIndex.argtypes = [_u32, ctypes.POINTER(_u32)]
    lib.TUSBAUDIO_OpenDeviceByIndex.restype = _u32
    lib.TUSBAUDIO_GetDeviceInstanceIdString.argtypes = [_u32, ctypes.POINTER(ctypes.c_uint16), _u32]
    lib.TUSBAUDIO_GetDeviceInstanceIdString.restype = _u32
    for name in ("TUSBAUDIO_ClassVendorRequestOut", "TUSBAUDIO_ClassVendorRequestIn"):
        fn = getattr(lib, name)
        fn.argtypes = [_u32, _u32, _u32, _u32, _u32, ctypes.c_uint16, ctypes.c_uint16,
                       ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_ubyte), _u32]
        fn.restype = _u32
    lib.TUSBAUDIO_CloseDevice.argtypes = [_u32]
    lib.TUSBAUDIO_CloseDevice.restype = _u32
    lib.TUSBAUDIO_StatusCodeStringA.argtypes = [_u32]
    lib.TUSBAUDIO_StatusCodeStringA.restype = ctypes.c_char_p
    _lib = lib
    return lib

def _st(code):
    s = _lib.TUSBAUDIO_StatusCodeStringA(code) if _lib else None
    return s.decode(errors="replace") if s else str(code)

class TusbError(RuntimeError):
    def __init__(self, what, code):
        super().__init__(f"{what}: {code}={_st(code)}")
        self.code = code

class DeviceError(RuntimeError):
    pass

class JobCancelled(Exception):
    pass

def _check(what, code):
    if code != 0:
        raise TusbError(what, code)

def _u16str(buf):
    out = []
    for c in buf:
        if not c:
            break
        out.append(chr(c))
    return "".join(out)

def colour_bytes(hexcol):
    v = int(hexcol.lstrip("#"), 16)
    return bytes([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, 0])  # ordre appareil B,G,R,0

def f32(v):
    return struct.pack("<f", float(v))

def level_db(level):
    if level <= 0:
        return -72.2
    return round(max(-72.2, min(0.0, 20 * math.log10(level) - 72.2)), 1)

def gate_attenuation(percent):
    percent = max(0, min(100, int(percent)))
    return GATE_ATTENUATION[25] if percent > 99 else GATE_ATTENUATION[int(percent * 0.24)]

def darken(hexcol, factor):
    v = int(hexcol, 16)
    r, g, b = (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF
    return "%02X%02X%02X" % (int(r * factor), int(g * factor), int(b * factor))

# ---------------- appareil ----------------
class GoXLR:
    """Acces brut. Aucun etat metier ici ; un seul fil l'utilise (la boucle USB du Controller)."""
    FIRST_READ_WAIT = 0.03     # lire trop tot fait caler le tube de controle (STALL)
    RETRY_WAIT = 0.01
    RESPONSE_TIMEOUT = 2.0
    INDEX_MAX = 0xFFFF         # index de commande sur 16 bits

    def __init__(self):
        _load()
        self.h = None
        self.count = 0
        self.serial = None
        self.firmware = None
        self.fw = (0, 0, 0, 0)
        self.busy_since = None
        self.stats = {"commands": 0, "stalls": 0, "resyncs": 0, "index_resets": 0, "opens": 0}

    @property
    def mix2(self):
        return self.fw[:2] >= (1, 3)   # Stream Mix 2 : firmware Mini >= 1.3

    def open(self):
        if self.h is not None:
            return
        _check("EnumerateDevices", _lib.TUSBAUDIO_EnumerateDevices())  # handle ferme : sans risque
        for idx in range(_lib.TUSBAUDIO_GetDeviceCount()):
            h = _u32(0)
            if _lib.TUSBAUDIO_OpenDeviceByIndex(idx, ctypes.byref(h)) != 0:
                continue
            buf = (ctypes.c_uint16 * 256)()
            if _lib.TUSBAUDIO_GetDeviceInstanceIdString(h.value, buf, 256) == 0 and "VID_1220" in _u16str(buf):
                self.h = h.value
                self.stats["opens"] += 1
                try:
                    self._activate()
                    self._read_info()
                except Exception:
                    self.close()
                    raise
                return
            _lib.TUSBAUDIO_CloseDevice(h.value)
        raise DeviceError("Aucune GoXLR trouvée par le pilote")

    def close(self):
        if self.h is not None:
            try:
                _lib.TUSBAUDIO_CloseDevice(self.h)
            finally:
                self.h = None

    def _req_out(self, request, data):
        arr = (ctypes.c_ubyte * len(data)).from_buffer_copy(data) if data else (ctypes.c_ubyte * 1)()
        meta = (ctypes.c_ubyte * 64)()
        self.busy_since = time.monotonic()
        try:
            code = _lib.TUSBAUDIO_ClassVendorRequestOut(self.h, 1, 0, request, 0, 0, len(data), arr, meta, 64)
        finally:
            self.busy_since = None
        _check(f"VendorOut({request})", code)

    def _req_in(self, request, length):
        buf = (ctypes.c_ubyte * length)()
        meta = (ctypes.c_ubyte * 64)()
        self.busy_since = time.monotonic()
        try:
            code = _lib.TUSBAUDIO_ClassVendorRequestIn(self.h, 1, 0, request, 0, 0, length, buf, meta, 64)
        finally:
            self.busy_since = None
        _check(f"VendorIn({request})", code)
        n = struct.unpack_from("<I", bytes(meta[:4]))[0]
        return bytes(buf[:min(n, length)])

    def _activate(self):
        self._req_in(0, 24)
        self._req_out(1, b"")
        time.sleep(0.2)
        try:
            self._req_in(3, 1040)      # vidange ; peut caler si rien n'est en attente
        except TusbError as e:
            if e.code != STATUS_STALL:
                raise
        self.count = 0

    def command(self, command_id, body=b"", retry=True):
        if self.h is None:
            raise DeviceError("GoXLR non connectée")
        if command_id == 0:
            self.count = 0
        else:
            if self.count >= self.INDEX_MAX:
                self.stats["index_resets"] += 1      # comme goxlr-utility : ResetCommandIndex avant debordement
                self.command(0, b"", retry=False)
            self.count += 1
        idx = self.count
        self._req_out(2, struct.pack("<IHH", command_id, len(body), idx) + b"\x00" * 8 + body)
        self.stats["commands"] += 1
        t0 = time.monotonic()
        wait = self.FIRST_READ_WAIT
        while time.monotonic() - t0 < self.RESPONSE_TIMEOUT:
            if wait:
                time.sleep(wait)
            wait = self.RETRY_WAIT
            try:
                resp = self._req_in(3, 1040)
            except TusbError as e:
                if e.code != STATUS_STALL:
                    raise
                self.stats["stalls"] += 1
                continue
            if len(resp) >= 16:
                _rid, rlen, ridx = struct.unpack_from("<IHH", resp)
                if ridx == idx:
                    return resp[16:16 + rlen]
        if retry and command_id != 0:
            self.stats["resyncs"] += 1
            log("Index de commande désynchronisé : remise à zéro et nouvel essai")
            self.command(0, b"", retry=False)
            return self.command(command_id, body, retry=False)
        raise DeviceError("Pas de réponse de la GoXLR")

    def _read_info(self):
        body = self.command((0x80F << 12) | 1)
        self.serial = body[:24].split(b"\x00")[0].decode(errors="replace")
        body = self.command((0x80F << 12) | 0)
        p, build = struct.unpack_from("<II", body)
        self.fw = (p >> 12, (p >> 8) & 0xF, p & 0xFF, build)
        self.firmware = ".".join(str(x) for x in self.fw)

    def set_volume(self, channel, value):
        self.command((0x806 << 12) | CHANNELS.index(channel), bytes([max(0, min(255, int(value)))]))

    def set_channel_state(self, channel, muted):
        self.command((0x809 << 12) | CHANNELS.index(channel), bytes([1 if muted else 0]))

    def set_fader(self, fader, channel):
        self.command((0x805 << 12) | FADERS.index(fader), bytes([CHANNELS.index(channel), 0, 0, 0]))

    def set_fader_display(self, fader, gradient, meter):
        self.command((0x814 << 12) | FADERS.index(fader), bytes([1 if gradient else 0, 1 if meter else 0]))

    def set_animation(self, mode, mod1, mod2, waterfall):
        enabled = 0 if mode == ANIMATIONS["none"] else 1
        self.command(0x816 << 12, bytes([enabled, mode, max(0, min(100, mod1)), max(0, min(100, mod2)), waterfall]))

    def set_routing(self, inp, outs):
        size = 26 if self.mix2 else 22   # 22 octets sans Stream Mix 2 (firmware Mini < 1.3)
        left, right = bytearray(size), bytearray(size)
        for out, on in outs.items():
            if not on or out not in OUTPUTS or (out == "StreamMix2" and not self.mix2):
                continue
            pl, pr = OUTPUTS[out]
            left[pl] = 0x20
            right[pr] = 0x20
        gl, gr = INPUTS[inp]
        self.command((0x804 << 12) | gl, bytes(left))
        self.command((0x804 << 12) | gr, bytes(right))

    def set_colour_map(self, data):
        self.command(0x803 << 12, bytes(data))

    def set_button_states(self, states):
        self.command(0x808 << 12, bytes(states))

    def get_button_states(self):
        body = self.command(0x800 << 12)
        if len(body) < 12:
            raise DeviceError(f"État des boutons tronqué ({len(body)} octets)")
        mask = struct.unpack_from("<I", body)[0]
        encoders = [struct.unpack_from("<b", body, 4 + i)[0] for i in range(4)]
        return mask, list(body[8:12]), encoders

    def mic_level(self):
        body = self.command(0x80C << 12)
        if len(body) < 2:
            raise DeviceError("Niveau micro tronqué")
        return struct.unpack_from("<H", body)[0]

    def set_mic_params(self, pairs):
        self.command(0x80B << 12, b"".join(struct.pack("<I", k) + bytes(v) for k, v in pairs))

    def set_effects(self, pairs):
        self.command(0x801 << 12, b"".join(struct.pack("<Ii", k, int(v)) for k, v in pairs))

    def set_mic_gain(self, mic_type, gain_db):
        val = bytearray(4)
        struct.pack_into("<H", val, 2, max(0, min(72, int(gain_db))))
        phantom = bytes([1, 0, 0, 0]) if mic_type == "condenser" else bytes(4)
        self.set_mic_params([(0x000, phantom), (MIC_GAIN_KEYS[mic_type], bytes(val))])

# ---------------- etat ----------------
def _hex(c):
    c = str(c).strip().lstrip("#").upper()
    if len(c) != 6 or any(ch not in "0123456789ABCDEF" for ch in c):
        raise ValueError(f"couleur invalide: {c}")
    return c

def _clamp(v, lo, hi):
    return max(lo, min(hi, int(round(float(v)))))

def default_state():
    return {
        "faders": {"A": "Mic", "B": "Music", "C": "Chat", "D": "System"},
        "volumes": {c: 128 for c in CHANNELS},
        "mutes": {c: False for c in CHANNELS},          # coupe partout
        "partial": {c: None for c in CHANNELS},         # coupe vers une sortie seulement (stream, chat...)
        "routing": _routing(),
        "colours": {t: ["00FFFF", "FFFFFF"] for t in COLOUR_TARGETS},
        "mic": {"type": "dynamic", "gain_db": 30},
        "dsp": copy.deepcopy(MIC_PRESETS["naturel"]["dsp"]),
        "mic_preset": "naturel",
        "bleep_db": -10,
        "lighting": {"theme": "voies", "animation": "none", "mod1": 39, "mod2": 39, "waterfall": "off",
                     "fader_style": {f: "gradient" for f in FADERS}},
        "mute_modes": {f: "all" for f in FADERS},       # effet d'un appui court sur le bouton mute du fader
        "mic_button": {"mode": "toggle", "target": "all", "blink": False},
        "vod": {"mode": "off"},
        "auto_scenes": {"enabled": False, "rules": [], "fallback": None},
        "prefs": {"hold_ms": 500, "osd": True, "update_reminded": None},
        "scene": None,
        "user_scenes": {},
    }

def normalize_dsp(src, base=None):
    d = copy.deepcopy(base or MIC_PRESETS["naturel"]["dsp"])
    src = src or {}
    for band, v in (src.get("eq") or {}).items():
        if str(band) in EQ_BANDS:
            d["eq"][str(band)] = _clamp(v, -9, 9)
    g = src.get("gate") or {}
    if "enabled" in g:
        d["gate"]["enabled"] = bool(g["enabled"])
    for k, lo, hi in (("threshold", -59, 0), ("attenuation", 0, 100), ("attack", 0, 45), ("release", 0, 45)):
        if k in g:
            d["gate"][k] = _clamp(g[k], lo, hi)
    c = src.get("comp") or {}
    for k, lo, hi in (("threshold", -40, 0), ("ratio", 0, 14), ("attack", 0, 19), ("release", 0, 19), ("makeup", -6, 24)):
        if k in c:
            d["comp"][k] = _clamp(c[k], lo, hi)
    if "deesser" in src:
        d["deesser"] = _clamp(src["deesser"], 0, 100)
    return d

def _norm_app(name):
    n = str(name or "").strip().lower()
    return n[:-4] if n.endswith(".exe") else n

def normalize_rules(rules, scene_names):
    out = []
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        app = str(r.get("app") or "").strip()[:64]
        if app and r.get("scene") in scene_names and _norm_app(app) not in [_norm_app(x["app"]) for x in out]:
            out.append({"app": app, "scene": r["scene"]})
    return out[:20]

def normalize_settings(st, src):
    """Reglages v4 (boutons, VOD, scenes auto, preferences). Modifie st sur place."""
    for f, mode in (src.get("mute_modes") or {}).items():
        if str(f).upper() in FADERS and mode in MUTE_TARGETS:
            st["mute_modes"][str(f).upper()] = mode
    mb = src.get("mic_button") or {}
    if mb.get("mode") in MIC_BUTTON_MODES:
        st["mic_button"]["mode"] = mb["mode"]
    if mb.get("target") in MUTE_TARGETS:
        st["mic_button"]["target"] = mb["target"]
    if "blink" in mb:
        st["mic_button"]["blink"] = bool(mb["blink"])
    vod = src.get("vod") or {}
    if vod.get("mode") in VOD_MODES:
        st["vod"]["mode"] = vod["mode"]
    pr = src.get("prefs") or {}
    if "hold_ms" in pr:
        st["prefs"]["hold_ms"] = _clamp(pr["hold_ms"], 250, 2000)
    if "osd" in pr:
        st["prefs"]["osd"] = bool(pr["osd"])
    if "update_reminded" in pr:
        st["prefs"]["update_reminded"] = pr["update_reminded"] if parse_semver(pr["update_reminded"]) else None
    au = src.get("auto_scenes") or {}
    names = set(SCENES) | set(st["user_scenes"])
    if "enabled" in au:
        st["auto_scenes"]["enabled"] = bool(au["enabled"])
    if "rules" in au:
        st["auto_scenes"]["rules"] = normalize_rules(au["rules"], names)
    if "fallback" in au:
        st["auto_scenes"]["fallback"] = au["fallback"] if au["fallback"] in names else None
    return st

def normalize_state(src):
    st = default_state()
    src = src if isinstance(src, dict) else {}
    for f, ch in (src.get("faders") or {}).items():
        if f.upper() in FADERS and ch in CHANNELS:
            st["faders"][f.upper()] = ch
    for ch, v in (src.get("volumes") or {}).items():
        if ch in CHANNELS:
            st["volumes"][ch] = _clamp(v, 0, 255)
    for ch, m in (src.get("mutes") or {}).items():
        if ch in CHANNELS:
            st["mutes"][ch] = bool(m)
    for ch, t in (src.get("partial") or {}).items():
        if ch in CHANNEL_INPUT and t in MUTE_TARGETS and t != "all" and not st["mutes"][ch]:
            st["partial"][ch] = t
    for inp, outs in (src.get("routing") or {}).items():
        if inp in INPUTS and isinstance(outs, dict):
            for out, on in outs.items():
                if out in OUTPUTS:
                    st["routing"][inp][out] = bool(on)
    for t, cols in (src.get("colours") or {}).items():
        t = COLOUR_ALIASES.get(t, t)
        if t in COLOUR_TARGETS:
            cols = [cols] if isinstance(cols, str) else list(cols)
            cols = [_hex(c) for c in cols if c]
            if cols:
                st["colours"][t] = (cols + cols)[:2]
    mic = src.get("mic") or {}
    if mic.get("type") in MIC_TYPES:
        st["mic"]["type"] = mic["type"]
    if mic.get("gain_db") is not None:
        st["mic"]["gain_db"] = _clamp(mic["gain_db"], 0, 72)
    if src.get("dsp"):
        st["dsp"] = normalize_dsp(src["dsp"])
    if src.get("mic_preset") in MIC_PRESETS or src.get("mic_preset") == "custom":
        st["mic_preset"] = src["mic_preset"]
    if "bleep_db" in src:
        st["bleep_db"] = _clamp(src["bleep_db"], -36, 0)
    li = src.get("lighting") or {}
    if li.get("theme") in THEMES or li.get("theme") == "custom":
        st["lighting"]["theme"] = li["theme"]
    if li.get("animation") in ANIMATIONS:
        st["lighting"]["animation"] = li["animation"]
    for k in ("mod1", "mod2"):
        if k in li:
            st["lighting"][k] = _clamp(li[k], 0, 100)
    if li.get("waterfall") in WATERFALL:
        st["lighting"]["waterfall"] = li["waterfall"]
    for f, style in (li.get("fader_style") or {}).items():
        if f in FADERS and style in FADER_STYLES:
            st["lighting"]["fader_style"][f] = style
    for name, sc in (src.get("user_scenes") or {}).items():
        if isinstance(sc, dict) and str(name).strip():
            st["user_scenes"][str(name).strip()[:40]] = sc
    if src.get("scene") in SCENES or src.get("scene") in st["user_scenes"]:
        st["scene"] = src["scene"]
    normalize_settings(st, src)
    return st

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def parse_volume(v):
    s = str(v).strip()
    if s.endswith("%"):
        return max(0, min(255, round(float(s[:-1]) * 255 / 100)))
    return max(0, min(255, int(float(s))))

def parse_bool(v):
    if isinstance(v, str):
        return v.lower() in ("1", "on", "true", "oui", "yes")
    return bool(v)

def describe(e):
    """Texte d'erreur lisible ; pour une erreur inattendue, ajoute le type et la ligne du code."""
    if isinstance(e, (TusbError, DeviceError)):
        return str(e)
    where = ""
    tb = traceback.extract_tb(e.__traceback__) if getattr(e, "__traceback__", None) else None
    if tb:
        fr = tb[-1]
        where = f" ({os.path.basename(fr.filename)}:{fr.lineno})"
    return f"{type(e).__name__}: {e}{where}"

# ---------------- controleur ----------------
class Controller:
    """Etat + boucle USB. Seul device_loop() parle a l'appareil ; le reste ne fait que modifier
    l'etat sous self.lock et marquer ce qui doit partir (self._dirty)."""

    def __init__(self, persist=True):
        self.lock = threading.RLock()
        self.dev = GoXLR()
        self.persist = persist
        self.state = normalize_state(self._initial_state())
        if self.state["lighting"]["theme"] in THEMES:
            self._theme_colours()
        self.connected = False
        self.present = None
        self.last_error = None
        self.connected_since = None
        self._conn_mono = None
        self.started = time.time()
        self.live = {"fader_positions": [None] * 4, "mic_db": None, "pressed": [], "encoders": [0] * 4}
        self.version = 1
        self.job = None
        self.fast_level = False
        self.level_until = 0.0
        self._dirty = set()
        self._want = 0
        self._done = 0
        self._save_dirty = False
        self._calls = deque()
        self.wake = threading.Event()
        self.heartbeat = time.monotonic()
        self._prev_mask = 0
        self._prev_pos = None
        self._btn = {}
        self._bleep = False
        self.blink = {}
        self._gain_override = None
        self._force_reconnect = False
        self.errors = deque(maxlen=15)
        self.connects = 0
        self.reconnects = 0
        self.fail_streak = 0
        self.auto_active = None
        self.auto_note = None
        self._auto_seen = False             # premiere evaluation faite (au demarrage, l'etat sauvegarde fait foi)
        self.supervised = os.environ.get("GOXLR_SUPERVISED") == "1"
        self.engine_restarts = int(os.environ.get("GOXLR_RESTARTS") or 0)
        self._last_backup = 0.0
        self.updater = Updater(self)

    def _initial_state(self):
        for p in (STATE_PATH, STATE_PATH + ".bak", DEFAULT_PROFILE_PATH):
            if os.path.exists(p):
                try:
                    data = load_json(p)
                    if p != STATE_PATH:
                        log(f"État repris depuis {os.path.basename(p)}")
                    return data
                except Exception as e:
                    log(f"Lecture {p} impossible: {e}")
        return {}

    def _mark(self, *keys, bump=True):
        """Marque des elements a envoyer ; la boucle USB les enverra avec la valeur la plus recente."""
        self._dirty.update(keys)
        self._want += 1
        if bump:
            self.version += 1
            self._save_dirty = True
        self.wake.set()
        return self._want

    # -- routage effectif (mutes partiels et VOD) --
    def vod_output(self):
        return "StreamMix2" if self.dev.mix2 else "Sampler"

    def effective_routing(self, inp):
        s = self.state
        r = dict(s["routing"][inp])
        vod_on = s["vod"]["mode"] == "no-music"
        vod = self.vod_output()
        if vod_on:          # VOD = stream sans la musique (comme « Stream No Music » de goxlr-utility)
            r[vod] = False if inp == "Music" else r["BroadcastMix"]
        ch = IN_CHANNEL[inp]
        if s["mutes"][ch]:
            if ch == "Mic":
                r = {o: False for o in r}
        else:
            t = s["partial"].get(ch)
            if t:
                for out in MUTE_TARGETS[t]:
                    r[out] = False
                if t == "stream" and vod_on:
                    r[vod] = False
        return r

    # -- plan d'envoi --
    ALL_KEYS = None

    def _plan(self, keys):
        s, d = self.state, self.dev
        if "all" in keys:
            keys = ({"faders", "mic", "dsp", "lighting", "colours", "buttons"}
                    | {("volume", c) for c in CHANNELS} | {("mute", c) for c in CHANNELS}
                    | {("route", i) for i in INPUTS})
        ops = []
        if "faders" in keys:
            for f in FADERS:
                ops.append((d.set_fader, (f, s["faders"][f])))
        for c in CHANNELS:
            if ("volume", c) in keys:
                ops.append((d.set_volume, (c, s["volumes"][c])))
        for c in CHANNELS:
            if ("mute", c) in keys:
                ops.append((d.set_channel_state, (c, s["mutes"][c])))
        if ("mute", "Mic") in keys and "dsp" not in keys:
            ops.append((d.set_effects, ([(0x0158, 1 if s["mutes"]["Mic"] else 0)],)))
        for i in INPUTS:
            if ("route", i) in keys:
                ops.append((d.set_routing, (i, self.effective_routing(i))))
        if "mic" in keys:
            mtype, gain = self._gain_override or (s["mic"]["type"], s["mic"]["gain_db"])
            ops.append((d.set_mic_gain, (mtype, gain)))
        if "dsp" in keys:
            params, effects = self._dsp_lists()
            ops.append((d.set_mic_params, (params,)))
            ops.append((d.set_effects, (effects,)))
        if "lighting" in keys:
            li = s["lighting"]
            for f in FADERS:
                g, m = FADER_STYLES[li["fader_style"][f]]
                ops.append((d.set_fader_display, (f, g, m)))
            ops.append((d.set_animation, (ANIMATIONS[li["animation"]], li["mod1"], li["mod2"], WATERFALL[li["waterfall"]])))
        if "colours" in keys:
            ops.append((d.set_colour_map, (self.colour_map(),)))
        if "buttons" in keys:
            ops.append((d.set_button_states, (self.button_states(),)))
        return ops

    def flush(self):
        """Envoie ce qui est marque. A appeler uniquement depuis la boucle USB."""
        with self.lock:
            if not self._dirty:
                return 0
            keys, self._dirty = self._dirty, set()
            gen = self._want
            ops = self._plan(keys)
        for fn, args in ops:
            fn(*args)
            self.heartbeat = time.monotonic()
        with self.lock:
            if gen > self._done:
                self._done = gen
        return len(ops)

    def _dsp_lists(self):
        s = self.state
        dsp, g, c = s["dsp"], s["dsp"]["gate"], s["dsp"]["comp"]
        thr = g["threshold"] if g["enabled"] else -59
        att = gate_attenuation(g["attenuation"] if g["enabled"] else 0)
        params = [(0x30200, f32(thr)), (0x30400, f32(g["attack"])), (0x30600, f32(g["release"])),
                  (0x30900, f32(att)),
                  (0x60200, f32(c["threshold"])), (0x60300, f32(RATIOS[c["ratio"]])),
                  (0x60400, f32(c["attack"])), (0x60600, f32(c["release"])), (0x60700, f32(c["makeup"])),
                  (0x70100, f32(s["bleep_db"] * 65536.0))]
        for band, (kf, kg) in EQ_BANDS.items():
            params += [(kf, f32(float(band))), (kg, f32(dsp["eq"][band]))]
        effects = [(0x0011, thr), (0x0016, g["attack"]), (0x0017, g["release"]), (0x0015, att),
                   (0x0014, 1), (0x0010, 2), (0x014B, 1),
                   (0x013D, c["threshold"]), (0x013C, c["ratio"]), (0x013E, c["attack"]),
                   (0x013F, c["release"]), (0x0140, c["makeup"]),
                   (0x000B, dsp["deesser"]), (0x0073, s["bleep_db"]),
                   (0x0158, 1 if s["mutes"]["Mic"] else 0)]
        return params, effects

    def _theme_colours(self):
        """Ecrit les couleurs du theme courant dans l'etat (le theme 'voies' suit les faders)."""
        s = self.state
        th = THEMES.get(s["lighting"]["theme"])
        if not th:
            return
        cols = s["colours"]
        for i, f in enumerate(FADERS):
            if th.get("per_channel"):
                top = CHANNEL_COLOURS[s["faders"][f]]
            elif th.get("faders"):
                top = th["faders"][i]
            else:
                top = th["top"]
            bottom = th.get("bottom") or darken(top, 0.16)
            cols[f"FadeMeter{i + 1}"] = [bottom, top]
            cols[f"Fader{i + 1}Mute"] = [top, darken(top, 0.3)]
        accent = th["accent"]
        cols["Global"] = [accent, accent]
        cols["Accent"] = [accent, accent]
        cols["MicrophoneMute"] = [CHANNEL_COLOURS["Mic"] if th.get("per_channel") else accent, "000000"]
        cols["Bleep"] = [accent, "000000"]

    def colour_map(self):
        s = self.state
        data = bytearray(520)
        for t, (start, count) in COLOUR_TARGETS.items():
            cols = s["colours"][t]
            if t.startswith("FadeMeter") and s["mutes"][s["faders"][FADERS[int(t[-1]) - 1]]]:
                cols = ["000000", "000000"]      # comme goxlr-utility sur Mini : fader coupe = eteint
            for i in range(count):
                pos = start * 4 + i * 4
                data[pos:pos + 4] = colour_bytes(cols[i])
        return data

    def _led(self, ch, mic_button=False):
        s = self.state
        muted = s["mutes"][ch] or bool(s["partial"].get(ch))
        if not muted:
            return BTN_DIM
        if (s["mutes"][ch] and self.blink.get(ch)) or (mic_button and s["mic_button"]["blink"]):
            return BTN_FLASH
        return BTN_ON

    def button_states(self):
        s = self.state
        arr = [BTN_DIM] * 24
        for i, b in enumerate(FADER_BUTTONS):
            arr[BUTTON_BITS[b]] = self._led(s["faders"][FADERS[i]])
        arr[BUTTON_BITS["MicrophoneMute"]] = self._led("Mic", mic_button=True)
        arr[BUTTON_BITS["Bleep"]] = BTN_ON if self._bleep else BTN_DIM
        return arr

    # -- mutes --
    def _mute_to(self, ch, target):
        s = self.state
        if target not in MUTE_TARGETS:
            target = "all"
        if target == "all" or ch not in CHANNEL_INPUT:
            s["mutes"][ch], s["partial"][ch] = True, None
        else:
            s["mutes"][ch], s["partial"][ch] = False, target

    def _unmute(self, ch):
        s = self.state
        s["mutes"][ch], s["partial"][ch] = False, None
        self.blink.pop(ch, None)

    def _mute_changed(self, ch):
        keys = [("mute", ch), "colours", "buttons"]
        if ch in CHANNEL_INPUT:
            keys.append(("route", CHANNEL_INPUT[ch]))
        self._mark(*keys)

    def _is_muted(self, ch):
        return self.state["mutes"][ch] or bool(self.state["partial"].get(ch))

    def _toggle(self, ch, target, who):
        if self._is_muted(ch):
            self._unmute(ch)
            what = "actif"
        else:
            self._mute_to(ch, target)
            what = "coupé " + MUTE_TARGET_LABELS["all" if self.state["mutes"][ch] else target]
        self._mute_changed(ch)
        log(f"{who} : {CHANNEL_LABELS[ch]} {what}")

    # -- connexion --
    def connect(self, apply=True):
        """Ouvre l'appareil (boucle USB uniquement). Enumerate n'est appele qu'avec le handle ferme."""
        self.dev.close()
        self.dev.open()
        with self.lock:
            self.connected = True
            self.present = True
            self.connected_since = time.time()
            self._conn_mono = time.monotonic()
            self.last_error = None
            self._prev_mask, self._prev_pos, self._btn, self._bleep = 0, None, {}, False
            if self.connects:
                self.reconnects += 1
            self.connects += 1
            self.version += 1
            if apply:
                self._dirty = {"all"}
                self._want += 1
        log(f"GoXLR connectée : série {self.dev.serial}, firmware {self.dev.firmware}"
            + (" (Stream Mix 2)" if self.dev.mix2 else ""))
        if apply:
            n = self.flush()
            log(f"État complet appliqué ({n} envois)")

    def drop(self, why):
        msg = describe(why)
        with self.lock:
            was = self.connected
            self.connected = False
            self.connected_since = None
            self._conn_mono = None
            self.last_error = msg
            self.live["fader_positions"] = [None] * 4
            self.live["pressed"] = []
            if was:
                self.version += 1
                self.errors.append({"t": time.time(), "msg": msg})
        try:
            self.dev.close()
        except Exception:
            pass
        if was:
            log("GoXLR perdue : " + msg)

    def _fail_calls(self, msg):
        while self._calls:
            _fn, box = self._calls.popleft()
            box["error"] = DeviceError(msg)
            box["ev"].set()

    def _run_calls(self):
        while self._calls:
            fn, box = self._calls.popleft()
            try:
                box["result"] = fn()
            except Exception as e:
                box["error"] = e
                box["ev"].set()
                raise
            box["ev"].set()

    def call(self, fn, timeout=5.0):
        """Execute fn dans la boucle USB et attend le resultat (commande brute, CLI)."""
        if not self.connected:
            raise DeviceError("GoXLR non connectée")
        box = {"ev": threading.Event()}
        self._calls.append((fn, box))
        self.wake.set()
        if not box["ev"].wait(timeout):
            raise DeviceError("La GoXLR ne répond pas")
        if "error" in box:
            e = box["error"]
            raise e if isinstance(e, DeviceError) else DeviceError(describe(e))
        return box.get("result")

    def _want_level(self, tick):
        if self.fast_level:
            return True
        if time.monotonic() < self.level_until:
            return tick % 2 == 0
        return False

    def device_loop(self, stop=None):
        next_try, tick = 0.0, 0
        while not (stop is not None and stop.is_set()):
            now = time.monotonic()
            self.heartbeat = now
            if self._force_reconnect:
                self._force_reconnect = False
                if self.connected:
                    self.drop(DeviceError("reconnexion demandée"))
                next_try = 0.0
            if not self.connected:
                self._fail_calls("GoXLR non connectée")
                if now >= next_try:
                    try:
                        self.connect()
                    except Exception as e:
                        absent = isinstance(e, DeviceError) and "Aucune GoXLR" in str(e)
                        msg = describe(e)
                        self.drop(e)
                        with self.lock:
                            changed = self.present != (not absent)
                            self.present = not absent
                            self.last_error = msg
                            if changed:
                                self.version += 1
                        if absent:
                            delay = 2.0
                            log("GoXLR absente (éteinte ou débranchée) : nouvel essai toutes les 2 s")
                        else:
                            self.fail_streak += 1
                            delay = min(30.0, 2.0 ** min(self.fail_streak, 5))
                            with self.lock:
                                self.errors.append({"t": time.time(), "msg": "connexion : " + msg})
                            log(f"Connexion impossible : {msg}")
                        next_try = time.monotonic() + delay
                self.wake.wait(0.25)
                self.wake.clear()
                continue
            try:
                self._run_calls()
                self.flush()
                self.poll_once(self._want_level(tick))
                self.flush()
                if self.fail_streak and self._conn_mono and time.monotonic() - self._conn_mono > 30:
                    self.fail_streak = 0
            except Exception as e:     # toute erreur, meme inattendue : on ferme et on repart proprement
                self.drop(e)
                self.fail_streak += 1
                next_try = time.monotonic() + min(30.0, 0.5 * 2 ** min(self.fail_streak, 6))
            tick += 1
            self.wake.wait(POLL_INTERVAL)
            self.wake.clear()

    # -- lecture en direct et boutons physiques --
    def poll_once(self, with_level=True):
        mask, vols, enc = self.dev.get_button_states()
        lvl = level_db(self.dev.mic_level()) if with_level else None
        now = time.monotonic()
        with self.lock:
            if lvl is not None:
                self.live["mic_db"] = lvl
                self.live["level_t"] = now
            elif self.live.get("level_t") and now - self.live["level_t"] > 1.5:
                self.live["mic_db"] = None
                self.live["level_t"] = None
            self._handle_inputs(mask, vols, now)
            self.live["encoders"] = enc

    def _handle_inputs(self, mask, vols, now):
        s = self.state
        pressed = mask & ~self._prev_mask
        released = self._prev_mask & ~mask
        self._prev_mask = mask
        for name, bit in BUTTON_BITS.items():
            b = 1 << bit
            if pressed & b:
                self._btn[name] = {"t": now, "held": False}
                self._on_down(name)
            if released & b:
                st = self._btn.pop(name, None) or {"t": now, "held": False}
                self._on_up(name, st["held"])
        hold_s = s["prefs"]["hold_ms"] / 1000.0
        for name, st in list(self._btn.items()):
            if not st["held"] and now - st["t"] >= hold_s:
                st["held"] = True
                self._on_hold(name)
        changed = False
        if self._prev_pos is not None:
            for i in range(4):
                if vols[i] != self._prev_pos[i]:   # fader physique bouge : l'appareil a deja change le volume
                    ch = s["faders"][FADERS[i]]
                    if s["volumes"][ch] != vols[i]:
                        s["volumes"][ch] = vols[i]
                        changed = True
        if changed:
            self.version += 1
            self._save_dirty = True
        self._prev_pos = list(vols)
        self.live["fader_positions"] = list(vols)
        self.live["pressed"] = [n for n, b in BUTTON_BITS.items() if mask & (1 << b)]

    def _on_down(self, name):
        s = self.state
        if name == "MicrophoneMute":
            mb = s["mic_button"]
            if mb["mode"] == "hold":
                self._mute_to("Mic", mb["target"])
                self._mute_changed("Mic")
            elif mb["mode"] == "ptt":
                self._unmute("Mic")
                self._mute_changed("Mic")
        elif name == "Bleep":
            self._bleep = True
            self._mark("buttons", bump=False)

    def _on_hold(self, name):
        s = self.state
        if name in FADER_BUTTONS:
            ch = s["faders"][FADERS[FADER_BUTTONS.index(name)]]
            if not s["mutes"][ch]:
                self._mute_to(ch, "all")
                self.blink[ch] = True
                self._mute_changed(ch)
                log(f"Bouton {FADER_BUTTONS.index(name) + 1} maintenu : {CHANNEL_LABELS[ch]} coupé partout")
        elif name == "MicrophoneMute" and s["mic_button"]["mode"] == "toggle" and not s["mutes"]["Mic"]:
            self._mute_to("Mic", "all")
            self.blink["Mic"] = True
            self._mute_changed("Mic")
            log("Bouton micro maintenu : micro coupé partout")

    def _on_up(self, name, held):
        s = self.state
        if name in FADER_BUTTONS:
            if held:
                return
            i = FADER_BUTTONS.index(name)
            self._toggle(s["faders"][FADERS[i]], s["mute_modes"][FADERS[i]], f"Bouton {i + 1}")
        elif name == "MicrophoneMute":
            mb = s["mic_button"]
            if mb["mode"] == "toggle":
                if not held:
                    self._toggle("Mic", mb["target"], "Bouton micro")
            elif mb["mode"] == "hold":
                self._unmute("Mic")
                self._mute_changed("Mic")
            elif mb["mode"] == "ptt":
                self._mute_to("Mic", mb["target"])
                self._mute_changed("Mic")
        elif name == "Bleep":
            self._bleep = False
            self._mark("buttons", bump=False)

    # -- actions (API) : ne touchent jamais l'USB --
    def act(self, action, p):
        p = p or {}
        if action == "update-check":
            self.updater.check(manual=True)
            return {"ok": True, "update": self.updater.snapshot()}
        if action == "update-install":
            self.updater.start_install()
            return {"ok": True}
        if action == "update-cancel":
            self.updater.cancel_install()
            return {"ok": True}
        if action == "update-ack":
            self.updater.ack_installed()
            return {"ok": True}
        if action == "update-remind":
            with self.lock:
                self.state["prefs"]["update_reminded"] = p.get("version") if parse_semver(p.get("version")) else None
                self.version += 1
                self._save_dirty = True
            return {"ok": True}
        if action == "raw":
            cid, body = int(str(p["command_id"]), 16), bytes.fromhex(p.get("body_hex") or "")
            resp = self.call(lambda: self.dev.command(cid, body))
            return {"ok": True, "response_hex": resp.hex()}
        if action == "reconnect":
            self._force_reconnect = True
            self.wake.set()
            log("Reconnexion de la GoXLR demandée")
            return {"ok": True}
        if action == "restart-engine":
            if not self.supervised:
                raise ValueError("Le moteur n'est pas lancé par son superviseur : relance la tâche planifiée « GoXLR Mini ».")
            log("Redémarrage du moteur demandé depuis l'interface")
            self.save_if_dirty()
            threading.Timer(0.4, lambda: os._exit(EXIT_RESTART)).start()
            return {"ok": True}
        with self.lock:
            result = self._act(action, p)
            self.version += 1
            self._save_dirty = True
            return result

    def _act(self, action, p):
        s = self.state
        if action == "volume":
            ch, v = self._channel(p["channel"]), parse_volume(p["value"])
            s["volumes"][ch] = v
            self._mark(("volume", ch))
        elif action == "mute":
            ch = self._channel(p["channel"])
            if parse_bool(p["muted"]):
                self._mute_to(ch, p.get("target") or "all")
            else:
                self._unmute(ch)
            self._mute_changed(ch)
        elif action == "fader":
            f, ch = str(p["fader"]).upper(), self._channel(p["channel"])
            if f not in FADERS:
                raise ValueError(f"fader inconnu: {f}")
            old = s["faders"][f]
            swapped = [k for k, v in s["faders"].items() if v == ch and k != f]
            for k in swapped:          # une voie par fader : on echange
                s["faders"][k] = old
            s["faders"][f] = ch
            s["scene"] = None
            self._prev_pos = None
            if s["lighting"]["theme"] == "voies":
                self._theme_colours()
            self._mark("faders", "colours", "buttons")
        elif action == "route":
            inp, out = p["input"], p["output"]
            if inp not in INPUTS or out not in OUTPUTS:
                raise ValueError("entrée ou sortie inconnue")
            s["routing"][inp][out] = parse_bool(p["enabled"])
            s["scene"] = None
            self._mark(("route", inp))
        elif action == "colour":
            t = COLOUR_ALIASES.get(p["target"], p["target"])
            if t == "all":
                c = _hex(p.get("colour_one") or p["colours"][0])
                for k in COLOUR_TARGETS:
                    s["colours"][k] = [darken(c, 0.16), c] if k.startswith("FadeMeter") else [c, c]
            elif t in COLOUR_TARGETS:
                cols = p.get("colours") or [p.get("colour_one"), p.get("colour_two")]
                for i, c in enumerate(cols[:2]):
                    if c:
                        s["colours"][t][i] = _hex(c)
            else:
                raise ValueError(f"cible couleur inconnue: {t}")
            s["lighting"]["theme"] = "custom"
            self._mark("colours")
        elif action == "theme":
            name = p["name"]
            if name not in THEMES:
                raise ValueError(f"thème inconnu: {name}")
            s["lighting"]["theme"] = name
            self._theme_colours()
            self._mark("colours")
        elif action == "lighting":
            li = s["lighting"]
            if p.get("animation") in ANIMATIONS:
                li["animation"] = p["animation"]
            for k in ("mod1", "mod2"):
                if k in p:
                    li[k] = _clamp(p[k], 0, 100)
            if p.get("waterfall") in WATERFALL:
                li["waterfall"] = p["waterfall"]
            styles = p.get("fader_style") or {}
            if isinstance(styles, str):
                styles = {f: styles for f in FADERS}
            for f, st in styles.items():
                if f in FADERS and st in FADER_STYLES:
                    li["fader_style"][f] = st
            self._mark("lighting")
        elif action == "mic":
            mtype = p.get("type", s["mic"]["type"])
            if mtype not in MIC_TYPES:
                raise ValueError(f"type micro inconnu: {mtype}")
            gain = p.get("gain_db")
            if gain is None and mtype != s["mic"]["type"] and p.get("suggest_gain"):
                gain = RECOMMENDED_GAIN[mtype]
            s["mic"] = {"type": mtype, "gain_db": _clamp(gain if gain is not None else s["mic"]["gain_db"], 0, 72)}
            self._mark("mic")
        elif action == "dsp":
            s["dsp"] = normalize_dsp(p, s["dsp"])
            if "bleep_db" in p:
                s["bleep_db"] = _clamp(p["bleep_db"], -36, 0)
            s["mic_preset"] = "custom"
            self._mark("dsp")
        elif action == "mic-preset":
            name = p["name"]
            if name not in MIC_PRESETS:
                raise ValueError(f"préréglage micro inconnu: {name}")
            s["dsp"] = copy.deepcopy(MIC_PRESETS[name]["dsp"])
            s["mic_preset"] = name
            self._mark("dsp")
        elif action == "scene":
            self._apply_scene(p["name"], p.get("with_mic", True))
        elif action == "scene-save":
            name = str(p["name"]).strip()[:40]
            if not name:
                raise ValueError("nom de scène vide")
            s["user_scenes"][name] = {k: copy.deepcopy(s[k]) for k in
                                      ("faders", "routing", "volumes", "mic", "dsp", "mic_preset", "lighting",
                                       "colours", "mute_modes", "vod")}
            s["scene"] = name
        elif action == "scene-delete":
            name = str(p["name"])
            s["user_scenes"].pop(name, None)
            if s["scene"] == name:
                s["scene"] = None
            au = s["auto_scenes"]
            au["rules"] = [r for r in au["rules"] if r["scene"] != name]
            if au["fallback"] == name:
                au["fallback"] = None
        elif action == "settings":
            self._settings(p)
        elif action == "auto-scenes":
            normalize_settings(s, {"auto_scenes": p})
            self.auto_active = "?"          # re-evaluation au prochain passage
            self._auto_seen = True
        elif action in ("detect-mic", "auto-gain"):
            self._start_job(action, p)
        elif action == "job-cancel":
            if self.job:
                self.job["cancel"] = True
        elif action == "profile":
            keep = s["user_scenes"]
            self.state = normalize_state(p.get("profile", p))
            if not self.state["user_scenes"]:
                self.state["user_scenes"] = keep
            if self.state["lighting"]["theme"] in THEMES:
                self._theme_colours()
            self.blink = {}
            self._prev_pos = None
            self._mark("all")
        else:
            raise KeyError(f"action inconnue: {action}")
        return {"ok": True, "queued": self.connected}

    def _settings(self, p):
        s = self.state
        before_mb = dict(s["mic_button"])
        before_vod = s["vod"]["mode"]
        normalize_settings(s, {k: p[k] for k in ("mute_modes", "mic_button", "vod", "prefs") if k in p})
        mb = s["mic_button"]
        if mb["mode"] == "ptt" and before_mb["mode"] != "ptt":
            self._mute_to("Mic", mb["target"])            # appuyer pour parler : micro coupe au repos
            self._mute_changed("Mic")
        elif before_mb["mode"] == "ptt" and mb["mode"] != "ptt" and self._is_muted("Mic"):
            self._unmute("Mic")
            self._mute_changed("Mic")
        elif mb["target"] != before_mb["target"] and s["partial"]["Mic"]:
            self._mute_to("Mic", mb["target"])
            self._mute_changed("Mic")
        if mb["blink"] != before_mb["blink"]:
            self._mark("buttons")
        if s["vod"]["mode"] != before_vod:
            self._mark(*[("route", i) for i in INPUTS])

    def _apply_scene(self, name, with_mic=True):
        s = self.state
        if name in SCENES:
            sc = SCENES[name]
            s["faders"] = dict(sc["faders"])
            s["routing"] = copy.deepcopy(sc["routing"])
            if with_mic and sc.get("mic_preset"):
                s["dsp"] = copy.deepcopy(MIC_PRESETS[sc["mic_preset"]]["dsp"])
                s["mic_preset"] = sc["mic_preset"]
            if s["lighting"]["theme"] == "voies":
                self._theme_colours()
        elif name in s["user_scenes"]:
            keep = {k: s[k] for k in ("user_scenes", "mutes", "partial", "auto_scenes", "prefs", "mic_button")}
            merged = normalize_state(dict(s, **copy.deepcopy(s["user_scenes"][name])))
            merged.update(keep)
            self.state = s = merged
        else:
            raise ValueError(f"scène inconnue: {name}")
        s["scene"] = name
        self._prev_pos = None
        self._mark("all")

    @staticmethod
    def _channel(ch):
        for c in CHANNELS:
            if c.lower() == str(ch).lower():
                return c
        raise ValueError(f"canal inconnu: {ch}")

    # -- analyses micro --
    def _start_job(self, kind, p):
        if self.job and self.job.get("running"):
            raise ValueError("Une analyse est déjà en cours.")
        if not self.connected:
            raise DeviceError("GoXLR non connectée")
        self.job = {"kind": kind, "running": True, "progress": 0.0, "step": "", "result": None,
                    "error": None, "started": time.time()}
        threading.Thread(target=self._run_job, args=(kind, dict(p)), daemon=True).start()

    def _job_update(self, **kw):
        with self.lock:
            self.job.update(kw)

    def _wait_applied(self, gen, timeout=4.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self._done >= gen:
                return
            if not self.connected:
                raise DeviceError("GoXLR déconnectée pendant l’analyse")
            time.sleep(0.02)
        raise DeviceError("La GoXLR ne répond pas")

    def _set_gain_and_wait(self, mtype, gain):
        with self.lock:
            self._gain_override = (mtype, gain)
            gen = self._mark("mic", bump=False)
        self._wait_applied(gen)

    def _sample(self, seconds, p0, p1):
        vals, t0 = [], time.time()
        while time.time() - t0 < seconds:
            if self.job.get("cancel"):
                raise JobCancelled()
            if not self.connected:
                raise DeviceError("GoXLR déconnectée pendant l’analyse")
            v = self.live["mic_db"]
            if v is not None:
                vals.append(v)
            self._job_update(progress=round(p0 + (p1 - p0) * (time.time() - t0) / seconds, 3))
            time.sleep(0.04)
        return vals

    def _run_job(self, kind, p):
        self.fast_level = True
        try:
            if kind == "detect-mic":
                result = self._detect_mic(bool(p.get("phantom")))
            else:
                result = self._auto_gain(float(p.get("target_db", -12)), float(p.get("seconds", 6)))
            self._job_update(running=False, progress=1.0, result=result, step="Terminé")
        except JobCancelled:
            self._job_update(running=False, error="Analyse annulée.")
        except Exception as e:
            log(f"Analyse {kind}: {describe(e)}")
            self._job_update(running=False, error=str(e))
        finally:
            self.fast_level = False
            with self.lock:
                self._gain_override = None
                self._mark("mic")

    def _detect_mic(self, phantom):
        tests = [("dynamic", 40, "Entrée XLR"), ("jack", 30, "Entrée jack 3,5 mm")]
        if phantom:
            tests.append(("condenser", 30, "Entrée XLR avec alimentation 48 V"))
        levels = {}
        n = len(tests)
        for i, (mtype, gain, label) in enumerate(tests):
            self._job_update(step=f"Écoute : {label}")
            self._set_gain_and_wait(mtype, gain)
            self._sample(0.6, i / n, (i + 0.3) / n)              # stabilisation
            vals = sorted(self._sample(1.6, (i + 0.3) / n, (i + 1) / n))
            floor = vals[len(vals) // 2] if vals else -72.2
            peak = vals[-1] if vals else -72.2
            levels[mtype] = {"floor_db": floor, "peak_db": peak, "gain_db": gain, "label": label}
        present = {k: v for k, v in levels.items() if v["peak_db"] > -70.5}
        if not present:
            return {"detected": None, "levels": levels,
                    "message": "Aucun micro détecté. Branche-le (XLR ou jack) puis relance l’analyse."
                               + ("" if phantom else " Micro statique : relance avec l’alimentation 48 V.")}
        best = max(present, key=lambda k: present[k]["floor_db"])
        return {"detected": best, "levels": levels, "recommended_preset": MIC_TYPE_PRESET[best],
                "recommended_gain": RECOMMENDED_GAIN[best],
                "message": {"dynamic": "Micro dynamique XLR détecté.", "jack": "Micro jack (casque) détecté.",
                            "condenser": "Micro statique détecté (alimentation 48 V)."}[best]}

    def _auto_gain(self, target_db, seconds):
        s = self.state
        old = s["mic"]["gain_db"]
        self._job_update(step="Parle normalement, comme en live")
        vals = sorted(v for v in self._sample(seconds, 0.0, 0.92) if v > -60)
        if len(vals) < 15:
            raise DeviceError("Je n’ai pas entendu ta voix. Rapproche-toi du micro et recommence.")
        peak = vals[max(0, int(len(vals) * 0.95) - 1)]
        new = _clamp(old + (target_db - peak), 0, 72)
        self._job_update(step="Application du nouveau gain")
        with self.lock:
            s["mic"]["gain_db"] = new
            gen = self._mark("mic")
        self._wait_applied(gen)
        return {"old_gain_db": old, "new_gain_db": new, "voice_peak_db": peak, "target_db": target_db,
                "message": f"Gain réglé de {old} à {new} dB."}

    # -- scenes automatiques --
    def auto_scene_tick(self, running):
        """Applique la scene de la premiere regle dont l'appli tourne (seulement quand ca change)."""
        with self.lock:
            cfg = self.state["auto_scenes"]
            if not cfg["enabled"] or not cfg["rules"]:
                self.auto_active = None
                return None
            names = {_norm_app(n) for n in running}
            match = next((r for r in cfg["rules"] if _norm_app(r["app"]) in names), None)
            key = (match["app"], match["scene"]) if match else None
            if key == self.auto_active:
                self._auto_seen = True
                return None
            prev, self.auto_active = self.auto_active, key
            if not self._auto_seen:
                # premiere evaluation apres le demarrage du moteur : l'etat sauvegarde fait foi
                self._auto_seen = True
                if match:
                    self.auto_note = {"t": time.time(), "scene": match["scene"], "why": match["app"] + " déjà ouvert",
                                      "applied": False}
                return None
            if match:
                target, why = match["scene"], match["app"] + " ouvert"
            elif prev not in (None, "?") and cfg["fallback"]:
                target, why = cfg["fallback"], "plus aucune appli de la liste"
            else:
                return None
            if self.state["scene"] == target:
                self.auto_note = {"t": time.time(), "scene": target, "why": why, "applied": False}
                return None
            self._apply_scene(target)
            self.auto_note = {"t": time.time(), "scene": target, "why": why, "applied": True}
            self.version += 1
            self._save_dirty = True
        log(f"Scène automatique : {target} ({why})")
        return target

    def app_watch_loop(self, interval=3.0):
        while True:
            time.sleep(interval)
            try:
                if self.state["auto_scenes"]["enabled"]:
                    self.auto_scene_tick(list_processes())
            except Exception as e:
                log(f"Scènes automatiques : {describe(e)}")

    # -- vues --
    def health_status(self):
        if self.connected:
            return "blocked" if time.monotonic() - self.heartbeat > 5 else "ok"
        if self.present is False:
            return "absent"
        if self.present is None and not self.connects:
            return "starting"
        return "error"

    def live_snapshot(self, want_level=False):
        if want_level:
            self.level_until = time.monotonic() + 3.0
        with self.lock:
            s = self.state
            return {"v": self.version, "boot": BOOT_ID, "connected": self.connected, "live": dict(self.live),
                    "job": dict(self.job) if self.job else None,
                    "mic": {"muted": s["mutes"]["Mic"], "partial": s["partial"]["Mic"]},
                    "health": self.health_status(), "sim": SIMULATE, "osd": s["prefs"]["osd"],
                    "scene": s["scene"], "app_version": VERSION, "update": self.updater.brief()}

    def health(self):
        now = time.monotonic()
        with self.lock:
            busy = self.dev.busy_since
            return {
                "status": self.health_status(), "version": VERSION, "pid": os.getpid(), "simulated": SIMULATE,
                "supervised": self.supervised, "engine_restarts": self.engine_restarts,
                "connected": self.connected, "present": self.present,
                "serial": self.dev.serial, "firmware": self.dev.firmware,
                "engine_uptime_s": round(time.time() - self.started),
                "device_uptime_s": round(time.time() - self.connected_since) if self.connected_since else None,
                "loop_age_ms": round((now - self.heartbeat) * 1000),
                "usb_call_ms": round((now - busy) * 1000) if busy else None,
                "reconnects": self.reconnects, "command_index": self.dev.count, "stats": dict(self.dev.stats),
                "pending": len(self._dirty), "last_error": self.last_error, "errors": list(self.errors),
                "auto_scene": self.auto_note, "log": list(RECENT_LOG)[-30:],
            }

    def snapshot(self):
        with self.lock:
            mix2 = self.dev.mix2 if self.connected else False
            return {
                "version": VERSION, "v": self.version, "connected": self.connected,
                "serial": self.dev.serial, "firmware": self.dev.firmware, "mix2": mix2,
                "error": None if self.connected else self.last_error, "health": self.health_status(),
                "sim": SIMULATE, "supervised": self.supervised,
                "update": self.updater.snapshot(),
                "state": json.loads(json.dumps(self.state)),
                "live": json.loads(json.dumps(self.live)),
                "job": json.loads(json.dumps(self.job)) if self.job else None,
                "blink": {k: v for k, v in self.blink.items() if v},
                "auto": {"active": list(self.auto_active) if isinstance(self.auto_active, tuple) else None,
                         "note": self.auto_note},
                "meta": {"channels": CHANNELS, "faders": FADERS, "inputs": list(INPUTS),
                         "outputs": [o for o in OUTPUTS if mix2 or o != "StreamMix2"],
                         "vod_output": self.vod_output(),
                         "channel_colours": CHANNEL_COLOURS, "mic_types": MIC_TYPES,
                         "recommended_gain": RECOMMENDED_GAIN, "mic_type_preset": MIC_TYPE_PRESET,
                         "mute_targets": list(MUTE_TARGETS), "mic_button_modes": MIC_BUTTON_MODES,
                         "channel_inputs": CHANNEL_INPUT,
                         "mic_presets": {k: {"label": v["label"], "desc": v["desc"], "dsp": v["dsp"]} for k, v in MIC_PRESETS.items()},
                         "scenes": {k: {"label": v["label"], "desc": v["desc"], "faders": v["faders"],
                                        "mic_preset": v["mic_preset"]} for k, v in SCENES.items()},
                         "themes": {k: {"label": v["label"], "preview": self._theme_preview(k)} for k, v in THEMES.items()},
                         "animations": list(ANIMATIONS), "fader_styles": list(FADER_STYLES),
                         "eq_bands": list(EQ_BANDS), "ratios": RATIOS, "known_apps": KNOWN_APPS},
            }

    def _theme_preview(self, name):
        th = THEMES[name]
        if th.get("per_channel"):
            return [CHANNEL_COLOURS[self.state["faders"][f]] for f in FADERS]
        if th.get("faders"):
            return th["faders"]
        return [th["top"]] * 4

    def save_if_dirty(self):
        if not (self.persist and self._save_dirty):
            return
        with self.lock:
            data = json.dumps(self.state, indent=2, ensure_ascii=False)
            self._save_dirty = False
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(STATE_PATH) and time.time() - self._last_backup > 600:
            try:
                with open(STATE_PATH, "rb") as src, open(STATE_PATH + ".bak", "wb") as dst:
                    dst.write(src.read())
                self._last_backup = time.time()
            except OSError:
                pass
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, STATE_PATH)

    def save_loop(self):
        while True:
            time.sleep(1)
            try:
                self.save_if_dirty()
            except Exception as e:
                log(f"Sauvegarde de l'état impossible : {e}")

# ---------------- processus (scenes automatiques) ----------------
def _win_processes():
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32), ("th32ProcessID", ctypes.c_uint32),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", ctypes.c_uint32),
                    ("cntThreads", ctypes.c_uint32), ("th32ParentProcessID", ctypes.c_uint32),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)       # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return set()
    names = set()
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            names.add(e.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return names

def list_processes():
    """Noms (minuscules) des processus en cours ; le simulateur fournit sa propre liste."""
    if SIMULATE:
        import simulator
        return {a.lower() for a in simulator.FAKE_APPS}
    if IS_WINDOWS:
        return _win_processes()
    try:
        out = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return set()
    return {os.path.basename(line.strip()).lower() for line in out.splitlines() if line.strip()}

def user_apps():
    names = sorted(n for n in list_processes() if n not in SYSTEM_PROCESSES)
    known = [{"app": n, "label": KNOWN_APPS[n]} for n in names if n in KNOWN_APPS]
    return {"known": known, "others": [n for n in names if n not in KNOWN_APPS][:300]}

# ---------------- mises a jour (releases GitHub, comme Wispad) ----------------
UPDATE_REPO = os.environ.get("GOXLR_UPDATE_REPO") or "samirmedani/goxlr-mini"
UPDATE_API = (os.environ.get("GOXLR_UPDATE_API") or "https://api.github.com").rstrip("/")
UPDATE_DOWNLOAD_PREFIX = os.environ.get("GOXLR_UPDATE_PREFIX") or f"https://github.com/{UPDATE_REPO}/releases/download/"
UPDATE_ASSET = "GoXLR-Mini.zip"
UPDATE_HASH_ASSET = "GoXLR-Mini.sha256"
UPDATE_TASK = "GoXLR Mini Update"
UPDATE_APPLY_TIMEOUT = 90                  # une installation qui demarre arrete le moteur en quelques secondes
DOWNLOAD_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
                  "github-releases.githubusercontent.com"} | set(filter(None, (os.environ.get("GOXLR_UPDATE_HOSTS") or "").split(",")))
UPDATE_FIRST_CHECK, UPDATE_EVERY, UPDATE_OFFLINE_RETRY = 5, 6 * 3600, 30 * 60
UPDATE_MAX_ZIP = 400 * 1024 * 1024
REQUIRED_PAYLOAD = ["goxlrctl.py", "ui.html", "manifest.json", "python/python.exe", "python/pythonw.exe",
                    "app/" + APP_NAME + ".exe"]


def parse_semver(text):
    """« v1.2.3 », « 1.2.3-beta.1 » -> (1, 2, 3, ("beta", "1")) ; None pour tout le reste."""
    s = str(text or "").strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    s = s.split("+", 1)[0]
    core, _, pre = s.partition("-")
    nums = core.split(".")
    if len(nums) != 3 or not all(n.isdigit() and (n == "0" or not n.startswith("0")) for n in nums):
        return None
    parts = tuple(pre.split(".")) if pre else ()
    if pre and not all(p and all(c.isalnum() or c == "-" for c in p) for p in parts):
        return None
    return int(nums[0]), int(nums[1]), int(nums[2]), parts


def version_lt(a, b):
    """a < b en semver (une pre-version passe avant la version finale) ; faux si l'une est illisible."""
    va, vb = parse_semver(a), parse_semver(b)
    if not va or not vb:
        return False
    if va[:3] != vb[:3]:
        return va[:3] < vb[:3]
    pa, pb = va[3], vb[3]
    if not pa or not pb:
        return bool(pa) and not pb
    for x, y in zip(pa, pb):
        if x == y:
            continue
        if x.isdigit() and y.isdigit():
            return int(x) < int(y)
        if x.isdigit() != y.isdigit():
            return x.isdigit()
        return x < y
    return len(pa) < len(pb)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(path=None):
    try:
        m = load_json(path or MANIFEST_PATH)
        return m if isinstance(m, dict) else None
    except Exception:
        return None


class UpdateError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


class UpdateCancelled(Exception):
    pass


def safe_extract(zpath, dest, limit=UPDATE_MAX_ZIP * 3):
    """Extrait sans jamais ecrire hors de dest (chemins absolus, « .. », liens) ni depasser limit octets."""
    root = os.path.realpath(dest)
    total = 0
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ":" in name.split("/")[0] or any(p == ".." for p in name.split("/")):
                raise UpdateError("archive", f"Chemin refusé dans l'archive : {name}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError("archive", f"Lien refusé dans l'archive : {name}")
            target = os.path.realpath(os.path.join(root, name))
            if not (target == root or target.startswith(root + os.sep)):
                raise UpdateError("archive", f"Chemin refusé dans l'archive : {name}")
            total += info.file_size
            if total > limit:
                raise UpdateError("archive", "Archive trop grosse.")
            if name.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)


class Updater:
    """Verifie les releases GitHub, telecharge, verifie et prepare une nouvelle version. L'echange des fichiers
    se fait dans une tache a part (apply-update) : le moteur peut etre arrete sans couper l'installation."""

    def __init__(self, ctl=None):
        self.ctl = ctl
        self.lock = threading.Lock()
        self.manifest = read_manifest()
        self.release_build = bool(self.manifest and self.manifest.get("release"))
        self.status = "idle"                 # idle checking up-to-date available
        self.result = None                   # dernier resultat : up-to-date found offline rate-limited unusable
        self.latest = None
        self.checked_at = None
        self.next_at = time.time() + UPDATE_FIRST_CHECK
        self.manual_at = 0.0
        self.phase = None                    # downloading verifying extracting applying failed
        self.progress = None
        self.error = None
        self.cancel = False
        self.installed = None                # resultat de la derniere installation (lu au demarrage)
        self.wake = threading.Event()
        self.launch_apply = self._launch_apply
        self.apply_timeout = UPDATE_APPLY_TIMEOUT
        self.started = time.time()
        self._load_result()

    # -- etat --
    def _set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)
        if self.ctl:
            with self.ctl.lock:
                self.ctl.version += 1

    def installable(self):
        if not self.release_build:
            return False, "dev"
        if not IS_WINDOWS:
            return False, "os"
        probe = os.path.join(BASE_DIR, ".ecriture-test")
        try:
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
        except OSError:
            return False, "readonly"
        return True, None

    def snapshot(self):
        ok, why = self.installable()
        with self.lock:
            return {"current": VERSION, "release_build": self.release_build, "status": self.status,
                    "result": self.result, "latest": self.latest, "checked_at": self.checked_at,
                    "phase": self.phase, "progress": self.progress, "error": self.error,
                    "installable": ok, "why_not": why, "repo": UPDATE_REPO,
                    "repo_url": f"https://github.com/{UPDATE_REPO}",
                    "release_page": (self.latest or {}).get("url") or f"https://github.com/{UPDATE_REPO}/releases/latest",
                    "installed": self.installed, "check_wait": max(0, round(self.manual_at + 60 - time.time())),
                    "reminded": self.ctl.state["prefs"].get("update_reminded") if self.ctl else None}

    def brief(self):
        with self.lock:
            return {"status": self.status, "latest": (self.latest or {}).get("version"), "phase": self.phase}

    # -- verification --
    def check(self, manual=False):
        with self.lock:
            if self.status == "checking":
                return
            if manual:
                wait = self.manual_at + 60 - time.time()
                if wait > 0:
                    raise ValueError(f"Une recherche par minute au plus : réessaie dans {int(wait) + 1} s.")
                self.manual_at = time.time()
            before = self.status
            self.status = "checking"
        kind, info, retry = self._fetch()
        now = time.time()
        with self.lock:
            self.checked_at = now
            if kind == "release":
                self.latest = info
                newer = version_lt(VERSION, info["version"])
                self.status = "available" if newer else "up-to-date"
                self.result = "found" if newer else "up-to-date"
                self.next_at = now + UPDATE_EVERY
            elif kind == "unusable":
                self.status = before if before not in ("idle", "checking") else "up-to-date"
                self.result = "up-to-date"
                self.next_at = now + UPDATE_EVERY
            elif kind == "rate-limited":
                self.status = before if before not in ("idle", "checking") else "idle"
                self.result = "rate-limited"
                self.next_at = now + min(6 * 3600, max(300, retry or 3600))
            else:
                self.status = before if before not in ("idle", "checking") else "idle"
                self.result = "offline"
                self.next_at = now + UPDATE_OFFLINE_RETRY
        if self.ctl:
            with self.ctl.lock:
                self.ctl.version += 1
        if kind == "release" and self.status == "available":
            log(f"Mise à jour disponible : {info['version']}")

    def _fetch(self):
        url = f"{UPDATE_API}/repos/{UPDATE_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": f"GoXLR-Mini/{VERSION}",
                                                   "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read(4_000_000).decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "unusable", None, None
            if e.code in (403, 429):
                retry = None
                try:
                    if e.headers.get("Retry-After"):
                        retry = float(e.headers["Retry-After"])
                    elif e.headers.get("X-RateLimit-Reset"):
                        retry = float(e.headers["X-RateLimit-Reset"]) - time.time()
                except (TypeError, ValueError):
                    retry = None
                return "rate-limited", None, retry
            return "offline", None, None
        except Exception:
            return "offline", None, None
        return parse_release(data)

    # -- installation --
    def start_install(self):
        ok, why = self.installable()
        if not ok:
            raise ValueError({"dev": "Version de développement : installe la nouvelle version depuis la page de la release.",
                              "os": "La mise à jour intégrée fonctionne sous Windows seulement.",
                              "readonly": "Dossier d’installation non modifiable : installe depuis la page de la release."}[why])
        with self.lock:
            if self.phase in ("downloading", "verifying", "extracting", "applying"):
                raise ValueError("Une installation est déjà en cours.")
            rel = dict(self.latest or {})
            if not rel or not version_lt(VERSION, rel.get("version")):
                raise ValueError("Aucune version plus récente à installer.")
            if not rel.get("asset"):
                raise ValueError("Cette release ne contient pas " + UPDATE_ASSET + " : installe depuis sa page.")
            self.phase, self.progress, self.error, self.cancel = "downloading", 0.0, None, False
        threading.Thread(target=self._install, args=(rel,), daemon=True, name="update").start()

    def cancel_install(self):
        with self.lock:
            if self.phase in ("downloading", "verifying", "extracting"):
                self.cancel = True

    def _check_cancel(self):
        if self.cancel:
            raise UpdateCancelled()

    def _install(self, rel):
        work = os.path.join(DATA_DIR, "update")
        try:
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work, exist_ok=True)
            asset = rel["asset"]
            zpath = os.path.join(work, UPDATE_ASSET)
            self._download(asset["url"], zpath, asset.get("size"))
            self._set(phase="verifying", progress=None)
            expected = asset.get("sha256") or self._fetch_sha(asset.get("sha_url"))
            if not expected:
                raise UpdateError("unverifiable", "La release n’annonce pas d’empreinte SHA-256 : installation refusée.")
            if asset.get("size") and os.path.getsize(zpath) != asset["size"]:
                raise UpdateError("corrupted", "Fichier incomplet : la taille ne correspond pas à celle annoncée par GitHub.")
            if sha256_file(zpath).lower() != expected.lower():
                raise UpdateError("corrupted", "Fichier modifié ou abîmé : l’empreinte ne correspond pas à celle de la release.")
            self._check_cancel()
            self._set(phase="extracting")
            new = os.path.join(work, "new")
            try:
                safe_extract(zpath, new)
            except zipfile.BadZipFile:
                raise UpdateError("archive", "Archive illisible.")
            man = read_manifest(os.path.join(new, "manifest.json"))
            if not man or man.get("version") != rel["version"]:
                raise UpdateError("archive", "L’archive ne correspond pas à la release annoncée.")
            if not version_lt(VERSION, man["version"]):
                raise UpdateError("not-newer", "Cette version n’est pas plus récente que celle installée.")
            missing = [p for p in REQUIRED_PAYLOAD if not os.path.exists(os.path.join(new, p))]
            if missing:
                raise UpdateError("archive", "Archive incomplète : " + ", ".join(missing))
            self._check_cancel()
            self._set(phase="applying", progress=None)
            plan = {"from": new, "to": BASE_DIR, "version": man["version"], "from_version": VERSION,
                    "data_dir": DATA_DIR, "port": HTTP_PORT, "task": TASK_NAME, "t": time.time()}
            with open(os.path.join(work, "plan.json"), "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
            log(f"Mise à jour {VERSION} → {man['version']} prête : remplacement des fichiers")
            self.launch_apply(new, work)
            self._watch_apply()
        except UpdateCancelled:
            self._set(phase=None, progress=None, error=None)
            log("Mise à jour annulée")
        except UpdateError as e:
            self._set(phase="failed", progress=None, error={"code": e.code, "msg": e.msg})
            log(f"Mise à jour : échec ({e.code})")
        except Exception as e:
            self._set(phase="failed", progress=None, error={"code": "internal", "msg": describe(e)})
            log(f"Mise à jour : échec ({describe(e)})")

    def _open_checked(self, url, timeout=20):
        if not url or not url.startswith(UPDATE_DOWNLOAD_PREFIX):
            raise UpdateError("source", "Adresse de téléchargement hors des releases du projet : refusée.")
        req = urllib.request.Request(url, headers={"User-Agent": f"GoXLR-Mini/{VERSION}"})
        r = urllib.request.urlopen(req, timeout=timeout)
        host = urllib.parse.urlparse(r.geturl()).hostname or ""
        if host not in DOWNLOAD_HOSTS:
            r.close()
            raise UpdateError("source", f"Téléchargement redirigé vers {host} : refusé.")
        return r

    def _download(self, url, path, size):
        try:
            with self._open_checked(url) as r, open(path, "wb") as f:
                total = size or int(r.headers.get("Content-Length") or 0) or None
                got = 0
                while True:
                    self._check_cancel()
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > UPDATE_MAX_ZIP:
                        raise UpdateError("corrupted", "Fichier trop gros.")
                    f.write(chunk)
                    self._set(progress=round(got / total, 3) if total else None)
        except (UpdateError, UpdateCancelled):
            raise
        except Exception as e:
            raise UpdateError("download", f"Téléchargement interrompu ({type(e).__name__}).")

    def _fetch_sha(self, url):
        if not url:
            return None
        try:
            with self._open_checked(url, timeout=10) as r:
                txt = r.read(4096).decode("ascii", "replace").strip().split()
            return txt[0] if txt and len(txt[0]) == 64 else None
        except UpdateError:
            raise
        except Exception:
            return None

    def _launch_apply(self, new, work):
        """Windows : tache SYSTEM a part qui lance apply-update avec le Python de la nouvelle version."""
        py = os.path.join(new, "python", "python.exe")
        script = os.path.join(new, "goxlrctl.py")
        tr = f'"{py}" "{script}" apply-update'
        mk = subprocess.run(["schtasks", "/create", "/tn", UPDATE_TASK, "/tr", tr, "/sc", "once", "/st", "23:59",
                             "/ru", "SYSTEM", "/rl", "HIGHEST", "/f"], capture_output=True, text=True)
        if mk.returncode != 0:
            raise UpdateError("launch", "Impossible de préparer l’installation (tâche planifiée).")
        run = subprocess.run(["schtasks", "/run", "/tn", UPDATE_TASK], capture_output=True, text=True)
        if run.returncode != 0:
            raise UpdateError("launch", "Impossible de lancer l’installation (tâche planifiée).")

    def _watch_apply(self):
        """L'installation arrete ce moteur des son debut. S'il tourne encore apres le delai, elle a echoue avant
        l'echange des fichiers (rien n'a ete touche) : on le dit au lieu de rester sur « installation en cours »."""
        deadline = time.time() + self.apply_timeout
        while time.time() < deadline:
            time.sleep(0.2)
            if self.phase != "applying":
                return
        if IS_WINDOWS:
            subprocess.run(["schtasks", "/delete", "/tn", UPDATE_TASK, "/f"], capture_output=True)
        raise UpdateError("launch", "L’installation n’a pas démarré, rien n’a été modifié. Réessaie ; "
                                    "si ça recommence, installe depuis la page de la release.")

    # -- apres une installation --
    def _load_result(self):
        p = os.path.join(DATA_DIR, "update", "result.json")
        r = read_manifest(p)
        if r and time.time() - float(r.get("t") or 0) < 3600:
            self._set(installed=r)
            return True
        return False

    def ack_installed(self):
        with self.lock:
            self.installed = None
        try:
            os.remove(os.path.join(DATA_DIR, "update", "result.json"))
        except OSError:
            pass

    def cleanup_after_install(self):
        """Au demarrage : la tache d'installation et la copie preparee ne servent plus.
        Renvoie False si une installation semble encore en cours (a retenter plus tard)."""
        work = os.path.join(DATA_DIR, "update")
        if not os.path.isdir(work):
            return True
        if self.phase:
            return False
        plan_path = os.path.join(work, "plan.json")
        if os.path.exists(plan_path) and not os.path.exists(os.path.join(work, "result.json")):
            done = (read_manifest(plan_path) or {}).get("version") == VERSION     # on tourne deja sur cette version
            if not done and time.time() - os.path.getmtime(plan_path) < 300:
                return False                # installation peut-etre en cours
        if IS_WINDOWS:
            subprocess.run(["schtasks", "/delete", "/tn", UPDATE_TASK, "/f"], capture_output=True)
        for name in ("new", UPDATE_ASSET, "plan.json"):
            p = os.path.join(work, name)
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else (os.path.exists(p) and os.remove(p))
        return True

    def loop(self):
        cleaned = False
        while True:
            self.wake.wait(5)
            self.wake.clear()
            try:
                if not cleaned and time.time() > self.started + 30:
                    cleaned = self.cleanup_after_install()
                if self.installed is None and time.time() - self.started < 180:
                    self._load_result()     # la tache d'installation ecrit son resultat apres le demarrage du moteur
                if time.time() >= self.next_at and not self.phase:
                    self.check()
            except Exception as e:
                log(f"Mises à jour : {describe(e)}")


def parse_release(data):
    """Reponse de GET /repos/…/releases/latest -> ("release", info, None) ou ("unusable", None, None)."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return "unusable", None, None
    tag = str(data.get("tag_name") or "")
    if not tag.startswith("v") or not parse_semver(tag):
        return "unusable", None, None
    info = {"version": tag[1:], "tag": tag, "notes": str(data.get("body") or "")[:20000],
            "url": str(data.get("html_url") or f"https://github.com/{UPDATE_REPO}/releases/tag/{tag}"),
            "published": data.get("published_at"), "asset": None}
    assets = {a.get("name"): a for a in (data.get("assets") or []) if isinstance(a, dict)}
    a = assets.get(UPDATE_ASSET)
    if a and str(a.get("browser_download_url") or "").startswith(UPDATE_DOWNLOAD_PREFIX):
        digest = str(a.get("digest") or "")
        sha = digest[7:].lower() if digest.startswith("sha256:") and len(digest) == 71 else None
        h = assets.get(UPDATE_HASH_ASSET)
        sha_url = h.get("browser_download_url") if h and str(h.get("browser_download_url") or "").startswith(UPDATE_DOWNLOAD_PREFIX) else None
        info["asset"] = {"url": a["browser_download_url"], "size": int(a.get("size") or 0) or None,
                         "sha256": sha, "sha_url": sha_url}
    return "release", info, None


# -- echange des fichiers (tache « GoXLR Mini Update », Python de la NOUVELLE version) --
def _engine_pids(root):
    """PID des python(w).exe lances depuis root (Windows)."""
    if not IS_WINDOWS:
        return []
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
    pids = []
    prefix = os.path.normcase(os.path.abspath(root)) + os.sep
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) < 2 or cols[0].lower() not in ("python.exe", "pythonw.exe"):
            continue
        pid = int(cols[1]) if cols[1].isdigit() else 0
        h = k32.OpenProcess(0x1000, 0, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.c_uint32(1024)
        try:
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and os.path.normcase(buf.value).startswith(prefix):
                pids.append(pid)
        finally:
            k32.CloseHandle(h)
    return pids


def _win_stop_engine(plan):
    subprocess.run(["schtasks", "/end", "/tn", plan["task"]], capture_output=True)
    for _ in range(30):
        pids = _engine_pids(plan["to"])
        if not pids:
            return
        for pid in pids:
            subprocess.run(["taskkill", "/f", "/pid", str(pid)], capture_output=True)
        time.sleep(0.5)


def _win_start_engine(plan):
    subprocess.run(["schtasks", "/run", "/tn", plan["task"]], capture_output=True)


def _powershell(script, timeout=60):
    """Lance un script PowerShell sans fenetre (encode en base64 : aucun souci de guillemets) ; sortie en UTF-8."""
    import base64
    full = "$ProgressPreference = 'SilentlyContinue'; [Console]::OutputEncoding = [Text.Encoding]::UTF8; " + script
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-EncodedCommand", base64.b64encode(full.encode("utf-16-le")).decode("ascii")],
                       capture_output=True, timeout=timeout, creationflags=0x08000000)
    return r.stdout.decode("utf-8", "replace")


def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def _win_list_apps(plan):
    """Appli GoXLR Mini ouverte depuis le dossier installe : [(pid, "DOMAINE\\compte")]."""
    if not IS_WINDOWS:
        return []
    out = _powershell("Get-CimInstance Win32_Process -Filter \"Name='GoXLR Mini.exe'\" | ForEach-Object { "
                      "$o = Invoke-CimMethod -InputObject $_ -MethodName GetOwner; "
                      "'{0}|{1}\\{2}|{3}' -f $_.ProcessId, $o.Domain, $o.User, $_.ExecutablePath }")
    prefix = os.path.normcase(os.path.join(plan["to"], "app")) + os.sep
    apps = []
    for line in out.splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) == 3 and parts[0].isdigit() and os.path.normcase(parts[2]).startswith(prefix) and parts[1] != "\\":
            apps.append((int(parts[0]), parts[1]))
    return apps


def _win_pid_alive(pid):
    out = subprocess.run(["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
    return f'"{pid}"' in out


def _win_restart_apps(plan, before, grace=12):
    """Les applis 4.1.3+ se relancent seules quand le moteur annonce la nouvelle version. Celles d'avant (ou une
    relance ratee) restent sur l'ancien exe : on les ferme et on rouvre la nouvelle dans la session de leur compte."""
    if not before:
        return []
    deadline = time.time() + grace
    stuck = [(pid, user) for pid, user in before]
    while stuck and time.time() < deadline:
        time.sleep(1)
        stuck = [(pid, user) for pid, user in stuck if _win_pid_alive(pid)]
    exe = os.path.join(plan["to"], "app", "GoXLR Mini.exe")
    users = []
    for pid, user in stuck:
        subprocess.run(["taskkill", "/f", "/pid", str(pid)], capture_output=True)
        if user not in users:
            users.append(user)
    for user in users:
        _powershell("$t = 'GoXLR Mini (relance)'; "
                    f"$a = New-ScheduledTaskAction -Execute {_ps_quote(exe)}; "
                    f"$p = New-ScheduledTaskPrincipal -UserId {_ps_quote(user)} -LogonType Interactive -RunLevel Limited; "
                    "Register-ScheduledTask -TaskName $t -Action $a -Principal $p -Force | Out-Null; "
                    "Start-ScheduledTask -TaskName $t; Start-Sleep 3; Unregister-ScheduledTask -TaskName $t -Confirm:$false")
        log(f"Appli relancée pour {user}")
    return users


def _wait_health(plan, timeout=45):
    t0 = time.time()
    url = f"http://127.0.0.1:{plan.get('port', 14565)}/api/health"
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if json.loads(r.read()).get("version") == plan["version"]:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def apply_update(plan, stop=None, start=None, wait=None, list_apps=None, restart_apps=None):
    """Sauvegarde les fichiers en place, copie la nouvelle version, verifie qu'elle repond ; sinon retour arriere.
    Les fichiers sont deplaces par renommage (permis meme pour un exe ouvert) dans backup/<date>-<version>."""
    stop = stop or _win_stop_engine
    start = start or _win_start_engine
    wait = wait or _wait_health
    list_apps = list_apps or _win_list_apps
    restart_apps = restart_apps or _win_restart_apps
    src, dst = plan["from"], plan["to"]
    new_files = sorted((read_manifest(os.path.join(src, "manifest.json")) or {}).get("files") or {})
    old_files = sorted((read_manifest(os.path.join(dst, "manifest.json")) or {}).get("files") or {})
    if not new_files:
        raise UpdateError("archive", "Manifeste sans liste de fichiers.")
    backup = os.path.join(dst, "backup", time.strftime("%Y%m%d-%H%M%S") + "-" + plan["from_version"])
    moved, copied = [], []
    result = {"version": plan["version"], "from_version": plan["from_version"], "t": time.time()}
    try:
        apps = list_apps(plan)
    except Exception as e:
        apps = []
        log(f"Applis ouvertes introuvables : {describe(e)}")
    stop(plan)
    try:
        for rel in sorted(set(old_files) | set(new_files)):
            cur = os.path.join(dst, rel)
            if os.path.isfile(cur):
                os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
                os.replace(cur, os.path.join(backup, rel))
                moved.append(rel)
        for rel in new_files:
            os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
            shutil.copy2(os.path.join(src, rel), os.path.join(dst, rel))
            copied.append(rel)
        start(plan)
        if not wait(plan):
            raise RuntimeError("la nouvelle version ne répond pas")
        result["ok"] = True
    except Exception as e:
        result.update(ok=False, error=describe(e))
        stop(plan)
        failed = os.path.join(dst, "backup", "echec-" + plan["version"])
        for rel in copied:
            p = os.path.join(dst, rel)
            if os.path.isfile(p):
                os.makedirs(os.path.dirname(os.path.join(failed, rel)), exist_ok=True)
                os.replace(p, os.path.join(failed, rel))
        for rel in moved:
            os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
            os.replace(os.path.join(backup, rel), os.path.join(dst, rel))
        start(plan)
    backups = sorted(d for d in os.listdir(os.path.join(dst, "backup")) if d[:1].isdigit()) if os.path.isdir(os.path.join(dst, "backup")) else []
    for d in backups[:-2]:
        shutil.rmtree(os.path.join(dst, "backup", d), ignore_errors=True)
    if result.get("ok") and IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\GoXLRMini",
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, plan["version"])
        except OSError:
            pass
    if result.get("ok"):
        try:
            restart_apps(plan, apps)
        except Exception as e:
            log(f"Relance de l’appli : {describe(e)}")
    os.makedirs(os.path.join(plan["data_dir"], "update"), exist_ok=True)
    with open(os.path.join(plan["data_dir"], "update", "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return result


def run_apply_update(base_dir=None):
    """Point d'entree de la tache « GoXLR Mini Update » : lit le plan prepare par le moteur."""
    global LOG_PREFIX
    LOG_PREFIX = "[mise à jour] "
    work = os.path.dirname(base_dir or BASE_DIR)            # BASE_DIR = <donnees>/update/new -> <donnees>/update
    plan = read_manifest(os.path.join(work, "plan.json"))
    if not plan:
        configure(data_dir=os.path.dirname(work))
        log(f"Installation impossible : plan.json introuvable dans {work}")
        raise SystemExit(1)
    configure(data_dir=plan["data_dir"])
    log(f"Installation de {plan['version']} (depuis {plan['from_version']})")
    try:
        r = apply_update(plan)
    except Exception as e:
        log(f"Échec avant l’échange des fichiers : {describe(e)}")
        raise
    log(("Version " + plan["version"] + " installée") if r.get("ok") else ("Échec, retour à " + plan["from_version"] + " : " + r.get("error", "")))
    return r

# ---------------- serveur HTTP ----------------
ACTIONS = {"volume", "mute", "fader", "route", "colour", "mic", "raw", "profile", "dsp", "mic-preset",
           "scene", "scene-save", "scene-delete", "theme", "lighting", "detect-mic", "auto-gain", "job-cancel",
           "settings", "auto-scenes", "reconnect", "restart-engine",
           "update-check", "update-install", "update-cancel", "update-ack", "update-remind"}
ALIASES = {"mic-gain": "mic"}

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = not IS_WINDOWS     # Windows : SO_REUSEADDR laisserait un second moteur ecouter le meme port

    def server_bind(self):
        if IS_WINDOWS and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

def _sim_action(name, req):
    import simulator
    sim = simulator.FakeTusb.shared()
    if name == "device":
        return sim.describe()
    if name == "press":
        sim.press(req["button"], float(req.get("ms", 150)))
    elif name == "down":
        sim.button_down(req["button"])
    elif name == "up":
        sim.button_up(req["button"])
    elif name == "fader":
        sim.move_fader(int(req["index"]), int(req["value"]))
    elif name == "unplug":
        sim.unplug()
    elif name == "plug":
        sim.plug()
    elif name == "hang":
        sim.hang(float(req.get("seconds", 20)))
    elif name == "talk":
        sim.dev.talking = parse_bool(req.get("on", True))
        if "db" in req:
            sim.dev.voice_db = float(req["db"])
    elif name == "mic-input":
        sim.dev.mic_input = req.get("input") or None
    elif name == "apps":
        simulator.FAKE_APPS.clear()
        simulator.FAKE_APPS.update(req.get("apps") or [])
    else:
        raise KeyError(f"action de simulation inconnue: {name}")
    return {"ok": True}

def make_handler(ctl):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"   # connexions persistantes : l'interface interroge ~20 fois/s

        def log_message(self, *a):
            pass

        def _send(self, body, ctype, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code)

        def _host_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _file(self, path):
            try:
                with open(path, "rb") as f:
                    return self._send(f.read(), "text/html; charset=utf-8")
            except OSError:
                return self._json({"error": os.path.basename(path) + " absent"}, 500)

        def do_GET(self):
            if not self._host_ok():
                return self._json({"error": "hôte refusé"}, 403)
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html"):
                return self._file(UI_PATH)
            if path in ("/overlay", "/overlay.html"):
                return self._file(OVERLAY_PATH)
            if path == "/api/live":
                return self._json(ctl.live_snapshot(want_level="level=1" in query))
            if path in ("/api/state", "/status"):
                return self._json(ctl.snapshot())
            if path == "/api/health":
                return self._json(ctl.health())
            if path == "/api/update":
                return self._json(ctl.updater.snapshot())
            if path == "/api/processes":
                return self._json(user_apps())
            if path == "/api/default-profile":
                try:
                    return self._json(normalize_state(load_json(DEFAULT_PROFILE_PATH)))
                except Exception as e:
                    return self._json({"error": str(e)}, 500)
            if path == "/api/sim/device" and SIMULATE:
                return self._json(_sim_action("device", {}))
            self._json({"error": "introuvable"}, 404)

        def do_POST(self):
            if not self._host_ok() or self.headers.get(API_HEADER) != "1":
                return self._json({"error": "requête refusée"}, 403)
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                name = self.path.split("?")[0].strip("/")
                name = name[4:] if name.startswith("api/") else name
                if name.startswith("sim/"):
                    if not SIMULATE:
                        return self._json({"error": "simulateur inactif"}, 404)
                    return self._json(_sim_action(name[4:], req))
                name = ALIASES.get(name, name)
                if name not in ACTIONS:
                    return self._json({"error": "action inconnue"}, 404)
                self._json(ctl.act(name, req))
            except (KeyError, ValueError) as e:
                self._json({"error": f"{e}"}, 400)
            except DeviceError as e:
                self._json({"error": str(e)}, 409)
            except Exception as e:
                log(f"Erreur API {self.path}: {describe(e)}")
                self._json({"error": str(e)}, 500)
    return H

def _watch_parent():
    """Le superviseur garde notre entree standard ouverte : a sa disparition, on s'arrete aussi."""
    try:
        stream = sys.stdin.buffer if sys.stdin is not None else None
        if stream is None:
            return
        while stream.read(1):
            pass
    except Exception:
        return
    log("Superviseur disparu : arrêt du moteur")
    os._exit(0)

def run_engine():
    ctl = Controller(persist=True)
    log(f"Démarrage du moteur goxlrctl {VERSION}" + (" (appareil simulé)" if SIMULATE else "")
        + (f", relance n°{ctl.engine_restarts}" if ctl.engine_restarts else "") + f", état : {STATE_PATH}")
    try:
        server = Server(("127.0.0.1", HTTP_PORT), make_handler(ctl))   # le port d'abord, l'USB ensuite
    except OSError as e:
        log(f"Port {HTTP_PORT} déjà pris ({e}) : un autre moteur tourne, arrêt sans toucher à l'USB")
        sys.exit(EXIT_PORT_BUSY)
    threading.Thread(target=ctl.device_loop, daemon=True, name="usb").start()
    threading.Thread(target=ctl.save_loop, daemon=True, name="save").start()
    threading.Thread(target=ctl.app_watch_loop, daemon=True, name="apps").start()
    threading.Thread(target=ctl.updater.loop, daemon=True, name="updates").start()
    if ctl.supervised:
        threading.Thread(target=_watch_parent, daemon=True, name="parent").start()
    log(f"Interface et API sur http://127.0.0.1:{HTTP_PORT}/")
    try:
        server.serve_forever()
    finally:
        ctl.save_if_dirty()

# ---------------- superviseur ----------------
def http_call(method, path, payload=None, timeout=10):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{HTTP_PORT}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json", API_HEADER: "1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def daemon_up():
    try:
        http_call("GET", "/api/live", timeout=3)
        return True
    except Exception:
        return False

def _child_python():
    exe = sys.executable
    if IS_WINDOWS and exe.lower().endswith("pythonw.exe"):
        alt = exe[: -len("pythonw.exe")] + "python.exe"   # python.exe + CREATE_NO_WINDOW : vraie entree standard
        if os.path.exists(alt):
            return alt
    return exe

def supervise():
    global LOG_PREFIX
    LOG_PREFIX = "[superviseur] "
    if daemon_up():
        log(f"Un moteur répond déjà sur le port {HTTP_PORT} : rien à faire")
        return
    log(f"Démarrage du superviseur {VERSION}" + (" (appareil simulé)" if SIMULATE else ""))
    restarts, quick_fails = 0, 0
    while True:
        env = dict(os.environ, GOXLR_SUPERVISED="1", GOXLR_RESTARTS=str(restarts), GOXLR_PORT=str(HTTP_PORT),
                   GOXLR_DATA_DIR=DATA_DIR, GOXLR_SIMULATE="1" if SIMULATE else "0")
        kw = {"creationflags": 0x08000000} if IS_WINDOWS else {}      # CREATE_NO_WINDOW
        child = subprocess.Popen([_child_python(), os.path.abspath(__file__), "daemon", "--child"],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env=env, cwd=BASE_DIR, **kw)
        t0 = last_ok = time.monotonic()
        reason = None
        while reason is None:
            time.sleep(1.5)
            rc = child.poll()
            if rc is not None:
                reason = f"moteur arrêté (code {rc})"
                break
            try:
                h = http_call("GET", "/api/health", timeout=3)
                last_ok = time.monotonic()
                if h.get("loop_age_ms", 0) > WATCHDOG_S * 1000:
                    reason = f"boucle USB figée depuis {h['loop_age_ms'] // 1000} s (pilote bloqué)"
            except Exception:
                if time.monotonic() - last_ok > 25:
                    reason = "moteur muet depuis 25 s"
        if child.poll() is None:
            child.kill()                 # TerminateProcess : fonctionne meme si un appel DLL est bloque
            try:
                child.wait(10)
            except Exception:
                pass
        rc = child.returncode
        lived = time.monotonic() - t0
        if rc == EXIT_PORT_BUSY and daemon_up():
            log("Un autre moteur occupe le port : arrêt du superviseur")
            return
        restarts += 1
        if rc == EXIT_RESTART:
            delay, quick_fails = 0.3, 0
        else:
            quick_fails = quick_fails + 1 if lived < 60 else 0
            delay = min(30.0, 1.0 if quick_fails <= 1 else 2.0 ** (quick_fails - 1))
        log(f"Relance du moteur : {reason}")
        time.sleep(delay)

# ---------------- CLI ----------------
def open_ui():
    if os.path.exists(APP_EXE):
        subprocess.Popen([APP_EXE])
        return
    if not daemon_up():
        if IS_WINDOWS:
            subprocess.run(["schtasks", "/run", "/tn", TASK_NAME], capture_output=True)
        for _ in range(20):
            time.sleep(0.5)
            if daemon_up():
                break
    url = f"http://127.0.0.1:{HTTP_PORT}/"
    browser = next((p for p in APP_BROWSERS if os.path.exists(p)), None)
    if browser:
        subprocess.Popen([browser, f"--app={url}", "--window-size=1280,800", "--no-first-run", "--no-default-browser-check"])
    else:
        import webbrowser
        webbrowser.open(url)

def cli_action(cmd, a):
    if cmd in ("status", "info", "buttons", "mic-level", "health"):
        return None, None
    table = {
        "volume": lambda: ("volume", {"channel": a[1], "value": a[2]}),
        "mute": lambda: ("mute", {"channel": a[1], "muted": a[2], "target": a[3] if len(a) > 3 else "all"}),
        "fader": lambda: ("fader", {"fader": a[1], "channel": a[2]}),
        "route": lambda: ("route", {"input": a[1], "output": a[2], "enabled": a[3]}),
        "colour": lambda: ("colour", {"target": a[1], "colour_one": a[2], "colour_two": a[3] if len(a) > 3 else None}),
        "mic-gain": lambda: ("mic", {"type": a[1], "gain_db": int(a[2])}),
        "scene": lambda: ("scene", {"name": a[1]}),
        "mic-preset": lambda: ("mic-preset", {"name": a[1]}),
        "theme": lambda: ("theme", {"name": a[1]}),
        "reconnect": lambda: ("reconnect", {}),
        "update-check": lambda: ("update-check", {}),
        "apply-profile": lambda: ("profile", load_json(a[1] if len(a) > 1 else DEFAULT_PROFILE_PATH)),
        "raw": lambda: ("raw", {"command_id": a[1], "body_hex": a[2] if len(a) > 2 else ""}),
    }
    if cmd not in table:
        raise SystemExit(__doc__)
    try:
        return table[cmd]()
    except IndexError:
        raise SystemExit(__doc__)

def one_shot(action, payload):
    """Sans moteur : ouvre l'appareil, applique une seule action, referme (n'ecrase pas le reste)."""
    ctl = Controller(persist=False)
    ctl.connect(apply=False)
    try:
        if action is None:
            ctl.poll_once()
            return ctl.snapshot()
        out = ctl.act(action, payload) if action != "raw" else {
            "ok": True, "response_hex": ctl.dev.command(int(str(payload["command_id"]), 16),
                                                        bytes.fromhex(payload.get("body_hex") or "")).hex()}
        ctl.flush()
        return out
    finally:
        ctl.dev.close()

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    opts = {}
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--port", "--data-dir") and i + 1 < len(args):
            opts[a] = args[i + 1]
            i += 2
            continue
        if a.startswith("--"):
            opts[a] = True
        else:
            rest.append(a)
        i += 1
    simulate = True if opts.get("--simulate") else None
    data_dir = opts.get("--data-dir")
    if simulate and not data_dir and not os.environ.get("GOXLR_DATA_DIR"):
        data_dir = default_data_dir() + "-sim"     # le simulateur ne touche jamais l'etat reel
    configure(simulate=simulate, port=opts.get("--port"), data_dir=data_dir)
    if not rest:
        print(__doc__)
        return
    cmd = rest[0]
    if cmd == "daemon":
        if opts.get("--child"):
            run_engine()
        else:
            supervise()
        return
    if cmd == "ui":
        open_ui()
        return
    if cmd == "apply-update":
        run_apply_update()
        return
    action, payload = cli_action(cmd, rest)
    if daemon_up():
        if action is None:
            out = http_call("GET", "/api/health" if cmd == "health" else "/api/state")
        else:
            out = http_call("POST", f"/api/{action}", payload)
    else:
        if cmd == "health":
            raise SystemExit("Le moteur ne tourne pas.")
        out = one_shot(action, payload)
    if action is None and cmd in ("buttons", "mic-level", "info"):
        out = {"buttons": out["live"]["pressed"], "fader_positions": out["live"]["fader_positions"],
               "mic_db": out["live"]["mic_db"]}
    elif action is None and cmd == "status":
        out = {k: out.get(k) for k in ("version", "connected", "serial", "firmware", "error", "health")} | {"live": out["live"]}
    print(json.dumps(out, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
