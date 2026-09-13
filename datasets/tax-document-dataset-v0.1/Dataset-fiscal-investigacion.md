# Base documental fiscal para evaluar un agente

Fecha de adquisición y auditoría: 12 de septiembre de 2026. Versión del paquete: 0.1.

**Ya hay material suficiente para empezar sin generar todo desde cero.** La base descargada contiene 50 expedientes de TaxCalcBench, cinco pares imagen/etiquetas de Fake W-2 y 39 PDF oficiales para completar formularios y escenarios. Además, se auditaron las 77 tareas fiscales etiquetadas de ExtractBench y se incluye su manifiesto y un descargador fijado a versión.

Esto es un **paquete de fuentes auditadas y preparación del dataset**, todavía no un benchmark completo del Tax Payment Leadsheet. La unidad que falta construir es el expediente coherente con documentos, hechos, pagos y respuesta final verificable.

## Qué se consiguió

| Fuente | Comprobación realizada | Incluido en el ZIP | Uso adecuado |
|---|---|---|---|
| [TaxCalcBench](https://github.com/column-tax/tax-calc-bench) | Subárbol TY25 completo: 50 expedientes, 264 PDF, 50 JSON de entrada y 50 XML esperados. Los 364 archivos coinciden con sus hashes Git. | Corpus completo, licencia MIT, manifiesto, auditoría y scripts. | Casos con varios documentos; candidatos para extracción y cálculo. Necesita labels propios del leadsheet. |
| [ExtractBench](https://huggingface.co/datasets/llamaindex/ExtractBench) | 370 registros de metadatos inspeccionados; 77 tareas con schemas fiscales, GT y reglas. Cinco PDF muestreados. | Inventario de las 77 tareas, auditoría, procedencia/licencia y descargador. Los PDF y GT de registros públicos se obtienen por separado. | Extracción, localización de evidencia y navegación de documentos. |
| [Fake W-2](https://huggingface.co/datasets/singhsays/fake-w2-us-tax-form-dataset) / [Kaggle](https://www.kaggle.com/datasets/mcvishnu1/fake-w2-us-tax-form-dataset) | HF tiene 2.000 imágenes: 1.800 train, 100 validation y 100 test. Se adquirieron cinco pares del test. | Cinco JPG con GT original, hashes y evidencia de licencia de Kaggle. | Pruebas de lectura de imágenes; no oracle de cálculo fiscal. |
| IRS, California FTB y New Jersey Treasury | 39 PDF descargados y parseados de 42 URL intentadas: formularios, instrucciones y un caso práctico educativo. | Los 39 originales, inventarios con SHA-256 y campos rellenables cuando existen. | Bases para generar mocks con datos controlados. Un formulario vacío no es un caso etiquetado. |

Las tres URL anuales que fallaron fueron 1099-INT, DIV y G de 2025. Se conservaron esos fallos en el inventario: INT y DIV se consiguieron como formularios de uso continuo revisados en 2024; G se consiguió para 2024. No se presentaron como descargas anuales 2025 equivalentes.

## Cobertura real por documento

| Necesidad | Material adquirido o localizado | Trabajo pendiente para el leadsheet |
|---|---|---|
| W-2 | 56 PDF en TaxCalcBench; 20 tareas W-2 de 2020 en ExtractBench; cinco imágenes Fake W-2 en el paquete. | Etiquetas de año, jurisdicción, evidencia y deduplicación. Añadir documentos corregidos y difíciles. |
| W-2c | Plantilla oficial descargada. | Pares original/corrección y valor vigente esperado. REISSUED no equivale a W-2c. |
| 1099 | TaxCalcBench: INT 24, B 21, DIV 20, R 18, MISC 14, G 13, NEC 11, K 6, SA 3. ExtractBench añade tareas B y tres consolidated statements. | Revisar campos relevantes por subtipo; distinguir retención, ingreso, refund y año correspondiente. |
| K-1 1065 y 1120-S | ExtractBench: 10 tareas 1065 y nueve 1120-S. Plantillas federales oficiales 2025 adquiridas. | Casos actuales coherentes con anexos estatales y pagos. Las diez tareas 1065 contienen sólo siete GT distintos. |
| K-1 1041 | Plantilla federal 2025 adquirida. | Documentos cumplimentados y GT. No se encontró schema dedicado en los corpus auditados. |
| K-1 estatal / PTET / composite | CA K-1 (565), 592-B, 3804 y 3804-CR; NJK-1 e instrucciones, descargados. | Asignación al contribuyente, retención vs crédito, entidad vs socio y duplicados entre documentos. Composite requiere soporte adicional. |
| Form 8959 | Plantillas 2024/2025; seis resultados IRS8959 dentro de XML de TaxCalcBench. | Los seis XML son outputs de cálculo, no seis PDF de entrada. Renderizar y validar casos y relaciones con W-2. |
| SUI / DI / SDI | Cinco W-2 de TaxCalcBench contienen SDI; plantilla NJ-2450 y referencias oficiales CA/NJ. | Reglas y nombres por jurisdicción, aportes del empleado vs empleador y reconciliación entre empleadores. “DUI” en la foto sigue sin interpretación confirmada. |
| Anticipos Q1–Q4 y extensiones | Valores en JSON de TaxCalcBench y vouchers oficiales 1040-ES, 4868, CA 540-ES y 3519. | Confirmaciones, estados de pago, banco/cuenta fiscal y fechas. Un voucher o una solicitud no acredita por sí solo un pago completado. |
| Saldo, assessments, refunds y crédito al año siguiente | 1040 previos, 1099-G, CA 540 y referencias de pagos. | Avisos, movimientos y relaciones entre ejercicios; distinguir refund declarado de recibido y crédito aplicado. |
| Schedule A / AMT / beneficio fiscal / FTC | Plantillas 2024/2025 de Schedule A, 6251 y 1116, además de 1040 y schedules. | Declaración previa completa y oracle fiscal validado por ejercicio. Los 50 PDF 1040 previos de TaxCalcBench sólo tienen dos páginas. |

También se adquirieron 23 PDF 1098/1098-T/1098-E y cinco W-2G dentro de TaxCalcBench. Son útiles como documentos complementarios y distractores; no amplían automáticamente las filas del leadsheet.

Las fuentes estatales nuevas se concentran en **California y New Jersey**. TaxCalcBench aporta casos CA, IL, NY y VA, pero eso no acredita cobertura integral de esos estados. NY IT-204-IP, IT-653 e IT-2658 y NJ-1080-C/PTE-K-1 quedaron pendientes de adquisición. No hay cobertura completa de todos los estados ni de todas las situaciones de una declaración estadounidense.

## Hallazgos que cambian el diseño del benchmark

1. **Los labels existentes no responden todavía a nuestra tarea.** TaxCalcBench tiene diez outputs federales y cuarenta estatales. Se contrastaron cinco pares PDF/XML y once importes: once coincidencias. Es una comprobación parcial, no una certificación de todos los campos ni del resultado fiscal completo.
2. **Año de revisión y año fiscal son distintos.** Un 1099-INT examinado conserva “Rev. January 2024” pero tiene vacío el año calendario. Otros quince PDF quedaron señalados para revisión, sin declararlos errores. Si la tarea proporciona el año del expediente, debe quedar registrado como contexto explícito.
3. **Cantidad de filas no equivale a diversidad.** Los 17 ejemplos 1099-B de ExtractBench proceden de dos fuentes de 2009; sus 20 W-2 son de una misma colección; los 1040 abarcan 2021–2024 con titulares repetidos entre años. Los splits deben agrupar fuentes relacionadas.
4. **Las etiquetas de Fake W-2 tienen huecos críticos.** El primer ejemplo inspeccionado es de 2010 y su GT de 45 campos omite año y box 14. Usa “None” textual en algunos campos. Sus importes no deben asumirse fiscalmente coherentes.
5. **Falta dificultad visual y de workflow.** Todos los PDF de TaxCalcBench tienen texto: 214 tienen una página y 50 tienen dos. Hay que añadir escaneos, fotos, anexos largos, versiones corregidas, documentos irrelevantes y contradicciones controladas.
6. **Las plantillas también requieren control de versión.** Algunos formularios CA con encabezado 2025 conservan pie 2024. Las URL NJ con /current/ pueden cambiar. El paquete preserva bytes, fecha y hash, y mantiene pendiente la validación de año por contenido cuando corresponde.

## Cómo convertirlo en un dataset sólido

Recomiendo tres suites con resultados separados:

| Suite | Pregunta que responde | Base |
|---|---|---|
| Extracción | ¿Lee el campo correcto y señala su evidencia? | ExtractBench, W-2 y 1099 adquiridos; adapters revisados. |
| Expediente y leadsheet | ¿Busca entre documentos y obtiene el resultado correcto por año, jurisdicción y categoría, sin contar dos veces? | TaxCalcBench adaptado + expedientes sintéticos nuevos de pagos y anexos. |
| Cálculo fiscal | ¿Aplica correctamente las reglas del ejercicio y sus dependencias? | Oracle determinista y casos revisados de 8959, Schedule A, AMT, FTC y reglas estatales. |

El generador nuevo debe partir de **hechos estructurados conocidos**, producir los documentos y conservar fuera del entorno del agente los hechos, relaciones y resultado esperado. El resultado de referencia debe calcularse con lógica independiente de la extracción; un LLM puede variar redacción o presentación, pero no ser la única fuente del GT.

Para la primera expansión propongo 100 expedientes base, con 1–3 representaciones visuales cada uno: 20 de retenciones/correcciones; 20 de K-1 y estados; 30 de pagos/estados/fechas; 15 de refunds/créditos; 15 de documentación incompleta, contradictoria o irrelevante. Son **cantidades propuestas, todavía no generadas**, no una garantía estadística de precisión. Las variantes del mismo expediente permanecen juntas en cualquier split.

La primera versión debe fijar ejercicio 2025, contexto previo 2024 y jurisdicciones seleccionadas. La lista de escenarios, contrato de GT y reglas de evaluación están en SPEC-evaluaciones.md. La parte inferior de análisis fiscal del workbook requiere especificación funcional adicional; las fotos no bastan para reconstruir todas sus fórmulas.

## Qué medir en el harness

Sí: se mide al **harness completo navegando y resolviendo tareas sobre esos documentos**. Los graders deben comprobar la respuesta y su evidencia, con métricas de extracción por campo, atribución de año/estado, deduplicación, tratamiento de datos faltantes y exactitud del expediente completo. Coste, tiempo y llamadas a herramientas se registran por separado. No hace falta exigir una secuencia concreta de herramientas para una respuesta correcta.

Los valores monetarios usan decimales y una política de redondeo explícita por tarea. Deben diferenciarse cero, vacío, ilegible, ausente, no aplicable y contradictorio. Para comparar agente directo, Document Intelligence y enfoque híbrido se mantienen los mismos expedientes, presupuesto y contexto autorizado. Los documentos de entrada son accesibles al agente; GT, expected_output, informes de auditoría y graders quedan fuera de su contenedor o montaje.

## Procedencia y reproducción

- TaxCalcBench: commit 8f89c2cf00a8906f4d896a02a2f45f9c9e85ae9b, licencia MIT incluida. El paper original describe TY24 como sintético; no se encontró una afirmación TY25 igualmente explícita. No se atribuye procedencia sintética verificada a cada registro TY25.
- ExtractBench: revisión f6180e917a050a84582e6366cff85b7dc1e84e58. La card declara Apache-2.0 para el dataset. Hay formularios de registros públicos reales con identificadores visibles; por eso el kit distribuye el manifiesto y un descargador separado, manteniendo esa procedencia explícita.
- Fake W-2: revisión HF ea077dbeb5715e7765308220c1d8c6e7d36cfd52. La [API oficial de Kaggle](https://www.kaggle.com/api/v1/datasets/view/mcvishnu1/fake-w2-us-tax-form-dataset) declara CC0 para el original; la card del repack HF enlaza ese origen pero no declara licencia propia.
- Formularios oficiales: se conservan fuente, ejercicio solicitado, fecha, bytes y SHA-256. Las plantillas e instrucciones son fuentes para generar datos; no etiquetas verificadas.

El ZIP incluye una comprobación local sin red, un notebook con sus resultados y scripts de adquisición. No se ejecutaron modelos ni se midió aún la precisión de ningún harness. No se incluyeron las fotos ni la plantilla corporativa. Cada fuente conserva su aviso; el paquete no sustituye las licencias de sus componentes.

Fuentes estatales y de pagos especialmente útiles: [CA K-1](https://www.ftb.ca.gov/forms/2025/2025-565-k-1.pdf), [CA 592-B](https://www.ftb.ca.gov/forms/2025/2025-592-b.pdf), [CA 3804](https://www.ftb.ca.gov/forms/2025/2025-3804.pdf), [CA 3804-CR](https://www.ftb.ca.gov/forms/2025/2025-3804-cr.pdf), [NJK-1](https://www.nj.gov/treasury/taxation/pdf/current/part/njk1.pdf), [NJ-2450](https://www.nj.gov/treasury/taxation/pdf/current/2450.pdf), [CA EDD](https://edd.ca.gov/en/payroll_taxes/what_are_state_payroll_taxes/), [IRS Direct Pay](https://www.irs.gov/payments/direct-pay-help), [IRS VITA 6744](https://www.irs.gov/pub/irs-pdf/f6744.pdf).
