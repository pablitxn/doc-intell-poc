# Operación diaria

[Inicio](../README.md) · [Mapa y conceptos](GUIA_DEL_PROYECTO.md) · [Índice de documentación](README.md)

Los comandos se ejecutan desde la raíz del repositorio. Las rutas `runs/ID_DE_LA_CORRIDA` son marcadores: reemplazarlas por el directorio que imprime la CLI.

## Preparar el entorno

Necesitás Docker activo, `uv` y una sesión de Codex CLI autenticada con cuenta ChatGPT. Pi y Tau se instalan dentro de la imagen. El entorno probado fue macOS/arm64 con workers Linux/arm64; la [guía corporativa](CORPORATE_READINESS.md) detalla el diagnóstico para otra máquina, Linux o WSL2. `uv` resuelve las dependencias de cada script: el builder requiere Python ≥3.12 y `run.py` admite ≥3.10,<3.15.

```bash
docker build -f containers/harnesses.Dockerfile \
  -t doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0 containers
docker compose up -d --wait
python3 -m evals --dataset datasets/tax-document-eval-v1 \
  --harness all --check --check-network
```

`--check` comprueba configuración, imagen, montaje y lectura de documentos. `--check-network` también prueba las conexiones permitidas y el transporte hacia Phoenix. No ejecutan inferencias; `ready` no demuestra acceso efectivo al modelo ni valida por sí solo las etiquetas del dataset. Para esas etiquetas, usar `uv run scripts/prepare_full_dataset.py --check`.

La cuenta de Codex existente se reutiliza con una credencial temporal de acceso. Si vence, refrescar la sesión con `codex login` y repetir el diagnóstico/corrida. Las credenciales no se guardan en el proyecto ni en reportes; los workers no renuevan el refresh token del host.

Phoenix se abre en [localhost:6006](http://127.0.0.1:6006), con proyecto de tracing `doc-intell-poc`. Compose conserva sus datos en un volumen: `docker compose stop` permite detenerlo sin borrarlos.

## Elegir la ejecución

| Comando u opción | Efecto |
|---|---|
| `./run.py ...` | Ejecuta, evalúa, guarda localmente y publica dataset, resultados, scores y trazas en Phoenix |
| `python3 -m evals ...` | Ejecuta y guarda reportes locales; no publica los resultados del evaluador. El OTel propio del harness puede enviar spans directamente |
| `--dataset datasets/tax-document-eval-v1` | Selecciona el conjunto completo; el valor por defecto es `tax-mini-poc` |
| `--task ID` | Limita la ejecución a una tarea; omitirlo selecciona todas |
| `--harness pi`, `--harness tau`, `--harness codex` | Elige un harness nativo |
| `--harness all` | Ejecuta secuencialmente los tres y genera una comparación |
| `--model NOMBRE` / `--models A B C` | Elige uno o varios modelos; no se sustituyen modelos silenciosamente |
| `--thinking medium` | Solicita ese nivel de razonamiento en los perfiles que lo soportan |
| `--repetitions N` | Repite cada tarea; cada invocación nativa comienza con sesión y contenedor nuevos |
| `--timeout 300` | Límite en segundos por invocación, no por la matriz completa |

Los perfiles fijan Pi 0.85.1, Tau 0.4.3 y Codex 0.145.0; el modelo por defecto es Sol con reasoning medium. Las versiones/configuración se registran en `harness_metadata`, junto con el ID de imagen. Para un perfil privado, su modelo y reasoning pueden ser sólo declaraciones hasta verificarlos contra su implementación/trazas.

Para explorar el minimal de forma explícita:

```bash
./run.py --dataset datasets/tax-mini-poc --harness codex \
  --model gpt-5.6-sol --thinking medium --task extract_doc_001 --timeout 180
```

Para el completo, seguí [su guía de ejecución](FULL_DATASET_READINESS.md#primera-corrida-real). Un modelo × un harness × todas sus tareas son **366 invocaciones**; tres modelos × tres harnesses son **3.294 por repetición**. El minimal tiene seis tareas, por lo que esa misma matriz son 54 invocaciones.

## Leer un resultado

Cada combinación harness/modelo genera `runs/<id>/`. `--repetitions` agrega filas dentro de ese experimento. Las ejecuciones con varios perfiles generan además un `comparison-<id>.json` y CSV que apuntan a los reportes originales.

| Archivo | Para qué abrirlo |
|---|---|
| `report.json` | Resultado principal: resumen, input exacto, respuesta original, errores, scores, tiempos, uso y versiones |
| `scores.csv` | Una fila por tarea/repetición; sirve para filtrar y ordenar los resultados |
| `dataset-snapshot.json` | Prompts y referencias privadas del dataset completo, incluso si se ejecutó una sola tarea |
| `traces.json` | Spans guardados por el runner, con IDs y atributos para publicar |
| `tasks/<tarea>-<repetición>/events.json` | Eventos normalizados; no contiene texto intermedio ni argumentos/resultados crudos de herramientas |
| `phoenix.json`, `traces-upload.json` | Progreso de publicación en el destino original; sirven para reintentos |

Empezá por `report.json`: `complete` indica que terminó la ejecución prevista; `summary.tasks_passed` indica cuántas tareas aprobaron. En `rows[]`, `input` muestra qué recibió el harness, `output` su respuesta y `scores.fields` indica qué valores/evidencias acertó. Las respuestas esperadas se encuentran en `dataset-snapshot.json → examples[] → expected`, buscando el mismo `task_id`; la procedencia de cada referencia está en `ground_truth/provenance.json` del dataset completo.

Este comando lee un reporte y muestra el resumen y la primera tarea que no aprobó. No llama modelos ni cambia el archivo:

```bash
python3 - runs/ID_DE_LA_CORRIDA/report.json <<'PY'
import json, sys
from pathlib import Path
report_path = Path(sys.argv[1])
report = json.loads(report_path.read_text())
print(json.dumps({"complete": report["complete"], "summary": report["summary"]}, indent=2))
for row in report["rows"]:
    if not row["scores"]["task_pass"]:
        print(json.dumps({"task_id": row["task_id"], "repetition": row["repetition"],
                          "output": row["output"], "error": row["error"],
                          "scores": row["scores"]}, indent=2))
        snapshot_path = report_path.parent / "dataset-snapshot.json"
        if snapshot_path.exists():
            snapshot = json.loads(snapshot_path.read_text())
            example = next(e for e in snapshot["examples"] if e["task_id"] == row["task_id"])
            print(json.dumps({"expected": example["expected"]}, indent=2))
        break
PY
```

## Interpretar scores y fallos

| Resultado | Qué significa / dónde mirar |
|---|---|
| `complete: false` | La ejecución quedó interrumpida; no tratarla como experimento completo |
| `scores.execution_status` distinto de `success` | Revisar `error` y `schema_errors`: timeout, error de adapter, no soportado o respuesta inválida |
| `schema_valid: false` | JSON, claves, tipos o formato de evidencias no cumplen el contrato |
| `value_accuracy < 1` | Hay valores incorrectos; ver cada campo de `scores.fields` y comparar `output` con `expected` |
| `evidence_accuracy < 1` | Documento, página o casilla no coincide con el conjunto requerido, aunque el monto sea correcto |
| `task_pass: true` | Ejecución exitosa, esquema válido y todos los valores/evidencias correctos |
| Reporte local completo, publicación fallida | Recuperar con `--upload-only`; no repetir la inferencia para arreglar Phoenix |

El estado de ejecución de la fila describe lo devuelto por el adapter; `scores.execution_status` incorpora además la validación de esquema. La CLI puede terminar con código 0 aunque una respuesta falle: es una herramienta de evaluación, no un gate de calidad. Para decidir si una corrida aprobó, leer sus scores.

Los importes se comparan con `Decimal` y se entregan como strings de dos decimales. Un cero es distinto de un campo ausente. La evidencia exige las referencias canónicas de la tarea: no acepta cualquier casilla que casualmente contenga el mismo importe. No evalúa bbox ni la trayectoria de herramientas. Los fallos de ejecución permanecen en el denominador; los scores de valores y evidencias también permiten diagnosticar respuestas cuyo esquema no aprobó.

El scorer conserva el nombre `tax-mini-v2`, pero se usa con ambos datasets. Los evaluadores son deterministas; no hay LLM juez ni reparación automática de respuestas. Ver [el recorrido de una tarea](GUIA_DEL_PROYECTO.md) para conectar esas reglas con los archivos.

## Recuperar o trasladar resultados

Para reintentar la publicación de una corrida actual en su destino original:

```bash
./run.py --dataset datasets/tax-document-eval-v1 \
  --upload-only runs/ID_DE_LA_CORRIDA --phoenix-url http://127.0.0.1:6006
```

Para reconstruir resultados guardados en otra instancia, incluso históricos:

```bash
./run.py --import-run runs/ID_DE_LA_CORRIDA \
  --phoenix-url http://127.0.0.1:6006 --output-dir runs/restored
```

Los dos comandos evitan nuevas inferencias. `--upload-only` exige el dataset y contrato/scoring actuales y reutiliza los checkpoints originales. `--import-run` conserva respuestas y scores históricos, verifica el destino y guarda recibos separados. También requieren importación las corridas anteriores al reordenamiento del scorer: tanto la matriz minimal v4 como las 12 pruebas del completo v5 conservan el hash de scoring anterior. Usar el mismo prompt v5 no alcanza para habilitar `--upload-only`. Ver [detalles](CORPORATE_READINESS.md#reconstruir-el-historial-en-phoenix).

`--phoenix-url` o `PHOENIX_ENDPOINT` eligen el destino; `PHOENIX_API_KEY` configura su autenticación. El endpoint admite un origen HTTP(S), sin credenciales embebidas ni prefijo de ruta. Ante una respuesta de red incierta pueden retransmitirse los mismos IDs; no se repite la inferencia. Los reportes incompletos no se publican.

`runs/` está ignorado por Git. Los respaldos versionados de [la matriz minimal](../artifacts/2026-09-13/README.md) y [las pruebas del completo](../artifacts/2026-09-13/full-dataset/README.md) contienen instrucciones para restaurarlos. Las comparaciones sólo admiten datasets, contratos, scoring y tareas/repeticiones compatibles: [reglas de fingerprints](FINGERPRINTS.md).

## Entender las trazas y el aislamiento

El runner genera una traza por tarea/harness/repetición. Pi y Tau aportan eventos observados de mensajes y herramientas; Codex aporta herramientas y uso agregado del turno, sin identificar necesariamente cada petición LLM. Los tiempos de eventos se observan al recibirlos; la duración total incluye preparar y limpiar contenedores. Los tokens cacheados forman parte de la entrada, no se suman dos veces. El coste desconocido de la suscripción queda `null`.

Cada worker recibe sólo sus documentos asignados bajo `/workspace/inputs/`, además de su consigna y credenciales temporales. Ground truth, código del evaluador, tests y reportes quedan fuera. El agente lee documentos con sus herramientas nativas; el runner no le preextrae las respuestas. Una red interna y proxy limitan la salida: Phoenix sólo admite POST `/v1/traces` desde el worker, no consultas a sus referencias o reportes.

El corporativo puede conservar su OTel y devolver JSON simple. Debe extraer el contexto recibido y terminar de exportar antes de salir. `--upload-only` recupera los spans guardados por nuestro runner; los spans privados que nunca llegaron al collector dependen del exporter corporativo. La configuración y prueba del SDK están en la [guía corporativa](CORPORATE_READINESS.md#otel-nativo).

La interfaz para un ejecutable instalado en el host sigue disponible:

```bash
./run.py --dataset datasets/tax-mini-poc --harness-command "mi-harness run" \
  --task extract_doc_001
```

Ese modo usa texto stdin / JSON stdout y timeout, pero no aplica el aislamiento Docker. Para conectar el corporativo con aislamiento, partir de su [perfil de ejemplo](../harnesses/corporate.example.json).

## Elegir los controles al cambiar algo

| Cambio | Control útil |
|---|---|
| Fuentes o preparación del dataset completo | `uv run scripts/prepare_full_dataset.py --check`, auditoría y tests del dataset |
| Loader, prompt, esquema o scoring | Tests de contrato y respuestas adversariales; revisar qué fingerprints cambiaron |
| Perfil, imagen o red | Diagnóstico `--check --check-network`, luego una tarea real explícita |
| Adapter, tracing, reporting o importación | Tests correspondientes y pruebas de integración con Docker/Phoenix |
| Documentación | Enlaces y ejemplos contra la CLI y los archivos; no necesita inferencias |

Las pruebas se agrupan por responsabilidad: [`unit/`](../tests/unit/) para lógica, [`datasets/`](../tests/datasets/) para fuentes/referencias y [`integration/`](../tests/integration/) para Docker/Phoenix. [`support/`](../tests/support/) contiene utilidades compartidas, y [`fixtures/`](../tests/fixtures/) datos y procesos de prueba. Por ejemplo, `python3 -m unittest tests.unit.test_scoring -v` ejecuta sólo el scoring; `tests.datasets.test_full_dataset` selecciona los controles del conjunto completo.

Suite local sin activar las integraciones opcionales:

```bash
python3 -m unittest discover -s tests -v
```

Este comando puede omitir tests por falta de dependencias PDF/protobuf y por los flags de integración. Un `OK (skipped=...)` no equivale a la suite completa.

Suite de referencia con dependencias fijadas y Docker/Phoenix efímeros:

```bash
DOC_INTELL_DOCKER_TESTS=1 DOC_INTELL_PHOENIX_TESTS=1 \
  uv run --with-requirements tests/requirements.txt \
  python -m unittest discover -s tests -q
```

Los tests usan dobles y SDKs de prueba donde corresponde; no llaman modelos. La evidencia de ejecución real está separada en los [reportes de auditoría](README.md#evidencia-del-dataset-completo).
