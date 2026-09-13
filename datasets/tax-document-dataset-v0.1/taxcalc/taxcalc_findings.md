# TaxCalcBench TY25: auditoría de archivos

Fecha de revisión: 2026-09-12. Se descargó el subárbol completo de datos TY25, se comprobó cada blob contra su SHA de Git y se inspeccionó el contenido de todos los PDF, JSON y XML. No se descargaron resultados generados por modelos.

## Fuente y versión fijada

- Repositorio: https://github.com/column-tax/tax-calc-bench
- Commit: `8f89c2cf00a8906f4d896a02a2f45f9c9e85ae9b`
- Árbol `tax_calc_bench/ty25/test_data`: `521d2767436e9a6c9ce4ad9ce71443694afa3838`
- Inventario reproducible: https://api.github.com/repos/column-tax/tax-calc-bench/git/trees/521d2767436e9a6c9ce4ad9ce71443694afa3838?recursive=1
- Licencia del repositorio: MIT, Copyright (c) 2025 Column Tax, Inc. Se descargó `LICENSE`. No hay una licencia distinta dentro del subárbol TY25 examinado. Conservar ese aviso al redistribuir.
- Licencia fijada: https://github.com/column-tax/tax-calc-bench/blob/8f89c2cf00a8906f4d896a02a2f45f9c9e85ae9b/LICENSE

## Cantidades comprobadas

50 expedientes y 364 archivos: **264 PDF de entrada (314 páginas), 50 `remaining_data.json` de entrada y 50 `output.xml` de resultados esperados**. Tamaño total: 29.727.900 bytes. Los 364 hashes Git coinciden. Árbol no truncado.

| PDF de entrada, según archivo y contenido | Archivos |
|---|---:|
| W-2 | 56 |
| 1040 previo, `1040_2024.pdf` | 50 |
| 1099-INT | 24 |
| 1099-B | 21 |
| 1099-DIV | 20 |
| 1099-R | 18 |
| 1099-MISC | 14 |
| 1099-G | 13 |
| 1099-NEC | 11 |
| 1099-K | 6 |
| 1099-SA | 3 |
| 1098 | 7 |
| 1098-T | 10 |
| 1098-E | 6 |
| W-2G | 5 |

CA, IL, NY y VA tienen 10 expedientes cada uno; otros 10 son US/federales. Importante: **los 40 `output.xml` estatales no contienen una declaración federal IRS1040 completa**. Sólo los 10 US contienen el elemento IRS1040. No son 50 pares federal+estatal.

## Cobertura que requiere distinguir formato y rol

| Necesidad | Evidencia del corpus |
|---|---|
| K-1 federal | No hay PDF K-1. `ty25-il-007/input/remaining_data.json` contiene `schk1`, con selector `partOrSCorp=P` y algunos datos de entidad/ingreso. Es información estructurada parcial, no documento para navegar. |
| Anexo K-1 estatal | El mismo expediente contiene campos `il_sch_ilk1_p`; no PDF de anexo. No se verificó cobertura PTET/composite en estos archivos. |
| Form 8959 | Elemento `IRS8959` en **6 outputs US**. No PDF de entrada. Útil como resultado de cálculo o base para renderizar mocks nuevos, no como extracción de un 8959 ya existente. |
| Schedule A | Elemento `IRS1040ScheduleA` en **5 outputs US**. Los 50 PDF 1040 previos tienen sólo dos páginas: **no incluyen el Schedule A previo completo**. |
| AMT / 6251 | Elemento `IRS6251` en **1 output US**, sin PDF de entrada. |
| SDI/DI | **5 W-2 PDF contienen texto SDI**: NY004, NY006, NY007, VA002 y VA004. El XML contiene cuatro descripciones SDI y una `VA SDI - E`. Visualmente se confirmó la casilla 14 de NY004. Esto cubre extracción de algunas etiquetas; no acredita cobertura de todas las jurisdicciones ni reglas de SUI/DI. |
| Anticipos y extensiones | Hay valores estructurados en JSON, incluidos anticipos federales no nulos en 3 expedientes y extensiones federales no nulas en 2. También existen campos estatales. **No comprobantes de pago como PDF**. |
| Créditos previos y reembolsos | Hay 1040 previos, 1099-G y campos de JSON de créditos/refunds. No expediente de confirmación bancaria, anulación y liquidación del mismo movimiento. |
| W-2c, versiones corregidas, duplicados, pagos cancelados | No archivo W-2c ni cobertura sistemática acreditada. Se debe añadir una suite específica; una casilla CORRECTED impresa en una plantilla 1099 no demuestra un caso corregido. |

Los IDs completos y todas las claves están en `taxcalc_findings.json` y `manifest.json`.

## Solidez de los labels y límites

Se validaron **5 pares documento/XML y 11 importes, todos coincidentes**: W-2 de US001, US003, US005 y CA001 (casillas 1 y 2), y 1099-R de US010 (casillas 1, 2a y 4). Los valores PDF se extrajeron por coordenadas de las casillas y se compararon exactamente con los elementos XML; sólo se seleccionaron pares con asociación unívoca. Ver `sample_label_validation.json` y `validate_label_samples.py`.

Eso valida esos campos concretos. El resto del XML sigue siendo **candidato para derivar labels**, hasta revisar correspondencia y transformación. El corpus no trae labels de asignación al Tax Payment Leadsheet, deduplicación, evidencia por página/casilla ni clasificación de pagos realizados/programados/cancelados. El ground truth XML debe permanecer inaccesible al harness evaluado.

Todos los 264 PDF tienen texto extraíble. Son 214 PDF de una página y 50 de dos páginas. **No constituyen una suite de escaneos/fotos difíciles ni documentos largos**.

Hallazgo de calidad: 16 PDF sólo contienen el año textual 2024. En `ty25-us-004/input/1099int_1.pdf` se inspeccionó visualmente que **2024 es la fecha de revisión de la plantilla y la casilla del año calendario está vacía**. No se debe etiquetar automáticamente el año fiscal a partir del año de revisión, ni marcar los 16 como errores sin inspección individual. El año del expediente puede servir como contexto explícito; una tarea sin ese contexto debe admitir información insuficiente. Muestra: `sample_1099int.png`.

El [paper original](https://arxiv.org/html/2507.16126v1#S3.SS2) describe los datos **TY24** como enteramente sintéticos, creados por expertos y verificados por un motor determinista. La documentación TY25 los llama PDFs realistas y se observaron identificadores de prueba. No se encontró una declaración TY25 de procedencia tan explícita como la del paper TY24; por precisión se conserva esa distinción.

## Reproducir

`python audit_download.py --all` descarga sólo el subárbol fijado. `generate_audit.py` usa pypdf para generar el manifiesto de hashes, páginas y claves. `validate_label_samples.py` usa pdfplumber para las 11 comparaciones. No requiere credenciales, llamadas a modelos ni ejecución del benchmark original.

En esta sesión los scripts de inspección usaron `/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3`. Los archivos originales están en `download/`, preservando el árbol de expedientes.
