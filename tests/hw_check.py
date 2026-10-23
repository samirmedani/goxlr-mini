# -*- coding: utf-8 -*-
"""Controle materiel rapide (moteur arrete) : ouverture, latence, niveau micro, rattrapage d'index.
La Mini repond avec son propre compteur : un saut d'index doit etre rattrape par une resynchronisation
(commande 0) sans perdre la connexion. Le passage naturel de 65535 se verifie moteur en marche
(/api/health : stats.index_resets >= 1 apres une heure). Usage sur le PC : python.exe hw_check.py [dossier]"""
import os
import sys
import time

ENGINE = sys.argv[1] if len(sys.argv) > 1 else r"C:\Program Files\GoXLR Mini"
sys.path.insert(0, ENGINE)
import goxlrctl as g  # noqa: E402

g.configure(data_dir=os.path.join(os.environ.get("TEMP", "."), "goxlr-hwcheck"))
ok = True
dev = g.GoXLR()
dev.open()
print(f"ouvert : serie {dev.serial}, firmware {dev.firmware}, mix2={dev.mix2}")
t0 = time.perf_counter()
for _ in range(40):
    mask, vols, enc = dev.get_button_states()
ms = (time.perf_counter() - t0) * 1000 / 40
print(f"lecture boutons : {ms:.1f} ms par commande, faders={vols}, masque={mask:#x}")
print(f"niveau micro : {g.level_db(dev.mic_level())} dB")
dev.count = 60000                      # saut volontaire : la Mini ne repond pas a cet index
try:
    for i in range(10):
        dev.get_button_states()
except Exception as e:
    ok = False
    print("ECHEC :", g.describe(e))
print(f"resynchronisations : {dev.stats['resyncs']}, index actuel : {dev.count}")
if dev.stats["resyncs"] != 1 or dev.count > 50:
    ok = False
print("la Mini repond toujours apres resynchronisation" if ok else "PROBLEME apres resynchronisation")
dev.close()
print("RESULTAT", "OK" if ok else "ECHEC")
sys.exit(0 if ok else 1)
