"""Radar Retomados: localiza cada imóvel no mapa e mede o comércio em volta.
1) Lê os imóveis ativos do Brasil (chave pública, só leitura).
2) Geolocaliza pelo endereço (rua) ou, se não der, pelo bairro, usando o Nominatim do OpenStreetMap
   (1 consulta por segundo, com cache no repositório para nunca repetir a mesma consulta).
3) Baixa o mapa do Brasil do OpenStreetMap (Geofabrik) e conta lojas, escritórios, bancos, restaurantes etc.
   num raio de 300 m e 800 m de cada imóvel.
Saída: data/geo_imoveis.json  [{id, lat, lon, nivel, poi300, poi800}] e data/geo_status.json"""
import json, os, re, sys, time, unicodedata, urllib.request, urllib.parse, datetime, math

API = "https://ryhyvzwqtktaaonznizn.supabase.co/rest/v1/radar_imoveis"
KEY = "sb_publishable_Ji31DC1ihqZTR7gmLeYTLw_GHgBjWN0"
UA = "RadarRetomados/1.0 (github.com/paulomarciojuniorbh-lgtm/radar-retomados; geolocalizacao de imoveis de leilao)"
LIMITE_GEO = int(os.environ.get("LIMITE_GEO", "6000"))
status = {"inicio": datetime.datetime.now(datetime.timezone.utc).isoformat()}
os.makedirs("data", exist_ok=True)

def sem_acento(s):
    return unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()

# 1) imóveis
imoveis, off = [], 0
while True:
    u = f"{API}?select=id,fonte,titulo,endereco,bairro,cidade,uf&ativo=eq.true&or=(pais.is.null,pais.eq.BR)&limit=1000&offset={off}"
    rows = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"apikey": KEY, "User-Agent": UA}), timeout=60))
    imoveis += rows
    if len(rows) < 1000: break
    off += 1000
status["imoveis"] = len(imoveis)

RUA = re.compile(r"^\s*(rua|r\.|avenida|av\.?|alameda|al\.|travessa|tv\.|rodovia|rod\.|estrada|est\.|pra[cç]a|largo|via|servid[aã]o|quadra|qd\.?)\b", re.I)
LIXO_BAIRRO = re.compile(r"\b(apto|apartamento|lote|lt|qd|quadra|casa|bloco|sala|loja|unidade|box)\b", re.I)

def bairro_de(x):
    b = (x.get("bairro") or "").strip()
    if b and not LIXO_BAIRRO.search(b): return b
    t = x.get("titulo") or ""
    if x["fonte"] == "resale":           # "Casa, Residencial, JARDIM DOS IPES"
        p = [s.strip() for s in t.split(",")]
        if len(p) >= 3 and not LIXO_BAIRRO.search(p[-1]): return p[-1].title()
    if x["fonte"] == "superbid":         # "Casa 201m² | Limeira-SP | Jardim São Lourenço | Oportunidade"
        p = [s.strip() for s in t.split("|")]
        cid = sem_acento(x.get("cidade"))
        for i, s in enumerate(p):
            if cid and cid in sem_acento(s) and i + 1 < len(p):
                cand = re.sub(r"\s*-\s*(pr[oó]x|oportunidade|desocupado|ocupado).*$", "", p[i + 1], flags=re.I).strip()
                if 2 < len(cand) < 50 and not re.search(r"\d", cand): return cand
    if x["fonte"] == "mega":             # "... - Bairro - Cidade - UF"
        p = [s.strip() for s in t.split(" - ")]
        if len(p) >= 3: return p[-3]
    return None

def rua_de(x):
    e = (x.get("endereco") or "").strip()
    if not e or not RUA.search(e): return None
    e = re.sub(r",?\s*N\.?\s*(\d+)", r", \1", e)
    e = re.sub(r"\b(s/?n|lote.*|lt.*|qd.*|quadra.*|apto.*|bloco.*)$", "", e, flags=re.I).strip(" ,")
    return e

# cache
cache = {}
if os.path.exists("data/geo_cache.json"):
    cache = json.load(open("data/geo_cache.json"))

ultimo = [0.0]
def nominatim(q, cidade, uf):
    k = sem_acento(q + "|" + cidade + "|" + uf)
    if k in cache: return cache[k]
    espera = 1.1 - (time.time() - ultimo[0])
    if espera > 0: time.sleep(espera)
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": f"{q}, {cidade}, {uf}, Brasil", "format": "jsonv2", "countrycodes": "br", "limit": 3, "addressdetails": 1})
    res = None
    for t in range(3):
        try:
            ultimo[0] = time.time()
            r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30))
            alvo = sem_acento(cidade)
            for it in r:
                a = it.get("address", {})
                cid = sem_acento(a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or "")
                if alvo and (cid == alvo or alvo in cid or cid in alvo):
                    res = {"lat": float(it["lat"]), "lon": float(it["lon"]), "tipo": it.get("addresstype") or it.get("type")}
                    break
            break
        except Exception as e:
            print("nominatim erro", e, flush=True); time.sleep(5 * (t + 1))
    cache[k] = res
    return res

saida_geo = {}
consultas = 0
t0 = time.time()
for x in imoveis:
    cid, uf = x.get("cidade") or "", x.get("uf") or ""
    if not cid: continue
    if consultas >= LIMITE_GEO or time.time() - t0 > 4.3 * 3600: status["parou"] = "limite"; break
    rua, bairro = rua_de(x), bairro_de(x)
    g, nivel = None, None
    if rua:
        antes = len(cache); g = nominatim(rua, cid, uf); consultas += len(cache) - antes
        if g and g["tipo"] not in ("city", "town", "village", "municipality", "state", "suburb", "neighbourhood", "quarter"): nivel = "rua"
        elif g: g = None
    if not g and bairro:
        antes = len(cache); g = nominatim(bairro, cid, uf); consultas += len(cache) - antes
        if g and g["tipo"] not in ("city", "town", "village", "municipality", "state"): nivel = "bairro"
        else: g = None
    if g: saida_geo[x["id"]] = {"lat": round(g["lat"], 6), "lon": round(g["lon"], 6), "nivel": nivel}
    if consultas and consultas % 200 == 0:
        json.dump(cache, open("data/geo_cache.json", "w"))
        print(f"{consultas} consultas, {len(saida_geo)} localizados", flush=True)
json.dump(cache, open("data/geo_cache.json", "w"))
status["consultas_novas"] = consultas
status["localizados"] = len(saida_geo)
status["por_nivel"] = {n: sum(1 for v in saida_geo.values() if v["nivel"] == n) for n in ("rua", "bairro")}
print(status, flush=True)

# 3) comércio em volta (OpenStreetMap, Geofabrik)
import osmium, numpy as np
from scipy.spatial import cKDTree
PBF = "/tmp/brasil.osm.pbf"
if not os.path.exists(PBF):
    urllib.request.urlretrieve("https://download.geofabrik.de/south-america/brazil-latest.osm.pbf", PBF)
AMEN = {"restaurant", "cafe", "fast_food", "bank", "pharmacy", "bar", "marketplace", "clinic", "dentist", "doctors", "bureau_de_change", "ice_cream", "pub", "food_court", "atm"}
class Poi(osmium.SimpleHandler):
    def __init__(self):
        super().__init__(); self.pts = []
    def node(self, n):
        t = n.tags
        if "shop" in t or "office" in t or ("amenity" in t and t["amenity"] in AMEN):
            self.pts.append((n.location.lat, n.location.lon))
h = Poi(); h.apply_file(PBF)
status["pontos_comerciais_osm"] = len(h.pts)
def xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.c_[np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]
P = np.array(h.pts)
arv = cKDTree(xyz(P[:, 0], P[:, 1]))
ids = list(saida_geo.keys())
Q = xyz(np.array([saida_geo[i]["lat"] for i in ids]), np.array([saida_geo[i]["lon"] for i in ids]))
corda = lambda m: 2 * math.sin(m / 6371000 / 2)
c300 = arv.query_ball_point(Q, corda(300), return_length=True)
c800 = arv.query_ball_point(Q, corda(800), return_length=True)
out = [{"id": i, **saida_geo[i], "poi300": int(a), "poi800": int(b)} for i, a, b in zip(ids, c300, c800)]
json.dump(out, open("data/geo_imoveis.json", "w"))
status["fim"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
json.dump(status, open("data/geo_status.json", "w"), indent=1, ensure_ascii=False)
print(status)
