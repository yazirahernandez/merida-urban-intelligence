"""
Fase 1 - Data & geographic assessment (Merida Urban Intelligence)

Lee las fuentes ORIGINALES directamente desde sus .zip (no las modifica),
perfila cada una y prueba la integracion geografica:
  1) Censo 2020 (AGEB)  <-> poligonos AGEB   : por clave CVEGEO
  2) DENUE (lat/lon)    <-> poligonos AGEB   : punto-en-poligono (sjoin)
  3) Delitos SESNSP     <-> poligonos municipio : por clave CVEGEO municipal

Uso (desde la raiz del repo):
    python src/phase1_assessment.py
Salidas en outputs/phase1/
"""
import zipfile
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

# ---------------------------------------------------------------- CONFIG
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs" / "phase1"
OUT.mkdir(parents=True, exist_ok=True)

CENSO_ZIP = RAW / "censo" / "resageburb_31csv20.zip"
MARCO_ZIP = RAW / "marco_geo" / "31_yucatan.zip"
DENUE_DIR = RAW / "denue"                      # cualquier denue*.zip de Yucatan
DELITOS_CSV = RAW / "delitos" / "Municipal-Delitos-2015-2025_ene2026.csv"

ENT, MUN, LOC = "31", "050", "0001"            # Yucatan, Merida, localidad Merida
CRS_METRIC = "EPSG:6372"                       # Mexico ITRF2008 / LCC (metros)
CRS_STORE = "EPSG:4326"

report = []                                    # lineas del reporte


def log(msg=""):
    print(msg)
    report.append(str(msg))


def section(title):
    log("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


# ---------------------------------------------------------------- 1. CENSO
section("1. CENSO 2020 - Principales resultados por AGEB y manzana urbana")
with zipfile.ZipFile(CENSO_ZIP) as z:
    name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
    censo = pd.read_csv(z.open(name), dtype=str, encoding="utf-8")
log(f"Archivo: {name} | filas={len(censo):,} | columnas={censo.shape[1]}")

# Nivel AGEB urbana de la localidad Merida (MZA == 000, AGEB != 0000)
c = censo[(censo.MUN == MUN) & (censo.LOC == LOC)
          & (censo.AGEB != "0000") & (censo.MZA == "000")].copy()
c["CVEGEO"] = c.ENTIDAD + c.MUN + c.LOC + c.AGEB
log(f"AGEB urbanas en Merida (31-050-0001): {len(c)}")
log(f"CVEGEO duplicados: {c.CVEGEO.duplicated().sum()}")

KPI_VARS = ["POBTOT", "POBFEM", "POBMAS", "P_12YMAS", "PEA", "PE_INAC",
            "POCUPADA", "PDESOCUP", "POB0_14", "POB15_64", "POB65_MAS",
            "P_60YMAS", "GRAPROES", "VIVTOT", "TVIVHAB", "VPH_INTER",
            "VPH_AUTOM", "PSINDER"]
prof = pd.DataFrame({
    "var": KPI_VARS,
    "n_asterisco": [(c[v] == "*").sum() for v in KPI_VARS],
    "n_ND": [(c[v] == "N/D").sum() for v in KPI_VARS],
})
for v in KPI_VARS:  # '*' = confidencial (<3), NO es cero -> NaN
    c[v] = pd.to_numeric(c[v].replace({"*": None, "N/D": None}), errors="coerce")
prof["min"] = [c[v].min() for v in KPI_VARS]
prof["mediana"] = [c[v].median() for v in KPI_VARS]
prof["max"] = [c[v].max() for v in KPI_VARS]
log(prof.to_string(index=False))
log(f"Poblacion total localidad (suma AGEB): {c.POBTOT.sum():,.0f}")
log(f"AGEB con POBTOT < 100 (tasas inestables): {(c.POBTOT < 100).sum()}")
log(f"AGEB con POBTOT = 0: {(c.POBTOT == 0).sum()}")
prof.to_csv(OUT / "censo_profile.csv", index=False)

# ---------------------------------------------------------------- 2. MARCO GEO
section("2. MARCO GEOESTADISTICO - poligonos AGEB urbana (31a) y municipios (31mun)")
ageb_all = gpd.read_file(f"zip://{MARCO_ZIP.as_posix()}!conjunto_de_datos/31a.shp")
mun_all = gpd.read_file(f"zip://{MARCO_ZIP.as_posix()}!conjunto_de_datos/31mun.shp")
log(f"CRS original AGEB: {ageb_all.crs.name if ageb_all.crs else 'SIN CRS'}")
log(f"Campos AGEB: {list(ageb_all.columns)}")
log(f"AGEB urbanas Yucatan: {len(ageb_all)} | municipios: {len(mun_all)}")

ageb = ageb_all[(ageb_all.CVE_MUN == MUN) & (ageb_all.CVE_LOC == LOC)].copy()
log(f"AGEB poligonos Merida (050-0001): {len(ageb)}")
log(f"Geometrias invalidas: {(~ageb.is_valid).sum()} | vacias: {ageb.is_empty.sum()}")
ageb["area_km2"] = ageb.to_crs(CRS_METRIC).area / 1e6
log(f"Area km2 -> min {ageb.area_km2.min():.3f} | mediana "
    f"{ageb.area_km2.median():.3f} | max {ageb.area_km2.max():.3f} | "
    f"total {ageb.area_km2.sum():.1f}")

# Prueba de integracion 1: censo <-> poligonos
set_c, set_p = set(c.CVEGEO), set(ageb.CVEGEO)
log("\n-- Integracion censo <-> poligonos (CVEGEO) --")
log(f"En ambos: {len(set_c & set_p)} | solo censo: {len(set_c - set_p)} | "
    f"solo poligonos: {len(set_p - set_c)}")
log(f"% de AGEB del censo con poligono: {100 * len(set_c & set_p) / len(set_c):.1f}%")
pob_sin_pol = c.loc[c.CVEGEO.isin(set_c - set_p), "POBTOT"].sum()
log(f"Poblacion en AGEB del censo SIN poligono: {pob_sin_pol:,.0f}")
pd.DataFrame({"CVEGEO": sorted(set_c ^ set_p)}).assign(
    origen=lambda d: d.CVEGEO.map(lambda k: "solo_censo" if k in set_c else "solo_poligono")
).to_csv(OUT / "cvegeo_no_match.csv", index=False)

# ---------------------------------------------------------------- 3. DENUE
section("3. DENUE - establecimientos Yucatan")
denue_zip = sorted(DENUE_DIR.glob("*.zip"))[0]
with zipfile.ZipFile(denue_zip) as z:
    csvs = [n for n in z.namelist() if n.lower().endswith(".csv")
            and "diccionario" not in n.lower()]
    dname = max(csvs, key=lambda n: z.getinfo(n).file_size)
    try:
        denue = pd.read_csv(z.open(dname), dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        denue = pd.read_csv(z.open(dname), dtype=str, encoding="latin-1")
denue.columns = denue.columns.str.strip().str.lower()
log(f"Archivo: {denue_zip.name}!{dname} | filas={len(denue):,}")
log(f"Columnas: {list(denue.columns)}")

denue["cve_mun"] = denue.cve_mun.str.zfill(3)
d = denue[denue.cve_mun == MUN].copy()
log(f"Establecimientos municipio Merida: {len(d):,}")
log(f"id duplicados: {d.id.duplicated().sum()}")
d["latitud"] = pd.to_numeric(d.latitud, errors="coerce")
d["longitud"] = pd.to_numeric(d.longitud, errors="coerce")
log(f"Sin coordenadas: {d[['latitud', 'longitud']].isna().any(axis=1).sum()}")
log(f"Rango lat {d.latitud.min():.4f}..{d.latitud.max():.4f} | "
    f"lon {d.longitud.min():.4f}..{d.longitud.max():.4f}")
d["sector2"] = d.codigo_act.str[:2]
log("Top sectores SCIAN (2 digitos):")
log(d.sector2.value_counts().head(10).to_string())
log("Tamano (per_ocu):")
log(d.per_ocu.value_counts().to_string())

# Clasificacion para los KPIs (Retail Density / Service Density).
#   comercio_minorista : SCIAN 46        -> Retail Density
#   servicios          : SCIAN 51 a 81   -> Service Density
#   El resto se conserva para "Dominant Economic Activity".
SECTOR_GRUPO = {
    "11": "primario", "21": "industria", "22": "industria", "23": "industria",
    "31": "industria", "32": "industria", "33": "industria",
    "43": "comercio_mayorista", "46": "comercio_minorista",
    "48": "transporte", "49": "transporte", "93": "gobierno",
}
SECTOR_GRUPO.update({s: "servicios" for s in
                     ["51", "52", "53", "54", "55", "56", "61", "62", "71", "72", "81"]})
d["grupo_kpi"] = d.sector2.map(SECTOR_GRUPO).fillna("sin_clasificar")
log("\nGrupos para KPIs (comercio = SCIAN 46, servicios = SCIAN 51-81):")
g = d.grupo_kpi.value_counts().to_frame("n")
g["pct"] = (100 * g.n / g.n.sum()).round(1)
log(g.to_string())
log(f"Sin clasificar (revisar codigos): {(d.grupo_kpi == 'sin_clasificar').sum()}")

# Prueba de integracion 2: puntos -> poligonos
pts = gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d.longitud, d.latitud),
                       crs=CRS_STORE).to_crs(ageb.crs)
j = gpd.sjoin(pts, ageb[["CVEGEO", "geometry"]], how="left", predicate="within")
log("\n-- Integracion DENUE -> AGEB (point-in-polygon) --")
log(f"Puntos del municipio dentro de alguna AGEB de la localidad: "
    f"{j.CVEGEO.notna().sum():,} de {len(j):,} ({100 * j.CVEGEO.notna().mean():.1f}%)")
log("(los que quedan fuera son de comisarias/localidades rurales: esperado)")
# Validacion cruzada: DENUE trae su propia clave de AGEB
if "ageb" in j.columns and "cve_loc" in j.columns:
    j["cvegeo_denue"] = ENT + MUN + j.cve_loc.str.zfill(4) + j.ageb.str.zfill(4)
    m = j[j.CVEGEO.notna()]
    log(f"Coincidencia sjoin vs clave AGEB reportada por DENUE: "
        f"{100 * (m.CVEGEO == m.cvegeo_denue).mean():.1f}%")

# Vista previa de KPIs economicos por AGEB (el calculo oficial sera en PostGIS)
m = j[j.CVEGEO.notna()]
kpi = (m.groupby("CVEGEO").agg(
          negocios=("id", "size"),
          comercio=("grupo_kpi", lambda s: (s == "comercio_minorista").sum()),
          servicios=("grupo_kpi", lambda s: (s == "servicios").sum()),
          sector_dominante=("sector2", lambda s: s.value_counts().idxmax()))
       .reindex(ageb.CVEGEO).fillna({"negocios": 0, "comercio": 0, "servicios": 0}))
kpi = kpi.join(ageb.set_index("CVEGEO").area_km2)
kpi = kpi.join(c.set_index("CVEGEO").POBTOT)
kpi["dens_negocios_km2"] = kpi.negocios / kpi.area_km2
kpi["dens_comercio_km2"] = kpi.comercio / kpi.area_km2
kpi["dens_servicios_km2"] = kpi.servicios / kpi.area_km2
kpi["negocios_x1000hab"] = (kpi.negocios / kpi.POBTOT * 1000).where(kpi.POBTOT >= 100)
kpi.to_csv(OUT / "denue_kpi_preview_by_ageb.csv")
log("\n-- Vista previa KPIs economicos por AGEB --")
log(f"AGEB sin ningun negocio: {(kpi.negocios == 0).sum()}")
log(f"AGEB nuevas (sin censo) con negocios: "
    f"{((kpi.POBTOT.isna()) & (kpi.negocios > 0)).sum()}")
log("Sector dominante (n de AGEB):")
log(kpi.sector_dominante.value_counts().head(8).to_string())
log(kpi[["dens_negocios_km2", "dens_comercio_km2", "dens_servicios_km2",
         "negocios_x1000hab"]].describe().round(1).to_string())

fig, ax = plt.subplots(figsize=(8, 8))
ageb.to_crs(CRS_STORE).plot(ax=ax, facecolor="none", edgecolor="grey", linewidth=0.3)
j[j.CVEGEO.notna()].to_crs(CRS_STORE).plot(ax=ax, markersize=0.2, color="crimson")
ax.set_title("DENUE asignado a AGEB urbanas - Merida")
ax.set_axis_off()
fig.savefig(OUT / "denue_points_on_ageb.png", dpi=200, bbox_inches="tight")

# ---------------------------------------------------------------- 4. DELITOS
section("4. DELITOS - SESNSP incidencia municipal (sin coordenadas)")
dl = pd.read_csv(DELITOS_CSV, encoding="latin-1", dtype={"Cve. Municipio": str})
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
dl = dl[dl.Clave_Ent.astype(str) == "31"].copy()
dl["CVEGEO"] = dl["Cve. Municipio"].str.zfill(5)
for mth in MESES:
    dl[mth] = pd.to_numeric(dl[mth], errors="coerce")
log(f"Filas Yucatan: {len(dl):,} | anios {dl['Año'].min()}-{dl['Año'].max()}")
log(f"Municipios en delitos: {dl.CVEGEO.nunique()} | tipos: "
    f"{dl['Tipo de delito'].nunique()} | subtipos: {dl['Subtipo de delito'].nunique()}")
log(f"Celdas mensuales vacias (meses aun no publicados o nulos): "
    f"{int(dl[MESES].isna().sum().sum())}")
dl["total"] = dl[MESES].sum(axis=1, min_count=1)
log("Incidentes por anio (Yucatan):")
log(dl.groupby("Año").total.sum().to_string())

set_d, set_m = set(dl.CVEGEO), set(mun_all.CVEGEO)
log("\n-- Integracion delitos <-> poligonos municipales --")
log(f"En ambos: {len(set_d & set_m)} | solo delitos: {sorted(set_d - set_m)} | "
    f"solo poligonos: {sorted(set_m - set_d)}")

(OUT / "phase1_report.txt").write_text("\n".join(report), encoding="utf-8")
print(f"\nReporte guardado en {OUT / 'phase1_report.txt'}")
