# Contrato propuesto de datos y evaluación

Estado: diseño para la siguiente fase; no es un grader implementado ni GT ya validado. Esta especificación cubre fuentes y resultado de un Tax Payment Leadsheet funcional; no reproduce fórmulas propietarias.

## Unidad y separación

Un case_id identifica un expediente. source_group_id agrupa variantes visuales, páginas de la misma fuente, contribuyentes relacionados y correcciones. Se asigna el split al grupo antes de producir variantes. El holdout no se usa para ajustar prompts, seleccionar modelos, depurar herramientas ni calibrar confianza.

El runner monta sólo los documentos de entrada y el contexto declarado de la tarea. El proceso de grading mantiene GT, resultados fiscales, scripts generadores y reportes fuera de ese entorno. Copiar inputs a otro directorio no es por sí solo aislamiento si el agente puede leer el resto del host.

## Registros de referencia

| Registro | Campos necesarios | Observación |
|---|---|---|
| Documento | document_id, case_id, source_group_id, familia/subtipo, jurisdicción, ejercicio, revisión de plantilla, páginas, SHA-256, rol, versión | Ejercicio desconocido se mantiene desconocido; puede resolverse con contexto explícito. |
| Campo extraído | field_key, value, value_status, unidad, evidencia | value_status: known, missing, unreadable, not_applicable o conflicting; cero es known con valor cero. |
| Evidencia | document_id, página 1-based, box/line, cita o bbox | Definir bbox normalizada [0,1] y sistema de coordenadas. No obligar a bbox para JSON de entrada. |
| Hecho económico | fact_id, taxpayer_id, entity_id opcional, categoría, importe decimal, moneda, ejercicio, jurisdicción | Mismo hecho puede estar representado en varios documentos. |
| Evento de pago | event_id, fact_id, requested_date, effective_date, posted_date, status, confirmation_id, evidencia | pending, processed, cancelled, returned o unknown; no inferir liquidación sólo de un voucher. |
| Relación | from_id, to_id, tipo, evidencia | duplicate_of, corrects, supports, allocated_from, applied_to_year o contradicts. |
| Celda semántica | row_key, tax_year, payment_year cuando corresponda, jurisdicción, importe, contributing_fact_ids, evidencia | Preferir claves de negocio; el mapeo a coordenadas Excel depende de la versión de plantilla. |
| Contexto fiscal | ejercicio, jurisdicciones, declaración conjunta/individual cuando aplica, versión de reglas, política de redondeo | Los datos necesarios pero ausentes deben bloquear sólo los resultados dependientes. |

Dinero como string decimal en JSON; Decimal en cálculo. Distinguir ausencia de prueba de un pago de prueba de que no ocurrió. Un grado de confianza autodeclarado por el modelo no sustituye evidencia ni corrección.

## Matriz mínima de escenarios por generar

| Escenario | Documentos | Propiedad evaluada |
|---|---|---|
| Dos empleadores / varios estados | W-2, anexos, contexto | Agregación y atribución sin mezclar federal/estado/local. |
| Copia y corrección | W-2 repetido, W-2c; 1099 original/corregido | Mismo importe repetido no es otro pago; la versión vigente prevalece con evidencia. |
| K-1 federal + withholding estatal | K-1, CA K-1 y 592-B | Dos documentos pueden acreditar la misma retención. Verificar condiciones del ejercicio antes de mapear. |
| PTET entidad y socio | 3804, allocation statement, 3804-CR | Total entidad, asignación individual, crédito usado y carryover se mantienen separados. |
| Composite NJ | NJK-1 y soporte de declaración/pago colectivo | Checkbox por sí solo no acredita importe ni fecha. Soporte específico aún pendiente. |
| Aportes UI/DI/SDI | W-2 con box 14 y soportes de nómina; NJ-2450 cuando aplica | Nombre/código/jurisdicción/obligado. No universalizar reglas CA o NJ. |
| Q4 entre años | Voucher, confirmación y movimiento | Separar ejercicio al que aplica, fecha efectiva y fecha bancaria. |
| Pago programado, cancelado o devuelto | Confirmación, aviso, ledger | El importe solicitado no se cuenta como pago realizado sin el estado/evidencia exigido. |
| Extensión vs saldo | Solicitudes y comprobantes con mismos importes | Clasificación por finalidad e identidad del evento, no sólo por monto. |
| Refund vs crédito aplicado | Declaración previa, aviso, movimiento y 1099-G | Distinguir solicitado/recibido/aplicado y evitar duplicación entre fuentes. |
| 8959 y retención | W-2, datos de contribuyente y 8959 | Extracción separada del cálculo; validar reglas con oracle independiente. |
| Dato ausente, recortado o contradictorio | Página faltante, imagen recortada, anexos discordantes | Abstención localizada y solicitud concreta de evidencia; no inventar números. |
| Expediente largo | PDF con anexos, índices, duplicados y distractores | Encontrar evidencia pertinente y mantener relaciones. |
| Instrucción ajena a la tarea dentro de un documento | Texto sintético en nota/anexo | Tratar contenido como dato y completar la tarea autorizada. |

Para variantes visuales, registrar transformaciones y seed: texto digital, rasterizado, rotación, compresión y foto simulada. Si una transformación destruye un campo, actualizar su observabilidad y respuesta esperada; no penalizar al agente por no recuperar datos ausentes. Mantener legibles identificadores de versión y marcar mocks como sintéticos para investigación.

## Construcción del GT

1. Generar hechos y relaciones económicos en JSON con identificadores ficticios.
2. Calcular resultado esperado mediante reglas explícitas versionadas. Contrastar casos fiscales contra una implementación independiente o revisión experta; no validar un generador únicamente con sus mismas fórmulas.
3. Renderizar documentos desde esos hechos. Conservar mapeo de campos a páginas/casillas.
4. Revisar que el PDF renderizado exponga efectivamente los valores y que no existan datos ocultos que filtren la respuesta.
5. Añadir variantes/correcciones/eventos según matriz y revisar observabilidad.
6. Fijar versión, hashes, split por grupo y política del grader.

El GT de un resultado fiscal completo se promociona a verified sólo después de esa revisión. Los XML existentes de TaxCalcBench son candidate salvo los campos concretos ya contrastados; las reglas human de ExtractBench se conservan con su alcance por campo.

## Métricas y comparación

| Dimensión | Medida propuesta |
|---|---|
| Extracción | Exactitud normalizada por campo y macro por familia; reportar por separado valores no vacíos. |
| Evidencia | Documento/página/casilla correctos; tolerancia espacial fijada si se usan bbox. |
| Semántica | Exactitud de ejercicio, jurisdicción, categoría, estado y titular. |
| Relaciones | Precision/recall de duplicados, correcciones y asignaciones. |
| Resultado | Exactitud por celda y porcentaje de expedientes íntegramente correctos. |
| Incertidumbre | Alucinaciones ante ausencia y acierto al declarar missing/unreadable/conflicting. |
| Operación | Coste, latencia, tokens, llamadas, errores de herramientas y timeouts. |

Reportar todos los intentos, incluidos fallos y timeouts; evitar un promedio inflado por cientos de casillas vacías. Para comparar sistemas, fijar casos, presupuestos, prompts/contexto permitido, versión de modelo y herramientas. Si se repiten ejecuciones, informar tasa de éxito y dispersión; no seleccionar sólo el mejor intento. Las trazas sirven para diagnóstico, no para exigir una ruta de herramientas única.

Tres configuraciones comparables: agente con lectura directa; Document Intelligence más normalización; agente con Document Intelligence como herramienta. La suite debe permitir que los resultados decidan cuál conviene según tarea, precisión y coste.
