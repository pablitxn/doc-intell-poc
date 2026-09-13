# Auditoría del dataset completo — 2026-09-13

El kit recibido está íntegro, pero su formato era de adquisición de fuentes: no incluía las tareas ni el ground truth del runner. Se preparó `datasets/tax-document-eval-v1` con **319 documentos, 55 expedientes, 366 tareas y 1.465 campos**. El kit original, sus licencias, archivos y hashes se conservan sin modificaciones.

La validez documentada corresponde a campos observables seleccionados y a sumas explícitas de retenciones. No certifica todos los resultados fiscales XML ni un Tax Payment Leadsheet completo. Las instrucciones y los resultados esperados no exigen inferir impuestos, estados de pago o importes ausentes.

## Comprobaciones de las fuentes

| Fuente / comprobación | Resultado |
|---|---|
| Snapshot de adquisición | 485 archivos coinciden con SHA256SUMS; membresía exacta salvo cachés y metadatos del sistema |
| TaxCalcBench | 364 archivos: 264 PDF, 50 JSON y 50 XML; hashes Git y SHA256 correctos; parseo válido |
| PDF de una página | 214 documentos, 14 familias, 649 importes; dos motores de lectura independientes coinciden |
| Form 1040 previo | 50 documentos de dos páginas; 50 años, 49 AGI y 25 elecciones de línea 36 comprobados con dos motores |
| Fake W-2 | Cinco imágenes revisadas visualmente; 110 importes y 15 booleanos coinciden con los labels fuente |
| Datos estructurados | 50 JSON; 431 valores y flags leídos por rutas explícitas, sin inferir liquidación de pagos |
| Conciliación | 47 tareas; sumas verificadas con Decimal y aritmética independiente en centavos |

Los motores usados fueron pdfplumber 0.11.9 y PDFium mediante pypdfium2 5.13.0. Las asignaciones de casilla/coordenadas se revisaron visualmente en una muestra de cada familia, las cinco imágenes W-2 y el formulario 1040. Todos los campos PDF seleccionados se comprobaron por extracción independiente; no se afirma revisión visual individual de las 314 páginas.

Los campos XML no sirven como referencia general de lectura: sólo diez outputs contienen IRS1040 federal y cuarenta son outputs estatales. Los PDF 1040 de entrada son del ejercicio anterior. Ningún XML se copia a `inputs/` del dataset preparado.

## Hallazgos y tratamiento

| Hallazgo | Impacto en evaluación | Tratamiento |
|---|---|---|
| 13 ceros impresos en W-2 se omiten en los XML asociados | Un oracle derivado de XML podría exigir ausencia frente a un cero visible | Valores tomados de la casilla visible; vacío y cero nunca se equiparan |
| 18 W-2 reutilizan EIN+SSN en asociaciones ambiguas | Unir documentos y XML sólo por esos IDs puede asignar la respuesta de otro formulario | No usar esa unión como fuente de labels |
| W-2 de imágenes son 2010 y repiten Copy B/C | Mezclar ejercicios o sumar dos copias infla resultados | Ejercicio por tarea; leer Copy B superior una vez |
| Filas repetidas en cajas 12 y 15–20 | `box=17` no distingue las dos filas estatales | Calificadores públicos: `12:a`, `17:first`, `17:second`, etc. |
| Campos AcroForm vacíos en 1040 con texto superpuesto visible | Un parser de campos puede informar ausencia incorrecta | Contrastar el texto visible; los widgets no son el oracle |
| Tres expedientes sin salarios/retenciones agregables | Fabricar un total cero premiaría una afirmación sin datos | IL002, NY010 y VA010 tienen extracción, sin conciliación de retenciones |
| US001 no muestra AGI ni importe de línea 36 en el 1040 previo | Ausencia podría convertirse en cero | Esa tarea sólo pide el año visible; no se inventan importes |
| Diez tensiones entre flags e importes en cuatro expedientes | Un monto declarado no prueba que un pago ocurrió | Preservar por separado flags y montos; no calcular pagos liquidados |
| Veinte grupos de PDF idénticos entre casos | Duplicados en distintos splits contaminarían la evaluación | 52 grupos de fuente para 55 casos; mantener juntos al definir futuros splits |
| Fechas de fixture y revisión de plantilla | No establecen año calendario ni fecha real de presentación | Año por contexto explícito o encabezado; no inferir por filename/footer/timestamp |

Las tensiones declaradas están en CA002 y VA003/VA004/VA009: por ejemplo, `paid_estimated_tax_pmts=false` junto con anticipos positivos, o flags de extensión/crédito negativos junto con importes positivos. Se conservan como observaciones de la fuente. La conciliación de retenciones excluye esos datos JSON explícitamente.

La revisión visual de CA 592-B encontró encabezado 2025 y pie 2024. No se reclasifica automáticamente por el pie: es una plantilla de referencia excluida del scoring. Los nombres de algunas claves Fake W-2 también requerían interpretación: el ID estatal de caja 15 es del empleador, y la caja 6 es impuesto Medicare retenido. Los IDs y direcciones están fuera de los campos evaluados.

## Contrato y evaluadores

Cada tarea declara expediente, año, campos, tipos, documentos y referencias canónicas. Los importes son strings decimales de dos dígitos; las casillas booleanas usan booleanos JSON. Para JSON, `page=1` es una convención explícita y `box` es el JSON pointer del valor. Para la imagen W-2, las filas y casillas repetidas se especifican en la consigna.

El prompt se versionó como `tax-fields-text-v5`. El scorer determinista conserva su política `tax-mini-v2`: esquema exacto, valores y conjunto documento/página/casilla. No puntúa bbox ni exige determinada trayectoria de herramientas. Se comprueba que un importe correcto con otra casilla, fila equivocada o evidencia extra falle; también se rechazan `None`, floats monetarios, campos extra y valores alterados.

Los 366 expected pasan el contrato, lo cual verifica compatibilidad del evaluador. La evidencia de su contenido es la revisión de fuentes anterior y la procedencia por campo en `ground_truth/provenance.json`. Las sumas se vuelven a calcular en tests desde las observaciones de extracción, sin invocar el builder.

347 de los 1.253 campos monetarios son ceros impresos, declarados o sumas sustentadas por contribuyentes explícitos. No hay recompensa por casillas vacías fuera de la selección. Para comparar calidad, el número de ceros y la distribución por familia deben acompañar al promedio; una extracción correcta en este conjunto no demuestra capacidad fiscal general.

Todo el conjunto está marcado como **development**. Se usó para revisar consignas e integración; no se presenta como holdout independiente ni se selecciona un ganador entre harnesses con estas pruebas.

## Ejecución y evidencia guardada

La reconstrucción temporal produjo archivos idénticos byte por byte. Los **256 tests de la suite completa aprobaron, sin omisiones**. Los diagnósticos de Pi, Tau y Codex pasaron con los 319 documentos y sus formatos. El test de Phoenix publicó y recuperó las 366 tareas y 55 casos sin truncado; también importó el snapshot completo y un run de fixture a otra instancia, con cinco scores y traza, sin duplicados. Ese fixture no es una evaluación de modelos.

Los resultados de la suite y las corridas reales se guardan en [la evidencia de esta revisión](../artifacts/2026-09-13/full-dataset/README.md). Los originales del benchmark minimal permanecen históricos y conservan su versión; no se mezclan con el nuevo dataset/contrato.

Se ejecutaron **12/12 tareas reales con resultado aprobado**, usando `gpt-5.6-sol` y razonamiento `medium`: cuatro tareas —PDF W-2, imagen W-2, JSON y conciliación— en Pi, Tau y Codex. Los **147 campos** tuvieron valores y evidencias correctos. La lectura posterior de Phoenix comprobó los 12 resultados, **60 scores y 77 spans**, además del dataset publicado completo de 366 tareas. Los reportes originales y sus snapshots se guardan en un archivo con hashes por miembro. Esta muestra comprueba integración y lectura de los formatos; no equivale a ejecutar la matriz completa de 3.294 invocaciones ni establece un ranking.

Una copia del proyecto sin `.git`, `runs/` ni credenciales, ubicada en otra ruta con espacios, pasó `uv run scripts/prepare_full_dataset.py --check` y los diagnósticos de los tres harnesses. La reconstrucción volvió a ser idéntica byte por byte. La prueba reutilizó Docker, imagen y autenticación del host actual; no representa una instalación en otro sistema operativo.

Para repetir la auditoría o ejecutar modelos, usar la [guía de ejecución](FULL_DATASET_READINESS.md) y el [notebook](FULL_DATASET_AUDIT.ipynb). La máquina corporativa y su harness privado deben pasar allí el diagnóstico y una corrida real; todavía no se probaron desde este entorno.
