"""
Report figures - Merida Urban Intelligence

Generates the complete, English, report-ready figure set from the Data Warehouse
(dw.v_kpi_ageb, dw.v_kpi_municipio, dw.v_delitos_tipo_tiempo, dw.fact_establecimiento)
and from the Phase 3 tables (outputs/tables/*.csv).

New with respect to phase3_spatial_analysis.py:
  - Spearman correlation matrices (AGEB and municipality)
  - Moran scatterplots (univariate and bivariate), the slope of each line is Moran's I
  - Global Moran's I bar chart
  - Point-in-polygon evidence map (DENUE points on AGEB polygons)

Run AFTER src/etl.py and src/phase3_spatial_analysis.py:
    python src/report_figures.py
Output: outputs/report_figures/*.png  (+ outputs/tables/corr_matrix_*.csv)
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
from esda import Moran, Moran_BV, Moran_Local, Moran_Local_BV
from esda.smoothing import Empirical_Bayes
from libpysal.weights import KNN, Queen, w_union
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy.stats import spearmanr
from sqlalchemy import create_engine

warnings.filterwarnings("ignore")
np.random.seed(12345)

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "outputs" / "report_figures"
TAB = ROOT / "outputs" / "tables"
FIG.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)
DB_URL = os.getenv("DATABASE_URL",
                   "postgresql+psycopg2://merida:merida123@localhost:5433/merida_dw")
MIN_POB, PERM, ALPHA = 100, 999, 0.05

# ---------------------------------------------------------------- STYLE
INK, INK2, MUTED, GRID, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, RED, GRAY_MID = "#2a78d6", "#eb6834", "#e34948", "#f0efec"
BLUES = LinearSegmentedColormap.from_list("blues", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
ORANGES = LinearSegmentedColormap.from_list("oranges", ["#fde4d6", "#f7a77f", "#eb6834", "#b8461b", "#7a2a0b"])
DIVERGING = LinearSegmentedColormap.from_list("div", ["#1c5cab", "#86b6ef", GRAY_MID, "#f09a99", "#b42d2d"])
LISA_COLORS = {"HH": "#d7191c", "LL": "#2c7bb6", "LH": "#abd9e9", "HL": "#fdae61",
               "Not significant": "#e8e8e8"}
LISA_NAMES = {"HH": "High-High", "LL": "Low-Low", "LH": "Low-High", "HL": "High-Low",
              "Not significant": "Not significant"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10.5, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.edgecolor": BASE, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": False,
    "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 100,
    "savefig.dpi": 220, "savefig.bbox": "tight", "savefig.facecolor": "white",
})

SUBSECTORS = {
    "461": "461 Grocery & food retail", "462": "462 Supermarkets & dept. stores",
    "463": "463 Textiles & clothing retail", "464": "464 Health products retail",
    "465": "465 Stationery & personal items", "466": "466 Furniture & appliances",
    "467": "467 Hardware retail", "468": "468 Vehicles & parts",
    "722": "722 Food & beverage services", "811": "811 Repair & maintenance",
    "812": "812 Personal services", "621": "621 Ambulatory health care",
    "541": "541 Professional services", "531": "531 Real estate",
    "611": "611 Education", "813": "813 Associations", "311": "311 Food manufacturing",
    "431": "431 Food wholesale", "931": "931 Government",
}


def save(fig, name):
    fig.savefig(FIG / name)
    plt.close(fig)
    print(f"  saved {name}")


# ---------------------------------------------------------------- DATA (same rules as Phase 3)
print("Loading data from the warehouse ...")
engine = create_engine(DB_URL)
ageb_all = gpd.read_postgis("SELECT * FROM dw.v_kpi_ageb", engine, geom_col="geom")
mun = gpd.read_postgis("SELECT * FROM dw.v_kpi_municipio ORDER BY cvegeo", engine, geom_col="geom")
del_tt = pd.read_sql("SELECT * FROM dw.v_delitos_tipo_tiempo", engine)
for df in (ageb_all, mun):
    for c in df.columns:
        if c not in ("geom", "cvegeo", "nom_mun", "subsector_dominante", "tiene_censo"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

ageb = ageb_all[ageb_all.tiene_censo & (ageb_all.pobtot >= MIN_POB)].copy()
for src, dst in [("densidad_pob_km2", "log_dens_pob"), ("dens_negocios_km2", "log_dens_neg"),
                 ("dens_comercio_km2", "log_dens_com"), ("dens_servicios_km2", "log_dens_serv"),
                 ("negocios_x1000hab", "log_neg_x1000")]:
    ageb[dst] = np.log1p(ageb[src])
AGEB_VARS = ["log_dens_pob", "log_dens_neg", "log_dens_com", "log_dens_serv",
             "log_neg_x1000", "tasa_pea_pct", "pct_65_mas", "graproes"]
ageb = ageb.dropna(subset=AGEB_VARS).reset_index(drop=True)

mun = mun[mun.pobtot > 0].reset_index(drop=True)
eb = Empirical_Bayes(mun.delitos_prom_anual.values.reshape(-1, 1), mun.pobtot.values.reshape(-1, 1))
mun["tasa_delitos_eb"] = eb.r.flatten() * 1000
mun["log_dens_neg"] = np.log1p(mun.dens_negocios_km2)
mun["log_dens_pob"] = np.log1p(mun.densidad_pob_km2)


def weights(gdf):
    w = Queen.from_dataframe(gdf, use_index=False, silence_warnings=True)
    if w.islands:
        w = w_union(w, KNN.from_dataframe(gdf, k=1, use_index=False))
    w.transform = "r"
    return w


w_ageb, w_mun = weights(ageb), weights(mun)
AG = ageb_all.to_crs(6372)          # all 501 AGEB polygons, metric CRS for plotting
AGA = ageb.to_crs(6372)             # analysis set
MU = mun.to_crs(6372)
MERIDA = MU[MU.cvegeo == "31050"]


def choropleth(ax, gdf, col, title, cmap=BLUES, fmt="{:,.0f}", k=5):
    gdf.plot(ax=ax, color="#eeeeee", edgecolor="white", linewidth=0.1)
    gdf.dropna(subset=[col]).plot(
        ax=ax, column=col, scheme="Quantiles", k=k, cmap=cmap, edgecolor="white",
        linewidth=0.1, legend=True,
        legend_kwds={"loc": "lower left", "fontsize": 8.5, "fmt": fmt, "frameon": False})
    ax.set_title(title, loc="left")
    ax.set_axis_off()


def lisa_labels(lm):
    q = pd.Series(lm.q).map({1: "HH", 2: "LH", 3: "LL", 4: "HL"})
    return q.where(lm.p_sim < ALPHA, "Not significant").values


def lisa_map(ax, gdf, labels, title, outline=None):
    g = gdf.assign(cluster=labels)
    for k, col in LISA_COLORS.items():
        sub = g[g.cluster == k]
        if len(sub):
            sub.plot(ax=ax, color=col, edgecolor="white", linewidth=0.15)
    if outline is not None:
        outline.boundary.plot(ax=ax, color=INK, linewidth=1.1)
    counts = g.cluster.value_counts()
    ax.legend(handles=[Patch(color=c, label=f"{LISA_NAMES[k]} ({counts.get(k, 0)})")
                       for k, c in LISA_COLORS.items()], loc="lower left", fontsize=9, frameon=False)
    ax.set_title(title, loc="left")
    ax.set_axis_off()


print("Building figures ...")

# ---------------------------------------------------------------- 1. POINT-IN-POLYGON EVIDENCE
pts = gpd.read_postgis("""
    SELECT f.geom, (f.geo_ageb_key IS NOT NULL AND a.en_localidad_merida) AS in_city,
           (a.cvegeo = f.cvegeo_ageb_reportado) AS key_match
    FROM dw.fact_establecimiento f
    JOIN dw.dim_geografia m ON m.geo_key = f.geo_mun_key AND m.cvegeo = '31050'
    LEFT JOIN dw.dim_geografia a ON a.geo_key = f.geo_ageb_key""", engine, geom_col="geom").to_crs(6372)
pct_in = 100 * pts.in_city.mean()
pct_match = 100 * pts.loc[pts.key_match.notna(), "key_match"].astype(bool).mean()
fig, ax = plt.subplots(figsize=(7.5, 7.5))
AG.plot(ax=ax, facecolor="none", edgecolor=BASE, linewidth=0.3)
pts[pts.in_city].plot(ax=ax, markersize=0.15, color=BLUE, alpha=0.6)
pts[~pts.in_city].plot(ax=ax, markersize=1.5, color=ORANGE)
xmin, ymin, xmax, ymax = AG.total_bounds
ax.set_xlim(xmin - 2000, xmax + 2000)
ax.set_ylim(ymin - 2000, ymax + 2000)
ax.legend(handles=[Line2D([], [], marker="o", ls="", color=BLUE, label=f"Assigned to a city AGEB ({pct_in:.1f}%)"),
                   Line2D([], [], marker="o", ls="", color=ORANGE, label="Outside city AGEBs (rural localities)"),
                   Patch(facecolor="none", edgecolor=BASE, label="AGEB polygons (locality 31-050-0001)")],
          loc="lower left", fontsize=7.5, frameon=False)
ax.set_title(f"DENUE establishments joined to AGEB polygons with ST_Intersects\n"
             f"Agreement with the AGEB key reported by DENUE: {pct_match:.1f}%", loc="left")
ax.set_axis_off()
save(fig, "fig02_point_in_polygon.png")

# ---------------------------------------------------------------- 2. DISTRIBUTION MAPS
fig, axs = plt.subplots(2, 2, figsize=(11, 11))
choropleth(axs[0, 0], AG, "densidad_pob_km2", "Population density (residents per km²)")
choropleth(axs[0, 1], AG, "tasa_pea_pct", "Economically active population rate (% of 12+)", fmt="{:.1f}")
choropleth(axs[1, 0], AG, "pct_65_mas", "Population aged 65+ (%)", fmt="{:.1f}")
choropleth(axs[1, 1], AG, "graproes", "Average years of schooling", fmt="{:.1f}")
fig.tight_layout()
save(fig, "fig03_demographic_maps.png")

fig, axs = plt.subplots(2, 2, figsize=(11, 11))
choropleth(axs[0, 0], AG, "dens_negocios_km2", "Business density (establishments per km²)", cmap=ORANGES)
choropleth(axs[0, 1], AG, "dens_comercio_km2", "Retail density (SCIAN 46, per km²)", cmap=ORANGES)
choropleth(axs[1, 0], AG, "dens_servicios_km2", "Service density (SCIAN 51–81, per km²)", cmap=ORANGES)
dom = AG.copy()
top = dom.subsector_dominante.value_counts().head(6).index.tolist()
dom["dominant"] = np.where(dom.subsector_dominante.isin(top),
                           dom.subsector_dominante.map(lambda s: SUBSECTORS.get(s, s)), "Other / no businesses")
cat_colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
order = [SUBSECTORS.get(s, s) for s in top]
for lab, col in zip(order, cat_colors):
    dom[dom.dominant == lab].plot(ax=axs[1, 1], color=col, edgecolor="white", linewidth=0.1)
dom[dom.dominant == "Other / no businesses"].plot(ax=axs[1, 1], color="#d6d5cf", edgecolor="white", linewidth=0.1)
axs[1, 1].legend(handles=[Patch(color=c, label=l) for l, c in zip(order, cat_colors)]
                 + [Patch(color="#d6d5cf", label="Other / no businesses")],
                 loc="lower left", fontsize=7, frameon=False)
axs[1, 1].set_title("Dominant economic activity (SCIAN subsector)", loc="left")
axs[1, 1].set_axis_off()
fig.tight_layout()
save(fig, "fig04_economic_maps.png")

fig, axs = plt.subplots(2, 2, figsize=(11, 8.6))
choropleth(axs[0, 0], MU, "tasa_delitos_x1000hab", "Crime rate, raw (incidents per 1,000 residents/yr)", cmap=ORANGES, fmt="{:.2f}")
choropleth(axs[0, 1], MU, "tasa_delitos_eb", "Crime rate, Empirical Bayes smoothed", cmap=ORANGES, fmt="{:.2f}")
choropleth(axs[1, 0], MU, "delitos_x100negocios", "Crime relative to business activity (per 100 businesses)", cmap=ORANGES, fmt="{:.1f}")
choropleth(axs[1, 1], MU, "dens_negocios_km2", "Business density (establishments per km²)", cmap=BLUES, fmt="{:.1f}")
for ax in axs.flat:
    MERIDA.boundary.plot(ax=ax, color=INK, linewidth=1.1)
fig.tight_layout()
save(fig, "fig05_municipal_safety_maps.png")

fig, axs = plt.subplots(2, 2, figsize=(10, 10.4))
choropleth(axs[0, 0], AG, "densidad_pob_km2", "(a) Population density, AGEB (res./km²)")
choropleth(axs[0, 1], AG, "pct_65_mas", "(b) Population aged 65+, AGEB (%)", fmt="{:.1f}")
choropleth(axs[1, 0], AG, "dens_negocios_km2", "(c) Business density, AGEB (per km²)", cmap=ORANGES)
choropleth(axs[1, 1], MU, "tasa_delitos_eb", "(d) Crime rate EB, municipality (per 1,000/yr)", cmap=ORANGES, fmt="{:.2f}")
MERIDA.boundary.plot(ax=axs[1, 1], color=INK, linewidth=1.1)
fig.tight_layout()
save(fig, "fig_key_maps.png")

# ---------------------------------------------------------------- 3. CRIME BY TYPE AND TIME
t = del_tt.copy()
t["date"] = pd.to_datetime(dict(year=t.anio, month=t.mes, day=1))
series = (t.assign(area=np.where(t.cvegeo == "31050", "Mérida", "Rest of Yucatán"))
          .groupby(["date", "area"]).incidentes.sum().unstack(fill_value=0))
rec = t[(t.anio >= 2023) & (t.cvegeo == "31050")]
top_types = rec.groupby("tipo_delito").incidentes.sum().nlargest(8).sort_values()
by_month = rec.groupby("mes").incidentes.sum().reindex(range(1, 13), fill_value=0)
fig, axs = plt.subplots(1, 3, figsize=(15, 4.2), gridspec_kw={"width_ratios": [1.5, 1, 1]})
for (area, col) in [("Mérida", BLUE), ("Rest of Yucatán", ORANGE)]:
    if area in series:
        axs[0].plot(series.index, series[area], color=col, lw=1.6, label=area)
axs[0].set_title("Monthly incidents, 2015–2025", loc="left")
axs[0].set_ylabel("Investigation files per month")
axs[0].legend(frameon=False, fontsize=8)
axs[0].grid(axis="y", color=GRID, lw=0.6)
axs[1].barh(top_types.index, top_types.values, color=BLUE, height=0.6)
for i, v in enumerate(top_types.values):
    axs[1].text(v, i, f" {v:,.0f}", va="center", fontsize=7.5, color=INK2)
axs[1].set_title("Mérida: incidents by type, 2023–2025", loc="left")
axs[1].tick_params(axis="y", labelsize=7.5)
axs[2].bar(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"], by_month.values, color=BLUE, width=0.65)
axs[2].set_title("Mérida: incidents by month, 2023–2025", loc="left")
axs[2].grid(axis="y", color=GRID, lw=0.6)
fig.tight_layout()
save(fig, "fig06_crime_type_time.png")

# ---------------------------------------------------------------- 4. CORRELATION MATRICES
AGEB_LABELS = {
    "log_dens_pob": "Population density (log)", "log_dens_neg": "Business density (log)",
    "log_dens_com": "Retail density (log)", "log_dens_serv": "Service density (log)",
    "log_neg_x1000": "Businesses per 1,000 (log)", "tasa_pea_pct": "Active population rate",
    "pct_0_14": "Aged 0–14 (%)", "pct_65_mas": "Aged 65+ (%)", "graproes": "Years of schooling",
}
MUN_LABELS = {
    "log_dens_pob": "Population density (log)", "log_dens_neg": "Business density (log)",
    "negocios_x1000hab": "Businesses per 1,000", "tasa_pea_pct": "Active population rate",
    "pct_65_mas": "Aged 65+ (%)", "tasa_delitos_eb": "Crime rate (EB)",
    "delitos_x100negocios": "Crimes per 100 businesses",
}


def spearman_matrix(df, labels):
    cols = list(labels)
    n = len(cols)
    rho, p = np.eye(n), np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = df[[cols[i], cols[j]]].dropna()
            r, pv = spearmanr(d.iloc[:, 0], d.iloc[:, 1])
            rho[i, j] = rho[j, i] = r
            p[i, j] = p[j, i] = pv
    names = [labels[c] for c in cols]
    return pd.DataFrame(rho, names, names), pd.DataFrame(p, names, names)


def heatmap(ax, rho, p, title):
    n = len(rho)
    mask = np.triu(np.ones((n, n), bool), k=1)
    data = np.ma.array(np.where(np.eye(n, dtype=bool), 0.0, rho.values), mask=mask)
    im = ax.imshow(data, cmap=DIVERGING, vmin=-1, vmax=1)
    for i in range(n):
        for j in range(n):
            if j <= i:
                v, pv = rho.values[i, j], p.values[i, j]
                star = "" if i == j else ("*" if pv < ALPHA else "")
                ax.text(j, i, "1" if i == j else f"{v:.2f}{star}", ha="center", va="center",
                        fontsize=9, color="white" if (abs(v) > 0.55 and i != j) else (MUTED if i == j else INK),
                        fontweight="bold" if (i != j and pv < ALPHA) else "normal")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(rho.columns, rotation=40, ha="right", fontsize=10)
    ax.set_yticklabels(rho.index, fontsize=10)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    ax.set_title(title, loc="left")
    return im


rho_a, p_a = spearman_matrix(ageb, AGEB_LABELS)
rho_m, p_m = spearman_matrix(mun, MUN_LABELS)
rho_a.round(3).to_csv(TAB / "corr_matrix_ageb_spearman.csv")
p_a.to_csv(TAB / "corr_matrix_ageb_pvalues.csv")
rho_m.round(3).to_csv(TAB / "corr_matrix_municipio_spearman.csv")
p_m.to_csv(TAB / "corr_matrix_municipio_pvalues.csv")
fig, axs = plt.subplots(1, 2, figsize=(15, 6.8), gridspec_kw={"width_ratios": [1.25, 1], "wspace": 0.55})
heatmap(axs[0], rho_a, p_a, f"(a) AGEB, n = {len(ageb)}")
im = heatmap(axs[1], rho_m, p_m, f"(b) Municipality, n = {len(mun)}")
cb = fig.colorbar(im, ax=axs, shrink=0.6, pad=0.02)
cb.set_label("Spearman ρ", color=INK2)
cb.outline.set_visible(False)
save(fig, "fig07_correlation_matrix.png")

# ---------------------------------------------------------------- 5. CORRELATION SCATTERPLOTS
PAIRS = [
    (ageb, "log_dens_pob", "log_dens_neg", "Population density vs business density", "AGEB"),
    (ageb, "pct_65_mas", "log_dens_com", "Aged 65+ vs retail density", "AGEB"),
    (ageb, "tasa_pea_pct", "log_neg_x1000", "Active population rate vs businesses per 1,000", "AGEB"),
    (ageb, "graproes", "log_dens_serv", "Schooling vs service density", "AGEB"),
    (mun, "log_dens_neg", "tasa_delitos_eb", "Business density vs crime rate (EB)", "Municipality"),
    (mun, "log_dens_pob", "tasa_delitos_eb", "Population density vs crime rate (EB)", "Municipality"),
]
ALL_LABELS = {**AGEB_LABELS, **MUN_LABELS}
fig, axs = plt.subplots(2, 3, figsize=(14, 8.5))
for ax, (df, x, y, title, scale) in zip(axs.flat, PAIRS):
    d = df[[x, y]].dropna()
    r, pv = spearmanr(d[x], d[y])
    ax.scatter(d[x], d[y], s=10, color=BLUE if scale == "AGEB" else ORANGE, alpha=0.55, linewidths=0)
    b = np.polyfit(d[x].rank(), d[y].rank(), 1)  # trend shown on original axes via lowess-free fit
    xs = np.linspace(d[x].min(), d[x].max(), 50)
    ax.plot(xs, np.polyval(np.polyfit(d[x], d[y], 1), xs), color=INK, lw=1.2)
    ax.set_title(f"{title}\n{scale}: ρ = {r:.2f}, p = {pv:.1e}", loc="left", fontsize=11)
    ax.set_xlabel(ALL_LABELS[x])
    ax.set_ylabel(ALL_LABELS[y])
    ax.grid(color=GRID, lw=0.5)
fig.tight_layout()
save(fig, "fig08_correlation_scatter.png")

# ---------------------------------------------------------------- 6. GLOBAL MORAN BAR CHART
mg_path = TAB / "moran_global.csv"
NICE = {"log_dens_pob": "Population density (log)", "log_dens_neg": "Business density (log)",
        "log_dens_com": "Retail density (log)", "log_dens_serv": "Service density (log)",
        "tasa_pea_pct": "Active population rate", "pct_65_mas": "Aged 65+ (%)",
        "graproes": "Years of schooling", "tasa_delitos_eb": "Crime rate (EB)",
        "tasa_delitos (Moran_Rate EB)": "Crime rate (EB-standardised Moran)"}
if mg_path.exists():
    mg = pd.read_csv(mg_path)
    mg["label"] = mg.apply(lambda r: f"{NICE.get(r.variable, r.variable)}", axis=1)
    mg = mg.sort_values(["escala", "I"], ascending=[True, True]).reset_index(drop=True)
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.2), gridspec_kw={"width_ratios": [7, 3]})
    for ax, (esc, col, name) in zip(axs, [("AGEB", BLUE, f"AGEB (n = {len(ageb)})"),
                                           ("Municipio", ORANGE, f"Municipality (n = {len(mun)})")]):
        s = mg[mg.escala == esc]
        ax.barh(s.label, s.I, color=col, height=0.6)
        for i, (v, pv) in enumerate(zip(s.I, s.p_sim)):
            ax.text(v, i, f" {v:.2f}  (p = {pv:.3f})", va="center", fontsize=8, color=INK2)
        ax.axvline(0, color=BASE, lw=0.8)
        ax.set_xlim(min(0, s.I.min()) - 0.05, max(1.0, s.I.max() + 0.35))
        ax.set_title(name, loc="left")
        ax.grid(axis="x", color=GRID, lw=0.5)
        ax.set_xlabel("Global Moran's I")
    fig.tight_layout()
    save(fig, "fig09_moran_global.png")
else:
    print("  (skip fig09: run phase3_spatial_analysis.py first to create outputs/tables/moran_global.csv)")

# ---------------------------------------------------------------- 7. MORAN SCATTERPLOTS
def moran_scatter(ax, x, w, title, y=None, color=BLUE, xlab="Standardised value (z)",
                  ylab="Spatial lag of z (mean of neighbours)"):
    zx = (x - x.mean()) / x.std()
    zy = zx if y is None else (y - y.mean()) / y.std()
    lag = w.sparse @ zy
    if y is None:
        m = Moran(x, w, permutations=PERM)
        lm = Moran_Local(x, w, permutations=PERM, seed=12345)
    else:
        m = Moran_BV(x, y, w, permutations=PERM)
        lm = Moran_Local_BV(x, y, w, permutations=PERM, seed=12345)
    labs = lisa_labels(lm)
    for k, c in LISA_COLORS.items():
        sel = labs == k
        ax.scatter(zx[sel], lag[sel], s=12, color=c if k != "Not significant" else "#bdbcb5",
                   alpha=0.8, linewidths=0, label=LISA_NAMES[k])
    xs = np.linspace(zx.min(), zx.max(), 50)
    slope = np.polyfit(zx, lag, 1)[0]
    ax.plot(xs, slope * xs, color=INK, lw=1.4)
    ax.axhline(0, color=BASE, lw=0.8)
    ax.axvline(0, color=BASE, lw=0.8)
    lim_x, lim_y = np.abs(zx).max() * 1.05, np.abs(lag).max() * 1.15
    for tx, ty, q in [(0.97, 0.97, "HH"), (0.03, 0.97, "LH"), (0.03, 0.03, "LL"), (0.97, 0.03, "HL")]:
        ax.text(tx, ty, q, transform=ax.transAxes, ha="right" if tx > 0.5 else "left",
                va="top" if ty > 0.5 else "bottom", fontsize=9, color=MUTED, fontweight="bold")
    ax.set_xlim(-lim_x, lim_x)
    ax.set_ylim(-lim_y, lim_y)
    ax.set_title(f"{title}\nI = {m.I:.3f}, p = {m.p_sim:.3f}", loc="left", fontsize=12)
    ax.set_xlabel(xlab, fontsize=10)
    ax.set_ylabel(ylab, fontsize=10)
    return m.I


fig, axs = plt.subplots(2, 3, figsize=(14, 9))
moran_scatter(axs[0, 0], ageb.pct_65_mas.values, w_ageb, "AGEB: aged 65+ (%)")
moran_scatter(axs[0, 1], ageb.graproes.values, w_ageb, "AGEB: years of schooling")
moran_scatter(axs[0, 2], ageb.log_dens_neg.values, w_ageb, "AGEB: business density (log)")
moran_scatter(axs[1, 0], ageb.log_dens_pob.values, w_ageb, "AGEB: population density (log)")
moran_scatter(axs[1, 1], mun.tasa_delitos_eb.values, w_mun, "Municipality: crime rate (EB)")
moran_scatter(axs[1, 2], ageb.log_dens_pob.values, w_ageb,
              "Bivariate (AGEB): population density (x)\nvs neighbours' business density (Wy)",
              y=ageb.log_dens_neg.values, xlab="Population density, z",
              ylab="Spatial lag of business density, z")
axs[0, 0].legend(loc="lower right", fontsize=9, frameon=False, markerscale=1.5,
                 bbox_to_anchor=(1.0, 0.08))
fig.tight_layout()
save(fig, "fig10_moran_scatterplots.png")

# ---------------------------------------------------------------- 8. LISA MAPS
fig, axs = plt.subplots(1, 2, figsize=(14, 7.5))
for ax, (v, lab) in zip(axs, [("log_dens_neg", "(a) Business density"), ("log_dens_pob", "(b) Population density")]):
    lisa_map(ax, AGA, lisa_labels(Moran_Local(ageb[v].values, w_ageb, permutations=PERM, seed=12345)), lab)
fig.tight_layout()
save(fig, "fig11_lisa_ageb.png")

fig, ax = plt.subplots(figsize=(8, 8))
lisa_map(ax, AGA, lisa_labels(Moran_Local_BV(ageb.log_dens_pob.values, ageb.log_dens_neg.values, w_ageb,
                                             permutations=PERM, seed=12345)),
         "Population density (x) vs neighbours' business density (Wy)")
save(fig, "fig12_lisa_bivariate_ageb.png")

fig, axs = plt.subplots(1, 2, figsize=(14, 6))
lisa_map(axs[0], MU, lisa_labels(Moran_Local(mun.tasa_delitos_eb.values, w_mun, permutations=PERM, seed=12345)),
         "(a) Crime rate (EB), univariate LISA", outline=MERIDA)
lisa_map(axs[1], MU, lisa_labels(Moran_Local_BV(mun.log_dens_neg.values, mun.tasa_delitos_eb.values, w_mun,
                                                permutations=PERM, seed=12345)),
         "(b) Business density (x) vs neighbours' crime rate (Wy)", outline=MERIDA)
fig.tight_layout()
save(fig, "fig13_lisa_municipal.png")

print(f"\nDone. Figures in {FIG}")
