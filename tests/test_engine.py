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
        self.assertEqual(self.req("GET", "/api/processes")[0], 200)


if __name__ == "__main__":
    unittest.main()
