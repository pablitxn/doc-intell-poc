# Pruebas de harnesses: definición e implementación v1

Estado: integración nativa implementada, auditoría completada y matriz Luna/Sol/Terra ejecutada: 54/54 tareas aprobadas y publicación en Phoenix verificada. La preparación para el corporativo agrega diagnóstico, conformance OTel con SDK real, fingerprints separados e importación a otra instancia: **225 tests aprobados**, sin nuevas inferencias. Ver [validación de esta etapa](VALIDATION_PRE_CORPORATE.md), [guía de traslado](CORPORATE_READINESS.md), [auditoría](DATASET_AUDIT.md), [matriz GPT-5.6](VALIDATION_GPT56.md) y [resultados históricos](VALIDATION.md). Los artefactos originales se conservan en `runs/` y en el [respaldo versionado](../artifacts/2026-09-13/README.md).

## Alcance acordado

- Mantener los cinco PDF sintéticos, seis tareas y 54 valores del dataset actual.
- Primera ruta: lectura de PDF con las herramientas nativas de Pi, Tau y Codex. Las herramientas disponibles incluyen shell, Poppler y librerías Python de PDF. No preextraemos respuestas ni texto desde el runner.
- Modelos `gpt-5.6-luna`, `gpt-5.6-sol` y `gpt-5.6-terra`, proveedor por suscripción `openai-codex` y razonamiento `medium`. Cada modelo se compara en los tres harnesses. Los prompts internos y el comportamiento de herramientas pertenecen a cada harness.
- Reutilizar la cuenta de Codex autorizada por el usuario. No crear API keys ni modificar la autenticación del host.
- Cinco tareas de extracción y una de conciliación; scoring determinista de valores/evidencias conservado, con validaciones de contrato reforzadas y aprobación consistente entre runner, CLI y Phoenix.
- Prompt `tax-mini-text-v4` y evaluador `tax-mini-v2`: formato explícito para todas las tareas y cita canónica de la línea 24 requerida públicamente. Validación de membresía exacta de campos y transporte JSON inequívoco; valores y PDF sin cambios.
- Cada repetición comienza con sesión y filesystem nuevos. Ejecución secuencial, sin retries del runner. Los retries internos de los productos siguen formando parte de su comportamiento.
- La nueva matriz es seis tareas por tres harnesses por tres modelos: 54 invocaciones con una pasada; 162 con tres repeticiones. La cantidad de repeticiones se registra en cada reporte.
- El MCP de Document Intelligence se implementará en una segunda etapa, usando las mismas tareas y scoring, y registrando una ruta de acceso diferente.

## Contrato estable

El proceso recibe un único texto UTF-8 por stdin y devuelve una respuesta final JSON `values/evidence`. Los adapters de Pi/Tau/Codex separan esa respuesta de sus eventos JSONL. La respuesta se evalúa sin reparar contenido, tipos, citas o JSON inválido. El perfil corporativo puede seguir devolviendo JSON simple.

Cada invocación interna recibe documentos públicos, IDs y contexto técnico. El ground truth sólo pertenece al runner/evaluador. Las rutas visibles dentro del contenedor son `/workspace/inputs/...`, independientes del host.

La imagen contiene únicamente herramientas y harnesses. Cada worker monta sólo sus PDF asignados y una credencial temporal de acceso. Una red interna y proxy con destinos permitidos evitan consultas a los evaluadores del host. El proxy ofrece POST `/v1/traces` para ingestión de telemetría nativa, sin consultas a Phoenix. La configuración explícita de `allowed_hosts` de un perfil reemplaza la lista de destinos de proveedor por defecto.

## Tracing y corporativo

- Una traza por tarea, harness y repetición: `task.execute`, `harness.execute`, operaciones observadas y `evaluate`.
- La respuesta, scores, tiempos y uso reportado se conservan en los reportes locales. Las trazas se exportan como OTLP protobuf con atributos OpenInference.
- Pi/Tau: lifecycle observado de mensajes y herramientas. Codex: herramientas y uso agregado de turno; no se inventan spans por petición de modelo cuando el CLI no expone esos límites.
- Timestamps internos: momento de recepción del evento, no latencia exacta del proveedor. La duración total incluye la preparación y limpieza del entorno.
- Tokens ausentes y coste de suscripción permanecen desconocidos. No se suman dos veces tokens cacheados ni snapshots acumulados.
- Los eventos persistidos contienen metadatos normalizados; no guardan stderr, texto intermedio ni argumentos/resultados crudos de herramientas.
- El corporativo conserva su implementación OTel. No necesita emitir JSONL ni adoptar nuestro collector de eventos. Se le ofrece `TRACEPARENT`, IDs de correlación y configuración estándar OTLP. Continuar el padre requiere que su código extraiga ese contexto; ofrecer una variable de entorno no demuestra propagación. Si crea su propia traza, se correlaciona por IDs de ejecución.
- `--upload-only` reenvía artefactos completos con el contrato/scoring vigentes y no repite inferencias. Un HTTP de resultado incierto puede obligar a reenviar los mismos IDs de span; no se promete entrega exactamente una vez.
- `--import-run` reconstruye resultados históricos en otra instancia con sus scores y metadatos originales. Revalida contenido remoto en cada reintento y guarda su recibo fuera de los originales; no ejecuta el evaluador actual ni llama al modelo.
- `--phoenix-url` configura también el destino del proxy para OTel nativo. La recuperación de spans emitidos directamente por el corporativo pertenece a su SDK/exporter; nuestro reintento sólo recupera los artefactos locales.

## Criterios de aceptación

1. Los tres CLI reales instalados y versionados en una imagen identificada por SHA.
2. Entrada exacta y extracción estricta de la respuesta final, con tests de errores, timeouts, tokens y limpieza.
3. Prueba Docker real: PDF asignado accesible, otros documentos/GT ocultos y consultas a Phoenix bloqueadas.
4. Repeticiones con identificadores independientes, errores incluidos en denominadores y comparación JSON/CSV.
5. Scores y traza asociados en Phoenix mediante `trace_id`; reintento de publicación sin llamar al harness.
6. Pruebas reales contra el modelo separadas de los dobles de tests.
7. Perfil corporativo con transporte JSON y OTel nativo, sin implementar todavía su CLI privado ni el MCP.
8. Diagnóstico desde una copia limpia que verifica runtime, documentos y transportes sin iniciar el harness ni inferencias.
9. Propagación padre-hijo con SDK OTel real y exportación HTTP/protobuf con y sin gzip a Phoenix efímero.
10. Comparación con fingerprints separados y migración explícita de copias de los nueve reportes auditados, manteniendo intactos los originales.
11. Importación a Phoenix vacío, recuperación tras respuesta incierta y reintento sin duplicados, con scores históricos y referencias guardadas cuando existen.

## Fuentes de las interfaces

- [Pi CLI y eventos](https://github.com/earendil-works/pi/tree/main/packages/coding-agent).
- [Tau CLI y autenticación](https://github.com/huggingface/tau).
- [Codex no interactivo](https://learn.chatgpt.com/docs/non-interactive-mode).
- [Experimentos y trace_id en Phoenix](https://arize-phoenix.readthedocs.io/projects/client/api/experiments.html).
