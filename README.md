# Document evaluation POC

Pruebas reales de **Pi, Tau y Codex** sobre cinco PDF sintéticos, seis tareas y 54 valores. Un runner entrega la misma tarea a cada harness, evalúa su JSON y publica resultados y trazas en Phoenix. Se conservan los PDF y valores esperados originales, con consigna explícita y validaciones reforzadas.

Las [definiciones de esta etapa](docs/PLAN.md) describen las condiciones de comparación y el futuro caso MCP → Document Intelligence.
La [auditoría del dataset y evaluadores](docs/DATASET_AUDIT.md) documenta la revisión de las 54 respuestas y los controles de integridad. La [matriz GPT-5.6](docs/VALIDATION_GPT56.md) completó 54/54 tareas con Luna, Sol y Terra en medium y verificó su publicación en Phoenix. La [validación histórica con GPT-5.5](docs/VALIDATION.md) conserva los resultados anteriores, con su versión de consigna y scoring.

El [reporte resumido del 13 de septiembre](docs/REPORTE_GPT56_2026-09-13.md) conserva el cierre de esta revisión. El [respaldo versionado de corridas](artifacts/2026-09-13/README.md) permite recuperar los resultados y las trazas al trasladar el proyecto.

La [guía para el harness corporativo](docs/CORPORATE_READINESS.md) reúne diagnóstico, tracing nativo, comparación con otra implementación e importación en un Phoenix nuevo. La [validación de esta preparación](docs/VALIDATION_PRE_CORPORATE.md) registra 225 tests aprobados y las pruebas reales de transporte y recuperación, sin nuevas inferencias.

## Preparar y ejecutar

Requisitos: Docker activo, `uv` y una sesión de Codex CLI autenticada con cuenta ChatGPT. Se verificó el runner en macOS/arm64 con workers Linux/arm64; Linux nativo y Windows mediante WSL2/Docker requieren su propio diagnóstico. Pi y Tau se instalan dentro de la imagen, sin instalar paquetes globales en el host.

```bash
docker build -f containers/harnesses.Dockerfile \
  -t doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0 containers
docker compose up -d --wait
./run.py --harness all --check
```

`--check` valida dataset, runtime, credenciales configuradas, lectura aislada de documentos y herramientas PDF sin ejecutar el harness. Con `--check-network` también prueba TLS hacia los destinos permitidos y transporte a Phoenix. Devuelve un JSON con controles, advertencias y `model_access: not_tested`; la configuración efectiva y el acceso al modelo se confirman en una corrida real.

```bash
./run.py --harness all --check --check-network
```

La cuenta de Codex existente se reutiliza mediante una credencial temporal de acceso. No se copia el refresh token ni se cambia el archivo de autenticación del host. Si vence el acceso, refrescar la sesión con `codex login` y volver a ejecutar; no hay renovación automática desde los workers.

Primera extracción y conciliación:

```bash
./run.py --harness all --task extract_doc_001 --timeout 180
./run.py --harness all --task reconcile_case --timeout 180
```

Luna, Sol y Terra, todos en `medium`: **54 invocaciones reales**, seis tareas × tres harnesses × tres modelos:

```bash
./run.py --harness all \
  --models gpt-5.6-luna gpt-5.6-sol gpt-5.6-terra \
  --thinking medium --repetitions 1 --timeout 180
```

Con `--repetitions 3` son 162 invocaciones. También se puede seleccionar `--harness pi`, `--harness tau` o `--harness codex`. Los perfiles fijan **Pi 0.85.1, Tau 0.4.3, Codex 0.145.0**, modelo por defecto **gpt-5.6-sol** y razonamiento **medium**. `--model`, `--models` y `--thinking` permiten otra configuración; debe estar soportada por los harnesses y por la cuenta. No se sustituyen modelos silenciosamente.

Phoenix: [http://127.0.0.1:6006](http://127.0.0.1:6006). Se conserva Phoenix 20.11.0, SQLite persistente y el cliente 3.5.0. `docker compose stop` conserva los datos. El proyecto de tracing es `doc-intell-poc`.

Para ejecutar sin publicación:

```bash
python3 -m evals --harness all --repetitions 3 --timeout 180
```

## Resultados y trazas

Cada experimento produce `runs/<id>/`:

- `report.json`: input exacto, respuesta original, scores por campo, errores, tiempos, tokens disponibles, configuración y versiones/hashes.
- `scores.csv`: una fila por tarea y repetición, con su `trace_id`.
- `traces.json`: spans OpenTelemetry/OpenInference listos para publicar.
- `tasks/<tarea>-<repetición>/events.json`: eventos normalizados de mensajes/herramientas; sin stderr, argumentos/resultados crudos ni textos intermedios.
- `phoenix.json` y `traces-upload.json`: progreso de publicación para reintentos.

`--harness all` agrega un `comparison-<id>.json` y CSV con calidad, duración y consumo por harness, respaldado por los reportes originales. Los resultados de extracción y conciliación también están separados en el resumen de cada experimento.

Los artefactos se guardan después de cada tarea terminada. Si falla la publicación:

```bash
./run.py --upload-only runs/ID-DE-LA-CORRIDA
```

Ese comando nunca llama al modelo. Los IDs de tareas y spans se conservan; ante una respuesta de red incierta puede repetirse la transmisión, no la inferencia. `--phoenix-url`/`PHOENIX_ENDPOINT` cambian el destino de los reportes y de ambas rutas de tracing, y `PHOENIX_API_KEY` configura su autenticación. El endpoint admite un origen HTTP(S), sin credenciales embebidas ni prefijo de ruta; los destinos loopback se traducen a `host.docker.internal` para el proxy.

Para reconstruir un historial en **otra instancia** usar `--import-run runs/ID --phoenix-url URL --output-dir runs/restored`. Esa importación conserva los scores históricos, revalida el destino y deja los originales intactos. No usa los checkpoints de la instancia anterior ni registra evaluadores actuales para reetiquetar resultados antiguos. [Detalles y referencias históricas](docs/CORPORATE_READINESS.md#reconstruir-el-historial-en-phoenix).

Si falla la publicación durante `--harness all`, se terminan las ejecuciones y la comparación locales, se informa cada directorio pendiente y el comando retorna 1. Los reportes interrumpidos, con `complete: false`, no se publican ni se mezclan con experimentos completos.

El runner crea una traza por tarea/harness/repetición, asociada al experimento de Phoenix. Pi/Tau aportan spans de mensajes y herramientas observados. Codex aporta herramientas y uso agregado del turno: sus eventos no identifican cada petición LLM. Los tiempos de eventos son observados al recibirlos; la duración total incluye contenedores y limpieza. Los tokens cacheados son subconjuntos del total de entrada. Los costes de suscripción no se presentan como costes API: quedan `null`.

## Entorno y entrada del harness

Un texto UTF-8 por stdin con instrucciones, IDs, documentos, campos/tipos y formato esperado. La respuesta final debe ser un único JSON `{"values": ..., "evidence": ...}`. El adapter separa eventos de respuesta; no corrige JSON, valores ni evidencias.

Cada tarea inicia un contenedor y sesión nuevos. Sólo se montan sus PDF asignados, como `/workspace/inputs/...`; el dataset privado, grader, tests, README y reportes quedan fuera. El agente usa sus herramientas nativas y puede invocar `pdftotext`, `pypdf`, `pdfplumber`, shell, etc. No hay extracción previa desde el runner ni llamadas directas del runner a APIs de modelos.

El worker usa una red interna con salida por un proxy limitado a los destinos del perfil. El proxy deniega lecturas de Phoenix y permite únicamente POST `/v1/traces` hacia ese servicio. Credenciales de modelo y de Phoenix no se imprimen en argumentos ni se guardan en reportes. El contexto de build es exclusivamente `containers/`.

## Conectar el harness corporativo

El [perfil de ejemplo](harnesses/corporate.example.json) espera un ejecutable que recibe texto por stdin y devuelve JSON simple. **Puede usar su propia implementación OTel; no tiene que emitir nuestros eventos JSONL.**

1. Crear una imagen que extienda la imagen de harnesses e instale el ejecutable corporativo.
2. Copiar el perfil de ejemplo y completar comando, versión, modelo/proveedor y las variables de entorno que deba recibir. Guardar nombres de variables, nunca sus valores secretos. `allowed_hosts` permite definir la lista completa de destinos del proveedor; reemplaza la lista de OpenAI usada por defecto.
3. Configurar su OTel con el endpoint de ingestión proporcionado. El runtime ofrece `TRACEPARENT`, `DOC_INTELL_RUN_ID`, `DOC_INTELL_TASK_ID`, `DOC_INTELL_REPETITION` y `OTEL_RESOURCE_ATTRIBUTES`, además de `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`/`PROTOCOL`. La relación padre-hijo requiere que su implementación extraiga el contexto; si no lo hace, las trazas se correlacionan por esos IDs cuando su SDK los registra.

```bash
./run.py --profile harnesses/mi-corporate.json --image mi-imagen-corporate --check
./run.py --profile harnesses/mi-corporate.json --image mi-imagen-corporate --task extract_doc_001
```

El perfil de ejemplo necesita completarse y su CLI privado todavía no se ha probado. El MCP de Document Intelligence pertenece a la siguiente etapa.

Los spans del OTel corporativo se envían directamente al collector. Su SDK debe cerrar/exportar antes de terminar el proceso y gestionar su propia recuperación; `--upload-only` sólo recupera los spans que guardó nuestro runner, no los spans nativos que nunca llegaron al collector.

La prueba de conformance usa un SDK real y verifica spans, padres y exportación con/sin gzip en Phoenix efímero. `forward_env` reserva contexto W3C, `DOC_INTELL_*` y `OTEL_*` para preservar la correlación administrada por el runner.

La interfaz anterior sigue disponible para un ejecutable instalado en el host:

```bash
./run.py --harness-command "mi-harness run"
python3 -m evals --harness-command "mi-harness run"
```

Ese modo conserva texto stdin/JSON stdout y timeout, pero **no aplica el aislamiento Docker** ni presume detalle de herramientas o spans OTel internos. Las credenciales las gestiona el ejecutable. No hay producción offline/replay; los dobles viven en tests.

## Scoring y validación

- `schema_valid`: estructura exacta, campos, tipos, decimales como strings y formato de citas. JSON con claves duplicadas o números no finitos se rechaza en el transporte.
- `value_accuracy`: comparación del grader original con `Decimal`, sin confundir ausencia y cero.
- `evidence_accuracy`: coincidencia del conjunto documento/página/casilla; no verifica bbox, texto de citas o trayectoria de herramientas.
- `task_pass`: ejecución exitosa, schema válido y todos los valores/evidencias correctos.
- `execution_status`: éxito, respuesta inválida, timeout, no soportado o error del adapter. Los errores de ejecución puntúan cero y permanecen en el denominador. Un error de formato invalida `schema_valid` y `task_pass`; `value_accuracy` sigue siendo una métrica diagnóstica independiente y puede reconocer un valor numéricamente correcto.

Antes de ejecutar modelos, el loader exige que tareas, tipos y ground truth tengan exactamente los mismos campos y valida integridad/rutas de documentos, formato de referencias y páginas dentro del rango declarado en el manifest. La existencia de las casillas y páginas en estos PDF se verificó durante la auditoría documental; el loader no interpreta sus etiquetas. La conciliación pide expresamente el total de Form 8959 línea 24: otro importe idéntico no sustituye esa cita. La política vigente es `tax-mini-v2` y el prompt `tax-mini-text-v4`; no se mezclan reportes de distintos hashes de dataset o evaluador.

Los tests no constituyen resultados de modelos:

```bash
python3 -m unittest discover -s tests -v
DOC_INTELL_DOCKER_TESTS=1 python3 -m unittest discover -s tests -p test_runtime_integration.py -v

# Suite completa, incluido protobuf y transporte OTel a Phoenix activo:
DOC_INTELL_DOCKER_TESTS=1 DOC_INTELL_PHOENIX_TESTS=1 \
  uv run --with arize-phoenix-client==3.5.0 --with opentelemetry-proto==1.44.0 \
  python -m unittest discover -s tests -q
```

El primer comando usa Python estándar; el test opcional de protobuf requiere las dependencias fijadas de `run.py`. El segundo prueba aislamiento con Docker real y no llama a proveedores. La suite completa incluye el cliente Phoenix para importar a una instancia efímera real.

El POC sigue usando el formato y grader de tax-mini-poc; agregar otro directorio de dataset no lo hace automáticamente compatible. No hay LLM juez. La CLI retorna 0 al producir/publicar reportes aunque los scores fallen, porque es una herramienta exploratoria, no un gate de CI.

Las nuevas comparaciones separan hashes de contrato/scoring y runtime. Un cambio de adapter ya no bloquea una comparación compatible; el scoring y las consignas sí deben coincidir. La [migración explícita del baseline](docs/FINGERPRINTS.md) permite usar las nueve corridas anteriores sin repetir llamadas a modelos.
