"""
Dashboard - Merida Urban Intelligence
Lee del Data Warehouse (PostGIS) y de los resultados de la Fase 3 (outputs/).

Uso (desde la raiz del repo, con la base levantada):
    streamlit run src/dashboard.py
"""
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
DB_URL = os.getenv("DATABASE_URL",
                   "postgresql+psycopg2://merida:merida123@localhost:5433/merida_dw")

st.set_page_config(page_title="Merida Urban Intelligence", page_icon="🗺️", layout="wide")


# ---------------------------------------------------------------- DATOS
@st.cache_resource
def engine():
    return create_engine(DB_URL)


@st.cache_data
def load_geo(view):
    g = gpd.read_postgis(f"SELECT * FROM dw.{view}", engine(), geom_col="geom")
    for c in g.columns:
        if c not in ("geom", "cvegeo", "nom_mun", "subsector_dominante", "tiene_censo"):
            g[c] = pd.to_numeric(g[c], errors="coerce")
    g["geom"] = g.geometry.simplify(0.0002, preserve_topology=True)
    return g


@st.cache_data
def load_sql(q):
    return pd.read_sql(q, engine())


def choropleth(gdf, col, label, zoom, center, hover):
    gj = gdf.set_index("cvegeo")[["geom"]].__geo_interface__
    fig = px.choropleth_map(
        gdf.drop(columns="geom"), geojson=gj, locations="cvegeo", featureidkey="id",
        color=col, color_continuous_scale="YlOrRd", map_style="carto-positron",
        zoom=zoom, center=center, opacity=0.75, hover_data=hover,
        labels={col: label})
    # escala robusta: evita que un valor extremo pinte todo del mismo color
    lo, hi = gdf[col].quantile([0.02, 0.98])
    fig.update_coloraxes(cmin=lo, cmax=hi)
    fig.update_layout(height=600, margin=dict(l=0, r=0, t=0, b=0))
    return fig


def csv(name):
    p = OUT / "tables" / name
    return pd.read_csv(p) if p.exists() else None


def image(name, caption):
    p = OUT / "maps" / name
    if p.exists():
        st.image(str(p), caption=caption, use_container_width=True)
    else:
        st.info(f"Falta {name}: corre primero `python src/phase3_spatial_analysis.py`.")


try:
    ageb = load_geo("v_kpi_ageb")
    mun = load_geo("v_kpi_municipio")
except Exception as e:
    st.error("No se pudo conectar al Data Warehouse. ¿Está corriendo `docker compose up -d` "
             f"y ya corriste `python src/etl.py`?\n\n{e}")
    st.stop()

MERIDA = dict(lat=20.98, lon=-89.62)
YUCATAN = dict(lat=20.75, lon=-88.9)

# ---------------------------------------------------------------- MENU
st.sidebar.title("🗺️ Mérida Urban Intelligence")
page = st.sidebar.radio("Secciones", [
    "🏠 Resumen",
    "👥 Población (AGEB)",
    "🏪 Actividad económica (AGEB)",
    "🚨 Seguridad pública (municipios)",
    "📊 Análisis espacial",
    "🗄️ Datos y fuentes",
])
st.sidebar.markdown("---")
st.sidebar.caption("Fuentes: INEGI Censo 2020, DENUE 05/2026, Marco Geoestadístico 2025, "
                   "SESNSP 2015–2025. Delitos sin coordenadas: se analizan por municipio.")

# ---------------------------------------------------------------- RESUMEN
if page == "🏠 Resumen":
    st.title("Mérida Urban Intelligence")
    st.write("Data Warehouse geoespacial que integra población, negocios y delitos para "
             "comparar zonas de Mérida y detectar patrones espaciales.")
    m = mun[mun.cvegeo == "31050"].iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Población (localidad Mérida)", f"{ageb.pobtot.sum():,.0f}")
    c2.metric("Negocios en AGEB urbanas", f"{ageb.negocios.sum():,.0f}")
    c3.metric("Delitos Mérida 2023–2025", f"{m.delitos_2023_2025:,.0f}")
    c4.metric("Tasa de delitos (x1000 hab/año)", f"{m.tasa_delitos_x1000hab:.2f}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AGEB analizadas", f"{len(ageb)}")
    c2.metric("Densidad media (hab/km²)", f"{ageb.densidad_pob_km2.median():,.0f}")
    c3.metric("Tasa de PEA media", f"{ageb.tasa_pea_pct.median():.1f}%")
    c4.metric("Negocios por 1000 hab (mediana)", f"{ageb.negocios_x1000hab.median():.1f}")
    st.subheader("¿Cómo está construido?")
    st.markdown(
        "- **Dos escalas:** AGEB urbana (501 zonas) para población y negocios; municipio "
        "(106) para delitos, porque el SESNSP no publica coordenadas ni datos por colonia.\n"
        "- **Integración:** censo por clave CVEGEO; negocios del DENUE por coordenadas con "
        "unión punto-en-polígono en PostGIS (99.8% asignados).\n"
        "- **Análisis:** correlaciones, Moran's I global, LISA y Moran bivariado.")

# ---------------------------------------------------------------- POBLACION
elif page == "👥 Población (AGEB)":
    st.title("Población por AGEB — Censo 2020")
    opciones = {
        "Densidad de población (hab/km²)": "densidad_pob_km2",
        "Población total": "pobtot",
        "Tasa de PEA (%)": "tasa_pea_pct",
        "Población de 0 a 14 años (%)": "pct_0_14",
        "Población de 15 a 64 años (%)": "pct_15_64",
        "Población de 65 años y más (%)": "pct_65_mas",
        "Grado promedio de escolaridad": "graproes",
    }
    label = st.selectbox("Indicador", list(opciones))
    col = opciones[label]
    d = ageb.dropna(subset=[col])
    st.plotly_chart(choropleth(d, col, label, 10.5, MERIDA, ["pobtot"]), use_container_width=True)
    c1, c2 = st.columns(2)
    c1.markdown("**10 AGEB con valor más alto**")
    c1.dataframe(d.nlargest(10, col)[["cvegeo", col, "pobtot"]], hide_index=True)
    c2.markdown("**Distribución**")
    c2.plotly_chart(px.histogram(d, x=col, nbins=40, labels={col: label}),
                    use_container_width=True)
    st.caption("Gris / sin color: AGEB sin datos del censo (creadas después de 2020) o con datos confidenciales.")

# ---------------------------------------------------------------- ECONOMIA
elif page == "🏪 Actividad económica (AGEB)":
    st.title("Actividad económica por AGEB — DENUE 05/2026")
    opciones = {
        "Densidad de negocios (por km²)": "dens_negocios_km2",
        "Negocios totales": "negocios",
        "Negocios por 1000 habitantes": "negocios_x1000hab",
        "Densidad de comercio al por menor (SCIAN 46)": "dens_comercio_km2",
        "Densidad de servicios (SCIAN 51–81)": "dens_servicios_km2",
    }
    label = st.selectbox("Indicador", list(opciones))
    col = opciones[label]
    d = ageb.dropna(subset=[col])
    st.plotly_chart(choropleth(d, col, label, 10.5, MERIDA, ["negocios", "subsector_dominante"]),
                    use_container_width=True)
    c1, c2 = st.columns(2)
    sub = load_sql("""
        SELECT s.subsector, MIN(s.nombre_act) AS ejemplo, COUNT(*) AS negocios
        FROM dw.fact_establecimiento f
        JOIN dw.dim_scian s USING (scian_key)
        JOIN dw.dim_geografia g ON g.geo_key = f.geo_ageb_key
        WHERE g.en_localidad_merida
        GROUP BY 1 ORDER BY 3 DESC LIMIT 10""")
    c1.markdown("**Subsectores SCIAN con más negocios**")
    c1.plotly_chart(px.bar(sub.sort_values("negocios"), x="negocios", y="subsector",
                           orientation="h", hover_data=["ejemplo"]), use_container_width=True)
    tam = load_sql("""
        SELECT t.per_ocu, t.orden, COUNT(*) AS negocios
        FROM dw.fact_establecimiento f
        JOIN dw.dim_tamano t USING (tamano_key)
        JOIN dw.dim_geografia g ON g.geo_key = f.geo_ageb_key
        WHERE g.en_localidad_merida
        GROUP BY 1, 2 ORDER BY 2""")
    c2.markdown("**Negocios por tamaño (personal ocupado)**")
    c2.plotly_chart(px.bar(tam, x="per_ocu", y="negocios"), use_container_width=True)

# ---------------------------------------------------------------- SEGURIDAD
elif page == "🚨 Seguridad pública (municipios)":
    st.title("Seguridad pública por municipio — SESNSP")
    st.info("El SESNSP publica los delitos por municipio, sin coordenadas ni colonia. "
            "Por eso esta sección compara los 106 municipios de Yucatán.")
    opciones = {
        "Tasa de delitos (x1000 hab/año, 2023–2025)": "tasa_delitos_x1000hab",
        "Delitos por cada 100 negocios": "delitos_x100negocios",
        "Delitos totales 2023–2025": "delitos_2023_2025",
        "Densidad de negocios (por km²)": "dens_negocios_km2",
    }
    label = st.selectbox("Indicador", list(opciones))
    col = opciones[label]
    st.plotly_chart(choropleth(mun.dropna(subset=[col]), col, label, 6.8, YUCATAN,
                               ["nom_mun", "pobtot", "negocios"]), use_container_width=True)
    st.caption("Municipios pequeños pueden tener tasas extremas por pocos casos; "
               "en el análisis espacial se usa la tasa suavizada (Empirical Bayes).")

    st.subheader("Delitos por tipo y tiempo")
    nombres = mun.sort_values("nom_mun")[["cvegeo", "nom_mun"]]
    idx = int(nombres.reset_index(drop=True).index[nombres.cvegeo.values == "31050"][0])
    sel = st.selectbox("Municipio", nombres.nom_mun.tolist(), index=idx)
    cve = nombres.loc[nombres.nom_mun == sel, "cvegeo"].iloc[0]
    tt = load_sql(f"""
        SELECT anio, mes, tipo_delito, SUM(incidentes) AS incidentes
        FROM dw.v_delitos_tipo_tiempo WHERE cvegeo = '{cve}'
        GROUP BY 1, 2, 3""")
    if tt.empty:
        st.warning("Sin delitos registrados para este municipio.")
    else:
        tt["fecha"] = pd.to_datetime(dict(year=tt.anio, month=tt.mes, day=1))
        c1, c2 = st.columns(2)
        serie = tt.groupby("fecha", as_index=False).incidentes.sum()
        c1.markdown(f"**{sel}: incidentes por mes, 2015–2025**")
        c1.plotly_chart(px.line(serie, x="fecha", y="incidentes"), use_container_width=True)
        top = (tt[tt.anio >= 2023].groupby("tipo_delito", as_index=False).incidentes.sum()
               .nlargest(8, "incidentes").sort_values("incidentes"))
        c2.markdown(f"**{sel}: principales tipos, 2023–2025**")
        c2.plotly_chart(px.bar(top, x="incidentes", y="tipo_delito", orientation="h"),
                        use_container_width=True)

# ---------------------------------------------------------------- ANALISIS ESPACIAL
elif page == "📊 Análisis espacial":
    st.title("Análisis espacial")
    tab1, tab2, tab3, tab4 = st.tabs(["Moran's I global", "Correlaciones",
                                      "Clusters LISA", "Moran bivariado"])
    with tab1:
        st.markdown("**¿Los valores parecidos están juntos en el mapa?** "
                    "I cercano a 0 = al azar; positivo = agrupamiento.")
        mg = csv("moran_global.csv")
        if mg is not None:
            st.dataframe(mg.round(4), hide_index=True, use_container_width=True)
            st.plotly_chart(px.bar(mg, x="I", y="variable", color="escala", orientation="h"),
                            use_container_width=True)
    with tab2:
        st.markdown("**Spearman**: se prefiere porque los datos están muy sesgados.")
        co = csv("correlaciones.csv")
        if co is not None:
            st.dataframe(co[["escala", "relacion", "n", "spearman_rho", "spearman_p", "pearson_r"]]
                         .round(4), hide_index=True, use_container_width=True)
    with tab3:
        st.markdown("**HH** = punto caliente, **LL** = punto frío, **HL/LH** = atípicos (p < 0.05).")
        vista = st.radio("Mapa", ["AGEB de Mérida", "Municipios (delitos)"], horizontal=True)
        if vista == "AGEB de Mérida":
            image("04_lisa_ageb.png", "LISA: densidad de negocios y de población")
        else:
            image("05_lisa_municipio.png", "LISA: tasa de delitos (EB) y bivariado negocios–delitos")
    with tab4:
        st.markdown("Relaciona una variable de cada zona con **otra variable de sus vecinos**.")
        bv = csv("moran_bivariado.csv")
        if bv is not None:
            st.dataframe(bv.round(4), hide_index=True, use_container_width=True)
        image("06_lisa_bivariado_ageb.png", "Densidad de población vs negocios de las AGEB vecinas")

# ---------------------------------------------------------------- DATOS
elif page == "🗄️ Datos y fuentes":
    st.title("Datos, fuentes y modelo")
    st.subheader("Fuentes (dim_fuente)")
    st.dataframe(load_sql("SELECT codigo, nombre, edicion, archivo, grano_original FROM dw.dim_fuente"),
                 hide_index=True, use_container_width=True)
    st.subheader("Registros en el Data Warehouse")
    st.dataframe(load_sql("""
        SELECT 'fact_censo' AS tabla, COUNT(*) AS registros FROM dw.fact_censo
        UNION ALL SELECT 'fact_establecimiento', COUNT(*) FROM dw.fact_establecimiento
        UNION ALL SELECT 'fact_delito_mensual', COUNT(*) FROM dw.fact_delito_mensual
        UNION ALL SELECT 'dim_geografia', COUNT(*) FROM dw.dim_geografia"""),
        hide_index=True)
    modelo = ROOT / "docs" / "warehouse_model.png"
    if modelo.exists():
        st.subheader("Modelo dimensional")
        st.image(str(modelo), use_container_width=True)
    st.subheader("Limitaciones")
    st.markdown(
        "- Sin delitos georreferenciados ni por colonia: la seguridad se analiza por municipio.\n"
        "- Los datos del SESNSP son carpetas de investigación (hay cifra negra).\n"
        "- Años distintos: censo 2020, DENUE 2026, delitos 2023–2025.\n"
        "- Correlación espacial no implica causalidad.")
