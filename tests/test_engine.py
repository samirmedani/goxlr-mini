# -*- coding: utf-8 -*-
"""Tests du moteur avec la fausse GoXLR (aucun materiel). Lancer : python3 -m unittest discover -s tests -v
Tournent aussi sur le PC avec le Python embarque 3.11 (meme code que la tache planifiee)."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine")
sys.path.insert(0, os.path.abspath(ENGINE))
import goxlrctl as g  # noqa: E402
import simulator  # noqa: E402


def wait_for(cond, timeout=5.0, step=0.01):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False


class Engine(unittest.TestCase):
    """Un moteur complet (boucle USB dans un fil) branche sur une fausse Mini neuve."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="goxlr-test-")
        g.configure(simulate=True, data_dir=self.tmp)
        self.sim = simulator.FakeTusb.reset_shared()
        self.sim.latency = 0.0
        g._lib = self.sim
        g.GoXLR.FIRST_READ_WAIT = 0.0
        g.GoXLR.RETRY_WAIT = 0.0005
        g.GoXLR.RESPONSE_TIMEOUT = 0.5
        g.POLL_INTERVAL = 0.002
        self.ctl = g.Controller(persist=True)
        self.ctl.state["prefs"]["hold_ms"] = 300
        self.stop = threading.Event()
        self.th = threading.Thread(target=self.ctl.device_loop, args=(self.stop,), daemon=True)
        self.th.start()
        self.assertTrue(wait_for(lambda: self.ctl.connected and not self.ctl._dirty and self.ctl._done >= self.ctl._want
                                 and self.ctl._prev_pos is not None))

    def tearDown(self):
        self.stop.set()
        self.th.join(3)
        self.ctl.dev.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def settle(self):
        """Attend que tout ce qui est marque soit parti vers l'appareil."""
        self.assertTrue(wait_for(lambda: not self.ctl._dirty and self.ctl._done >= self.ctl._want and self.ctl.connected))
        time.sleep(0.02)

    def led(self, button):
        return self.sim.dev.button_states[g.BUTTON_BITS[button]]

    # ---------- la panne du 20 octobre ----------
    def test_index_16_bits_passe_sans_erreur(self):
        """70 000 commandes : la v3 plantait a 65 535 (struct.error). Ici une remise a zero, puis ca continue."""
        dev = self.ctl.dev
        self.stop.set()
        self.th.join(3)
        start = dev.count
        for _ in range(70000 - start):
            dev.get_button_states()
        self.assertEqual(dev.stats["index_resets"], 1)
        self.assertEqual(self.sim.dev.index_resets, 1)
        self.assertLess(dev.count, 6000)
        self.assertEqual(dev.stats["resyncs"], 0, "la Mini simulee repond avec son propre compteur : aucun decalage")
        self.assertEqual(self.sim.dev.errors, [])

    def test_saut_de_compteur_rattrape(self):
        """Vu sur la vraie Mini : un index inattendu n'a pas de reponse ; le moteur resynchronise sans couper."""
        self.stop.set()
        self.th.join(3)
        self.ctl.dev.count = 60000
        self.ctl.dev.get_button_states()
        self.assertEqual(self.ctl.dev.stats["resyncs"], 1)
        self.ctl.dev.get_button_states()

    def test_erreur_inattendue_reconnecte(self):
        """Une erreur Python quelconque pendant l'echange USB ferme et rouvre proprement (v3 : boucle infinie)."""
        real = self.ctl.dev.get_button_states
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            if calls["n"] == 3:
                raise ValueError("panne simulee")
            return real()
        self.ctl.dev.get_button_states = boom
        self.assertTrue(wait_for(lambda: self.ctl.reconnects == 1 and self.ctl.connected, timeout=6))
        self.assertTrue(any("panne simulee" in e["msg"] for e in self.ctl.errors))
        self.assertEqual(self.sim.enumerate_violations, 0)

    def test_debranche_rebranche_reapplique(self):
        self.sim.unplug()
        self.assertTrue(wait_for(lambda: not self.ctl.connected))
        self.assertEqual(self.ctl.health()["status"], "absent") if wait_for(lambda: self.ctl.present is False) else None
        self.ctl.act("volume", {"channel": "Game", "value": 211})
        self.ctl.act("mute", {"channel": "Chat", "muted": True})
        self.sim.plug()
        self.assertTrue(wait_for(lambda: self.ctl.connected, timeout=6))
        self.settle()
        self.assertEqual(self.sim.dev.volumes[g.CHANNELS.index("Game")], 211)
        self.assertTrue(self.sim.dev.muted[g.CHANNELS.index("Chat")])
        self.assertEqual(self.sim.enumerate_violations, 0, "EnumerateDevices jamais appele handle ouvert")

    def test_absente_dit_ce_que_voit_windows(self):
        """Allumee sur un cable qui ne fait que charger : Windows ne la voit pas, l'appli le dit ; elle revient seule."""
        self.ctl.ABSENT_RETRY_S = 0.1
        self.sim.unplug()
        self.assertTrue(wait_for(lambda: self.ctl.usb == "none" and self.ctl.health_status() == "absent", timeout=3))
        self.assertEqual(self.ctl.live_snapshot()["usb"], "none")
        self.sim.unplugged_usb = "failed"
        self.assertTrue(wait_for(lambda: self.ctl.usb == "failed", timeout=3))
        self.sim.plug()
        self.assertTrue(wait_for(lambda: self.ctl.connected and self.ctl.usb == "mini", timeout=8))
        self.assertTrue(any("ne fait peut-être que charger" in line for line in g.RECENT_LOG))

    def test_api_repond_pendant_un_blocage_usb(self):
        self.sim.hang(1.5)
        time.sleep(0.2)
        t0 = time.monotonic()
        r = self.ctl.act("volume", {"channel": "Music", "value": 100})
        snap = self.ctl.live_snapshot()
        self.assertLess(time.monotonic() - t0, 0.2)
        self.assertTrue(r["ok"])
        self.assertTrue(wait_for(lambda: self.ctl.health()["loop_age_ms"] > 800, timeout=2))
        self.assertEqual(self.ctl.health_status(), "blocked") if self.ctl.health()["loop_age_ms"] > 5000 else None
        self.settle()
        self.assertEqual(self.sim.dev.volumes[g.CHANNELS.index("Music")], 100)
        self.assertIn("v", snap)

    def test_formats_envoyes_justes(self):
        self.ctl.act("scene", {"name": "streaming"})
        self.settle()
        self.assertEqual(self.sim.dev.errors, [])
        self.assertEqual(len(self.sim.dev.colour_map), 520)

    def test_sous_mixages_initialises(self):
        """Firmware 1.2.0.46+ : casque sur le mix A et chaque sortie sur le mix A, comme goxlr-utility."""
        self.assertEqual(self.sim.dev.monitored_mix, 0)
        self.assertEqual(self.sim.dev.channel_mixes, bytes([2, 4, 6, 8, 255, 255, 255, 255]))

    # ---------- mutes ----------
    def test_couper_du_stream_seulement(self):
        self.ctl.act("mute", {"channel": "Music", "muted": True, "target": "stream"})
        self.settle()
        d = self.sim.dev
        self.assertFalse(d.muted[g.CHANNELS.index("Music")], "la voie reste active")
        self.assertFalse(d.route_on("Music", "BroadcastMix"))
        self.assertTrue(d.route_on("Music", "Headphones"))
        fader = [f for f, ch in self.ctl.state["faders"].items() if ch == "Music"][0]
        self.assertEqual(self.led(g.FADER_BUTTONS[g.FADERS.index(fader)]), g.BTN_ON)
        self.ctl.act("mute", {"channel": "Music", "muted": False})
        self.settle()
        self.assertTrue(d.route_on("Music", "BroadcastMix"))

    def test_micro_coupe_partout_coupe_ses_routes(self):
        self.ctl.act("mute", {"channel": "Mic", "muted": True})
        self.settle()
        d = self.sim.dev
        self.assertTrue(d.muted[0])
        self.assertEqual(d.effects.get(0x0158), 1)
        self.assertFalse(d.route_on("Microphone", "ChatMic"))

    def test_appui_court_suit_le_mode_du_fader(self):
        self.ctl.act("fader", {"fader": "B", "channel": "Music"})
        self.ctl.act("settings", {"mute_modes": {"B": "stream"}})
        self.settle()
        self.sim.press("Fader2Mute", 120)
        self.assertTrue(wait_for(lambda: self.ctl.state["partial"]["Music"] == "stream", timeout=2))
        self.assertFalse(self.ctl.state["mutes"]["Music"])
        self.sim.press("Fader2Mute", 120)
        self.assertTrue(wait_for(lambda: self.ctl.state["partial"]["Music"] is None, timeout=2))

    def test_appui_long_coupe_partout_et_clignote(self):
        self.ctl.act("fader", {"fader": "B", "channel": "Music"})
        self.ctl.act("settings", {"mute_modes": {"B": "stream"}})
        self.settle()
        self.sim.button_down("Fader2Mute")
        self.assertTrue(wait_for(lambda: self.ctl.state["mutes"]["Music"], timeout=2))
        self.sim.button_up("Fader2Mute")
        self.settle()
        self.assertTrue(self.ctl.state["mutes"]["Music"], "le relachement apres un appui long ne reactive pas")
        self.assertEqual(self.led("Fader2Mute"), g.BTN_FLASH)
        self.assertTrue(self.sim.dev.muted[g.CHANNELS.index("Music")])

    def test_bouton_micro_appuyer_pour_parler(self):
        self.ctl.act("settings", {"mic_button": {"mode": "ptt", "target": "all"}})
        self.settle()
        self.assertTrue(self.ctl.state["mutes"]["Mic"])
        self.sim.button_down("MicrophoneMute")
        self.assertTrue(wait_for(lambda: not self.ctl.state["mutes"]["Mic"], timeout=2))
        self.settle()
        self.assertFalse(self.sim.dev.muted[0])
        self.sim.button_up("MicrophoneMute")
        self.assertTrue(wait_for(lambda: self.ctl.state["mutes"]["Mic"], timeout=2))

    def test_bouton_micro_maintenir_pour_couper(self):
        self.ctl.act("settings", {"mic_button": {"mode": "hold", "target": "chat"}})
        self.sim.button_down("MicrophoneMute")
        self.assertTrue(wait_for(lambda: self.ctl.state["partial"]["Mic"] == "chat", timeout=2))
        self.settle()
        self.assertFalse(self.sim.dev.route_on("Microphone", "ChatMic"))
        self.assertTrue(self.sim.dev.route_on("Microphone", "BroadcastMix"))
        self.sim.button_up("MicrophoneMute")
        self.assertTrue(wait_for(lambda: self.ctl.state["partial"]["Mic"] is None, timeout=2))

    def test_fader_physique_change_le_volume(self):
        self.sim.move_fader(2, 77)
        ch = self.ctl.state["faders"]["C"]
        self.assertTrue(wait_for(lambda: self.ctl.state["volumes"][ch] == 77, timeout=2))

    def test_fader_fugace_ignore(self):
        """Une valeur de fader lue une seule fois (Mini qui renvoie un « fader en haut » fugace) ne change rien."""
        ch = self.ctl.state["faders"]["A"]
        before = self.ctl.state["volumes"][ch]
        with self.ctl.lock:
            for v in (128, 255, 128, 128, 128, 128):
                self.ctl._handle_inputs(0, [v, 128, 128, 128], time.monotonic())
        self.assertEqual(self.ctl.state["volumes"][ch], before)

    def test_faders_jamais_remontes_masques(self):
        """Faders lus a 0 depuis la connexion : position inconnue, l'appli n'affiche pas « fader a 0 % »."""
        with self.ctl.lock:
            self.ctl._prev_pos, self.ctl.faders_seen = None, False
            for _ in range(5):
                self.ctl._handle_inputs(0, [0, 0, 0, 0], time.monotonic())
        self.assertEqual(self.ctl.live["fader_positions"], [None] * 4)

    # ---------- routage ----------
    def test_vod_sans_musique(self):
        self.ctl.act("settings", {"vod": {"mode": "no-music"}})
        self.settle()
        d = self.sim.dev
        self.assertEqual(d.route_on("Game", "Sampler"), d.route_on("Game", "BroadcastMix"))
        self.assertTrue(d.route_on("Game", "Sampler"))
        self.assertFalse(d.route_on("Music", "Sampler"))
        self.ctl.act("mute", {"channel": "Game", "muted": True, "target": "stream"})
        self.settle()
        self.assertFalse(d.route_on("Game", "Sampler"), "coupe du stream = coupe aussi de la VOD")

    # ---------- analyses micro ----------
    def test_gain_auto(self):
        self.sim.dev.mic_input = "dynamic"
        self.sim.dev.talking = True
        self.ctl.state["mic"] = {"type": "dynamic", "gain_db": 40}
        self.ctl._mark("mic")
        self.settle()
        self.ctl.act("auto-gain", {"seconds": 1.2})
        self.assertTrue(wait_for(lambda: not self.ctl.job["running"], timeout=6))
        self.assertIsNone(self.ctl.job["error"], self.ctl.job)
        new = self.ctl.job["result"]["new_gain_db"]
        self.assertTrue(52 <= new <= 64, new)
        self.settle()
        self.assertEqual(self.sim.dev.gains["dynamic"], new)

    def test_detection_micro_jack(self):
        self.sim.dev.mic_input = "jack"
        self.ctl.act("detect-mic", {})
        self.assertTrue(wait_for(lambda: not self.ctl.job["running"], timeout=10))
        self.assertEqual(self.ctl.job["result"]["detected"], "jack", self.ctl.job)
        self.settle()
        self.assertEqual(self.sim.dev.mic_type, self.ctl.state["mic"]["type"], "le type d'origine est remis apres l'analyse")

    def _voice_setup(self, body, timeout=40):
        """Lance « Régler ma voix » en parlant quand l'assistant le demande et en se taisant pendant le silence."""
        done = threading.Event()

        def speaker():
            while not done.is_set():
                job = self.ctl.job or {}
                self.sim.dev.talking = job.get("phase") in ("detect", "voice")
                time.sleep(0.01)
        th = threading.Thread(target=speaker, daemon=True)
        th.start()
        try:
            self.ctl.act("voice-setup", body)
            self.assertTrue(wait_for(lambda: not self.ctl.job["running"], timeout=timeout))
        finally:
            done.set()
            th.join(1)
        self.assertIsNone(self.ctl.job["error"], self.ctl.job)
        return self.ctl.job["result"]

    def test_regler_ma_voix_micro_statique(self):
        """Un micro statique branche alors que l'etat dit « dynamique » (donc sans 48 V) : l'assistant le trouve,
        allume le 48 V, cale les cretes de la voix vers -12 dB et place le noise gate entre bruit et voix."""
        self.sim.dev.mic_input = "condenser"
        self.ctl.state["mic"] = {"type": "dynamic", "gain_db": 30}
        self.ctl._mark("mic")
        self.settle()
        res = self._voice_setup({"voice_seconds": 2.5, "silence_seconds": 1.2})
        self.settle()
        s, cal = self.ctl.state, res["cal"]
        self.assertEqual((res["type"], s["mic"]["type"], s["mic_preset"]), ("condenser", "condenser", "studio"))
        self.assertTrue(self.sim.dev.phantom, "48 V allume pour le micro statique")
        self.assertEqual(self.sim.dev.gains["condenser"], s["mic"]["gain_db"])
        self.assertTrue(-14.5 <= cal["voice_peak_db"] <= -9.5, cal)
        gate = s["dsp"]["gate"]["threshold"]
        self.assertTrue(cal["noise_peak_db"] + 3 <= gate <= cal["voice_low_db"], (gate, cal))
        self.assertLess(s["dsp"]["comp"]["threshold"], cal["voice_peak_db"])
        self.assertEqual(s["mic_cal"], cal)
        self.assertAlmostEqual(res["snr_db"], cal["voice_db"] - cal["noise_peak_db"], delta=0.11)
        self.assertTrue(any("bruit de fond" in n["t"].lower() for n in res["notes"]), res["notes"])
        # les seuils suivent le gain : 6 dB de plus, gate et compresseur 6 dB plus haut
        self.ctl.act("mic", {"gain_db": s["mic"]["gain_db"] + 6})
        self.assertEqual(s["dsp"]["gate"]["threshold"], min(-10, gate + 6))
        self.ctl.act("mic-preset", {"name": "radio"})
        self.assertNotEqual(s["dsp"]["gate"]["threshold"], g.MIC_PRESETS["radio"]["dsp"]["gate"]["threshold"])
        # une scene integree garde la voix mesuree
        self.ctl.act("mic-preset", {"name": "studio"})
        self.ctl.act("scene", {"name": "discord"})
        self.assertEqual(s["mic_preset"], "studio")

    def test_regler_ma_voix_qui_sature(self):
        self.sim.dev.mic_input = "dynamic"
        self.sim.dev.voice_db = -2.0         # voix tres forte a 40 dB : l'entree sature
        self.ctl.state["mic"] = {"type": "dynamic", "gain_db": 45}
        self.ctl._mark("mic")
        self.settle()
        res = self._voice_setup({"detect": False, "voice_seconds": 2.0, "silence_seconds": 1.0})
        self.assertTrue(-14.5 <= res["cal"]["voice_peak_db"] <= -9.5, res)
        self.assertLess(res["gain_db"], 35)

    def test_m_ecouter_puis_retour(self):
        d, mon = self.sim.dev, g.CHANNELS.index("MicMonitor")
        self.ctl.act("route", {"input": "Microphone", "output": "Headphones", "enabled": False})
        self.ctl.act("volume", {"channel": "MicMonitor", "value": 0})
        self.settle()
        self.ctl.act("mic-listen", {"seconds": 0.4, "level": 120})
        self.assertTrue(wait_for(lambda: d.volumes[mon] == 120 and d.route_on("Microphone", "Headphones"), timeout=2))
        self.assertGreater(self.ctl.live_snapshot()["listening"], 0)
        self.assertTrue(wait_for(lambda: d.volumes[mon] == 0 and not d.route_on("Microphone", "Headphones"), timeout=3))
        self.assertEqual(self.ctl.live_snapshot()["listening"], 0)
        self.assertEqual(self.ctl.state["volumes"]["MicMonitor"], 0, "l'etat enregistre n'a pas bouge")

    # ---------- scenes automatiques ----------
    def test_scenes_automatiques(self):
        c = self.ctl
        c.act("auto-scenes", {"enabled": True, "rules": [{"app": "obs64.exe", "scene": "streaming"}], "fallback": "ecoute"})
        c._auto_seen = False                 # comme au demarrage du moteur
        self.assertIsNone(c.auto_scene_tick(["obs64.exe"]), "OBS deja ouvert au demarrage : on ne touche a rien")
        self.assertEqual(c.auto_scene_tick([]), "ecoute", "OBS ferme : scene de repli")
        self.assertEqual(c.auto_scene_tick(["OBS64.EXE"]), "streaming")
        self.assertEqual(c.state["scene"], "streaming")
        self.assertIsNone(c.auto_scene_tick(["obs64.exe", "spotify.exe"]))
        self.assertEqual(c.auto_scene_tick(["spotify.exe"]), "ecoute")
        c.act("auto-scenes", {"enabled": False})
        self.assertIsNone(c.auto_scene_tick(["obs64.exe"]))

    # ---------- persistance ----------
    def test_etat_sauve_et_relu(self):
        self.ctl.act("volume", {"channel": "Chat", "value": 33})
        self.ctl.act("settings", {"mic_button": {"mode": "hold"}})
        self.ctl.save_if_dirty()
        st = g.normalize_state(g.load_json(g.STATE_PATH))
        self.assertEqual(st["volumes"]["Chat"], 33)
        self.assertEqual(st["mic_button"]["mode"], "hold")

    def test_profil_v3_relu(self):
        v3 = {"faders": {"A": "Mic"}, "mutes": {"Mic": True}, "user_scenes": {"Soir": {"faders": {"A": "Music"}}}}
        st = g.normalize_state(v3)
        self.assertTrue(st["mutes"]["Mic"])
        self.assertEqual(st["mute_modes"]["A"], "all")
        self.assertIn("Soir", st["user_scenes"])


class HeadphoneEq(unittest.TestCase):
    """Egaliseur du casque (Equalizer APO), sans appareil : calculs, fichier, installation simulee, live."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="goxlr-hp-")
        g.configure(simulate=True, data_dir=self.tmp)
        self.sim = simulator.FakeTusb.reset_shared()
        g._lib = self.sim
        self.ctl = g.Controller(persist=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self, name=g.EQAPO_FILE):
        with open(os.path.join(self.tmp, "eqapo-sim", "config", name), encoding="ascii") as f:
            return f.read()

    def test_preampli_comme_autoeq(self):
        """Correction seule : le preampli calcule rejoint celui d'AutoEq (HD 560S : -6,6 dB), avec 0,3 dB de marge."""
        flt, pre = g.hp_filters(g.normalize_hp_eq({"headphone": "Sennheiser HD 560S"}))
        self.assertEqual(len(flt), 10)
        self.assertTrue(-7.2 <= pre <= -6.6, pre)
        self.assertEqual(g.hp_filters(g.normalize_hp_eq({}))[1], 0.0)

    def test_fichier_equalizer_apo(self):
        eq = g.normalize_hp_eq({"headphone": "Sennheiser HD 560S", "bands": [4, 5, 3, 1, 0, 0, 0, 0, 0, 0],
                                "channels": ["Game", "Chat"]})
        t = g.hp_config_text(eq, True)
        t.encode("ascii")
        self.assertIn("Device: GoXLR Game; GoXLR Chat", t)
        self.assertIn("Filter 1: ON LSC Fc 105 Hz Gain 9.0 dB Q 0.70", t)
        self.assertIn("Filter 11: ON PK Fc 31 Hz Gain 4.0 dB Q 1.41", t)
        self.assertTrue(t.rstrip().endswith("Device: all"))
        self.assertNotIn("Filter", g.hp_config_text(eq, False, "live"))

    def test_installation_simulee_puis_live(self):
        c = self.ctl
        st = c.snapshot()["hp_eq"]
        self.assertFalse(st["apo"])
        c.act("hp-eq", {"headphone": "Sennheiser HD 560S", "style": "basses"})
        self.assertEqual(c.state["hp_eq"]["bands"], g.HP_STYLES["basses"]["bands"])
        c.act("hp-eq-setup", {})
        self.assertTrue(wait_for(lambda: not c.eqapo.setup["running"], timeout=5))
        self.assertIsNone(c.eqapo.setup["error"], c.eqapo.setup)
        st = c.snapshot()["hp_eq"]
        self.assertTrue(st["apo"] and st["endpoints"]["Game"] and st["active"], st)
        self.assertTrue(c.state["hp_eq"]["enabled"])
        self.assertIn("Include: goxlr-mini.txt", self.cfg("config.txt"))
        self.assertIn("Preamp: -", self.cfg())
        # OBS ouvert : coupe ; ferme : revient
        c.hp_tick(["obs64.exe", "discord.exe"])
        self.assertNotIn("Filter", self.cfg())
        self.assertTrue(c.snapshot()["hp_eq"]["live"])
        c.hp_tick(["discord.exe"])
        self.assertIn("Filter", self.cfg())
        # retrait : effets d'origine, egaliseur coupe
        c.act("hp-eq-remove", {})
        self.assertTrue(wait_for(lambda: not c.eqapo.setup["running"], timeout=5))
        self.assertFalse(c.snapshot()["hp_eq"]["endpoints"]["Game"])
        self.assertNotIn("Filter", self.cfg())

    def test_profils(self):
        c = self.ctl
        c.act("hp-eq", {"bands": [1, 2, 3, 0, 0, 0, 0, 0, 0, 9]})
        self.assertIsNone(c.state["hp_eq"]["style"], "bande touchee a la main : reglage perso")
        c.act("hp-eq-save", {"name": "FPS"})
        self.assertEqual(c.state["hp_eq"]["style"], "custom:FPS")
        c.act("hp-eq", {"style": "neutre"})
        c.act("hp-eq", {"style": "custom:FPS"})
        self.assertEqual(c.state["hp_eq"]["bands"][9], 9)
        st = g.normalize_state(json.loads(json.dumps(c.state)))
        self.assertEqual(st["hp_eq"]["custom"]["FPS"][0], 1)
        c.act("hp-eq-delete", {"name": "FPS"})
        self.assertNotIn("FPS", c.state["hp_eq"]["custom"])
        self.assertIsNone(c.state["hp_eq"]["style"])

    def test_ancienne_config_gardee(self):
        d = os.path.join(self.tmp, "eqapo-sim", "config")
        os.makedirs(d)
        with open(os.path.join(d, "config.txt"), "w") as f:
            f.write("Include: autre-outil.txt\n")
        self.ctl.eqapo.sim_apo = True
        self.ctl.act("hp-eq", {"enabled": True})
        cfg = self.cfg("config.txt")
        self.assertIn("Include: goxlr-mini.txt", cfg)
        self.assertNotIn("autre-outil", cfg)
        backups = [n for n in os.listdir(d) if n.startswith("config.goxlr-mini-backup-")]
        self.assertEqual(len(backups), 1)


class VoiceFit(unittest.TestCase):
    """Placement des reglages par rapport a une voix mesuree (sans appareil)."""
    CAL = {"type": "condenser", "gain_db": 30, "t": 1.0, "noise_db": -63.0, "noise_peak_db": -60.0,
           "voice_low_db": -36.0, "voice_db": -24.0, "voice_peak_db": -12.0}

    def test_gate_entre_bruit_et_voix(self):
        d = g.fit_dsp("studio", self.CAL, 30)
        self.assertTrue(-54 <= d["gate"]["threshold"] <= -40, d["gate"])
        self.assertEqual(d["comp"]["threshold"], -28)
        self.assertTrue(4 <= d["comp"]["makeup"] <= 10, d["comp"])
        # le gate ferme pousse le bruit (plus la compensation) sous -75 dB, sans aller plus loin que necessaire
        att = -g.gate_attenuation(d["gate"]["attenuation"])
        self.assertGreaterEqual(-60 + d["comp"]["makeup"] - att, -75 - 1)
        self.assertLessEqual(-60 + d["comp"]["makeup"] - att, g.RESIDUAL_NOISE_DB)

    def test_piece_bruyante_coupe_plus(self):
        loud = dict(self.CAL, noise_db=-48.0, noise_peak_db=-44.0)
        self.assertGreater(g.fit_dsp("studio", loud, 30)["gate"]["attenuation"],
                           g.fit_dsp("studio", self.CAL, 30)["gate"]["attenuation"])

    def test_sans_mesure_valeurs_d_usine(self):
        self.assertEqual(g.fit_dsp("studio"), g.MIC_PRESETS["studio"]["dsp"])
        self.assertEqual(g.fit_dsp("brut", self.CAL, 30), g.MIC_PRESETS["brut"]["dsp"])

    def test_mesure_relue_ou_rejetee(self):
        self.assertEqual(g.normalize_cal(self.CAL), self.CAL)
        self.assertIsNone(g.normalize_cal({"type": "condenser"}))
        self.assertIsNone(g.normalize_cal({**self.CAL, "type": "ruban"}))
        self.assertEqual(g.normalize_state({"mic_cal": self.CAL})["mic_cal"], self.CAL)

    def test_usb_sans_windows(self):
        g.configure(simulate=True, data_dir=tempfile.gettempdir())
        g._lib = None
        self.assertIsNone(g.usb_scan(), "rien a dire quand l'information manque")


class Http(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="goxlr-http-")
        g.configure(simulate=True, data_dir=self.tmp)
        self.sim = simulator.FakeTusb.reset_shared()
        g._lib = self.sim
        self.ctl = g.Controller(persist=False)
        self.srv = g.Server(("127.0.0.1", 0), g.make_handler(self.ctl))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=3) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_post_sans_en_tete_refuse(self):
        self.assertEqual(self.req("POST", "/api/volume", {"channel": "Mic", "value": 1})[0], 403)

    def test_hote_etranger_refuse(self):
        self.assertEqual(self.req("GET", "/api/state", headers={"Host": "evil.example"})[0], 403)

    def test_routes_principales(self):
        self.assertEqual(self.req("GET", "/api/health")[0], 200)
        self.assertEqual(self.req("GET", "/api/live?level=1")[0], 200)
        code, st = self.req("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertIn("mute_targets", st["meta"])
        code, r = self.req("POST", "/api/mute", {"channel": "Music", "muted": True, "target": "stream"}, {"X-GoXLR": "1"})
        self.assertEqual((code, r["ok"]), (200, True))
        self.assertEqual(self.req("POST", "/api/nimporte", {}, {"X-GoXLR": "1"})[0], 404)
        self.assertEqual(self.req("POST", "/api/volume", {"channel": "Zzz", "value": 1}, {"X-GoXLR": "1"})[0], 400)
        self.assertNotEqual(self.req("POST", "/api/mic-listen", {"seconds": 0}, {"X-GoXLR": "1"})[0], 404)
        self.assertEqual(self.req("GET", "/api/processes")[0], 200)


if __name__ == "__main__":
    unittest.main()
