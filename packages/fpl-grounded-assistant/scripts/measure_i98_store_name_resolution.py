"""i98 relaxation audit: what each candidate alias newly resolves, and that
nothing which resolved before changes target. Runs against the LIVE bootstrap
and a fpl-tactical understat_shots parquet (2025-26: 449 distinct names).

CANDIDATES is the hand-verified store-form -> web_name table the audit was run
with on 2026-09-17; the in-process patch below applies the ACCEPTED subset on
top of whatever KNOWN_NICKNAMES already holds, so re-running after the merge
reports 0 newly resolved (they resolve "before") and still 0 changed targets."""
import sys, json, html, os

# Usage: python scripts/measure_i98_store_name_resolution.py <packages dir> <store parquet> <out.json>
PK = os.path.abspath(sys.argv[1])
sys.path[:0] = [os.path.join(PK, p) for p in (
    "fpl-grounded-assistant", "fpl-data-core", "fpl-api-client", "fpl-player-registry",
    "fpl-query-tools", "fpl-tool-contract", "fpl-tool-runner", "fpl-captain-engine", "football-data-contract")]
import requests, pandas as pd
from fpl_grounded_assistant.zonal_weakness_tool import resolve_store_player
from fpl_player_registry import nicknames

boot = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=60).json()
df = pd.read_parquet(sys.argv[2])
names = sorted(html.unescape(n) for n in df["player"].unique())   # as the store will read after the ingest fix

# Candidate aliases: store form -> FPL web_name (hand-verified same person;
# "Jacob Bruun Larsen" -> "Strand Larsen" from the heuristic is a DIFFERENT
# player and is deliberately absent).
CANDIDATES = {
    "Abduqodir Khusanov": "Khusanov", "Alejandro Garnacho": "Garnacho", "Alysson Edward": "Alysson",
    "Ao Tanaka": "Tanaka", "Ben Doak": "Gannon-Doak", "Ben White": "White", "Bruno Fernandes": "B.Fernandes",
    "Bruno Guimarães": "Bruno G.", "Carlos Alcaraz": "Alcaraz", "Dan Ballard": "Ballard",
    "Daniel Muñoz": "Muñoz", "Diego Gómez": "Gomez", "Diogo Dalot": "Dalot", "Dominic Solanke": "Solanke",
    "Emiliano Buendía": "Buendía", "Fabio Carvalho": "Carvalho", "Florentino Luís": "Florentino",
    "Gabriel Jesus": "G.Jesus", "Gabriel Martinelli": "Martinelli", "Jefferson Lerma": "Lerma",
    "Jorge Cuenca": "J.Cuenca", "Joseph Gomez": "Gomez", "Joshua King": "King", "Kaoru Mitoma": "Mitoma",
    "Manuel Ugarte": "Ugarte", "Marcos Senesi": "Senesi", "Martín Zubimendi": "Zubimendi",
    "Matheus Cunha": "Cunha", "Matthew Cash": "Cash", "Mikel Merino": "Merino", "Moisés Caicedo": "Caicedo",
    "Nico González": "N.Gonzalez", "Pape Sarr": "P.M.Sarr", "Pedro Neto": "Neto", "Rodrigo Muniz": "Muniz",
    "Rúben Dias": "Rúben", "Treymaurice Nyoni": "Nyoni", "Wataru Endo": "Endo", "Yeremi Pino": "Yeremy",
    "Oli McBurnie": "McBurnie",
}

def snapshot():
    return {n: (el["id"], el["web_name"]) if (el := resolve_store_player(n, boot)) else None for n in names}

before = snapshot()
from fpl_player_registry.resolution import normalize_player_name
norm_count = {}
for e in boot["elements"]:
    k = normalize_player_name(e["web_name"])
    norm_count[k] = norm_count.get(k, 0) + 1
web_count = {e["web_name"]: norm_count[normalize_player_name(e["web_name"])] for e in boot["elements"]}

accepted, rejected = {}, {}
for store_form, web in CANDIDATES.items():
    if web_count.get(web, 0) == 0:
        rejected[store_form] = f"web_name {web!r} not in today's bootstrap"
    elif web_count[web] > 1:
        rejected[store_form] = f"web_name {web!r} normalizes like {web_count[web]} players' web_names -- alias would be ambiguous"
    elif before.get(store_form) is not None:
        rejected[store_form] = f"already resolves to {before[store_form]}"
    elif store_form not in before:
        rejected[store_form] = "not in the 2025-26 store (kept out: nothing measured fails)"
    else:
        accepted.setdefault(web, []).append(store_form)

# Apply the accepted aliases in-process and re-measure.
patched = {k: list(v) for k, v in nicknames.KNOWN_NICKNAMES.items()}
for web, forms in accepted.items():
    patched.setdefault(web, []).extend(forms)
nicknames.KNOWN_NICKNAMES.clear(); nicknames.KNOWN_NICKNAMES.update(patched)
import fpl_player_registry.resolution as R
R.KNOWN_NICKNAMES = nicknames.KNOWN_NICKNAMES
after = snapshot()

changed = {n: (before[n], after[n]) for n in names if before[n] is not None and before[n] != after[n]}
newly = {n: after[n] for n in names if before[n] is None and after[n] is not None}
wrong_target = {n: after[n] for n, t in newly.items() if CANDIDATES.get(n) != t[1]}
print(f"store names {len(names)} | resolved before {sum(v is not None for v in before.values())} | after {sum(v is not None for v in after.values())}")
print(f"previously-resolved names that changed target: {changed}")
print(f"newly resolved: {len(newly)}; any to an unintended web_name: {wrong_target}")
for n, t in sorted(newly.items()): print(f"  {n!r:26} -> {t[1]!r}")
print("rejected:"); [print(f"  {k!r:26} {v}") for k, v in rejected.items()]
json.dump({"accepted": accepted, "rejected": rejected, "newly": newly, "changed": changed,
           "resolved_before": sum(v is not None for v in before.values()),
           "resolved_after": sum(v is not None for v in after.values())},
          open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
