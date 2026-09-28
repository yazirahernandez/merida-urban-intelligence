-- =====================================================================
-- 04_validation.sql  -  Conteos, llaves y KPIs de muestra.
-- Cada consulta empieza con una linea de marcador (ver src/etl.py).
-- =====================================================================

-- @check Conteo de registros por tabla
SELECT 'dim_geografia (municipio)' AS tabla, COUNT(*) FROM dw.dim_geografia WHERE nivel = 'municipio'
UNION ALL SELECT 'dim_geografia (ageb)',          COUNT(*) FROM dw.dim_geografia WHERE nivel = 'ageb'
UNION ALL SELECT 'dim_geografia (ageb Merida)',   COUNT(*) FROM dw.dim_geografia WHERE en_localidad_merida
UNION ALL SELECT 'dim_tiempo',                    COUNT(*) FROM dw.dim_tiempo
UNION ALL SELECT 'dim_delito',                    COUNT(*) FROM dw.dim_delito
UNION ALL SELECT 'dim_scian',                     COUNT(*) FROM dw.dim_scian
UNION ALL SELECT 'dim_tamano',                    COUNT(*) FROM dw.dim_tamano
UNION ALL SELECT 'fact_censo',                    COUNT(*) FROM dw.fact_censo
UNION ALL SELECT 'fact_establecimiento',          COUNT(*) FROM dw.fact_establecimiento
UNION ALL SELECT 'fact_delito_mensual',           COUNT(*) FROM dw.fact_delito_mensual;

-- @check Staging vs DW (registros que no entraron al DW)
SELECT 'censo'   AS fuente, (SELECT COUNT(*) FROM stg.censo)   AS stg, (SELECT COUNT(*) FROM dw.fact_censo) AS dw
UNION ALL
SELECT 'denue', (SELECT COUNT(*) FROM stg.denue), (SELECT COUNT(*) FROM dw.fact_establecimiento)
UNION ALL
SELECT 'delitos (suma incidentes)', (SELECT SUM(incidentes) FROM stg.delitos),
       (SELECT SUM(incidentes) FROM dw.fact_delito_mensual);

-- @check Censo: suma de AGEB de la localidad Merida (esperado 921,771)
SELECT SUM(c.pobtot) AS pob_ageb_merida
FROM dw.fact_censo c JOIN dw.dim_geografia g USING (geo_key)
WHERE g.en_localidad_merida;

-- @check Union espacial DENUE: % dentro de AGEB y coincidencia con clave reportada
SELECT COUNT(*)                                                     AS negocios_mun_merida,
       COUNT(f.geo_ageb_key)                                         AS en_alguna_ageb,
       ROUND(100.0 * COUNT(f.geo_ageb_key) / COUNT(*), 1)            AS pct_en_ageb,
       ROUND(100.0 * AVG((a.cvegeo = f.cvegeo_ageb_reportado)::INT)
             FILTER (WHERE a.cvegeo IS NOT NULL), 1)                 AS pct_coincide_clave_denue
FROM dw.fact_establecimiento f
JOIN dw.dim_geografia m ON m.geo_key = f.geo_mun_key AND m.cvegeo = '31050'
LEFT JOIN dw.dim_geografia a ON a.geo_key = f.geo_ageb_key;

-- @check Integridad: AGEB sin municipio padre (esperado 0)
SELECT COUNT(*) AS ageb_sin_padre FROM dw.dim_geografia
WHERE nivel = 'ageb' AND parent_geo_key IS NULL;

-- @check KPIs AGEB: resumen
SELECT COUNT(*) AS n_ageb,
       ROUND(SUM(pobtot))                                  AS pob_total,
       ROUND(AVG(densidad_pob_km2)::NUMERIC, 1)            AS densidad_pob_media,
       ROUND(AVG(tasa_pea_pct)::NUMERIC, 1)                AS tasa_pea_media,
       SUM(negocios)                                       AS negocios,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY negocios_x1000hab)::NUMERIC, 1) AS mediana_neg_x1000
FROM dw.v_kpi_ageb;

-- @check KPIs municipio: top 5 por tasa de delitos (2023-2025)
SELECT cvegeo, nom_mun, pobtot, negocios,
       ROUND(delitos_prom_anual, 1)     AS delitos_prom_anual,
       ROUND(tasa_delitos_x1000hab, 2)  AS tasa_x1000,
       ROUND(delitos_x100negocios, 2)   AS delitos_x100neg
FROM dw.v_kpi_municipio
ORDER BY tasa_delitos_x1000hab DESC NULLS LAST
LIMIT 5;

-- @check Delitos por tipo y anio en Merida (top 5 tipos, 2023-2025)
SELECT tipo_delito, anio, SUM(incidentes) AS incidentes
FROM dw.v_delitos_tipo_tiempo
WHERE cvegeo = '31050' AND anio BETWEEN 2023 AND 2025
  AND tipo_delito IN (SELECT tipo_delito FROM dw.v_delitos_tipo_tiempo
                      WHERE cvegeo = '31050' AND anio BETWEEN 2023 AND 2025
                      GROUP BY 1 ORDER BY SUM(incidentes) DESC LIMIT 5)
GROUP BY 1, 2 ORDER BY 1, 2;
