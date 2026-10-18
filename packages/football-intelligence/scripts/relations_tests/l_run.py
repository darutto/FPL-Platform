import os, re, json, random, html, pathlib, sys
sys.stdout.reconfigure(encoding='utf-8')
TO=pathlib.Path("C:/Users/thera/wt-fi9-live/packages/sportmonks-client/trial-output")
# load key from the main checkout .env (never printed)
for line in open("C:/Users/thera/fpl-platform/packages/fpl-grounded-assistant/.env",encoding='utf-8'):
    line=line.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
from openai import OpenAI
client=OpenAI(); MODEL="gpt-5.6-luna"
facts=json.loads((TO/"relations/l_facts.json").read_text(encoding="utf-8"))
SYS=("Eres un analista de Fantasy Premier League. Con SOLO los hechos que te doy, explica en español, en 90 a 120 palabras, "
     "qué ha pasado con este jugador y qué conviene vigilar para decidir si fichar o mantener. No inventes datos ni números que no estén en los hechos; "
     "si algo no se puede saber con los hechos, dilo. No des consejos genéricos.")
def ask(payload):
    r=client.responses.create(model=MODEL,max_output_tokens=1500,instructions=SYS,input=[{"role":"user","content":"HECHOS:\n"+json.dumps(payload,ensure_ascii=False)}])
    return r.output_text, getattr(r,"model",MODEL)
out={}
for name,f in facts.items():
    v1_in=f["fpl"]; v2_in={**f["fpl"],"sportmonks":f["sm"]}
    t1,m1=ask(v1_in); t2,m2=ask(v2_in)
    out[name]={"v1":t1,"v2":t2,"model":m1,"v1_facts":v1_in,"v2_facts":v2_in}
    print(name,m1,len(t1.split()),len(t2.split()))
(TO/"relations/l_out.json").write_text(json.dumps(out,ensure_ascii=False,indent=1),encoding="utf-8")
# numbers check
def nums(s): return {round(float(x),2) for x in re.findall(r"(?<![\w.])\d+(?:[.,]\d+)?",s.replace(",", "."))}
def fact_nums(o):
    s=json.dumps(o,ensure_ascii=False); return {round(float(x),2) for x in re.findall(r"\d+(?:\.\d+)?",s)}
rep={}
for name,o in out.items():
    for v,fk in (("v1","v1_facts"),("v2","v2_facts")):
        N=nums(o[v]); F=fact_nums(o[fk]); bad=sorted(x for x in N if x not in F and not any(abs(x-y)<0.011 for y in F))
        rep[f"{name}/{v}"]={"numbers":len(N),"not_in_facts":bad}
print(json.dumps(rep,ensure_ascii=False,indent=1))
# blind pages
rng=random.Random(20261018); key={}; pg=TO/"relations/blind"; pg.mkdir(exist_ok=True)
for name,o in out.items():
    order=["v1","v2"]; rng.shuffle(order); key[name]={"X":order[0],"Y":order[1]}
    body="".join(f"<section><h2>Explicación {lab}</h2><div class=a>{html.escape(o[v])}</div></section>" for lab,v in zip(("X","Y"),order))
    (pg/f"{name.replace('.','').replace(' ','_')}.html").write_text("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Caso</title><style>body{font:16px/1.5 system-ui;margin:16px;max-width:900px}.a{white-space:pre-wrap;border:1px solid #ccc;padding:12px;border-radius:8px}</style>"+f"<h1>{html.escape(name)}</h1>{body}<p>¿Cuál explica mejor?</p>",encoding="utf-8")
(TO/"relations/l_key.json").write_text(json.dumps(key,indent=1),encoding="utf-8")
