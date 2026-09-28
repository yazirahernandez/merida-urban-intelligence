"""
ETL - Merida Urban Intelligence
RAW (zip/csv originales, sin modificar) -> CLEAN (pandas/geopandas)
-> stg.* (PostGIS) -> SPATIAL JOIN + modelo dimensional (sql/02_load.sql) -> dw.*

Uso (desde la raiz del repo, con la base levantada: docker compose up -d):
    python src/etl.py

Conexion: variable de entorno DATABASE_URL o, por defecto,
postgresql://merida:merida123@localhost:5433/merida_dw
"""
import os
import re
import sys
import time
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SQL = ROOT / "sql"

CENSO_ZIP = RAW / "censo" / "resageburb_31csv20.zip"
MARCO_ZIP = RAW / "marco_geo" / "31_yucatan.zip"
DENUE_DIR = RAW / "denue"
DELITOS_CSV = RAW / "delitos" / "Municipal-Delitos-2015-2025_ene2026.csv"

DB_URL = os.getenv("DATABASE_URL",
                   "postgresql+psycopg2://merida:merida123@localhost:5433/merida_dw")
ENT = "31"
CRS_METRIC = "EPSG:6372"   # Mexico ITRF2008 LCC, metros (para areas)
CRS_STORE = 4326
BBOX_YUC = dict(lat=(19.5, 21.8), lon=(-90.6, -87.4))   # filtro de coordenadas absurdas

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

CENSO_VARS = ["POBTOT", "POBFEM", "POBMAS", "P_0A2", "P_3A5", "P_6A11", "P_12A14",
              "P_15A17", "P_18A24", "POB0_14", "POB15_64", "POB65_MAS", "P_60YMAS",
              "P_12YMAS", "P_15YMAS", "P_18YMAS", "PEA", "PE_INAC", "POCUPADA",
              "PDESOCUP", "GRAPROES", "PSINDER", "PDER_SS", "TOTHOG", "VIVTOT",
              "TVIVHAB", "VIVPAR_HAB", "VIVPAR_DES", "VPH_INTER", "VPH_AUTOM",
              "VPH_PC", "PROM_OCUP"]

# comercio_minorista = SCIAN 46 (Retail Density); servicios = SCIAN 51-81 (Service Density)
SECTOR_GRUPO = {
    "11": "primario", "21": "industria", "22": "industria", "23": "industria",
    "31": "industria", "32": "industria", "33": "industria",
    "43": "comercio_mayorista", "46": "comercio_minorista",
    "48": "transporte", "49": "transporte", "93": "gobierno",
    **{s: "servicios" for s in ["51", "52", "53", "54", "55", "56",
                                "61", "62", "71", "72", "81"]},
}


def step(msg):
    print(f"\n[{time.strftime('%H:%M:%S')}] {msg}")


def run_sql_file(engine, path):
    """Ejecuta un archivo .sql completo (varias sentencias) en una transaccion."""
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(Path(path).read_text(encoding="utf-8"))
        raw.commit()
    finally:
        raw.close()


def to_multipolygon(geom):
    return MultiPolygon([geom]) if geom.geom_type == "Polygon" else geom


# ---------------------------------------------------------------- EXTRACT + CLEAN
def clean_geografia():
    layers = {}
    for layer, name in [("31a", "ageb"), ("31mun", "municipio")]:
        g = gpd.read_file(f"zip://{MARCO_ZIP.as_posix()}!conjunto_de_datos/{layer}.shp")
        g.columns = [c.lower() if c != "geometry" else c for c in g.columns]
        assert g.crs is not None, f"{layer} sin CRS"
        invalid = (~g.is_valid).sum()
        if invalid:
            print(f"  {layer}: {invalid} geometrias invalidas -> make_valid")
            g["geometry"] = g.make_valid()
        g["area_km2"] = g.to_crs(CRS_METRIC).area / 1e6
        g = g.to_crs(CRS_STORE)
        g["geometry"] = g.geometry.apply(to_multipolygon)
        g = g.rename_geometry("geom")
        assert not g.cvegeo.duplicated().any(), f"{layer}: CVEGEO duplicado"
        layers[name] = g
        print(f"  {layer}: {len(g)} poligonos | CRS original -> EPSG:{CRS_STORE}")
    return layers["ageb"], layers["municipio"]


def clean_censo():
    with zipfile.ZipFile(CENSO_ZIP) as z:
        name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        df = pd.read_csv(z.open(name), dtype=str, encoding="utf-8")
    df = df[df.ENTIDAD == ENT]
    mun = df[(df.MUN != "000") & (df.LOC == "0000") & (df.AGEB == "0000") & (df.MZA == "000")].copy()
    mun["cvegeo"], mun["nivel"] = mun.ENTIDAD + mun.MUN, "municipio"
    ageb = df[(df.AGEB != "0000") & (df.MZA == "000")].copy()
    ageb["cvegeo"] = ageb.ENTIDAD + ageb.MUN + ageb.LOC + ageb.AGEB
    ageb["nivel"] = "ageb"
    out = pd.concat([mun, ageb])[["cvegeo", "nivel"] + CENSO_VARS]
    # '*' = dato confidencial (<3 unidades) y 'N/D' = no disponible -> NULL (no cero)
    n_mask = int(out[CENSO_VARS].isin(["*", "N/D"]).sum().sum())
    for v in CENSO_VARS:
        out[v] = pd.to_numeric(out[v].replace({"*": None, "N/D": None}), errors="coerce")
    out.columns = [c.lower() for c in out.columns]
    assert not out.cvegeo.duplicated().any()
    print(f"  municipios: {len(mun)} | AGEB urbanas: {len(ageb)} | celdas '*'/N/D -> NULL: {n_mask}")
    return out


def clean_denue():
    zpath = sorted(DENUE_DIR.glob("*.zip"))[0]
    with zipfile.ZipFile(zpath) as z:
        name = max([n for n in z.namelist() if n.lower().endswith(".csv")
                    and "diccionario" not in n.lower()], key=lambda n: z.getinfo(n).file_size)
        try:
            df = pd.read_csv(z.open(name), dtype=str, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(z.open(name), dtype=str, encoding="latin-1")
    df.columns = df.columns.str.strip().str.lower()
    n0 = len(df)
    df = df.drop_duplicates(subset="id")
    df["id"] = pd.to_numeric(df.id, errors="coerce").astype("Int64")
    df["latitud"] = pd.to_numeric(df.latitud, errors="coerce")
    df["longitud"] = pd.to_numeric(df.longitud, errors="coerce")
    ok = (df.id.notna() & df.latitud.between(*BBOX_YUC["lat"])
          & df.longitud.between(*BBOX_YUC["lon"]))
    df = df[ok].copy()
    df["cve_ent"] = df.cve_ent.str.zfill(2)
    df["cve_mun"] = df.cve_mun.str.zfill(3)
    df["codigo_act"] = df.codigo_act.str.strip().str.zfill(6)
    df["nombre_act"] = df.nombre_act.str.strip()
    df["per_ocu"] = df.per_ocu.str.strip()
    df["grupo_kpi"] = df.codigo_act.str[:2].map(SECTOR_GRUPO).fillna("sin_clasificar")
    has_ageb = df.ageb.notna() & df.cve_loc.notna()
    df["cvegeo_ageb_reportado"] = None
    df.loc[has_ageb, "cvegeo_ageb_reportado"] = (
        df.cve_ent + df.cve_mun + df.cve_loc.str.zfill(4) + df.ageb.str.zfill(4))[has_ageb]
    # fecha_alta 'YYYY-MM' -> YYYYMM
    fa = df.fecha_alta.fillna("").str.extract(r"(\d{4})\D?(\d{2})")
    df["alta_tiempo_key"] = pd.to_numeric(fa[0] + fa[1], errors="coerce").astype("Int64")
    cols = ["id", "nom_estab", "codigo_act", "nombre_act", "grupo_kpi", "per_ocu",
            "cve_ent", "cve_mun", "cvegeo_ageb_reportado", "alta_tiempo_key",
            "latitud", "longitud"]
    print(f"  filas: {n0:,} -> {len(df):,} (duplicados o coordenadas invalidas: {n0 - len(df)})")
    print(f"  sin clasificar SCIAN: {(df.grupo_kpi == 'sin_clasificar').sum()}")
    return df[cols]


def clean_delitos():
    df = pd.read_csv(DELITOS_CSV, encoding="latin-1", dtype=str)
    df = df[pd.to_numeric(df.Clave_Ent, errors="coerce") == int(ENT)].copy()
    df["cvegeo"] = df["Cve. Municipio"].str.strip().str.zfill(5)
    df = df.rename(columns={"Año": "anio", "Bien jurídico afectado": "bien_juridico",
                            "Tipo de delito": "tipo_delito", "Subtipo de delito": "subtipo_delito",
                            "Modalidad": "modalidad"})
    # Fallback por si la codificacion cambia los encabezados con acento
    df.columns = [re.sub(r"^A.o$", "anio", c) for c in df.columns]
    df = df.rename(columns={c: "bien_juridico" for c in df.columns if c.startswith("Bien jur")})
    long = df.melt(id_vars=["anio", "cvegeo", "bien_juridico", "tipo_delito",
                            "subtipo_delito", "modalidad"],
                   value_vars=MESES, var_name="mes", value_name="incidentes")
    long["incidentes"] = pd.to_numeric(long.incidentes, errors="coerce")
    n_na = long.incidentes.isna().sum()
    long = long[long.incidentes.fillna(0) > 0]        # los ceros no aportan a sumas
    long["tiempo_key"] = (long.anio.astype(int) * 100
                          + long.mes.map({m: i + 1 for i, m in enumerate(MESES)}))
    for c in ["bien_juridico", "tipo_delito", "subtipo_delito", "modalidad"]:
        long[c] = long[c].str.strip()
    long["incidentes"] = long.incidentes.astype(int)
    print(f"  filas anchas: {len(df):,} -> largas con incidentes>0: {len(long):,} "
          f"| meses nulos: {n_na} | total incidentes: {long.incidentes.sum():,}")
    return long[["cvegeo", "tiempo_key", "bien_juridico", "tipo_delito",
                 "subtipo_delito", "modalidad", "incidentes"]]


# ---------------------------------------------------------------- MAIN
def main():
    engine = create_engine(DB_URL)
    with engine.connect() as con:
        con.execute(text("SELECT 1"))

    step("1/6 Esquema (sql/01_schema.sql)")
    run_sql_file(engine, SQL / "01_schema.sql")

    step("2/6 Geografia: Marco Geoestadistico")
    ageb, mun = clean_geografia()
    ageb[["cvegeo", "cve_ent", "cve_mun", "cve_loc", "cve_ageb", "area_km2", "geom"]] \
        .to_postgis("geo_ageb", engine, schema="stg", if_exists="replace", index=False)
    mun[["cvegeo", "cve_ent", "cve_mun", "nomgeo", "area_km2", "geom"]] \
        .to_postgis("geo_municipio", engine, schema="stg", if_exists="replace", index=False)

    step("3/6 Censo 2020")
    clean_censo().to_sql("censo", engine, schema="stg", if_exists="replace", index=False)

    step("4/6 DENUE")
    clean_denue().to_sql("denue", engine, schema="stg", if_exists="replace",
                         index=False, chunksize=10_000, method="multi")

    step("5/6 Delitos SESNSP")
    clean_delitos().to_sql("delitos", engine, schema="stg", if_exists="replace",
                           index=False, chunksize=10_000, method="multi")

    step("6/6 Carga del DW + union espacial (sql/02_load.sql) y vistas (sql/03_views.sql)")
    run_sql_file(engine, SQL / "02_load.sql")
    run_sql_file(engine, SQL / "03_views.sql")

    step("Validacion (sql/04_validation.sql)")
    checks = re.split(r"^-- @check ", (SQL / "04_validation.sql").read_text(encoding="utf-8"),
                      flags=re.M)[1:]
    with engine.connect() as con:
        for chk in checks:
            title, query = chk.split("\n", 1)
            print(f"\n--- {title.strip()}")
            print(pd.read_sql(text(query.strip().rstrip(";")), con).to_string(index=False))
    print("\nETL terminado.")


if __name__ == "__main__":
    sys.exit(main())
