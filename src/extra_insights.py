"""
Additional insights - Merida Urban Intelligence (beyond the brief)

  A. Beach-season effect: do coastal municipalities concentrate their recorded crime in
     July-August, when Merida residents move to the coast? (dw.v_delitos_tipo_tiempo)
  B. Schools vs children: are basic-education schools where school-age children live?
     (DENUE SCIAN 6111x points + Census 2020 ages, AGEB scale)
  C. Jobs vs residence: estimated jobs (DENUE staff-size midpoints) vs resident workers
     (Census POCUPADA) - job centres and dormitory areas.

Reads only from the Data Warehouse. Run after src/etl.py:
    python src/extra_insights.py
Outputs: outputs/report_figures/fig14-16_*.png, outputs/tables/insights_summary.json,
         outputs/tables/insight_*.csv
"""
import json
import os
import unicodedata
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from esda import Moran, Moran_Local
from libpysal.weights import KNN, Queen, w_union
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.patches import Patch
from scipy.stats import mannwhitneyu, spearmanr
from shapely.geometry import Point
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
eng = create_engine(DB_URL)
PERM, ALPHA = 999, 0.05
CENTRE = Point(-89.6237, 20.9671)          # Plaza Grande, historic centre of Merida
SUMMER = (7, 8)                            # July and August (school holidays, beach season)
MIN_INCIDENTS = 30                         # municipalities with fewer incidents are too noisy
# Municipalities to force as coastal / inland if the automatic rule needs correcting (CVEGEO).
COASTAL_ADD, COASTAL_REMOVE = set(os.getenv("COASTAL_ADD", "").split(",")) - {""}, set()

INK, INK2, MUTED, GRID, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#898781"
DIV = LinearSegmentedColormap.from_list("div", ["#1c5cab", "#86b6ef", "#f0efec", "#f7a77f", "#b8461b"])
BLUES = LinearSegmentedColormap.from_list("blues", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
LISA_COLORS = {"HH": "#d7191c", "LL": "#2c7bb6", "LH": "#abd9e9", "HL": "#fdae61", "NS": "#e8e8e8"}
LISA_NAMES = {"HH": "High-High", "LL": "Low-Low", "LH": "Low-High", "HL": "High-Low", "NS": "Not significant"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10.5, "axes.titlesize": 12,
                     "axes.titleweight": "bold", "axes.edgecolor": BASE, "axes.labelcolor": INK2,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.dpi": 220, "savefig.bbox": "tight",
                     "savefig.facecolor": "white"})
summary = {}


def save(fig, name):
    fig.savefig(FIG / name)
    plt.close(fig)
    print(f"  saved {name}")


def weights(gdf):
    w = Queen.from_dataframe(gdf, use_index=False, silence_warnings=True)
    if w.islands:
        w = w_union(w, KNN.from_dataframe(gdf, k=1, use_index=False))
    w.transform = "r"
    return w


def lisa(values, w):
    lm = Moran_Local(values, w, permutations=PERM, seed=12345)
    q = pd.Series(lm.q).map({1: "HH", 2: "LH", 3: "LL", 4: "HL"})
    return q.where(lm.p_sim < ALPHA, "NS").values


def lisa_map(ax, gdf, labels, title):
    g = gdf.assign(c=labels)
    for k, col in LISA_COLORS.items():
        if (g.c == k).any():
            g[g.c == k].plot(ax=ax, color=col, edgecolor="white", linewidth=0.15)
    n = g.c.value_counts()
    ax.legend(handles=[Patch(color=c, label=f"{LISA_NAMES[k]} ({n.get(k, 0)})") for k, c in LISA_COLORS.items()],
              loc="lower left", fontsize=8.5, frameon=False)
    ax.set_title(title, loc="left")
    ax.set_axis_off()


def rho(x, y):
    d = pd.concat([x, y], axis=1).dropna()
    r, p = spearmanr(d.iloc[:, 0], d.iloc[:, 1])
    return float(r), float(p), int(len(d))


# =====================================================================================
# A. BEACH SEASON
# =====================================================================================
print("A. Beach-season effect")
mun = gpd.read_postgis("SELECT * FROM dw.v_kpi_municipio ORDER BY cvegeo", eng, geom_col="geom")
for c in ["pobtot", "delitos_prom_anual", "tasa_delitos_x1000hab"]:
    mun[c] = pd.to_numeric(mun[c], errors="coerce")
monthly = pd.read_sql("""SELECT cvegeo, anio, mes, SUM(incidentes) AS n
                         FROM dw.v_delitos_tipo_tiempo GROUP BY 1, 2, 3""", eng)

# Coastal municipalities of Yucatán (Gulf of Mexico coastline). Edit this list if needed.
COASTAL = ["Celestún", "Hunucmá", "Progreso", "Ixil", "Dzemul", "Telchac Puerto", "Sinanché", "Yobaín",
           "Dzidzantún", "Dzilam de Bravo", "San Felipe", "Río Lagartos", "Tizimín"]
norm = lambda x: unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().strip().lower()
coastal_n = {norm(c) for c in COASTAL}
mun["coastal"] = mun.nom_mun.map(norm).isin(coastal_n)
missing = coastal_n - set(mun.nom_mun.map(norm))
if missing:
    print("  WARNING: coastal names not found in the warehouse:", sorted(missing))
mun.loc[mun.cvegeo.isin(COASTAL_ADD), "coastal"] = True
mun.loc[mun.cvegeo.isin(COASTAL_REMOVE), "coastal"] = False
mun.loc[mun.cvegeo == "31050", "coastal"] = False
print("  coastal municipalities:", ", ".join(sorted(mun.loc[mun.coastal, "nom_mun"])))

pv = monthly.pivot_table(index="cvegeo", columns="mes", values="n", aggfunc="sum").reindex(columns=range(1, 13)).fillna(0)
tot = pv.sum(axis=1)
expected = 62 / 365
season = pd.DataFrame({"cvegeo": pv.index, "total": tot.values,
                       "summer_share": (pv[list(SUMMER)].sum(axis=1) / tot).values})
season["summer_index"] = season.summer_share / expected
mun = mun.merge(season, on="cvegeo", how="left")
mun["group"] = np.where(mun.cvegeo == "31050", "Mérida", np.where(mun.coastal, "Coastal", "Inland"))
ok = mun[mun.total >= MIN_INCIDENTS]
c_idx = ok.loc[ok.group == "Coastal", "summer_index"].dropna()
i_idx = ok.loc[ok.group == "Inland", "summer_index"].dropna()
mw_p = float(mannwhitneyu(c_idx, i_idx, alternative="greater").pvalue) if len(c_idx) >= 3 and len(i_idx) >= 3 else None

grp_month = (monthly.merge(mun[["cvegeo", "group"]], on="cvegeo")
             .groupby(["group", "mes"]).n.sum().unstack(0).reindex(range(1, 13)).fillna(0))
profile = 100 * grp_month / grp_month.mean()
by_year = (monthly.merge(mun[["cvegeo", "group"]], on="cvegeo")
           .assign(summer=lambda d: d.mes.isin(SUMMER))
           .groupby(["anio", "group"]).apply(lambda d: d.loc[d.summer, "n"].sum() / d.n.sum())
           .unstack())
years_coastal_higher = int((by_year.get("Coastal", 0) > by_year.get("Inland", 0)).sum()) if "Coastal" in by_year else 0

# rates with and without the summer months, coastal group (2023-2025, annualised)
rec = monthly[monthly.anio.between(2023, 2025)].merge(mun[["cvegeo", "group", "pobtot"]], on="cvegeo")
def grp_rates(g):
    d = rec[rec.group == g]
    pop = mun.loc[mun.group == g, "pobtot"].sum()
    full = d.n.sum() / 3 / pop * 1000
    off = d.loc[~d.mes.isin(SUMMER), "n"].sum() / 3 * 12 / 10 / pop * 1000
    return float(full), float(off)
cf, co = grp_rates("Coastal")
inf, ino = grp_rates("Inland")
hh = pd.read_csv(TAB / "lisa_resultados.csv") if (TAB / "lisa_resultados.csv").exists() else pd.DataFrame()
hh_codes = set(hh[(hh.get("escala") == "Municipio") & (hh.get("variable") == "tasa_delitos_eb")
                  & (hh.get("cluster") == "HH")].cvegeo.astype(str).str.zfill(5)) if len(hh) else set()
summary["beach"] = {
    "n_coastal": int(mun.coastal.sum()), "coastal_names": sorted(mun.loc[mun.coastal, "nom_mun"].tolist()),
    "n_coastal_tested": int(len(c_idx)), "n_inland_tested": int(len(i_idx)),
    "summer_share_coastal": float(grp_month.loc[list(SUMMER), "Coastal"].sum() / grp_month["Coastal"].sum()) if "Coastal" in grp_month else None,
    "summer_share_inland": float(grp_month.loc[list(SUMMER), "Inland"].sum() / grp_month["Inland"].sum()),
    "summer_share_merida": float(grp_month.loc[list(SUMMER), "Mérida"].sum() / grp_month["Mérida"].sum()),
    "expected_share": expected, "median_index_coastal": float(c_idx.median()) if len(c_idx) else None,
    "median_index_inland": float(i_idx.median()), "mannwhitney_p": mw_p,
    "peak_month_coastal": int(profile["Coastal"].idxmax()) if "Coastal" in profile else None,
    "peak_month_inland": int(profile["Inland"].idxmax()), "peak_month_merida": int(profile["Mérida"].idxmax()),
    "years_coastal_higher": years_coastal_higher, "years_total": int(len(by_year)),
    "rate_coastal_full": cf, "rate_coastal_offseason": co, "rate_inland_full": inf, "rate_inland_offseason": ino,
    "hh_coastal": int(mun[mun.cvegeo.isin(hh_codes)].coastal.sum()), "hh_total": len(hh_codes),
}
mun[["cvegeo", "nom_mun", "group", "total", "summer_share", "summer_index"]].to_csv(TAB / "insight_beach_season.csv", index=False)

fig = plt.figure(figsize=(15, 5.2))
ax0 = fig.add_axes([0.0, 0.02, 0.36, 0.88])
ax1 = fig.add_axes([0.42, 0.14, 0.33, 0.72])
ax2 = fig.add_axes([0.81, 0.14, 0.18, 0.72])
M = mun.to_crs(6372)
M.plot(ax=ax0, color="#eeeeee", edgecolor="white", linewidth=0.2)
M[M.total >= MIN_INCIDENTS].plot(ax=ax0, column="summer_index", cmap=DIV,
                                norm=TwoSlopeNorm(vmin=0.4, vcenter=1.0, vmax=1.8), edgecolor="white", linewidth=0.2,
                                legend=True, legend_kwds={"shrink": 0.6, "label": "July–Aug share / expected"})
M[M.coastal].boundary.plot(ax=ax0, color=INK, linewidth=0.9)
M[M.cvegeo == "31050"].boundary.plot(ax=ax0, color=BLUE, linewidth=1.6)
ax0.set_title("(a) Summer index (1 = no seasonality)\nblack outline = coastal, blue = Mérida", loc="left")
ax0.set_axis_off()
months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
ax1.axvspan(5.5, 7.5, color="#f6e3d6", lw=0)
for g, col in [("Coastal", ORANGE), ("Inland", GREY), ("Mérida", BLUE)]:
    if g in profile:
        ax1.plot(range(12), profile[g].values, color=col, lw=2, marker="o", ms=4, label=g)
ax1.axhline(100, color=BASE, lw=0.8)
ax1.set_xticks(range(12))
ax1.set_xticklabels(months)
ax1.set_ylabel("Monthly incidents (100 = average month)")
ax1.set_title("(b) Seasonal profile, 2015–2025", loc="left")
ax1.legend(frameon=False, fontsize=9)
ax1.grid(axis="y", color=GRID, lw=0.5)
data = [c_idx.values, i_idx.values]
for k, (vals, col) in enumerate(zip(data, [ORANGE, GREY])):
    x = np.random.normal(k, 0.06, len(vals))
    ax2.scatter(x, vals, s=14, color=col, alpha=0.7, linewidths=0)
    if len(vals):
        ax2.hlines(np.median(vals), k - 0.25, k + 0.25, color=INK, lw=2)
ax2.axhline(1, color=BASE, lw=0.8, ls="--")
ax2.set_xticks([0, 1])
ax2.set_xticklabels([f"Coastal\n(n={len(c_idx)})", f"Inland\n(n={len(i_idx)})"])
ax2.set_ylabel("Summer index")
ax2.set_title("(c) Coastal vs inland" + (f"\np = {mw_p:.3f}" if mw_p is not None else ""), loc="left")
save(fig, "fig14_beach_season.png")

# =====================================================================================
# B. SCHOOLS VS CHILDREN
# =====================================================================================
print("B. Schools vs children")
ag = gpd.read_postgis("""
    SELECT g.cvegeo, g.area_km2, c.pobtot, c.pob0_14, c.p_3a5, c.p_6a11, c.p_12a14, c.graproes,
           c.pocupada, g.geom
    FROM dw.dim_geografia g JOIN dw.fact_censo c USING (geo_key)
    WHERE g.en_localidad_merida""", eng, geom_col="geom").to_crs(6372)
for c in ag.columns.drop(["cvegeo", "geom"]):
    ag[c] = pd.to_numeric(ag[c], errors="coerce")
ag = ag[ag.pobtot >= 100].reset_index(drop=True)
ag["kids"] = ag[["p_3a5", "p_6a11", "p_12a14"]].sum(axis=1, min_count=1)
ag["kids_share"] = 100 * ag.kids / ag.pobtot
cent = ag.copy()
cent["geom"] = ag.geometry.representative_point()
cent = cent.set_geometry("geom")
centre = gpd.GeoSeries([CENTRE], crs=4326).to_crs(6372).iloc[0]
ag["dist_centre_km"] = cent.distance(centre) / 1000

schools = gpd.read_postgis("""
    SELECT f.geom, s.codigo_act FROM dw.fact_establecimiento f JOIN dw.dim_scian s USING (scian_key)
    WHERE LEFT(s.codigo_act, 5) IN ('61111', '61112', '61113', '61114')""", eng, geom_col="geom").to_crs(6372)
schools["private"] = schools.codigo_act.str[-1] == "1"
near = gpd.sjoin_nearest(cent[["cvegeo", "geom"]], schools[["geom"]], distance_col="d").groupby("cvegeo").d.min()
ag["dist_school_m"] = ag.cvegeo.map(near)
buf = cent[["cvegeo", "geom"]].copy()
buf["geom"] = buf.geometry.buffer(1000)
j = gpd.sjoin(schools, buf.set_geometry("geom"), predicate="within")
ag["schools_1km"] = ag.cvegeo.map(j.groupby("cvegeo").size()).fillna(0)
ag["private_share_1km"] = 100 * ag.cvegeo.map(j.groupby("cvegeo").private.mean())
kids_pts = cent[["cvegeo", "geom"]].assign(kids=ag.kids)
jk = gpd.sjoin(kids_pts, buf.set_geometry("geom").rename(columns={"cvegeo": "owner"}), predicate="within")
ag["kids_1km"] = ag.cvegeo.map(jk.groupby("owner").kids.sum())
ag["kids_per_school"] = ag.kids_1km / ag.schools_1km.replace(0, np.nan)
ag["log_kids_per_school"] = np.log1p(ag.kids_per_school)
w_ag = weights(ag)
v = ag.log_kids_per_school.fillna(ag.log_kids_per_school.max())
mi = Moran(v.values, w_ag, permutations=PERM)
lab_b = lisa(v.values, w_ag)
r1 = rho(ag.kids_share, ag.dist_school_m)
r2 = rho(ag.kids_share, ag.kids_per_school)
r3 = rho(ag.dist_centre_km, ag.kids_per_school)
r4 = rho(ag.graproes, ag.private_share_1km)
hh_b = ag[lab_b == "HH"]
summary["schools"] = {
    "n_schools": int(len(schools)), "private_share": float(100 * schools.private.mean()),
    "median_dist_m": float(ag.dist_school_m.median()), "p90_dist_m": float(ag.dist_school_m.quantile(.9)),
    "median_kids_per_school": float(ag.kids_per_school.median()),
    "rho_kidsshare_dist": r1, "rho_kidsshare_kidsperschool": r2, "rho_centre_kidsperschool": r3,
    "rho_schooling_private": r4, "moran_I": float(mi.I), "moran_p": float(mi.p_sim),
    "n_hh": int((lab_b == "HH").sum()), "hh_kids_share": float(hh_b.kids.sum() / hh_b.pobtot.sum() * 100) if len(hh_b) else None,
    "city_kids_share": float(ag.kids.sum() / ag.pobtot.sum() * 100),
    "hh_median_dist_centre_km": float(hh_b.dist_centre_km.median()) if len(hh_b) else None,
    "city_median_dist_centre_km": float(ag.dist_centre_km.median()),
}
ag[["cvegeo", "kids", "kids_share", "dist_school_m", "schools_1km", "kids_per_school",
    "private_share_1km", "dist_centre_km"]].assign(lisa=lab_b).to_csv(TAB / "insight_schools.csv", index=False)

fig, axs = plt.subplots(2, 2, figsize=(13, 12.5))
ag.plot(ax=axs[0, 0], column="kids_per_school", scheme="Quantiles", k=5, cmap=BLUES, edgecolor="white",
        linewidth=0.1, missing_kwds={"color": "#3a3a3a", "label": "No school within 1 km"}, legend=True,
        legend_kwds={"loc": "lower left", "fontsize": 8.5, "fmt": "{:,.0f}", "frameon": False})
axs[0, 0].set_title("(a) School-age children per basic school within 1 km", loc="left")
axs[0, 0].set_axis_off()
lisa_map(axs[0, 1], ag, lab_b, f"(b) LISA, children per school (Moran's I = {mi.I:.2f})")
axs[1, 0].scatter(ag.kids_share, ag.kids_per_school, s=12, color=BLUE, alpha=0.55, linewidths=0)
axs[1, 0].set_xlabel("Children aged 3–14 (% of residents)")
axs[1, 0].set_ylabel("Children per basic school within 1 km")
axs[1, 0].set_title(f"(c) Where children live vs school supply\nρ = {r2[0]:.2f}, p = {r2[1]:.1e}", loc="left")
axs[1, 0].grid(color=GRID, lw=0.5)
axs[1, 1].scatter(ag.graproes, ag.private_share_1km, s=12, color=ORANGE, alpha=0.55, linewidths=0)
axs[1, 1].set_xlabel("Average years of schooling (adults)")
axs[1, 1].set_ylabel("Private schools within 1 km (%)")
axs[1, 1].set_title(f"(d) Private share of nearby schools vs adult schooling\nρ = {r4[0]:.2f}, p = {r4[1]:.1e}", loc="left")
axs[1, 1].grid(color=GRID, lw=0.5)
fig.tight_layout()
save(fig, "fig15_schools_children.png")

# =====================================================================================
# C. JOBS VS RESIDENCE
# =====================================================================================
print("C. Jobs vs residence")
jobs = pd.read_sql("""
    SELECT g.cvegeo, SUM(CASE t.orden WHEN 1 THEN 3 WHEN 2 THEN 8 WHEN 3 THEN 20.5 WHEN 4 THEN 40.5
                                      WHEN 5 THEN 75.5 WHEN 6 THEN 175.5 WHEN 7 THEN 300 ELSE 3 END) AS jobs
    FROM dw.fact_establecimiento f
    JOIN dw.dim_geografia g ON g.geo_key = f.geo_ageb_key
    LEFT JOIN dw.dim_tamano t USING (tamano_key)
    WHERE g.en_localidad_merida GROUP BY 1""", eng)
ag["jobs"] = ag.cvegeo.map(jobs.set_index("cvegeo").jobs.astype(float)).fillna(0)
cj = ag[ag.pocupada >= 50].reset_index(drop=True)
cj["ratio"] = cj.jobs / cj.pocupada
cj["log2_ratio"] = np.log2(cj.ratio.clip(lower=1 / 64))
city_ratio = float(cj.jobs.sum() / cj.pocupada.sum())
# daytime population: residents - resident workers + jobs (jobs rescaled so citywide workers balance)
scale = cj.pocupada.sum() / cj.jobs.sum()
cj["day_pop"] = cj.pobtot - cj.pocupada + cj.jobs * scale
cj["day_night"] = cj.day_pop / cj.pobtot
w_cj = weights(cj)
mj = Moran(cj.log2_ratio.values, w_cj, permutations=PERM)
lab_c = lisa(cj.log2_ratio.values, w_cj)
top10 = cj.jobs.sort_values(ascending=False)
share_top10 = float(top10.head(int(np.ceil(len(cj) * 0.1))).sum() / cj.jobs.sum() * 100)
rj = rho(cj.dist_centre_km, cj.log2_ratio)
rk = rho(cj.dist_centre_km, cj.day_night)
summary["jobs"] = {
    "n_ageb": int(len(cj)), "est_jobs": float(cj.jobs.sum()), "resident_workers": float(cj.pocupada.sum()),
    "city_ratio": city_ratio, "share_jobs_top10pct_ageb": share_top10,
    "pct_dormitory": float((cj.ratio < 0.5).mean() * 100), "pct_job_centre": float((cj.ratio > 2).mean() * 100),
    "rho_dist_ratio": rj, "rho_dist_daynight": rk, "moran_I": float(mj.I), "moran_p": float(mj.p_sim),
    "n_hh": int((lab_c == "HH").sum()), "n_ll": int((lab_c == "LL").sum()),
    "max_day_night": float(cj.day_night.max()), "median_day_night": float(cj.day_night.median()),
}
cj[["cvegeo", "jobs", "pocupada", "ratio", "day_pop", "day_night", "dist_centre_km"]].assign(lisa=lab_c).to_csv(
    TAB / "insight_jobs_residence.csv", index=False)

fig = plt.figure(figsize=(15, 6.2))
a0 = fig.add_axes([0.0, 0.03, 0.34, 0.88])
a1 = fig.add_axes([0.35, 0.03, 0.34, 0.88])
a2 = fig.add_axes([0.75, 0.13, 0.24, 0.72])
cj.plot(ax=a0, column="log2_ratio", cmap=DIV, norm=TwoSlopeNorm(vmin=-4, vcenter=0, vmax=4), edgecolor="white",
        linewidth=0.1, legend=True, legend_kwds={"shrink": 0.55, "label": "log2(jobs / resident workers)"})
a0.set_title("(a) Jobs per resident worker\nblue = dormitory, orange = job centre", loc="left")
a0.set_axis_off()
lisa_map(a1, cj, lab_c, f"(b) LISA, jobs-to-workers ratio (I = {mj.I:.2f})")
bins = pd.cut(cj.dist_centre_km, np.arange(0, cj.dist_centre_km.max() + 1, 1))
g = cj.groupby(bins, observed=True).agg(jobs=("jobs", "sum"), workers=("pocupada", "sum"))
mid = [b.mid for b in g.index]
a2.plot(mid, g.jobs / g.workers, color=ORANGE, lw=2, marker="o", ms=4)
a2.axhline(1, color=BASE, lw=0.8, ls="--")
a2.set_yscale("log")
a2.set_xlabel("Distance to the historic centre (km)")
a2.set_ylabel("Jobs per resident worker (log scale)")
a2.set_title(f"(c) Gradient from the centre\nρ = {rj[0]:.2f}", loc="left")
a2.grid(color=GRID, lw=0.5)
save(fig, "fig16_jobs_residence.png")

(TAB / "insights_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=float),
                                           encoding="utf-8")
print("\nSummary:")
print(json.dumps(summary, indent=2, ensure_ascii=False, default=float))
