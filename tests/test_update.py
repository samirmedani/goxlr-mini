# -*- coding: utf-8 -*-
"""Tests du systeme de mise a jour, avec un faux GitHub local (aucun reseau)."""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine")
sys.path.insert(0, os.path.abspath(ENGINE))
import goxlrctl as g  # noqa: E402
import simulator  # noqa: E402


def make_zip(version, extra=None, files=None):
    files = dict(files or {"goxlrctl.py": "print('v')", "ui.html": "<html></html>", "python/python.exe": "x",
                           "python/pythonw.exe": "x", "app/GoXLR Mini.exe": "x", "LICENSE": "MIT"})
    files["manifest.json"] = json.dumps({"name": "GoXLR Mini", "version": version, "release": True,
                                         "files": {k: "" for k in list(files) + ["manifest.json"]}})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


class FakeGitHub:
    def __init__(self):
        self.release = None
        self.status = 200
        self.headers = {}
        self.blobs = {}
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.endswith("/releases/latest"):
                    if fake.status != 200:
                        self.send_response(fake.status)
                        for k, v in fake.headers.items():
                            self.send_header(k, v)
                        self.send_header("Content-Length", "2")
                        self.end_headers()
                        self.wfile.write(b"{}")
                        return
                    body = json.dumps(fake.release).encode()
                elif self.path in fake.blobs:
                    body = fake.blobs[self.path]
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def publish(self, version, blob, digest=True, name="GoXLR-Mini.zip"):
        path = f"/dl/v{version}/{name}"
        self.blobs[path] = blob
        asset = {"name": name, "size": len(blob), "browser_download_url": self.base + path}
        if digest:
            asset["digest"] = "sha256:" + hashlib.sha256(blob).hexdigest()
        self.release = {"tag_name": f"v{version}", "draft": False, "prerelease": False, "body": "**Nouveau**\n- truc",
                        "html_url": f"https://github.com/x/y/releases/tag/v{version}", "assets": [asset]}

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class Versions(unittest.TestCase):
    def test_semver(self):
        self.assertTrue(g.version_lt("4.1.0", "4.1.1"))
        self.assertTrue(g.version_lt("4.1.0", "4.10.0"))
        self.assertTrue(g.version_lt("4.2.0-beta.2", "4.2.0"))
        self.assertTrue(g.version_lt("4.2.0-beta.2", "4.2.0-beta.10"))
        self.assertFalse(g.version_lt("4.1.0", "4.1.0"))
        self.assertFalse(g.version_lt("4.1.0", "latest"))
        self.assertIsNone(g.parse_semver("v01.2.3"))
        self.assertIsNone(g.parse_semver("1.2"))
        self.assertEqual(g.parse_semver("v1.2.3+abc")[:3], (1, 2, 3))

    def test_release_mal_formee(self):
        self.assertEqual(g.parse_release({"tag_name": "latest"})[0], "unusable")
        self.assertEqual(g.parse_release({"tag_name": "v9.0.0", "prerelease": True})[0], "unusable")
        kind, info, _ = g.parse_release({"tag_name": "v9.0.0", "assets": [
            {"name": "GoXLR-Mini.zip", "browser_download_url": "https://evil.example/GoXLR-Mini.zip"}]})
        self.assertEqual(kind, "release")
        self.assertIsNone(info["asset"], "un fichier hors des releases du projet n'est jamais proposé")


class Updates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="goxlr-upd-")
        g.configure(simulate=True, data_dir=os.path.join(self.tmp, "data"))
        g._lib = simulator.FakeTusb.reset_shared()
        self.gh = FakeGitHub()
        self.saved = (g.UPDATE_API, g.UPDATE_DOWNLOAD_PREFIX, set(g.DOWNLOAD_HOSTS), g.VERSION)
        g.UPDATE_API = self.gh.base
        g.UPDATE_DOWNLOAD_PREFIX = self.gh.base + "/dl/"
        g.DOWNLOAD_HOSTS.add("127.0.0.1")
        g.VERSION = "4.1.0"
        self.ctl = g.Controller(persist=False)
        self.up = self.ctl.updater
        self.up.installable = lambda: (True, None)
        self.applied = []
        self.up.launch_apply = lambda new, work: self.applied.append((new, work))

    def tearDown(self):
        g.UPDATE_API, g.UPDATE_DOWNLOAD_PREFIX, hosts, g.VERSION = self.saved
        g.DOWNLOAD_HOSTS.clear()
        g.DOWNLOAD_HOSTS.update(hosts)
        self.gh.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait_phase(self, *phases, timeout=8):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.up.phase in phases:
                return self.up.phase
            time.sleep(0.02)
        self.fail(f"phase {self.up.phase}, attendu {phases} ; erreur {self.up.error}")

    def test_trouve_et_installe(self):
        self.gh.publish("4.1.1", make_zip("4.1.1"))
        self.up.check()
        self.assertEqual(self.up.status, "available")
        self.assertEqual(self.up.latest["version"], "4.1.1")
        self.up.start_install()
        self.wait_phase("applying")
        time.sleep(0.1)
        self.assertEqual(len(self.applied), 1)
        new, work = self.applied[0]
        plan = json.load(open(os.path.join(work, "plan.json"), encoding="utf-8"))
        self.assertEqual((plan["version"], plan["from_version"]), ("4.1.1", "4.1.0"))
        self.assertTrue(os.path.isfile(os.path.join(new, "app", "GoXLR Mini.exe")))

    def test_installation_qui_ne_demarre_pas(self):
        """Si la tache d'installation ne demarre pas, le moteur tourne toujours : echec affiche, on peut reessayer."""
        self.up.apply_timeout = 0.3
        self.gh.publish("4.1.1", make_zip("4.1.1"))
        self.up.check()
        self.up.start_install()
        self.wait_phase("failed")
        self.assertEqual(self.up.error["code"], "launch")
        self.up.start_install()
        self.wait_phase("applying")
        self.assertEqual(len(self.applied), 2)

    def test_nettoyage_au_demarrage_apres_installation(self):
        """Au demarrage qui suit une installation, la copie preparee part dans la minute (pas 6 h plus tard)."""
        work = os.path.join(g.DATA_DIR, "update")
        os.makedirs(os.path.join(work, "new", "python"))
        for n in (g.UPDATE_ASSET, "plan.json", "result.json"):
            open(os.path.join(work, n), "w").write("{}")
        self.up.started = time.time() - 31
        self.up.next_at = time.time() + 6 * 3600          # premiere recherche deja faite
        threading.Thread(target=self.up.loop, daemon=True).start()
        self.up.wake.set()
        t0 = time.time()
        while time.time() - t0 < 3 and os.listdir(work) != ["result.json"]:
            time.sleep(0.05)
        self.assertEqual(os.listdir(work), ["result.json"])

    def test_resultat_ecrit_apres_le_demarrage(self):
        """La tache d'installation ecrit result.json une fois le nouveau moteur en ligne : l'avis « installé » suit."""
        self.assertIsNone(self.up.installed)
        self.up.next_at = time.time() + 6 * 3600
        threading.Thread(target=self.up.loop, daemon=True).start()
        work = os.path.join(g.DATA_DIR, "update")
        os.makedirs(work, exist_ok=True)
        json.dump({"version": "4.1.1", "from_version": "4.1.0", "t": time.time(), "ok": True},
                  open(os.path.join(work, "result.json"), "w"))
        self.up.wake.set()
        t0 = time.time()
        while time.time() - t0 < 3 and self.up.installed is None:
            time.sleep(0.05)
        self.assertEqual((self.up.installed or {}).get("version"), "4.1.1")

    def test_nettoyage_apres_avis_lu(self):
        """L'interface a deja lu et efface result.json : le plan de la version en cours suffit pour nettoyer."""
        work = os.path.join(g.DATA_DIR, "update")
        os.makedirs(os.path.join(work, "new"))
        with open(os.path.join(work, "plan.json"), "w") as f:
            json.dump({"version": g.VERSION}, f)
        self.assertTrue(self.up.cleanup_after_install())
        self.assertEqual(os.listdir(work), [])
        os.makedirs(os.path.join(work, "new"))
        with open(os.path.join(work, "plan.json"), "w") as f:
            json.dump({"version": "9.9.9"}, f)          # installation d'une autre version peut-etre en cours
        self.assertFalse(self.up.cleanup_after_install())
        self.assertEqual(sorted(os.listdir(work)), ["new", "plan.json"])

    def test_a_jour(self):
        self.gh.publish("4.1.0", make_zip("4.1.0"))
        self.up.check()
        self.assertEqual(self.up.status, "up-to-date")
        with self.assertRaises(ValueError):
            self.up.start_install()

    def test_recherche_manuelle_une_par_minute(self):
        self.gh.publish("4.1.0", make_zip("4.1.0"))
        self.up.check(manual=True)
        with self.assertRaises(ValueError):
            self.up.check(manual=True)

    def test_limite_github_et_hors_ligne(self):
        self.gh.status = 429
        self.gh.headers = {"Retry-After": "900"}
        self.up.check()
        self.assertEqual(self.up.result, "rate-limited")
        self.assertAlmostEqual(self.up.next_at - time.time(), 900, delta=5)
        self.gh.status = 503
        self.up.check()
        self.assertEqual(self.up.result, "offline")
        self.assertAlmostEqual(self.up.next_at - time.time(), g.UPDATE_OFFLINE_RETRY, delta=5)
        self.gh.status = 404
        self.up.check()
        self.assertEqual(self.up.result, "up-to-date")

    def test_empreinte_fausse_refusee(self):
        blob = make_zip("4.1.1")
        self.gh.publish("4.1.1", blob)
        self.gh.release["assets"][0]["digest"] = "sha256:" + "0" * 64
        self.up.check()
        self.up.start_install()
        self.wait_phase("failed")
        self.assertEqual(self.up.error["code"], "corrupted")
        self.assertEqual(self.applied, [])

    def test_sans_empreinte_refusee(self):
        self.gh.publish("4.1.1", make_zip("4.1.1"), digest=False)
        self.up.check()
        self.up.start_install()
        self.wait_phase("failed")
        self.assertEqual(self.up.error["code"], "unverifiable")

    def test_empreinte_en_fichier_acceptee(self):
        blob = make_zip("4.1.1")
        self.gh.publish("4.1.1", blob, digest=False)
        path = "/dl/v4.1.1/GoXLR-Mini.sha256"
        self.gh.blobs[path] = (hashlib.sha256(blob).hexdigest() + "  GoXLR-Mini.zip\n").encode()
        self.gh.release["assets"].append({"name": "GoXLR-Mini.sha256", "browser_download_url": self.gh.base + path})
        self.up.check()
        self.up.start_install()
        self.wait_phase("applying")

    def test_archive_piegee_refusee(self):
        self.gh.publish("4.1.1", make_zip("4.1.1", extra={"../../evil.txt": "x"}))
        self.up.check()
        self.up.start_install()
        self.wait_phase("failed")
        self.assertEqual(self.up.error["code"], "archive")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))

    def test_version_differente_refusee(self):
        self.gh.publish("4.1.1", make_zip("4.0.9"))
        self.up.check()
        self.up.start_install()
        self.wait_phase("failed")
        self.assertEqual(self.up.error["code"], "archive")

    def test_archive_incomplete_refusee(self):
        self.gh.publish("4.1.1", make_zip("4.1.1", files={"goxlrctl.py": "x"}))
        self.up.check()
        self.up.start_install()
        self.wait_phase("failed")
        self.assertIn("incomplète", self.up.error["msg"])

    def test_dev_ne_s_installe_pas(self):
        up = g.Updater(self.ctl)
        self.assertEqual(up.installable(), (False, "dev"))


class Apply(unittest.TestCase):
    """Echange des fichiers : sauvegarde, copie, verification, retour arriere."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="goxlr-apply-")
        self.src, self.dst, self.data = (os.path.join(self.tmp, n) for n in ("new", "install", "data"))
        for root, ver, txt in ((self.dst, "4.1.0", "ancien"), (self.src, "4.1.1", "nouveau")):
            os.makedirs(os.path.join(root, "app"))
            for rel in ("goxlrctl.py", "app/GoXLR Mini.exe"):
                open(os.path.join(root, rel), "w").write(txt)
            json.dump({"version": ver, "files": {"goxlrctl.py": "", "app/GoXLR Mini.exe": "", "manifest.json": ""}},
                      open(os.path.join(root, "manifest.json"), "w"))
        open(os.path.join(self.dst, "state-utilisateur.json"), "w").write("garde")
        self.plan = {"from": self.src, "to": self.dst, "version": "4.1.1", "from_version": "4.1.0",
                     "data_dir": self.data, "port": 1, "task": "t"}
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_apply(self, healthy):
        return g.apply_update(self.plan, stop=lambda p: self.calls.append("stop"),
                              start=lambda p: self.calls.append("start"), wait=lambda p: healthy,
                              list_apps=lambda p: [(42, "PC\\joueur")],
                              restart_apps=lambda p, apps: self.calls.append(("apps", apps)))

    def test_succes(self):
        r = self.run_apply(True)
        self.assertTrue(r["ok"])
        self.assertEqual(open(os.path.join(self.dst, "goxlrctl.py")).read(), "nouveau")
        self.assertEqual(open(os.path.join(self.dst, "state-utilisateur.json")).read(), "garde")
        backups = os.listdir(os.path.join(self.dst, "backup"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(open(os.path.join(self.dst, "backup", backups[0], "goxlrctl.py")).read(), "ancien")
        self.assertEqual(json.load(open(os.path.join(self.data, "update", "result.json")))["version"], "4.1.1")
        self.assertEqual(self.calls, ["stop", "start", ("apps", [(42, "PC\\joueur")])])

    def test_retour_arriere(self):
        r = self.run_apply(False)
        self.assertFalse(r["ok"])
        self.assertEqual(open(os.path.join(self.dst, "goxlrctl.py")).read(), "ancien")
        self.assertEqual(open(os.path.join(self.dst, "app", "GoXLR Mini.exe")).read(), "ancien")
        self.assertEqual(self.calls, ["stop", "start", "stop", "start"])     # l'ancienne appli reste ouverte

    def test_point_d_entree_trouve_le_plan(self):
        """La tache lance <donnees>/update/new/goxlrctl.py apply-update ; le plan est dans <donnees>/update."""
        work = os.path.join(self.data, "update")
        os.makedirs(os.path.join(work, "new"))
        json.dump(self.plan, open(os.path.join(work, "plan.json"), "w"))
        seen = []
        saved = (g.apply_update, g.LOG_PREFIX, g.DATA_DIR)
        g.apply_update = lambda plan: seen.append(plan) or {"ok": True}
        try:
            g.run_apply_update(base_dir=os.path.join(work, "new"))
        finally:
            g.apply_update, g.LOG_PREFIX = saved[:2]
            g.configure(data_dir=saved[2])
        self.assertEqual([p["version"] for p in seen], ["4.1.1"])


if __name__ == "__main__":
    unittest.main()
