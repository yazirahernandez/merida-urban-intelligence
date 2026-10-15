"""
Technical report builder - Merida Urban Intelligence

Builds docs/Merida_Urban_Intelligence_Technical_Report.pdf from:
  - the Data Warehouse (KPI table is computed live from the dw views)
  - outputs/tables/*.csv          (src/phase3_spatial_analysis.py)
  - outputs/report_figures/*.png  (src/report_figures.py)
  - docs/warehouse_model_en.png

Run order:
    python src/etl.py
    python src/phase3_spatial_analysis.py
    python src/report_figures.py
    python src/build_report.py
"""
import json
import os
import sys
from pathlib import Path

import matplotlib
import pandas as pd
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, Image, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "outputs" / "report_figures"
TAB = ROOT / "outputs" / "tables"
OUT = ROOT / "docs" / "Merida_Urban_Intelligence_Technical_Report.pdf"
DB_URL = os.getenv("DATABASE_URL",
                   "postgresql+psycopg2://merida:merida123@localhost:5433/merida_dw")
REPO = "github.com/yazirahernandez/merida-urban-intelligence"

needed = [FIG / "fig_key_maps.png", FIG / "fig07_correlation_matrix.png",
          FIG / "fig10_moran_scatterplots.png", TAB / "moran_global.csv",
          TAB / "correlaciones.csv", ROOT / "docs" / "warehouse_model_en.png"]
missing = [str(p.relative_to(ROOT)) for p in needed if not p.exists()]
if missing:
    sys.exit("Missing inputs: " + ", ".join(missing) +
             "\nRun phase3_spatial_analysis.py and report_figures.py first.")

# ---------------------------------------------------------------- FONTS (STIX ships with matplotlib)
TTF = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
for name, file in [("Serif", "STIXGeneral.ttf"), ("Serif-Bold", "STIXGeneralBol.ttf"),
                   ("Serif-Italic", "STIXGeneralItalic.ttf"), ("Serif-BoldItalic", "STIXGeneralBolIta.ttf"),
                   ("Sans", "DejaVuSans.ttf"), ("Sans-Bold", "DejaVuSans-Bold.ttf"),
                   ("Mono", "DejaVuSansMono.ttf")]:
    pdfmetrics.registerFont(TTFont(name, str(TTF / file)))
pdfmetrics.registerFontFamily("Serif", normal="Serif", bold="Serif-Bold",
                              italic="Serif-Italic", boldItalic="Serif-BoldItalic")

NAVY, ACCENT, LIGHT = colors.HexColor("#14213d"), colors.HexColor("#2a78d6"), colors.HexColor("#eef3fa")
W = letter[0] - 1.4 * inch
body = ParagraphStyle("body", fontName="Serif", fontSize=9.7, leading=11.6, alignment=TA_JUSTIFY, spaceAfter=4)
small = ParagraphStyle("small", parent=body, fontSize=9, leading=11)
bullet = ParagraphStyle("bul", parent=body, leftIndent=11, bulletIndent=1, spaceAfter=2)
h1 = ParagraphStyle("h1", fontName="Sans-Bold", fontSize=11, leading=14, spaceBefore=7, spaceAfter=3,
                    textColor=NAVY, keepWithNext=1)
h2 = ParagraphStyle("h2", fontName="Serif-BoldItalic", fontSize=10.3, leading=12.5, spaceBefore=3,
                    spaceAfter=2, keepWithNext=1)
tag = ParagraphStyle("tag", fontName="Sans", fontSize=7.4, leading=9, textColor=ACCENT, spaceAfter=3)
cap = ParagraphStyle("cap", fontName="Serif-Italic", fontSize=8.6, leading=10.2, alignment=TA_JUSTIFY,
                     spaceBefore=2, spaceAfter=6)
cell = ParagraphStyle("cell", fontName="Serif", fontSize=8.3, leading=9.8)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Serif-Bold")
S = []


def P(t, st=body):
    S.append(Paragraph(t, st))


def H(t, rubric=None):
    S.append(Paragraph(t, h1))
    if rubric:
        S.append(Paragraph(rubric, tag))


def B(t):
    S.append(Paragraph(t, bullet, bulletText="•"))


def img(path, width):
    w, h = PILImage.open(path).size
    return Image(str(path), width=width, height=width * h / w)


def fig(path, width, caption):
    S.append(KeepTogether([img(path, width), Paragraph(caption, cap)]))


def side(path, img_w, caption, flowables):
    left = [img(path, img_w), Paragraph(caption, cap)]
    t = Table([[left, flowables]], colWidths=[img_w + 10, W - img_w - 10])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (0, 0), 10), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    S.append(t)


def table(rows, widths, caption, width=None, as_flowable=False, keep=True):
    width = width or W
    data = [[Paragraph(str(c), cellb if i == 0 else cell) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[x * width for x in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dce6f0")),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black), ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    items = [Paragraph(caption, ParagraphStyle("tc", parent=cap, fontName="Serif-Bold", alignment=TA_CENTER,
                                               spaceAfter=2)), t, Spacer(1, 5)]
    if as_flowable:
        return items
    if keep:
        S.append(KeepTogether(items))
    else:
        S.append(CondPageBreak(1.3 * inch))
        S.extend(items)


def f(x, d=1):
    return "—" if pd.isna(x) else f"{x:,.{d}f}"


# ---------------------------------------------------------------- LIVE NUMBERS FROM THE WAREHOUSE
eng = create_engine(DB_URL)
q = lambda s: pd.read_sql(s, eng)
city = q("""
WITH a AS (SELECT geo_key, area_km2, tiene_censo FROM dw.dim_geografia WHERE en_localidad_merida),
c AS (SELECT SUM(pobtot) pob, SUM(pea) pea, SUM(p_12ymas) p12, SUM(pob0_14) p014,
             SUM(pob15_64) p1564, SUM(pob65_mas) p65
      FROM dw.fact_censo f JOIN a USING (geo_key)),
ar AS (SELECT SUM(area_km2) tot, SUM(area_km2) FILTER (WHERE tiene_censo) cen FROM a),
e AS (SELECT COUNT(*) n,
             COUNT(*) FILTER (WHERE s.grupo_kpi = 'comercio_minorista') ret,
             COUNT(*) FILTER (WHERE s.grupo_kpi = 'servicios') serv
      FROM dw.fact_establecimiento f JOIN dw.dim_scian s USING (scian_key)
      JOIN a ON a.geo_key = f.geo_ageb_key)
SELECT * FROM c, ar, e""").iloc[0].astype(float)
dom = q("""SELECT s.subsector, COUNT(*) n FROM dw.fact_establecimiento f JOIN dw.dim_scian s USING (scian_key)
           JOIN dw.dim_geografia g ON g.geo_key = f.geo_ageb_key WHERE g.en_localidad_merida
           GROUP BY 1 ORDER BY 2 DESC LIMIT 1""").iloc[0]
dom_ageb = q("""SELECT subsector_dominante, COUNT(*) n FROM dw.v_kpi_ageb
                WHERE subsector_dominante IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 1""").iloc[0]
ag = q("SELECT * FROM dw.v_kpi_ageb WHERE tiene_censo").drop(columns="geom")
mu = q("SELECT * FROM dw.v_kpi_municipio").drop(columns="geom")
mer = mu[mu.cvegeo == "31050"].iloc[0]
types = q("""SELECT tipo_delito, SUM(incidentes) n FROM dw.v_delitos_tipo_tiempo
             WHERE cvegeo = '31050' AND anio BETWEEN 2023 AND 2025 GROUP BY 1 ORDER BY 2 DESC LIMIT 3""")
peak = q("""SELECT nombre_mes, SUM(incidentes) n FROM dw.v_delitos_tipo_tiempo
            WHERE cvegeo = '31050' AND anio BETWEEN 2023 AND 2025 GROUP BY 1 ORDER BY 2 DESC LIMIT 1""").iloc[0]
counts = q("""SELECT 'fact_censo' t, COUNT(*) n FROM dw.fact_censo
              UNION ALL SELECT 'fact_establecimiento', COUNT(*) FROM dw.fact_establecimiento
              UNION ALL SELECT 'fact_delito_mensual', COUNT(*) FROM dw.fact_delito_mensual
              UNION ALL SELECT 'dim_geografia', COUNT(*) FROM dw.dim_geografia""").set_index("t").n
MONTHS_EN = dict(zip(["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
                      "Septiembre", "Octubre", "Noviembre", "Diciembre"],
                     ["January", "February", "March", "April", "May", "June", "July", "August",
                      "September", "October", "November", "December"]))
TYPES_EN = {"Daño a la propiedad": "property damage", "Narcomenudeo": "drug dealing", "Robo": "robbery",
            "Amenazas": "threats", "Violencia familiar": "domestic violence", "Lesiones": "injuries",
            "Fraude": "fraud", "Otros delitos del Fuero Común": "other common-law offences"}
SUBSECTORS = {"461": "grocery and food retail", "722": "food and beverage services",
              "811": "repair and maintenance", "621": "ambulatory health care",
              "541": "professional services", "812": "personal services"}


def dist(col, sub=None):
    s = (sub if sub is not None else ag)[col].dropna().astype(float)
    return f"{s.median():,.1f} [{s.quantile(.1):,.1f}–{s.quantile(.9):,.1f}]"


ag100 = ag[ag.pobtot >= 100]
mg = pd.read_csv(TAB / "moran_global.csv")
co = pd.read_csv(TAB / "correlaciones.csv")
bv = pd.read_csv(TAB / "moran_bivariado.csv")
lisa = pd.read_csv(TAB / "lisa_resultados.csv")
lisa_n = lisa.groupby(["variable", "cluster"]).size()
hh_mun = sorted(lisa[(lisa.escala == "Municipio") & (lisa.variable == "tasa_delitos_eb")
                     & (lisa.cluster == "HH")].nombre.dropna().tolist())


def lc(var, cl):
    return int(lisa_n.get((var, cl), 0))


# ---------------------------------------------------------------- TITLE
S.append(Paragraph("Mérida Urban Intelligence", ParagraphStyle(
    "t", fontName="Sans-Bold", fontSize=19, leading=23, textColor=NAVY, alignment=TA_CENTER)))
S.append(Paragraph("A Geospatial Data Warehouse for Demographic, Economic and Public-Safety Analysis",
                   ParagraphStyle("t2", fontName="Serif-Bold", fontSize=12.5, leading=16, alignment=TA_CENTER)))
S.append(Spacer(1, 4))
P("Yazira Abyade Hernández Rives · Business Intelligence, Unit 2 Project · Universidad Politécnica de Yucatán · "
  f"October 2026<br/>Repository: {REPO}", ParagraphStyle("sub", parent=small, alignment=TA_CENTER))
S.append(Spacer(1, 5))
abstract = (
    "<b>Abstract.</b> Four public sources — INEGI Census 2020, DENUE 05/2026, the INEGI Geostatistical "
    "Framework and SESNSP crime records — are integrated into a dimensional Data Warehouse in "
    "PostgreSQL/PostGIS. The sources do not share a geographic representation, so the core design problem "
    "was choosing a unit of analysis. The solution is a two-scale model: 501 urban AGEBs for demographic and "
    "economic analysis inside Mérida, and Yucatán's 106 municipalities for public safety, because no "
    "georeferenced or colonia-level crime data exist. All 14 required KPIs are computed from warehouse views. "
    "Mérida is strongly segregated by age (Moran's I = 0.84) and schooling (0.78); residential and commercial "
    "intensity co-locate across neighbouring AGEBs (bivariate I = 0.28); and recorded crime clusters along the "
    "Mérida–northern-coast corridor (I = 0.26). Annex A maps every requirement and rubric component of the "
    "brief to the figure, table or file that satisfies it; Annex B adds three exploratory insights beyond the brief; Annex C contains the complete figure set.")
t = Table([[Paragraph(abstract, ParagraphStyle("abs", parent=body, fontSize=9.3, leading=11.4))]], colWidths=[W])
t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                       ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                       ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
S.append(t)

# ---------------------------------------------------------------- 1. SOURCES
H("1. Problem, Data Sources and Profiling",
  "PHASE 1 · DATA &amp; GEOGRAPHIC ASSESSMENT (RUBRIC: 15 PTS) · source inventory, profiling, traceability")
P("The objective is a reproducible warehouse that computes territorial KPIs, compares areas within Mérida and "
  "tests whether demographic, economic and public-safety patterns are geographically associated. Table 1 is the "
  "source inventory. Each source arrives at a different grain and with a different spatial representation: "
  "tabular records with geographic keys (census), points (DENUE), polygons (framework) and municipal "
  "aggregates without coordinates (crime). Every fact row keeps a key to <font face='Mono' size='8'>dim_fuente</font>, "
  "which stores file name and edition, so all values remain traceable to their source.")
table([
    ["Layer", "Source and edition", "Original grain / representation", "Profile", "Variables used"],
    ["Demographic", "INEGI Census 2020, results by AGEB and urban block", "Block + AGEB/municipal totals; keys, no geometry",
     "40,140 rows; 483 Mérida AGEBs; 0 duplicates", "POBTOT, age groups, P_12YMAS, PEA, GRAPROES, dwellings (32)"],
    ["Economic", "INEGI DENUE Yucatán, 05/2026", "One establishment; lat/lon, SCIAN class, staff size",
     "146,384 rows; 0 duplicates or missing coordinates", "id, codigo_act, per_ocu, latitud, longitud, ageb"],
    ["Geographic", "INEGI Geostatistical Framework, Dec 2025", "AGEB and municipal polygons (ITRF2008 LCC)",
     "1,562 AGEB + 106 polygons; 0 invalid", "CVEGEO, CVE_MUN, CVE_LOC, CVE_AGEB, geometry"],
    ["Public safety", "SESNSP municipal incidence 2015–2025", "Municipality × year × subtype; 12 month columns; no coordinates",
     "114,268 rows; 157,917 incidents; 40 types", "Cve. Municipio, tipo, subtipo, modalidad, Enero–Diciembre"],
], [0.11, 0.2, 0.24, 0.23, 0.22], "Table 1. Source inventory and initial profiling")
P("<b>Data-quality issues.</b> Census cells marked <font face='Mono' size='8'>*</font> (confidential, fewer "
  "than three units) were loaded as NULL rather than zero; 16 AGEBs have fewer than 100 residents and 5 have "
  "none, so per-capita rates are withheld for them. The 2025 framework contains 18 AGEBs created after 2020 "
  "that have no census record. Recorded crime in Yucatán falls from 34,716 incidents (2015) to about 4,200 "
  "(2022–2024), an 88% drop that is more consistent with recording changes than with a real decline, so the "
  "crime KPIs use the 2023–2025 average and no trend is inferred.")

# ---------------------------------------------------------------- 2. GEOGRAPHY
H("2. Geographic Integration Strategy",
  "PHASE 1 · geographic-unit decision · CRS and geometry checks · point-to-polygon test")
table([
    ["Candidate unit", "Units", "Decision"],
    ["Urban block", "16,540", "Rejected: census suppresses most indicators; too few businesses per block"],
    ["Colonia", "—", "Rejected: not an INEGI unit; cannot be joined to the census"],
    ["<b>Urban AGEB</b>", "<b>501</b>", "<b>Selected</b>: finest unit with complete census data and official polygons"],
    ["Municipality", "106", "Used only for public safety (SESNSP has no coordinates)"],
], [0.2, 0.12, 0.68], "Table 2. Candidate units of analysis")
P("The urban AGEB of the locality of Mérida (31-050-0001) was selected. No public dataset of georeferenced or "
  "colonia-level crime exists for Mérida, so crime is integrated at municipal scale, producing a <b>two-scale "
  "design</b>. Municipal crime was deliberately not disaggregated to AGEBs: allocating it by population would "
  "give every AGEB the same rate, and allocating it by business counts would manufacture the crime–business "
  "association under test. The latitude/longitude-to-polygon requirement is demonstrated with DENUE points "
  "(Figure 1). Polygons were checked in GeoPandas (CRS ITRF2008 LCC, 0 invalid or empty geometries), areas were "
  "computed in EPSG:6372 and geometries stored in EPSG:4326.")
side(FIG / "fig02_point_in_polygon.png", 2.75 * inch,
     "Figure 1. DENUE points joined to AGEB polygons in PostGIS. [Phase 1 · point–polygon evidence]",
     table([
         ["Integration", "Method", "Result"],
         ["Census → AGEB", "13-digit CVEGEO key", "483 of 483 census AGEBs matched (100%)"],
         ["DENUE → AGEB", "ST_MakePoint(lon, lat), ST_Intersects", "99.8% of Mérida-municipality establishments inside an AGEB; 100% agree with DENUE's own AGEB key"],
         ["Crime → municipality", "5-digit CVEGEO key", "106 of 106 municipalities matched"],
     ], [0.27, 0.33, 0.4], "Table 3. Spatial integration results", width=W - 2.75 * inch - 10, as_flowable=True))

# ---------------------------------------------------------------- 3. ETL + DW
H("3. ETL Pipeline and Data Warehouse",
  "PHASE 2 · ETL, SPATIAL INTEGRATION &amp; REPRODUCIBILITY (20 PTS) · POSTGRESQL/POSTGIS DW (20 PTS)")
P("The pipeline follows RAW → CLEAN → SPATIAL JOIN → DW. <font face='Mono' size='8'>src/etl.py</font> reads the "
  "original ZIP files without modifying them, standardises types, keys, categories and CRS, removes duplicates "
  "and invalid coordinates, and loads a staging schema (<font face='Mono' size='8'>stg</font>). Numbered SQL "
  "scripts then create the schema (01), load dimensions and facts with the point-in-polygon join executed in "
  "PostGIS (02), create the KPI views (03) and run validation queries (04). The database runs in Docker "
  "(PostgreSQL 16, PostGIS 3.4) and the full pipeline is idempotent.")
side(ROOT / "docs" / "warehouse_model_en.png", 3.0 * inch,
     "Figure 2. Star schema around a conformed geography dimension. [Phase 2 · model diagram]",
     [Paragraph("<b>Grain.</b> <font face='Mono' size='8'>fact_censo</font>: one geographic unit (AGEB or "
                "municipality). <font face='Mono' size='8'>fact_establecimiento</font>: one establishment with its "
                "point — the atomic grain lets every economic KPI be recomputed without the raw files. "
                "<font face='Mono' size='8'>fact_delito_mensual</font>: municipality × month × offence.", body),
      Paragraph("<b>Grain change.</b> The SESNSP file has twelve month columns; they were unpivoted into one row per "
                "month and zero rows dropped. The incident total is preserved exactly (157,917 in staging and in the DW).", body),
      Paragraph(f"<b>Validation.</b> Loaded rows: {counts['fact_censo']:,} census units, "
                f"{counts['fact_establecimiento']:,} establishments, {counts['fact_delito_mensual']:,} crime rows, "
                f"{counts['dim_geografia']:,} geographic units. Population of the city AGEBs sums to "
                f"{city.pob:,.0f}, the official 2020 figure; no AGEB lacks its parent municipality.", body),
      Paragraph("<b>Dimensions.</b> geography (AGEB → municipality hierarchy, polygon, area), time (month), "
                "offence, SCIAN activity with KPI group, establishment size and source.", body)])

# ---------------------------------------------------------------- 4. KPIs
H("4. KPIs", "KPIs &amp; SPATIAL ANALYSIS (15 PTS) · all 14 required KPIs computed from dw views")
P("All KPIs are SQL views (<font face='Mono' size='8'>v_kpi_ageb</font>, <font face='Mono' size='8'>v_kpi_municipio</font>, "
  "<font face='Mono' size='8'>v_delitos_tipo_tiempo</font>). Retail is SCIAN 46 and services SCIAN 51–81. The "
  "dominant activity uses the three-digit subsector, because at two digits sector 46 dominates 402 of 501 AGEBs. "
  "Per-capita AGEB rates require at least 100 residents. Table 4 is computed live from the warehouse.")
pob = city.pob
table([
    ["Category", "KPI", "Formula", "Mérida", "AGEB median [P10–P90]"],
    ["Demographic", "Total Population", "Σ POBTOT", f"{pob:,.0f}", dist("pobtot")],
    ["", "Population Density", "POBTOT / km²", f"{pob / city.cen:,.0f} /km²", dist("densidad_pob_km2")],
    ["", "Econ. Active Pop. Rate", "100 × PEA / P_12YMAS", f"{100 * city.pea / city.p12:.1f}%", dist("tasa_pea_pct")],
    ["", "Population by Age Group", "% 0–14 / 15–64 / 65+", f"{100*city.p014/pob:.1f} / {100*city.p1564/pob:.1f} / {100*city.p65/pob:.1f}%", "65+: " + dist("pct_65_mas")],
    ["Economic", "Total Businesses", "count of DENUE rows", f"{city.n:,.0f}", dist("negocios")],
    ["", "Business Density", "businesses / km²", f"{city.n / city.tot:,.0f} /km²", dist("dens_negocios_km2")],
    ["", "Businesses per 1,000", "1000 × businesses / POBTOT", f"{1000 * city.n / pob:,.1f}", dist("negocios_x1000hab", ag100)],
    ["", "Retail Density", "SCIAN 46 / km²", f"{city.ret / city.tot:,.0f} /km²", dist("dens_comercio_km2")],
    ["", "Service Density", "SCIAN 51–81 / km²", f"{city.serv / city.tot:,.0f} /km²", dist("dens_servicios_km2")],
    ["", "Dominant Activity", "most frequent subsector", f"{dom.subsector} ({100 * dom.n / city.n:.0f}%)",
     f"{dom_ageb.subsector_dominante} dominates {dom_ageb.n} AGEBs"],
    ["Public safety", "Total Crime Incidents", "Σ incidents 2023–2025", f"{mer.delitos_2023_2025:,.0f}", "municipal scale (106 units)"],
    ["", "Crime Rate", "1000 × annual incidents / POBTOT", f"{mer.tasa_delitos_x1000hab:.2f}",
     f"state median {mu.tasa_delitos_x1000hab.median():.2f}"],
    ["", "Incidents by Type and Time", "Σ by type × month", f"top: {TYPES_EN.get(types.tipo_delito[0], types.tipo_delito[0])}",
     f"peak month {MONTHS_EN.get(peak.nombre_mes, peak.nombre_mes)} (Fig. C4)"],
    ["", "Crime vs Business Activity", "100 × annual incidents / businesses", f"{mer.delitos_x100negocios:.2f}",
     f"state median {mu.delitos_x100negocios.median():.2f}"],
], [0.13, 0.21, 0.24, 0.16, 0.26], "Table 4. Required KPIs (Mérida = locality 31-050-0001; crime = Mérida municipality)", keep=False)

# ---------------------------------------------------------------- 5. METHODS
H("5. Spatial Analysis Methods", "PHASE 3 · interpretation requirement: neighbourhood rule and its implications")
P("<b>Neighbourhood rule.</b> Two units are neighbours if they share an edge or a vertex (Queen contiguity); "
  "weights are row-standardised, so a spatial lag is the mean of the neighbours. One AGEB and two municipalities "
  "without contiguous neighbours were linked to their nearest neighbour (KNN, k = 1). <i>Implication:</i> large "
  "peripheral AGEBs receive many neighbours (up to 20) and small central ones few (mean 5.4), so central lags "
  "summarise a smaller area; results also depend on the unit chosen (MAUP). <b>Transformations.</b> Densities are "
  "analysed as log(1 + x). Small municipalities produce unstable rates, so the crime rate is smoothed with "
  "<b>Empirical Bayes</b> and also tested with the Assunção–Reis EB-standardised Moran's I. <b>Inference.</b> "
  "999 permutations, α = 0.05, fixed seed. Spearman's ρ is preferred to Pearson's r because distributions are "
  "heavily skewed.")

# ---------------------------------------------------------------- 6. RESULTS
H("6. Results", "PHASE 3 · requirements 1–5: distribution, correlation, global Moran, LISA, bivariate")
P("6.1 Geographic distribution", h2)
P("Age structure is <b>concentric</b>: residents aged 65+ concentrate in the historic centre and decline outward "
  "(Figure 3b). Schooling follows a <b>north–south gradient</b>, highest in the north and north-east (Fig. C1). "
  "Population density peaks in a ring around the centre rather than in the centre itself (3a), whereas business "
  "density peaks in the centre and radiates outward (3c). Professional (541) and ambulatory health services "
  "(621) dominate the centre and north-centre, and neighbourhood grocery retail (461) dominates the south and "
  "west (Fig. C2). At state scale, the smoothed crime rate is highest in Mérida and the municipalities to its "
  f"north and north-east (3d). In Mérida, {mer.delitos_2023_2025:,.0f} incidents were recorded in 2023–2025; the "
  "most frequent were " + ", ".join(TYPES_EN.get(x, x) for x in types.tipo_delito) +
  f", with a peak in {MONTHS_EN.get(peak.nombre_mes, peak.nombre_mes)} (Fig. C4).")
fig(FIG / "fig_key_maps.png", 3.9 * inch,
    "Figure 3. Selected indicators (quintiles): (a–c) AGEBs of Mérida, (d) municipalities, Mérida outlined. "
    "Full map sets: Figures C1–C3. [Phase 3 · Req. 1 Geographic distribution]")

P("6.2 Correlation", h2)
P("Figure 4 gives the full Spearman matrices, which extend the seven relationships tested in the analysis "
  "(Table 5). Population density and business density are positively associated (ρ = 0.43); the share of older "
  "residents rises with retail density (ρ = 0.38); and the active-population rate falls as businesses per resident "
  "rise (ρ = −0.36). The last two results are best read together: the historic centre combines an older "
  "population — which lowers the active rate — with many establishments, so age structure is a plausible "
  "confounder. Schooling and service density are unrelated (p = 0.32). At municipal scale the crime rate is not "
  "correlated with business or population density (ρ ≈ 0.06–0.09); Pearson's r is higher (≈ 0.27) only because "
  "of a few extreme values. Scatterplots: Figure C5.")
fig(FIG / "fig07_correlation_matrix.png", 5.9 * inch,
    "Figure 4. Spearman correlation matrices, (a) AGEB and (b) municipality. Bold values with * are significant "
    "at α = 0.05. [Phase 3 · Req. 2 Correlation]")
rows = [["Scale", "Relationship (x vs y)", "Spearman ρ", "p", "Pearson r", "Bivariate Moran (x vs Wy)"]]
EN = {"log_dens_pob": "population density", "log_dens_neg": "business density", "graproes": "schooling",
      "log_dens_serv": "service density", "pct_65_mas": "aged 65+", "log_dens_com": "retail density",
      "tasa_pea_pct": "active population rate", "log_neg_x1000": "businesses per 1,000",
      "negocios_x1000hab": "businesses per 1,000", "tasa_delitos_eb": "crime rate (EB)"}
for _, r in co.iterrows():
    m = bv[(bv.x == r.x) & (bv.y_rezagada == r.y)]
    b = f"{m.I_bv.iloc[0]:.3f} (p = {m.p_sim.iloc[0]:.3f})" if len(m) else "—"
    p = "<0.001" if r.spearman_p < 0.001 else f"{r.spearman_p:.3f}"
    rows.append(["AGEB" if r.escala == "AGEB" else "Municipality",
                 f"{EN.get(r.x, r.x).capitalize()} vs {EN.get(r.y, r.y)}",
                 f"{r.spearman_rho:.3f}", p, f"{r.pearson_r:.3f}", b])
table(rows, [0.13, 0.37, 0.11, 0.09, 0.1, 0.2], "Table 5. Tested relationships: correlation and bivariate spatial association", keep=False)

P("6.3 Global spatial autocorrelation", h2)
P("Every AGEB indicator is significantly clustered (Table 6). The strongest patterns concern composition, not "
  "density: age structure (I = 0.84) and schooling (I = 0.78) show that Mérida is strongly segregated by life "
  "stage and education; economic densities cluster at a moderate level (0.49–0.53). The Moran scatterplots "
  "(Figure 5) show the mechanism: the slope of each fitted line equals Moran's I, and most points fall in the "
  "High-High and Low-Low quadrants. Bar chart: Figure C6.")
rows = [["Scale", "Indicator", "Moran's I", "E[I]", "z", "p"]]
NICE = {"log_dens_pob": "Population density (log)", "log_dens_neg": "Business density (log)",
        "log_dens_com": "Retail density (log)", "log_dens_serv": "Service density (log)",
        "tasa_pea_pct": "Economically active population rate", "pct_65_mas": "Share aged 65+",
        "graproes": "Average years of schooling", "tasa_delitos_eb": "Crime rate, EB-smoothed",
        "tasa_delitos (Moran_Rate EB)": "Crime rate, EB-standardised (Assunção–Reis)"}
for _, r in mg.sort_values(["escala", "I"], ascending=[True, False]).iterrows():
    rows.append(["AGEB" if r.escala == "AGEB" else "Municipality", NICE.get(r.variable, r.variable),
                 f"{r.I:.3f}", f"{r.EI:.4f}", f"{r.z:.2f}", f"{r.p_sim:.3f}"])
table(rows, [0.16, 0.44, 0.11, 0.1, 0.09, 0.1], "Table 6. Global Moran's I (Queen contiguity, row-standardised, 999 permutations)", keep=False)
fig(FIG / "fig10_moran_scatterplots.png", 4.9 * inch,
    "Figure 5. Moran scatterplots: standardised value (x) against the mean of the neighbours (y). The slope is "
    "Moran's I; colours show the LISA class of each unit (p &lt; 0.05). Panel (f) is the bivariate case. "
    "[Phase 3 · Req. 3 Global Moran's I and Req. 5 Bivariate]")

P("6.4 Local spatial patterns (LISA)", h2)
P(f"For business density, {lc('log_dens_neg', 'HH')} AGEBs form a single High-High core around the historic "
  f"centre with an eastern extension, while {lc('log_dens_neg', 'LL')} Low-Low AGEBs lie along the northern and "
  f"north-eastern edge and the southern fringe (Figure 6a). Population density forms separate High-High pockets "
  f"({lc('log_dens_pob', 'HH')} AGEBs) in the southern, western and eastern inner ring, and Low-Low areas "
  f"({lc('log_dens_pob', 'LL')}) in the northern periphery (6b). At state scale (Figure 7a) the High-High crime "
  f"cluster is a corridor linking Mérida with the northern coast: {', '.join(hh_mun)}; Low-Low clusters occupy "
  "the south-centre and east.")
fig(FIG / "fig11_lisa_ageb.png", 4.2 * inch,
    "Figure 6. LISA clusters of (a) business density and (b) population density, AGEBs of Mérida, p &lt; 0.05. "
    "[Phase 3 · Req. 4 Local spatial patterns]")
fig(FIG / "fig13_lisa_municipal.png", 4.5 * inch,
    "Figure 7. (a) LISA of the EB-smoothed crime rate; (b) bivariate LISA, business density vs the neighbours' "
    "crime rate. Mérida outlined. [Phase 3 · Req. 4 and Req. 5]")

P("6.5 Bivariate spatial relationship", h2)
P("Dense residential AGEBs are surrounded by business-dense AGEBs (bivariate I = 0.28, p = 0.001; Figure 5f). "
  "The bivariate LISA (Fig. C7) locates this: the historic centre is Low-High — few residents surrounded by many "
  "businesses — inside a ring of High-High AGEBs where dense housing borders dense commerce. Across "
  "municipalities, dense municipalities border high-crime ones (I = 0.17, p = 0.006), whereas the "
  "business-density version is only marginal (I = 0.10, p = 0.057).")

# ---------------------------------------------------------------- 7. LIMITATIONS
H("7. Limitations, Cautions and Conclusion")
B("<b>No georeferenced or colonia-level crime</b>: safety is analysed only across municipalities. SESNSP counts "
  "investigation files, not offences, and the 2015–2022 drop likely reflects recording practice.")
B("<b>Different years</b> (census 2020, DENUE 2026, crime 2023–2025) and <b>small numbers</b>, mitigated with a "
  "100-resident threshold and EB smoothing; DENUE may under-represent informal activity.")
B("<b>MAUP and neighbourhood rule</b>: another unit or a distance-based rule could change magnitudes and cluster "
  "boundaries. <b>Association is not causation</b>: results describe co-location only.")
P("<b>Conclusion.</b> A reproducible PostgreSQL/PostGIS warehouse integrates four heterogeneous sources through a "
  "defensible two-scale model and computes every KPI from warehouse views. Mérida is structured concentrically by "
  "age and commerce and along a north–south axis by schooling; residential and commercial intensity co-locate "
  "across neighbouring areas; and recorded crime clusters along the Mérida–northern-coast corridor. "
  "Georeferenced incidents would let safety indicators enter the AGEB model.")
P("<b>References.</b> Anselin (1995) LISA, <i>Geographical Analysis</i> 27(2) · Assunção &amp; Reis (1999), "
  "<i>Statistics in Medicine</i> 18(16) · INEGI: Census 2020 by AGEB (2021), Marco Geoestadístico (2025), "
  "DENUE 05/2026 · Openshaw (1984) <i>The Modifiable Areal Unit Problem</i> · Rey &amp; Anselin (2007) PySAL, "
  "<i>Review of Regional Studies</i> 37(1) · SESNSP (2026) Incidencia delictiva municipal 2015–2025.",
  ParagraphStyle("ref", parent=small, fontSize=8.2, leading=9.8))

# ---------------------------------------------------------------- ANNEX A: TRACEABILITY
S.append(PageBreak())
H("Annex A. Brief Requirements and Rubric Traceability")
P("Each requirement of the Unit 2 brief, grouped by rubric component, with the evidence in this report and in the "
  "repository.", small)
table([
    ["Rubric component (pts)", "Brief requirement", "Evidence in this report", "Repository file"],
    ["Data &amp; geographic assessment (15)", "Source inventory and profiling", "Table 1, Section 1", "src/phase1_assessment.py, outputs/phase1/"],
    ["", "Candidate units and justified selection", "Table 2, Section 2", "README §2"],
    ["", "Polygons loaded: CRS, validity, identifiers", "Section 2", "outputs/phase1/phase1_report.txt"],
    ["", "Data-quality issues, assumptions, traceability", "Section 1, Section 7, dim_fuente", "README §9"],
    ["", "Lat/lon to points; point-to-polygon test", "Figure 1, Table 3", "sql/02_load.sql"],
    ["ETL, spatial integration &amp; reproducibility (20)", "Raw files unchanged; cleaning; CRS; grain; documented transformations", "Section 3", "src/etl.py, docker-compose.yml"],
    ["", "Validated load: counts, keys, relationships", "Section 3 (Validation)", "sql/04_validation.sql"],
    ["PostgreSQL/PostGIS DW (20)", "Fact/dimension tables, grain, keys", "Figure 2, Section 3", "sql/01_schema.sql"],
    ["", "Model diagram and data dictionary", "Figure 2", "docs/warehouse_model.png, docs/data_dictionary.md"],
    ["KPIs &amp; spatial analysis (15)", "14 required KPIs", "Table 4", "sql/03_views.sql"],
    ["", "Req. 1 Geographic distribution (maps)", "Figure 3; Figures C1–C4", "outputs/report_figures/"],
    ["", "Req. 2 Correlation (≥ 3 relationships)", "Figure 4, Table 5; Figure C5", "outputs/tables/correlaciones.csv"],
    ["", "Req. 3 Global Moran's I (≥ 2 indicators)", "Table 6, Figure 5; Figure C6", "outputs/tables/moran_global.csv"],
    ["", "Req. 4 Local Moran's I / LISA", "Figures 6–7", "outputs/tables/lisa_resultados.csv"],
    ["", "Req. 5 Bivariate Moran's I", "Table 5, Figures 5f, 7b; Figure C7", "outputs/tables/moran_bivariado.csv"],
    ["", "Neighbourhood rule and causation caution", "Sections 5 and 7", "src/phase3_spatial_analysis.py"],
    ["Collaboration &amp; Git history (20)", "Commits across phases", "—", "Git log of the repository"],
    ["Documentation &amp; report (10)", "README and 4–6 page report", "This document (Sections 1–7)", "README.md, docs/"],
    ["Beyond the brief", "Exploratory insights: beach season, schools vs children, jobs vs residence", "Annex B, Figures B1–B3", "src/extra_insights.py"],
], [0.21, 0.31, 0.23, 0.25], "Table A1. Requirement and rubric traceability")

# ---------------------------------------------------------------- ANNEX B: ADDITIONAL INSIGHTS
INS = TAB / "insights_summary.json"
if INS.exists():
    ins = json.loads(INS.read_text(encoding="utf-8"))
    MONTH = ["", "January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]

    def pv(p):
        return "p &lt; 0.001" if p < 0.001 else f"p = {p:.3f}"

    S.append(PageBreak())
    H("Annex B. Additional Insights (beyond the brief)")
    P("Three exploratory analyses use only data already in the warehouse to ask less obvious questions. They "
      "describe areas, not people (ecological fallacy), and show association, not causation. All numbers below are "
      "written by <font face='Mono' size='8'>src/build_report.py</font> from "
      "<font face='Mono' size='8'>outputs/tables/insights_summary.json</font>, produced by "
      "<font face='Mono' size='8'>src/extra_insights.py</font>.")

    b = ins["beach"]
    P("B.1 Is the crime corridor a beach-season effect?", h2)
    supported = (b["mannwhitney_p"] is not None and b["mannwhitney_p"] < 0.05
                 and b["median_index_coastal"] > b["median_index_inland"])
    txt = ("Crime rates use resident population, but in July and August many Mérida households move to the coast. "
           f"If visitors drive the coastal High-High corridor, coastal municipalities should concentrate their "
           f"incidents in those months. Coastal municipalities (n = {b["n_coastal"]}, those with a Gulf of Mexico coastline) "
           f"recorded {100 * b['summer_share_coastal']:.1f}% of their 2015–2025 incidents in July–August, against "
           f"{100 * b['summer_share_inland']:.1f}% inland and {100 * b['summer_share_merida']:.1f}% in Mérida; with no "
           f"seasonality the share would be {100 * b['expected_share']:.1f}%. The coastal profile peaks in "
           f"{MONTH[b['peak_month_coastal']]} and Mérida's in {MONTH[b['peak_month_merida']]}. Among municipalities "
           f"with at least 30 incidents, the median summer index is {b['median_index_coastal']:.2f} on the coast and "
           f"{b['median_index_inland']:.2f} inland (one-sided Mann–Whitney, {pv(b['mannwhitney_p'])}); the coast had "
           f"the higher summer share in {b['years_coastal_higher']} of {b['years_total']} years. "
           f"{b['hh_coastal']} of the {b['hh_total']} High-High crime municipalities are coastal. ")
    if max(b["summer_share_coastal"], b["summer_share_inland"], b["summer_share_merida"]) < b["expected_share"]:
        txt += ("Unexpectedly, July–August is below its expected share everywhere, Mérida included: recorded crime "
                "dips in the summer holidays rather than rising. ")
    if supported:
        txt += (f"<b>The hypothesis is supported.</b> Part of the coastal corridor reflects seasonal visitors that a "
                f"resident denominator ignores; excluding July–August, the coastal rate changes from "
                f"{b['rate_coastal_full']:.2f} to {b['rate_coastal_offseason']:.2f} incidents per 1,000 residents a year.")
    else:
        txt += ("<b>The hypothesis is not supported</b> by monthly totals: coastal crime is not significantly "
                "concentrated in July–August, so the corridor is not simply a summer-visitor artefact. "
                f"Excluding July–August, the coastal rate changes from {b['rate_coastal_full']:.2f} to "
                f"{b['rate_coastal_offseason']:.2f} per 1,000.")
    P(txt + " <i>Caveat:</i> Easter week, the other beach peak, moves between March and April and cannot be "
      "isolated with monthly data.")
    fig(FIG / "fig14_beach_season.png", W,
        "Figure B1. (a) Summer index = share of incidents in July–August divided by the share expected without "
        "seasonality; (b) monthly profile by group; (c) summer index by municipality. [Beyond the brief]")

    s = ins["schools"]
    P("B.2 Do schools follow the children?", h2)
    r2, r3, r4 = s["rho_kidsshare_kidsperschool"], s["rho_centre_kidsperschool"], s["rho_schooling_private"]
    txt = (f"The warehouse holds {s['n_schools']:,} basic-education establishments (preschool to lower secondary, "
           f"{s['private_share']:.0f}% private). The median AGEB is {s['median_dist_m']:,.0f} m from the nearest "
           f"school and the 90th percentile {s['p90_dist_m']:,.0f} m. Counting school-age children (3–14) and schools "
           f"within 1 km of each AGEB, the median is {s['median_kids_per_school']:,.0f} children per school. ")
    if r2[1] < 0.05 and r2[0] > 0.2:
        txt += (f"<b>School supply has not followed the young population:</b> AGEBs with more children have more "
                f"children per nearby school (ρ = {r2[0]:.2f}, {pv(r2[1])}). ")
    elif r2[1] < 0.05 and r2[0] < -0.2:
        txt += (f"<b>Schools are more abundant where children concentrate</b> (ρ = {r2[0]:.2f}, {pv(r2[1])}). ")
    else:
        txt += f"Children per school is not clearly related to the share of children (ρ = {r2[0]:.2f}, {pv(r2[1])}). "
    txt += (f"Pressure {'rises' if r3[0] > 0 else 'falls'} with distance to the historic centre (ρ = {r3[0]:.2f}, "
            f"{pv(r3[1])}) and is spatially clustered (Moran's I = {s['moran_I']:.2f}, {pv(s['moran_p'])}). ")
    if s["n_hh"] and s["hh_kids_share"] is not None:
        txt += (f"The {s['n_hh']} High-High AGEBs — candidate under-served areas — have {s['hh_kids_share']:.1f}% "
                f"children against {s['city_kids_share']:.1f}% citywide and lie a median "
                f"{s['hh_median_dist_centre_km']:.1f} km from the centre ({s['city_median_dist_centre_km']:.1f} km for "
                "all AGEBs). ")
    if r4[1] < 0.05 and abs(r4[0]) > 0.2:
        txt += (f"The private share of nearby schools {'rises' if r4[0] > 0 else 'falls'} with adult schooling "
                f"(ρ = {r4[0]:.2f}), a socioeconomic sorting of school supply. ")
    else:
        txt += f"The private share of nearby schools is not clearly related to adult schooling (ρ = {r4[0]:.2f}). "
    P(txt + "<i>Caveat:</i> DENUE counts establishments, not capacity or enrolment; children are from 2020 and "
      "schools from 2026.")
    fig(FIG / "fig15_schools_children.png", 5.6 * inch,
        "Figure B2. School supply vs school-age population: (a) children per basic school within 1 km (dark grey = "
        "no school within 1 km), (b) LISA, (c) share of children vs children per school, (d) private share vs adult "
        "schooling. [Beyond the brief]")

    j = ins["jobs"]
    P("B.3 Where people work vs where they live", h2)
    rj = j["rho_dist_ratio"]
    txt = (f"Summing staff-size midpoints gives about {j['est_jobs']:,.0f} establishment jobs against "
           f"{j['resident_workers']:,.0f} employed residents (ratio {j['city_ratio']:.2f}); DENUE omits informal and "
           f"home-based work and the midpoints are approximate, so levels are indicative and the spatial pattern is "
           f"what matters. The top 10% of AGEBs hold {j['share_jobs_top10pct_ageb']:.0f}% of the jobs. "
           f"{j['pct_dormitory']:.0f}% of AGEBs are dormitory areas (under one job per two resident workers) and "
           f"{j['pct_job_centre']:.0f}% are job centres (over two). The ratio {'falls' if rj[0] < 0 else 'rises'} "
           f"with distance to the historic centre (ρ = {rj[0]:.2f}, {pv(rj[1])}) and clusters (Moran's I = "
           f"{j['moran_I']:.2f}). Estimated daytime population reaches {j['max_day_night']:.0f} times the resident "
           "population in the most commercial AGEB. ")
    if rj[0] < -0.2 and rj[1] < 0.05:
        txt += ("<b>This is the mechanism behind the Low-High centre in Section 6.5</b>: who is in an area during "
                "the day differs sharply from who lives there, so per-resident rates overstate intensity in the "
                "centre — the same denominator problem that B.1 tests on the coast.")
    else:
        txt += ("Jobs are not strongly concentrated towards the centre, so the Low-High centre of Section 6.5 is "
                "not explained by employment alone.")
    P(txt)
    fig(FIG / "fig16_jobs_residence.png", W,
        "Figure B3. (a) Estimated jobs per resident worker (log2), (b) LISA of the ratio, (c) ratio by 1-km ring "
        "from the historic centre. [Beyond the brief]")
else:
    print("Note: outputs/tables/insights_summary.json not found - run src/extra_insights.py to add Annex B.")

# ---------------------------------------------------------------- ANNEX C: FIGURES
S.append(CondPageBreak(3 * inch))
H("Annex C. Complete Figure Set")
fig(FIG / "fig03_demographic_maps.png", 5.6 * inch,
    "Figure C1. Demographic indicators by AGEB, Census 2020 (quintiles; grey = no census data). [Req. 1]")
fig(FIG / "fig04_economic_maps.png", 5.6 * inch,
    "Figure C2. Economic indicators by AGEB, DENUE 05/2026 (quintiles). [Req. 1]")
fig(FIG / "fig05_municipal_safety_maps.png", 6.3 * inch,
    "Figure C3. Public-safety and business indicators by municipality, SESNSP 2023–2025 average; Mérida outlined. [Req. 1]")
fig(FIG / "fig06_crime_type_time.png", W,
    "Figure C4. Incidents by type and time (KPI 'Incidents by Type and Time'). [Req. 1]")
fig(FIG / "fig08_correlation_scatter.png", W,
    "Figure C5. Scatterplots of the tested relationships with Spearman's ρ and a least-squares line. [Req. 2]")
if (FIG / "fig09_moran_global.png").exists():
    fig(FIG / "fig09_moran_global.png", W, "Figure C6. Global Moran's I by indicator and scale. [Req. 3]")
fig(FIG / "fig12_lisa_bivariate_ageb.png", 4.4 * inch,
    "Figure C7. Bivariate LISA: population density (x) vs the neighbours' business density (Wy). [Req. 5]")


def footer(c, d):
    c.saveState()
    c.setFont("Sans", 7.5)
    c.setFillColor(colors.HexColor("#52514e"))
    c.drawString(0.7 * inch, 0.45 * inch, "Mérida Urban Intelligence · Technical Report")
    c.drawRightString(letter[0] - 0.7 * inch, 0.45 * inch, str(d.page))
    c.restoreState()


OUT.parent.mkdir(exist_ok=True)
doc = SimpleDocTemplate(str(OUT), pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                        topMargin=0.6 * inch, bottomMargin=0.7 * inch,
                        title="Mérida Urban Intelligence - Technical Report",
                        author="Yazira Abyade Hernández Rives")
doc.build(S, onFirstPage=footer, onLaterPages=footer)
print(f"Report written to {OUT}")
