-- =====================================================================
-- 03_views.sql  -  KPIs calculados desde el DW
--   dw.v_kpi_ageb            : KPIs demograficos y economicos, AGEB de la localidad Merida
--   dw.v_kpi_municipio       : KPIs demograficos, economicos y de seguridad, 106 municipios
--   dw.v_delitos_tipo_tiempo : incidentes por tipo y tiempo
-- Periodo de delitos para KPIs: 2023-2025 (promedio anual), ver README.
-- Tasas por habitante solo con poblacion >= 100 (evita tasas infladas).
-- =====================================================================

-- ---------------------------------------------------------------- AGEB
CREATE OR REPLACE VIEW dw.v_kpi_ageb AS
WITH est AS (
    SELECT f.geo_ageb_key AS geo_key,
           COUNT(*)                                             AS negocios,
           COUNT(*) FILTER (WHERE s.grupo_kpi = 'comercio_minorista') AS comercio,
           COUNT(*) FILTER (WHERE s.grupo_kpi = 'servicios')          AS servicios
    FROM dw.fact_establecimiento f
    JOIN dw.dim_scian s USING (scian_key)
    WHERE f.geo_ageb_key IS NOT NULL
    GROUP BY 1
),
dom AS (  -- actividad dominante a nivel subsector (3 digitos)
    SELECT DISTINCT ON (f.geo_ageb_key)
           f.geo_ageb_key AS geo_key, s.subsector AS subsector_dominante,
           COUNT(*) AS n_dom
    FROM dw.fact_establecimiento f
    JOIN dw.dim_scian s USING (scian_key)
    WHERE f.geo_ageb_key IS NOT NULL
    GROUP BY 1, 2
    ORDER BY f.geo_ageb_key, COUNT(*) DESC, s.subsector
)
SELECT g.geo_key, g.cvegeo, g.tiene_censo, g.area_km2,
       -- demograficos
       c.pobtot,
       c.pobtot / g.area_km2                                     AS densidad_pob_km2,
       100.0 * c.pea / NULLIF(c.p_12ymas, 0)                     AS tasa_pea_pct,
       c.pob0_14, c.pob15_64, c.pob65_mas,
       100.0 * c.pob0_14   / NULLIF(c.pobtot, 0)                 AS pct_0_14,
       100.0 * c.pob15_64  / NULLIF(c.pobtot, 0)                 AS pct_15_64,
       100.0 * c.pob65_mas / NULLIF(c.pobtot, 0)                 AS pct_65_mas,
       c.graproes,
       -- economicos
       COALESCE(e.negocios, 0)                                   AS negocios,
       COALESCE(e.negocios, 0)  / g.area_km2                     AS dens_negocios_km2,
       CASE WHEN c.pobtot >= 100
            THEN 1000.0 * COALESCE(e.negocios, 0) / c.pobtot END AS negocios_x1000hab,
       COALESCE(e.comercio, 0)  / g.area_km2                     AS dens_comercio_km2,
       COALESCE(e.servicios, 0) / g.area_km2                     AS dens_servicios_km2,
       d.subsector_dominante,
       100.0 * d.n_dom / NULLIF(e.negocios, 0)                   AS pct_subsector_dominante,
       g.geom
FROM dw.dim_geografia g
LEFT JOIN dw.fact_censo c ON c.geo_key = g.geo_key
LEFT JOIN est e           ON e.geo_key = g.geo_key
LEFT JOIN dom d           ON d.geo_key = g.geo_key
WHERE g.nivel = 'ageb' AND g.en_localidad_merida;

-- ---------------------------------------------------------------- MUNICIPIO
CREATE OR REPLACE VIEW dw.v_kpi_municipio AS
WITH est AS (
    SELECT f.geo_mun_key AS geo_key,
           COUNT(*) AS negocios,
           COUNT(*) FILTER (WHERE s.grupo_kpi = 'comercio_minorista') AS comercio,
           COUNT(*) FILTER (WHERE s.grupo_kpi = 'servicios')          AS servicios
    FROM dw.fact_establecimiento f
    JOIN dw.dim_scian s USING (scian_key)
    GROUP BY 1
),
dom AS (
    SELECT DISTINCT ON (f.geo_mun_key)
           f.geo_mun_key AS geo_key, s.subsector AS subsector_dominante
    FROM dw.fact_establecimiento f
    JOIN dw.dim_scian s USING (scian_key)
    GROUP BY 1, 2
    ORDER BY f.geo_mun_key, COUNT(*) DESC, s.subsector
),
del AS (
    SELECT f.geo_key,
           SUM(f.incidentes)                                  AS delitos_2023_2025,
           SUM(f.incidentes) / 3.0                            AS delitos_prom_anual
    FROM dw.fact_delito_mensual f
    JOIN dw.dim_tiempo t USING (tiempo_key)
    WHERE t.anio BETWEEN 2023 AND 2025
    GROUP BY 1
)
SELECT g.geo_key, g.cvegeo, g.nom_mun, g.area_km2,
       c.pobtot,
       c.pobtot / g.area_km2                                        AS densidad_pob_km2,
       100.0 * c.pea / NULLIF(c.p_12ymas, 0)                        AS tasa_pea_pct,
       100.0 * c.pob0_14   / NULLIF(c.pobtot, 0)                    AS pct_0_14,
       100.0 * c.pob65_mas / NULLIF(c.pobtot, 0)                    AS pct_65_mas,
       COALESCE(e.negocios, 0)                                      AS negocios,
       COALESCE(e.negocios, 0)  / g.area_km2                        AS dens_negocios_km2,
       1000.0 * COALESCE(e.negocios, 0) / NULLIF(c.pobtot, 0)       AS negocios_x1000hab,
       COALESCE(e.comercio, 0)  / g.area_km2                        AS dens_comercio_km2,
       COALESCE(e.servicios, 0) / g.area_km2                        AS dens_servicios_km2,
       d.subsector_dominante,
       COALESCE(dl.delitos_2023_2025, 0)                            AS delitos_2023_2025,
       COALESCE(dl.delitos_prom_anual, 0)                           AS delitos_prom_anual,
       1000.0 * COALESCE(dl.delitos_prom_anual, 0) / NULLIF(c.pobtot, 0)  AS tasa_delitos_x1000hab,
       100.0  * COALESCE(dl.delitos_prom_anual, 0) / NULLIF(e.negocios, 0) AS delitos_x100negocios,
       g.geom
FROM dw.dim_geografia g
LEFT JOIN dw.fact_censo c ON c.geo_key = g.geo_key
LEFT JOIN est e           ON e.geo_key = g.geo_key
LEFT JOIN dom d           ON d.geo_key = g.geo_key
LEFT JOIN del dl          ON dl.geo_key = g.geo_key
WHERE g.nivel = 'municipio';

-- ---------------------------------------------------------------- DELITOS POR TIPO Y TIEMPO
CREATE OR REPLACE VIEW dw.v_delitos_tipo_tiempo AS
SELECT g.cvegeo, g.nom_mun, t.anio, t.mes, t.nombre_mes, t.trimestre,
       d.bien_juridico, d.tipo_delito, d.subtipo_delito, d.modalidad,
       f.incidentes
FROM dw.fact_delito_mensual f
JOIN dw.dim_geografia g USING (geo_key)
JOIN dw.dim_tiempo t    USING (tiempo_key)
JOIN dw.dim_delito d    USING (delito_key);
