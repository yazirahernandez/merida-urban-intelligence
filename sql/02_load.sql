-- =====================================================================
-- 02_load.sql  -  Carga del DW desde el esquema stg (llenado por src/etl.py)
-- La conversion lat/lon -> punto y la union punto-en-poligono se hacen aqui,
-- en PostGIS.
-- =====================================================================

-- ---------------------------------------------------------------- dim_fuente
INSERT INTO dw.dim_fuente (codigo, nombre, edicion, archivo, grano_original) VALUES
 ('CENSO2020', 'INEGI Censo de Poblacion y Vivienda 2020 - Principales resultados por AGEB y manzana urbana',
  '2020', 'resageburb_31csv20.zip', 'Manzana / AGEB urbana / localidad / municipio'),
 ('MG',        'INEGI Marco Geoestadistico - Yucatan',
  'dic-2025', '31_yucatan.zip (31a.shp, 31mun.shp)', 'Poligono AGEB urbana / municipio'),
 ('DENUE',     'INEGI Directorio Estadistico Nacional de Unidades Economicas - Yucatan',
  '05/2026', 'denue_31_csv.zip', 'Establecimiento (punto lat/lon)'),
 ('SESNSP',    'SESNSP Incidencia delictiva del fuero comun municipal',
  '2015-2025, corte ene-2026', 'Municipal-Delitos-2015-2025_ene2026.csv',
  'Municipio x anio x subtipo x modalidad (12 columnas de mes)');

-- ---------------------------------------------------------------- dim_tiempo
INSERT INTO dw.dim_tiempo (tiempo_key, anio, mes, nombre_mes, trimestre, semestre)
SELECT EXTRACT(YEAR FROM d)::INT * 100 + EXTRACT(MONTH FROM d)::INT,
       EXTRACT(YEAR FROM d), EXTRACT(MONTH FROM d),
       (ARRAY['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio',
              'Agosto','Septiembre','Octubre','Noviembre','Diciembre'])[EXTRACT(MONTH FROM d)::INT],
       EXTRACT(QUARTER FROM d),
       CASE WHEN EXTRACT(MONTH FROM d) <= 6 THEN 1 ELSE 2 END
FROM generate_series('1990-01-01'::date, '2030-12-01'::date, interval '1 month') AS d;

-- ---------------------------------------------------------------- dim_geografia
-- 1) municipios
INSERT INTO dw.dim_geografia (cvegeo, nivel, cve_ent, cve_mun, nom_mun,
                              tiene_censo, area_km2, geom)
SELECT m.cvegeo, 'municipio', m.cve_ent, m.cve_mun, m.nomgeo,
       EXISTS (SELECT 1 FROM stg.censo c WHERE c.cvegeo = m.cvegeo),
       m.area_km2, m.geom
FROM stg.geo_municipio m;

-- 2) AGEB urbanas, enlazadas a su municipio
INSERT INTO dw.dim_geografia (cvegeo, nivel, cve_ent, cve_mun, cve_loc, cve_ageb,
                              nom_mun, parent_geo_key, en_localidad_merida,
                              tiene_censo, area_km2, geom)
SELECT a.cvegeo, 'ageb', a.cve_ent, a.cve_mun, a.cve_loc, a.cve_ageb,
       p.nom_mun, p.geo_key,
       (a.cve_mun = '050' AND a.cve_loc = '0001'),
       EXISTS (SELECT 1 FROM stg.censo c WHERE c.cvegeo = a.cvegeo),
       a.area_km2, a.geom
FROM stg.geo_ageb a
JOIN dw.dim_geografia p
  ON p.nivel = 'municipio' AND p.cve_ent = a.cve_ent AND p.cve_mun = a.cve_mun;

-- ---------------------------------------------------------------- dim_delito
INSERT INTO dw.dim_delito (bien_juridico, tipo_delito, subtipo_delito, modalidad)
SELECT DISTINCT bien_juridico, tipo_delito, subtipo_delito, modalidad
FROM stg.delitos;

-- ---------------------------------------------------------------- dim_scian
-- Si un codigo trae mas de un nombre, se toma el mas frecuente
INSERT INTO dw.dim_scian (codigo_act, nombre_act, sector, subsector, grupo_kpi)
SELECT DISTINCT ON (codigo_act)
       codigo_act, nombre_act, LEFT(codigo_act, 2), LEFT(codigo_act, 3), grupo_kpi
FROM (SELECT codigo_act, nombre_act, grupo_kpi, COUNT(*) AS n
      FROM stg.denue GROUP BY 1, 2, 3) t
ORDER BY codigo_act, n DESC;

-- ---------------------------------------------------------------- dim_tamano
INSERT INTO dw.dim_tamano (per_ocu, orden, estrato) VALUES
 ('0 a 5 personas',     1, 'micro'),
 ('6 a 10 personas',    2, 'micro'),
 ('11 a 30 personas',   3, 'pequena'),
 ('31 a 50 personas',   4, 'pequena'),
 ('51 a 100 personas',  5, 'mediana'),
 ('101 a 250 personas', 6, 'mediana'),
 ('251 y más personas', 7, 'grande');
-- Cualquier otro rango que traiga el DENUE se agrega sin estrato
INSERT INTO dw.dim_tamano (per_ocu, orden, estrato)
SELECT DISTINCT per_ocu, 99, 'otro' FROM stg.denue
WHERE per_ocu IS NOT NULL
  AND per_ocu NOT IN (SELECT per_ocu FROM dw.dim_tamano);

-- ---------------------------------------------------------------- fact_censo
INSERT INTO dw.fact_censo
SELECT g.geo_key,
       (SELECT fuente_key FROM dw.dim_fuente WHERE codigo = 'CENSO2020'),
       c.pobtot, c.pobfem, c.pobmas,
       c.p_0a2, c.p_3a5, c.p_6a11, c.p_12a14, c.p_15a17, c.p_18a24,
       c.pob0_14, c.pob15_64, c.pob65_mas, c.p_60ymas,
       c.p_12ymas, c.p_15ymas, c.p_18ymas,
       c.pea, c.pe_inac, c.pocupada, c.pdesocup,
       c.graproes, c.psinder, c.pder_ss,
       c.tothog, c.vivtot, c.tvivhab, c.vivpar_hab, c.vivpar_des,
       c.vph_inter, c.vph_autom, c.vph_pc, c.prom_ocup
FROM stg.censo c
JOIN dw.dim_geografia g ON g.cvegeo = c.cvegeo;

-- ---------------------------------------------------------------- fact_establecimiento
-- lat/lon -> Point(4326) y union espacial con AGEB y municipio.
-- Municipio: por ubicacion; si el punto cae fuera de todo poligono (costa,
-- error de captura) se usa la clave de municipio que reporta el DENUE.
WITH pts AS (
    SELECT d.*, ST_SetSRID(ST_MakePoint(d.longitud, d.latitud), 4326) AS pt
    FROM stg.denue d
)
INSERT INTO dw.fact_establecimiento
       (id_denue, geo_ageb_key, geo_mun_key, scian_key, tamano_key,
        alta_tiempo_key, fuente_key, nom_estab, cvegeo_ageb_reportado, geom)
SELECT p.id,
       a.geo_key,
       COALESCE(ms.geo_key, ma.geo_key),
       s.scian_key,
       t.tamano_key,
       dt.tiempo_key,
       (SELECT fuente_key FROM dw.dim_fuente WHERE codigo = 'DENUE'),
       p.nom_estab,
       p.cvegeo_ageb_reportado,
       p.pt
FROM pts p
LEFT JOIN LATERAL (SELECT g.geo_key FROM dw.dim_geografia g
                   WHERE g.nivel = 'ageb' AND ST_Intersects(g.geom, p.pt)
                   ORDER BY g.geo_key LIMIT 1) a ON TRUE
LEFT JOIN LATERAL (SELECT g.geo_key FROM dw.dim_geografia g
                   WHERE g.nivel = 'municipio' AND ST_Intersects(g.geom, p.pt)
                   ORDER BY g.geo_key LIMIT 1) ms ON TRUE
LEFT JOIN dw.dim_geografia ma ON ma.nivel = 'municipio' AND ma.cvegeo = p.cve_ent || p.cve_mun
JOIN dw.dim_scian s       ON s.codigo_act = p.codigo_act
LEFT JOIN dw.dim_tamano t ON t.per_ocu = p.per_ocu
LEFT JOIN dw.dim_tiempo dt ON dt.tiempo_key = p.alta_tiempo_key
WHERE COALESCE(ms.geo_key, ma.geo_key) IS NOT NULL;

-- ---------------------------------------------------------------- fact_delito_mensual
INSERT INTO dw.fact_delito_mensual (geo_key, tiempo_key, delito_key, fuente_key, incidentes)
SELECT g.geo_key, d.tiempo_key, dd.delito_key,
       (SELECT fuente_key FROM dw.dim_fuente WHERE codigo = 'SESNSP'),
       SUM(d.incidentes)
FROM stg.delitos d
JOIN dw.dim_geografia g ON g.nivel = 'municipio' AND g.cvegeo = d.cvegeo
JOIN dw.dim_delito dd
  ON dd.bien_juridico = d.bien_juridico AND dd.tipo_delito = d.tipo_delito
 AND dd.subtipo_delito = d.subtipo_delito AND dd.modalidad = d.modalidad
GROUP BY 1, 2, 3, 4;

ANALYZE dw.dim_geografia;
ANALYZE dw.fact_establecimiento;
ANALYZE dw.fact_delito_mensual;
