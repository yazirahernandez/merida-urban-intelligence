-- =====================================================================
-- 01_schema.sql  -  Merida Urban Intelligence Data Warehouse
-- Crea los esquemas stg (staging) y dw (modelo dimensional).
-- Es idempotente: borra y recrea las tablas del DW.
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS dw;

DROP VIEW  IF EXISTS dw.v_kpi_ageb, dw.v_kpi_municipio, dw.v_delitos_tipo_tiempo CASCADE;
DROP TABLE IF EXISTS dw.fact_delito_mensual, dw.fact_establecimiento, dw.fact_censo CASCADE;
DROP TABLE IF EXISTS dw.dim_geografia, dw.dim_tiempo, dw.dim_delito,
                     dw.dim_scian, dw.dim_tamano, dw.dim_fuente CASCADE;

-- ---------------------------------------------------------------- DIMENSIONES

-- Trazabilidad: de que archivo/edicion viene cada hecho
CREATE TABLE dw.dim_fuente (
    fuente_key      SMALLSERIAL PRIMARY KEY,
    codigo          VARCHAR(20) UNIQUE NOT NULL,
    nombre          TEXT NOT NULL,
    edicion         TEXT,
    archivo         TEXT,
    grano_original  TEXT
);

-- Geografia conformada: municipios (106) y AGEB urbanas (jerarquia via parent)
CREATE TABLE dw.dim_geografia (
    geo_key              SERIAL PRIMARY KEY,
    cvegeo               VARCHAR(13) UNIQUE NOT NULL,
    nivel                VARCHAR(10) NOT NULL CHECK (nivel IN ('municipio', 'ageb')),
    cve_ent              CHAR(2) NOT NULL,
    cve_mun              CHAR(3) NOT NULL,
    cve_loc              CHAR(4),
    cve_ageb             CHAR(4),
    nom_mun              TEXT,
    parent_geo_key       INT REFERENCES dw.dim_geografia (geo_key),
    en_localidad_merida  BOOLEAN NOT NULL DEFAULT FALSE,
    tiene_censo          BOOLEAN NOT NULL DEFAULT FALSE,
    area_km2             NUMERIC(12, 4) NOT NULL,
    geom                 geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX ix_dim_geografia_geom  ON dw.dim_geografia USING GIST (geom);
CREATE INDEX ix_dim_geografia_nivel ON dw.dim_geografia (nivel);

-- Tiempo a grano mensual; tiempo_key = YYYYMM
CREATE TABLE dw.dim_tiempo (
    tiempo_key  INT PRIMARY KEY,
    anio        SMALLINT NOT NULL,
    mes         SMALLINT NOT NULL CHECK (mes BETWEEN 1 AND 12),
    nombre_mes  VARCHAR(12) NOT NULL,
    trimestre   SMALLINT NOT NULL,
    semestre    SMALLINT NOT NULL
);

-- Clasificacion del SESNSP
CREATE TABLE dw.dim_delito (
    delito_key      SERIAL PRIMARY KEY,
    bien_juridico   TEXT NOT NULL,
    tipo_delito     TEXT NOT NULL,
    subtipo_delito  TEXT NOT NULL,
    modalidad       TEXT NOT NULL,
    UNIQUE (bien_juridico, tipo_delito, subtipo_delito, modalidad)
);

-- Actividad economica SCIAN (clase de 6 digitos) + agrupacion para KPIs
CREATE TABLE dw.dim_scian (
    scian_key   SERIAL PRIMARY KEY,
    codigo_act  CHAR(6) UNIQUE NOT NULL,
    nombre_act  TEXT NOT NULL,
    sector      CHAR(2) NOT NULL,
    subsector   CHAR(3) NOT NULL,
    grupo_kpi   VARCHAR(20) NOT NULL
);

-- Tamano del establecimiento por personal ocupado
CREATE TABLE dw.dim_tamano (
    tamano_key  SMALLSERIAL PRIMARY KEY,
    per_ocu     TEXT UNIQUE NOT NULL,
    orden       SMALLINT NOT NULL,
    estrato     VARCHAR(10) NOT NULL
);

-- ---------------------------------------------------------------- HECHOS

-- Grano: una fila por unidad geografica (AGEB urbana o municipio), Censo 2020
CREATE TABLE dw.fact_censo (
    geo_key     INT PRIMARY KEY REFERENCES dw.dim_geografia (geo_key),
    fuente_key  SMALLINT NOT NULL REFERENCES dw.dim_fuente (fuente_key),
    pobtot INT, pobfem INT, pobmas INT,
    p_0a2 INT, p_3a5 INT, p_6a11 INT, p_12a14 INT, p_15a17 INT, p_18a24 INT,
    pob0_14 INT, pob15_64 INT, pob65_mas INT, p_60ymas INT,
    p_12ymas INT, p_15ymas INT, p_18ymas INT,
    pea INT, pe_inac INT, pocupada INT, pdesocup INT,
    graproes NUMERIC(5, 2),
    psinder INT, pder_ss INT,
    tothog INT, vivtot INT, tvivhab INT, vivpar_hab INT, vivpar_des INT,
    vph_inter INT, vph_autom INT, vph_pc INT,
    prom_ocup NUMERIC(5, 2)
);

-- Grano: un establecimiento del DENUE (detalle completo, sin agregar)
CREATE TABLE dw.fact_establecimiento (
    id_denue               BIGINT PRIMARY KEY,
    geo_ageb_key           INT REFERENCES dw.dim_geografia (geo_key),   -- NULL = fuera de AGEB urbana
    geo_mun_key            INT NOT NULL REFERENCES dw.dim_geografia (geo_key),
    scian_key              INT NOT NULL REFERENCES dw.dim_scian (scian_key),
    tamano_key             SMALLINT REFERENCES dw.dim_tamano (tamano_key),
    alta_tiempo_key        INT REFERENCES dw.dim_tiempo (tiempo_key),
    fuente_key             SMALLINT NOT NULL REFERENCES dw.dim_fuente (fuente_key),
    n_establecimientos     SMALLINT NOT NULL DEFAULT 1,
    nom_estab              TEXT,
    cvegeo_ageb_reportado  VARCHAR(13),     -- clave AGEB que declara el DENUE (validacion)
    geom                   geometry(Point, 4326) NOT NULL
);
CREATE INDEX ix_fest_geom  ON dw.fact_establecimiento USING GIST (geom);
CREATE INDEX ix_fest_ageb  ON dw.fact_establecimiento (geo_ageb_key);
CREATE INDEX ix_fest_mun   ON dw.fact_establecimiento (geo_mun_key);
CREATE INDEX ix_fest_scian ON dw.fact_establecimiento (scian_key);

-- Grano: municipio x mes x delito (subtipo + modalidad), SESNSP
CREATE TABLE dw.fact_delito_mensual (
    geo_key     INT NOT NULL REFERENCES dw.dim_geografia (geo_key),
    tiempo_key  INT NOT NULL REFERENCES dw.dim_tiempo (tiempo_key),
    delito_key  INT NOT NULL REFERENCES dw.dim_delito (delito_key),
    fuente_key  SMALLINT NOT NULL REFERENCES dw.dim_fuente (fuente_key),
    incidentes  INT NOT NULL CHECK (incidentes >= 0),
    PRIMARY KEY (geo_key, tiempo_key, delito_key)
);
CREATE INDEX ix_fdel_tiempo ON dw.fact_delito_mensual (tiempo_key);
