"""
Fase 3 - Spatial analytics (Merida Urban Intelligence)

Todo se lee del Data Warehouse (vistas dw.v_kpi_ageb, dw.v_kpi_municipio,
dw.v_delitos_tipo_tiempo), nunca de los archivos crudos.

  1. Distribucion geografica  -> outputs/maps/01-03
  2. Correlaciones (Spearman) -> outputs/tables/correlaciones.csv, outputs/figures/
  3. Moran's I global         -> outputs/tables/moran_global.csv
  4. LISA (Local Moran)       -> outputs/maps/04-05, outputs/tables/lisa_*.csv
  5. Moran bivariado          -> outputs/tables/moran_bivariado.csv, outputs/maps/06

Dos escalas (ver README):
  - AGEB urbanas de la localidad Merida: demografia + economia
  - 106 municipios de Yucatan: seguridad publica (el SESNSP no tiene coordenadas)

Regla de vecindad: contiguidad Queen (comparten borde o vertice), pesos
estandarizados por fila. Unidades sin vecinos (islas) se conectan a su vecino
mas cercano (KNN k=1).

Uso:  python src/phase3_spatial_analysis.py
"""
import os
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from esda import Moran, Moran_BV, Moran_Local, Moran_Local_BV, Moran_Rate
from esda.smoothing import Empirical_Bayes
from libpysal.weights import KNN, Queen, w_union
from matplotlib.patches import Patch
from scipy.stats import pearsonr, spearmanr
from sqlalchemy import create_engine

warnings.filterwarnings("ignore")
np.random.seed(12345)            # permutaciones reproducibles

ROOT = Path(__file__).resolve().parents[1]
MAPS, FIGS, TABS = (ROOT / "outputs" / d for d in ("maps", "figures", "tables"))
for d in (MAPS, FIGS, TABS):
    d.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("DATABASE_URL",
                   "postgresql+psycopg2://merida:merida123@localhost:5433/merida_dw")
PERM = 999
ALPHA = 0.05
MIN_POB = 100                    # mismo umbral que en las vistas
summary = []

SUBSECTORES = {
    "461": "Abarrotes y alimentos (menudeo)", "462": "Autoservicio y departamentales",
    "463": "Textiles, ropa y calzado", "464": "Articulos para la salud",
    "465": "Papeleria y art. personales", "466": "Muebles y enseres",
    "467": "Ferreteria y tlapaleria", "468": "Vehiculos y refacciones",
    "722": "Preparacion de alimentos y bebidas", "811": "Reparacion y mantenimiento",
    "812": "Servicios personales", "621": "Servicios medicos ambulatorios",
    "541": "Servicios profesionales", "531": "Servicios inmobiliarios",
    "611": "Servicios educativos", "813": "Asociaciones y organizaciones",
    "311": "Industria alimentaria", "431": "Mayoreo de alimentos",
    "931": "Gobierno",
}


def log(msg=""):
    print(msg)
    summary.append(str(msg))


def section(t):
    log("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


# ---------------------------------------------------------------- DATOS DESDE EL DW
engine = create_engine(DB_URL)
ageb_all = gpd.read_postgis("SELECT * FROM dw.v_kpi_ageb", engine, geom_col="geom")
mun = gpd.read_postgis("SELECT * FROM dw.v_kpi_municipio ORDER BY cvegeo",
                       engine, geom_col="geom")
del_tt = pd.read_sql("SELECT * FROM dw.v_delitos_tipo_tiempo", engine)

for df in (ageb_all, mun):
    for c in df.columns:
        if c not in ("geom", "cvegeo", "nom_mun", "subsector_dominante", "tiene_censo"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

section("0. Conjuntos de analisis")
# AGEB: con censo y poblacion suficiente para tasas estables
ageb = ageb_all[ageb_all.tiene_censo & (ageb_all.pobtot >= MIN_POB)].copy()
ageb["log_dens_pob"] = np.log1p(ageb.densidad_pob_km2)
ageb["log_dens_neg"] = np.log1p(ageb.dens_negocios_km2)
ageb["log_dens_com"] = np.log1p(ageb.dens_comercio_km2)
ageb["log_dens_serv"] = np.log1p(ageb.dens_servicios_km2)
ageb["log_neg_x1000"] = np.log1p(ageb.negocios_x1000hab)
AGEB_VARS = ["log_dens_pob", "log_dens_neg", "log_dens_com", "log_dens_serv",
             "log_neg_x1000", "tasa_pea_pct", "pct_65_mas", "graproes"]
n0 = len(ageb)
ageb = ageb.dropna(subset=AGEB_VARS).reset_index(drop=True)
log(f"AGEB en la vista: {len(ageb_all)} | con censo y pobtot >= {MIN_POB}: {n0} "
    f"| sin nulos en variables: {len(ageb)}")

# Municipios: tasa de delitos suavizada por Empirical Bayes (numeros pequenos)
mun = mun[mun.pobtot > 0].reset_index(drop=True)
eb = Empirical_Bayes(mun.delitos_prom_anual.values.reshape(-1, 1),
                     mun.pobtot.values.reshape(-1, 1))
mun["tasa_delitos_eb"] = eb.r.flatten() * 1000
mun["log_dens_neg"] = np.log1p(mun.dens_negocios_km2)
mun["log_dens_pob"] = np.log1p(mun.densidad_pob_km2)
log(f"Municipios: {len(mun)} | tasa cruda x1000: media {mun.tasa_delitos_x1000hab.mean():.2f}, "
    f"max {mun.tasa_delitos_x1000hab.max():.2f} | tasa EB x1000: media "
    f"{mun.tasa_delitos_eb.mean():.2f}, max {mun.tasa_delitos_eb.max():.2f}")


def build_weights(gdf, label):
    w = Queen.from_dataframe(gdf, use_index=False, silence_warnings=True)
    n_isl = len(w.islands)
    if n_isl:
        w = w_union(w, KNN.from_dataframe(gdf, k=1, use_index=False))
    w.transform = "r"
    card = pd.Series(w.cardinalities)
    log(f"Pesos {label}: Queen, n={w.n}, islas conectadas por KNN(1)={n_isl}, "
        f"vecinos por unidad: media {card.mean():.1f}, min {card.min()}, max {card.max()}")
    return w


w_ageb = build_weights(ageb, "AGEB")
w_mun = build_weights(mun, "municipio")


# ---------------------------------------------------------------- 1. MAPAS
section("1. Distribucion geografica (mapas en outputs/maps)")


def choropleth(ax, gdf, col, title, scheme="Quantiles", k=5, cmap="YlOrRd", fmt="{:.0f}"):
    base = gdf.to_crs(6372)
    base.plot(ax=ax, color="#eeeeee", edgecolor="white", linewidth=0.1)
    base.dropna(subset=[col]).plot(
        ax=ax, column=col, scheme=scheme, k=k, cmap=cmap, edgecolor="white",
        linewidth=0.1, legend=True,
        legend_kwds={"loc": "lower left", "fontsize": 7, "fmt": fmt, "title_fontsize": 7})
    ax.set_title(title, fontsize=10)
    ax.set_axis_off()


fig, axs = plt.subplots(2, 2, figsize=(13, 13))
choropleth(axs[0, 0], ageb_all, "densidad_pob_km2", "Densidad de poblacion (hab/km2)")
choropleth(axs[0, 1], ageb_all, "tasa_pea_pct", "Tasa de PEA (% de 12+)", cmap="Blues", fmt="{:.1f}")
choropleth(axs[1, 0], ageb_all, "pct_65_mas", "Poblacion de 65+ (%)", cmap="Purples", fmt="{:.1f}")
choropleth(axs[1, 1], ageb_all, "graproes", "Grado promedio de escolaridad", cmap="Greens", fmt="{:.1f}")
fig.suptitle("Merida (localidad 31-050-0001) - indicadores demograficos por AGEB, Censo 2020\n"
             "Clases por quintiles; gris = sin dato (AGEB sin censo o confidencial)", fontsize=12)
fig.tight_layout()
fig.savefig(MAPS / "01_ageb_demografia.png", dpi=180)
plt.close(fig)

fig, axs = plt.subplots(2, 2, figsize=(13, 13))
choropleth(axs[0, 0], ageb_all, "dens_negocios_km2", "Densidad de negocios (por km2)")
choropleth(axs[0, 1], ageb_all, "dens_comercio_km2", "Densidad de comercio al por menor (SCIAN 46)", cmap="OrRd")
choropleth(axs[1, 0], ageb_all, "dens_servicios_km2", "Densidad de servicios (SCIAN 51-81)", cmap="PuBu")
dom = ageb_all.copy()
top = dom.subsector_dominante.value_counts().head(6).index
dom["dominante"] = np.where(dom.subsector_dominante.isin(top),
                            dom.subsector_dominante.map(lambda s: f"{s} {SUBSECTORES.get(s, '')}"),
                            "Otro / sin negocios")
dom.to_crs(6372).plot(ax=axs[1, 1], column="dominante", categorical=True, cmap="tab10",
                      edgecolor="white", linewidth=0.1, legend=True,
                      legend_kwds={"loc": "lower left", "fontsize": 7})
axs[1, 1].set_title("Subsector SCIAN dominante", fontsize=10)
axs[1, 1].set_axis_off()
fig.suptitle("Merida - actividad economica por AGEB, DENUE 05/2026 (quintiles)", fontsize=12)
fig.tight_layout()
fig.savefig(MAPS / "02_ageb_economia.png", dpi=180)
plt.close(fig)

fig, axs = plt.subplots(2, 2, figsize=(13, 11))
choropleth(axs[0, 0], mun, "tasa_delitos_x1000hab", "Tasa de delitos cruda (x1000 hab/anio)", cmap="Reds", fmt="{:.2f}")
choropleth(axs[0, 1], mun, "tasa_delitos_eb", "Tasa de delitos suavizada EB (x1000 hab/anio)", cmap="Reds", fmt="{:.2f}")
choropleth(axs[1, 0], mun, "delitos_x100negocios", "Delitos por cada 100 negocios (anual)", cmap="RdPu", fmt="{:.1f}")
choropleth(axs[1, 1], mun, "dens_negocios_km2", "Densidad de negocios (por km2)", cmap="YlOrBr", fmt="{:.1f}")
for ax in axs.flat:
    mun[mun.cvegeo == "31050"].to_crs(6372).boundary.plot(ax=ax, color="black", linewidth=1.2)
fig.suptitle("Yucatan - seguridad publica y actividad economica por municipio\n"
             "Delitos SESNSP promedio 2023-2025; contorno negro = Merida", fontsize=12)
fig.tight_layout()
fig.savefig(MAPS / "03_municipio_seguridad.png", dpi=180)
plt.close(fig)
log("Mapas 01-03 guardados.")

# Delitos por tipo y tiempo
t = del_tt.copy()
t["fecha"] = pd.to_datetime(dict(year=t.anio, month=t.mes, day=1))
serie = t.assign(ambito=np.where(t.cvegeo == "31050", "Merida", "Resto de Yucatan")) \
         .groupby(["fecha", "ambito"]).incidentes.sum().unstack(fill_value=0)
rec = t[(t.anio >= 2023) & (t.cvegeo == "31050")]
top_tipos = rec.groupby("tipo_delito").incidentes.sum().nlargest(8).sort_values()
fig, axs = plt.subplots(1, 2, figsize=(15, 5))
serie.plot(ax=axs[0])
axs[0].set_title("Incidentes mensuales SESNSP, 2015-2025")
axs[0].set_ylabel("Carpetas de investigacion")
top_tipos.plot.barh(ax=axs[1], color="#c0392b")
axs[1].set_title("Merida: principales tipos de delito, 2023-2025")
fig.tight_layout()
fig.savefig(FIGS / "delitos_tipo_tiempo.png", dpi=160)
plt.close(fig)
mes_tab = rec.groupby("mes").incidentes.sum()
log(f"Merida 2023-2025: {rec.incidentes.sum():,} incidentes | mes con mas: "
    f"{int(mes_tab.idxmax())} | mes con menos: {int(mes_tab.idxmin())}")
log("Top tipos Merida 2023-2025:\n" + top_tipos.sort_values(ascending=False).to_string())


# ---------------------------------------------------------------- 2. CORRELACIONES
section("2. Correlaciones (Spearman; Pearson como referencia)")
PARES = [
    ("AGEB", ageb, "log_dens_pob", "log_dens_neg", "Densidad de poblacion vs densidad de negocios"),
    ("AGEB", ageb, "graproes", "log_dens_serv", "Escolaridad vs densidad de servicios"),
    ("AGEB", ageb, "pct_65_mas", "log_dens_com", "% 65+ vs densidad de comercio"),
    ("AGEB", ageb, "tasa_pea_pct", "log_neg_x1000", "Tasa PEA vs negocios por 1000 hab"),
    ("Municipio", mun, "log_dens_neg", "tasa_delitos_eb", "Densidad de negocios vs tasa de delitos (EB)"),
    ("Municipio", mun, "log_dens_pob", "tasa_delitos_eb", "Densidad de poblacion vs tasa de delitos (EB)"),
    ("Municipio", mun, "negocios_x1000hab", "tasa_delitos_eb", "Negocios por 1000 hab vs tasa de delitos (EB)"),
]
rows = []
for esc, df, x, y, lab in PARES:
    d = df[[x, y]].dropna()
    rs, ps = spearmanr(d[x], d[y])
    rp, pp = pearsonr(d[x], d[y])
    rows.append(dict(escala=esc, relacion=lab, x=x, y=y, n=len(d),
                     spearman_rho=round(rs, 3), spearman_p=ps,
                     pearson_r=round(rp, 3), pearson_p=pp))
corr = pd.DataFrame(rows)
corr.to_csv(TABS / "correlaciones.csv", index=False)
log(corr[["escala", "relacion", "n", "spearman_rho", "spearman_p", "pearson_r"]]
    .to_string(index=False, formatters={"spearman_p": "{:.2e}".format}))

fig, axs = plt.subplots(2, 4, figsize=(18, 8))
for ax, (esc, df, x, y, lab) in zip(axs.flat, PARES):
    ax.scatter(df[x], df[y], s=8, alpha=0.5, color="#2E86AB")
    r = corr[(corr.x == x) & (corr.y == y)].iloc[0]
    ax.set_title(f"{lab}\n({esc}) rho={r.spearman_rho:.2f}, p={r.spearman_p:.1e}", fontsize=8)
    ax.set_xlabel(x, fontsize=8)
    ax.set_ylabel(y, fontsize=8)
axs.flat[-1].set_axis_off()
fig.tight_layout()
fig.savefig(FIGS / "correlaciones.png", dpi=160)
plt.close(fig)


# ---------------------------------------------------------------- 3. MORAN GLOBAL
section(f"3. Moran's I global ({PERM} permutaciones)")
rows = []
for v in ["log_dens_pob", "log_dens_neg", "log_dens_com", "log_dens_serv",
          "tasa_pea_pct", "pct_65_mas", "graproes"]:
    m = Moran(ageb[v].values, w_ageb, permutations=PERM)
    rows.append(dict(escala="AGEB", variable=v, I=m.I, EI=m.EI, z=m.z_sim, p_sim=m.p_sim))
m = Moran(mun.log_dens_neg.values, w_mun, permutations=PERM)
rows.append(dict(escala="Municipio", variable="log_dens_neg", I=m.I, EI=m.EI, z=m.z_sim, p_sim=m.p_sim))
m = Moran(mun.tasa_delitos_eb.values, w_mun, permutations=PERM)
rows.append(dict(escala="Municipio", variable="tasa_delitos_eb", I=m.I, EI=m.EI, z=m.z_sim, p_sim=m.p_sim))
# Moran para tasas estandarizado EB (Assuncao-Reis): corrige varianza desigual
mr = Moran_Rate(mun.delitos_prom_anual.values, mun.pobtot.values, w_mun, permutations=PERM)
rows.append(dict(escala="Municipio", variable="tasa_delitos (Moran_Rate EB)", I=mr.I, EI=mr.EI,
                 z=mr.z_sim, p_sim=mr.p_sim))
mg = pd.DataFrame(rows)
mg["interpretacion"] = np.where(mg.p_sim >= ALPHA, "No significativo (patron compatible con aleatoriedad)",
                        np.where(mg.z > 0, "Agrupamiento: valores similares son vecinos",
                                 "Dispersion: valores distintos son vecinos"))
mg.to_csv(TABS / "moran_global.csv", index=False)
log(mg.round(4).to_string(index=False))


# ---------------------------------------------------------------- 4. LISA
section(f"4. LISA - Local Moran (p < {ALPHA})")
LISA_COLORS = {"HH": "#d7191c", "LL": "#2c7bb6", "LH": "#abd9e9", "HL": "#fdae61",
               "No significativo": "#e8e8e8"}


def lisa_labels(lm):
    q = pd.Series(lm.q).map({1: "HH", 2: "LH", 3: "LL", 4: "HL"})
    return q.where(lm.p_sim < ALPHA, "No significativo").values


def lisa_map(ax, gdf, labels, title):
    g = gdf.assign(cluster=labels).to_crs(6372)
    for k, col in LISA_COLORS.items():
        sub = g[g.cluster == k]
        if len(sub):
            sub.plot(ax=ax, color=col, edgecolor="white", linewidth=0.15)
    counts = g.cluster.value_counts()
    ax.legend(handles=[Patch(color=c, label=f"{k} ({counts.get(k, 0)})")
                       for k, c in LISA_COLORS.items()], loc="lower left", fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_axis_off()


lisa_out = []
fig, axs = plt.subplots(1, 2, figsize=(15, 8))
for ax, (v, lab) in zip(axs, [("log_dens_neg", "Densidad de negocios"),
                              ("log_dens_pob", "Densidad de poblacion")]):
    lm = Moran_Local(ageb[v].values, w_ageb, permutations=PERM, seed=12345)
    lab_v = lisa_labels(lm)
    lisa_map(ax, ageb, lab_v, f"LISA AGEB - {lab}")
    lisa_out.append(pd.DataFrame({"escala": "AGEB", "variable": v, "cvegeo": ageb.cvegeo,
                                  "Ii": lm.Is, "p_sim": lm.p_sim, "cluster": lab_v}))
    log(f"AGEB {v}: " + pd.Series(lab_v).value_counts().to_dict().__str__())
fig.suptitle("Clusters y valores atipicos espaciales, AGEB de Merida (Queen, 999 perm.)")
fig.tight_layout()
fig.savefig(MAPS / "04_lisa_ageb.png", dpi=180)
plt.close(fig)

fig, axs = plt.subplots(1, 2, figsize=(15, 7))
lm = Moran_Local(mun.tasa_delitos_eb.values, w_mun, permutations=PERM, seed=12345)
lab_v = lisa_labels(lm)
lisa_map(axs[0], mun, lab_v, "LISA municipios - tasa de delitos (EB)")
lisa_out.append(pd.DataFrame({"escala": "Municipio", "variable": "tasa_delitos_eb",
                              "cvegeo": mun.cvegeo, "nombre": mun.nom_mun,
                              "Ii": lm.Is, "p_sim": lm.p_sim, "cluster": lab_v}))
log("Municipio tasa_delitos_eb: " + str(pd.Series(lab_v).value_counts().to_dict()))
hh = mun.loc[lab_v == "HH", "nom_mun"].tolist()
log(f"  Municipios HH (alta tasa rodeados de alta tasa): {hh}")

# LISA bivariado municipio: densidad de negocios (focal) vs rezago de tasa de delitos
lbv = Moran_Local_BV(mun.log_dens_neg.values, mun.tasa_delitos_eb.values, w_mun,
                     permutations=PERM, seed=12345)
lab_b = lisa_labels(lbv)
lisa_map(axs[1], mun, lab_b, "LISA bivariado: densidad de negocios (x)\nvs tasa de delitos EB de los vecinos (Wy)")
lisa_out.append(pd.DataFrame({"escala": "Municipio", "variable": "BV log_dens_neg~W tasa_delitos_eb",
                              "cvegeo": mun.cvegeo, "nombre": mun.nom_mun,
                              "Ii": lbv.Is, "p_sim": lbv.p_sim, "cluster": lab_b}))
for ax in axs:
    mun[mun.cvegeo == "31050"].to_crs(6372).boundary.plot(ax=ax, color="black", linewidth=1.2)
fig.tight_layout()
fig.savefig(MAPS / "05_lisa_municipio.png", dpi=180)
plt.close(fig)
pd.concat(lisa_out).to_csv(TABS / "lisa_resultados.csv", index=False)


# ---------------------------------------------------------------- 5. MORAN BIVARIADO
section("5. Moran bivariado global (x focal, y rezagada espacialmente)")
BV = [
    ("AGEB", ageb, w_ageb, "log_dens_pob", "log_dens_neg"),
    ("AGEB", ageb, w_ageb, "graproes", "log_dens_serv"),
    ("Municipio", mun, w_mun, "log_dens_neg", "tasa_delitos_eb"),
    ("Municipio", mun, w_mun, "log_dens_pob", "tasa_delitos_eb"),
]
rows = []
for esc, df, w, x, y in BV:
    b = Moran_BV(df[x].values, df[y].values, w, permutations=PERM)
    rows.append(dict(escala=esc, x=x, y_rezagada=y, I_bv=b.I, z=b.z_sim, p_sim=b.p_sim))
bv = pd.DataFrame(rows)
bv.to_csv(TABS / "moran_bivariado.csv", index=False)
log(bv.round(4).to_string(index=False))

lbv = Moran_Local_BV(ageb.log_dens_pob.values, ageb.log_dens_neg.values, w_ageb,
                     permutations=PERM, seed=12345)
fig, ax = plt.subplots(figsize=(9, 9))
lab_b = lisa_labels(lbv)
lisa_map(ax, ageb, lab_b, "LISA bivariado AGEB: densidad de poblacion (x)\n"
                          "vs densidad de negocios de las AGEB vecinas (Wy)")
fig.tight_layout()
fig.savefig(MAPS / "06_lisa_bivariado_ageb.png", dpi=180)
plt.close(fig)
log("AGEB BV pob~W negocios: " + str(pd.Series(lab_b).value_counts().to_dict()))

(ROOT / "outputs" / "phase3_summary.txt").write_text("\n".join(summary), encoding="utf-8")
print(f"\nResumen: {ROOT / 'outputs' / 'phase3_summary.txt'}")
