# Diccionario de datos — Merida Urban Intelligence DW

Base: PostgreSQL 16 + PostGIS 3.4 · Esquema analítico: `dw` · Esquema intermedio: `stg`
Diagrama: [`warehouse_model.png`](warehouse_model.png) (fuente editable: `warehouse_model.dot`)

## Resumen del modelo

| Tabla | Tipo | Grano | Filas (carga actual) | Fuente |
|---|---|---|---|---|
| `dim_geografia` | Dimensión | Una unidad geográfica: municipio o AGEB urbana | 106 municipios + 1,562 AGEB | Marco Geoestadístico dic-2025 |
| `dim_tiempo` | Dimensión | Un mes (1990-01 a 2030-12) | 492 | Generada |
| `dim_delito` | Dimensión | Combinación bien jurídico + tipo + subtipo + modalidad | 68 | SESNSP |
| `dim_scian` | Dimensión | Una clase SCIAN de 6 dígitos | 815 | DENUE |
| `dim_tamano` | Dimensión | Un rango de personal ocupado | 7 | DENUE |
| `dim_fuente` | Dimensión | Un archivo fuente con su edición | 4 | Documentación |
| `fact_censo` | Hecho | Una unidad geográfica (AGEB o municipio) en el Censo 2020 | 1,636 | Censo 2020 |
| `fact_establecimiento` | Hecho | Un establecimiento | 146,383 | DENUE 05/2026 |
| `fact_delito_mensual` | Hecho | Municipio × mes × delito | 23,897 | SESNSP |

Llaves: todas las relaciones están declaradas como `FOREIGN KEY`. Geometrías en EPSG:4326; las áreas se calculan en EPSG:6372 (México ITRF2008 LCC, metros) antes de reproyectar.

---

## Dimensiones

### `dw.dim_geografia`
Dimensión conformada que usan las tres tablas de hechos. Contiene dos niveles unidos por `parent_geo_key` (AGEB → municipio).

| Columna | Tipo | Descripción |
|---|---|---|
| `geo_key` | serial PK | Llave sustituta |
| `cvegeo` | varchar(13) UQ | Clave INEGI: 5 dígitos (municipio) o 13 dígitos (AGEB = ent+mun+loc+ageb) |
| `nivel` | varchar | `municipio` o `ageb` |
| `cve_ent`, `cve_mun` | char | Claves de entidad (31) y municipio |
| `cve_loc`, `cve_ageb` | char | Claves de localidad y AGEB (NULL en municipios) |
| `nom_mun` | text | Nombre del municipio |
| `parent_geo_key` | int FK → `dim_geografia` | Municipio al que pertenece la AGEB (NULL en municipios) |
| `en_localidad_merida` | boolean | TRUE si la AGEB es de la localidad 31-050-0001 (unidad de análisis urbana) |
| `tiene_censo` | boolean | FALSE para AGEB creadas después de 2020 (sin datos censales) |
| `area_km2` | numeric | Área calculada en EPSG:6372 |
| `geom` | MultiPolygon, 4326 | Polígono oficial, con índice GIST |

### `dw.dim_tiempo`
| Columna | Tipo | Descripción |
|---|---|---|
| `tiempo_key` | int PK | Año×100 + mes (ej. 202403) |
| `anio`, `mes`, `nombre_mes` | | Componentes de la fecha |
| `trimestre`, `semestre` | smallint | Agrupaciones |

### `dw.dim_delito`
| Columna | Tipo | Descripción |
|---|---|---|
| `delito_key` | serial PK | Llave sustituta |
| `bien_juridico` | text | Bien jurídico afectado (ej. El patrimonio) |
| `tipo_delito` | text | Tipo (ej. Robo) |
| `subtipo_delito` | text | Subtipo (ej. Robo a casa habitación) |
| `modalidad` | text | Modalidad (ej. Con violencia) |

### `dw.dim_scian`
| Columna | Tipo | Descripción |
|---|---|---|
| `scian_key` | serial PK | Llave sustituta |
| `codigo_act` | char(6) UQ | Clase SCIAN |
| `nombre_act` | text | Descripción de la actividad; si un código trae más de un nombre se toma el más frecuente |
| `sector` | char(2) | Primeros 2 dígitos |
| `subsector` | char(3) | Primeros 3 dígitos; nivel usado para la actividad dominante |
| `grupo_kpi` | varchar | Agrupación derivada: `comercio_minorista` (46), `servicios` (51–81), `comercio_mayorista` (43), `industria` (21–23, 31–33), `transporte` (48–49), `gobierno` (93), `primario` (11) |

### `dw.dim_tamano`
| Columna | Tipo | Descripción |
|---|---|---|
| `tamano_key` | smallserial PK | Llave sustituta |
| `per_ocu` | text UQ | Rango de personal ocupado, tal como lo publica el DENUE |
| `orden` | smallint | Orden del rango (1 = más chico) |
| `estrato` | varchar | Agrupación derivada: micro (0–10), pequeña (11–50), mediana (51–250), grande (251+). Criterio simplificado por personal ocupado, sin distinguir sector |

### `dw.dim_fuente`
| Columna | Tipo | Descripción |
|---|---|---|
| `fuente_key` | smallserial PK | Llave sustituta |
| `codigo` | varchar UQ | CENSO2020, MG, DENUE, SESNSP |
| `nombre`, `edicion`, `archivo`, `grano_original` | text | Trazabilidad de la fuente |

---

## Hechos

### `dw.fact_censo`
**Grano:** una unidad geográfica (AGEB urbana o municipio) en el Censo de Población y Vivienda 2020.
Los valores confidenciales (`*`, menos de 3 unidades) y no disponibles (`N/D`) se cargan como NULL, no como cero.

| Columna | Descripción (INEGI) |
|---|---|
| `geo_key` | PK y FK → `dim_geografia` |
| `fuente_key` | FK → `dim_fuente` |
| `pobtot`, `pobfem`, `pobmas` | Población total, femenina y masculina |
| `p_0a2`, `p_3a5`, `p_6a11`, `p_12a14`, `p_15a17`, `p_18a24` | Población por grupo de edad |
| `pob0_14`, `pob15_64`, `pob65_mas`, `p_60ymas` | Grandes grupos de edad |
| `p_12ymas`, `p_15ymas`, `p_18ymas` | Población de 12, 15 y 18 años y más |
| `pea`, `pe_inac` | Población de 12+ económicamente activa e inactiva |
| `pocupada`, `pdesocup` | Población de 12+ ocupada y desocupada |
| `graproes` | Grado promedio de escolaridad (15+) |
| `psinder`, `pder_ss` | Población sin y con afiliación a servicios de salud |
| `tothog` | Total de hogares censales |
| `vivtot`, `tvivhab`, `vivpar_hab`, `vivpar_des` | Viviendas totales, habitadas, particulares habitadas y deshabitadas |
| `vph_inter`, `vph_autom`, `vph_pc` | Viviendas particulares habitadas con Internet, automóvil y computadora |
| `prom_ocup` | Promedio de ocupantes por vivienda |

### `dw.fact_establecimiento`
**Grano:** un establecimiento del DENUE. Se conserva el detalle completo, así que cualquier KPI se puede recalcular sin volver a los archivos crudos.

| Columna | Tipo | Descripción |
|---|---|---|
| `id_denue` | bigint PK | Identificador del DENUE |
| `geo_ageb_key` | int FK | AGEB donde cae el punto (`ST_Intersects`). NULL si está fuera de toda AGEB urbana |
| `geo_mun_key` | int FK | Municipio donde cae el punto. Si el punto cae fuera de todos los polígonos, se usa la clave que reporta el DENUE |
| `scian_key` | int FK | Actividad económica |
| `tamano_key` | smallint FK | Rango de personal ocupado |
| `alta_tiempo_key` | int FK | Mes de alta en el DENUE |
| `fuente_key` | smallint FK | Fuente |
| `n_establecimientos` | smallint | Siempre 1; es la medida aditiva |
| `nom_estab` | text | Nombre del establecimiento |
| `cvegeo_ageb_reportado` | varchar(13) | Clave de AGEB que declara el DENUE; sirve para validar la unión espacial |
| `geom` | Point, 4326 | Construido con `ST_MakePoint(longitud, latitud)` |

### `dw.fact_delito_mensual`
**Grano:** municipio × mes × delito (subtipo + modalidad). Datos del SESNSP (carpetas de investigación del fuero común).
La fuente trae 12 columnas de mes; se transformó a una fila por mes y se omiten las combinaciones con 0 incidentes, porque no afectan ninguna suma.
**No hay coordenadas:** la escala más fina posible es el municipio.

| Columna | Tipo | Descripción |
|---|---|---|
| `geo_key` | PK/FK | Municipio |
| `tiempo_key` | PK/FK | Mes |
| `delito_key` | PK/FK | Delito |
| `fuente_key` | FK | Fuente |
| `incidentes` | int | Número de carpetas de investigación |

---

## Vistas de KPIs (`sql/03_views.sql`)

| Vista | Unidad | Uso |
|---|---|---|
| `dw.v_kpi_ageb` | 501 AGEB de la localidad Mérida | KPIs demográficos y económicos; análisis espacial urbano |
| `dw.v_kpi_municipio` | 106 municipios de Yucatán | KPIs demográficos, económicos y de seguridad; análisis espacial de delitos |
| `dw.v_delitos_tipo_tiempo` | Municipio × mes × delito | Distribución por tipo y tiempo |

| KPI | Columna | Fórmula |
|---|---|---|
| Total Population | `pobtot` | Σ población de la unidad |
| Population Density | `densidad_pob_km2` | pobtot / area_km2 |
| Economically Active Population Rate | `tasa_pea_pct` | 100 × pea / p_12ymas |
| Population by Age Group | `pct_0_14`, `pct_15_64`, `pct_65_mas` | 100 × grupo / pobtot |
| Total Businesses | `negocios` | Número de establecimientos |
| Business Density | `dens_negocios_km2` | negocios / area_km2 |
| Businesses per 1,000 Residents | `negocios_x1000hab` | 1000 × negocios / pobtot (en AGEB, solo si pobtot ≥ 100) |
| Retail Density | `dens_comercio_km2` | negocios SCIAN 46 / area_km2 |
| Service Density | `dens_servicios_km2` | negocios SCIAN 51–81 / area_km2 |
| Dominant Economic Activity | `subsector_dominante` | Subsector SCIAN (3 dígitos) con más establecimientos |
| Total Crime Incidents | `delitos_2023_2025` | Σ incidentes 2023–2025 (municipio) |
| Crime Rate | `tasa_delitos_x1000hab` | 1000 × (incidentes / 3 años) / pobtot |
| Incidents by Type and Time | `v_delitos_tipo_tiempo` | Σ incidentes por tipo, subtipo, año y mes |
| Crime relative to Business Activity | `delitos_x100negocios` | 100 × (incidentes / 3 años) / negocios |

## Reglas y supuestos principales

- `*` y `N/D` del censo se cargan como NULL; nunca como 0.
- Las tasas por habitante en AGEB se omiten si pobtot < 100, porque en esas unidades cualquier conteo produce tasas extremas.
- Las 18 AGEB posteriores a 2020 existen en `dim_geografia` con `tiene_censo = FALSE`: cuentan para densidades de negocios, no para tasas por habitante.
- Los KPIs de delitos usan 2023–2025 porque es el periodo más cercano al DENUE 05/2026 y el más estable de la serie. La serie completa (2015–2025) queda en el DW.
- Periodos de referencia distintos: censo 2020, DENUE 2026, delitos 2023–2025.
