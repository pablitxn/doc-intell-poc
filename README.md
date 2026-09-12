# Document evaluation POC

Primera iteración: definir un estilo simple para las evaluaciones y ejecutarlas localmente con respuestas de prueba o guardadas. Python 3.10+, biblioteca estándar, sin instalación ni credenciales.

El dataset original contiene 5 PDF sintéticos, 6 tareas y 54 valores de un único expediente. Su grader se conserva sin cambios. Este proyecto todavía no ejecuta el harness, modelos, Azure DI ni Phoenix; las ejecuciones se marcan `is_benchmark: false`.

## Ejecutar

Desde la raíz del repositorio:

```bash
python3 -m unittest discover -s tests -v
python3 -m evals --smoke
python3 -m evals --predictions model-output.json
python3 -m evals --predictions model-output.json --task reconcile_case
```

`--smoke` devuelve respuestas vacías intencionalmente: debe evaluar 54 campos y aprobar 0/6 tareas. Los tests prueban por separado que las referencias aprueban y los errores deliberados fallan. No son mediciones de calidad de un modelo.

`--predictions` recibe el formato original del dataset:

```json
{
  "answers": {
    "extract_doc_001": {
      "values": {"wages": "123.00"},
      "evidence": {
        "wages": [{"document_id": "DOC-001", "page": 1, "box": "1"}]
      }
    }
  }
}
```

Este ejemplo está incompleto: una tarea necesita todos sus campos de `tasks.json`. Las tareas ausentes cuentan como fallidas; `--task` permite evaluar una sola. Un archivo JSON ilegible es un error de entrada de la CLI.

Cada ejecución genera `runs/<timestamp>-<id>/report.json` y `scores.csv`. El JSON conserva inputs, respuestas, errores, checks por campo, denominadores, hashes del dataset y código, y versión del evaluador. El CSV tiene una fila por tarea. El tiempo mide la llamada al adapter local; en replay no representa latencia del harness. Los costes no medidos son `null`. La CLI retorna 0 cuando produce el reporte, aunque los scores fallen: en esta etapa es una herramienta exploratoria, no un quality gate de CI.

## Arquitectura y estilo

```text
datasets/
  tax-mini-poc/           # PDF, tareas, manifiesto, GT y grader original
evals/
  contracts.py           # TaskInput, Example y firma del adapter
  datasets/
    loader.py            # Carga y validación del dataset
  adapters/
    offline.py           # Respuestas de prueba y replay; futuros adapters aquí
  evaluators/
    schema.py            # Validación de la respuesta sin consultar GT
    tax_mini.py          # Política de scoring para tax-mini-poc
  experiments/
    runner.py            # Ejecución y reportes
  __main__.py            # CLI
tests/
```

`datasets/` contiene los datos; `evals/datasets/` contiene el código que los carga. Cada futuro dataset tendrá su propio directorio. El loader y el runner actuales siguen usando el formato y la política de tax-mini-poc; alojar otro dataset no lo hace automáticamente compatible.

```text
tasks + manifest ──> TaskInput ──> adapter ──> output
                                                │
ground_truth ──> Example.expected ──> evaluate <───┘
                                       │
                                  JSON / CSV
```

| Archivo | Responsabilidad |
|---|---|
| `evals/contracts.py` | Dos dataclasses y la firma `HarnessAdapter(TaskInput) -> object`. |
| `evals/datasets/loader.py` | Carga, verificación de hashes y separación de inputs/referencias. |
| `evals/adapters/offline.py` | Respuestas vacías y replay del formato `answers/TASK_ID`. |
| `evals/evaluators/schema.py` | Validación de tipos y referencias, sin consultar valores esperados. |
| `evals/evaluators/tax_mini.py` | Puente al grader existente y composición de scores. |
| `evals/experiments/runner.py` | Una llamada por tarea, scoring y persistencia de resultados. |
| `evals/__main__.py` | Argumentos y salida de consola. |

Funciones pequeñas, nombres explícitos y dependencias pasadas por parámetros. Usamos dataclasses para distinguir el input público del ejemplo con GT, y diccionarios para el JSON del dominio. Una función callable basta para el adapter; no hay clases base, registro de plugins ni framework propio. Un evaluador no llama al harness, no persiste archivos y no modifica la respuesta.

Para sumar un check, escribir una función en `evals/evaluators/`, incluir su resultado en `tax_mini.evaluate` y agregar una prueba positiva y otra negativa. Cambiar la política implica incrementar `EVALUATOR_VERSION`; ambas rutas deberán usar la misma versión.

## Cómo se inyecta el harness

Por el parámetro `adapter` de `run_experiment`. Hoy ya se puede ejecutar este ejemplo desde la raíz:

```python
from pathlib import Path

from evals.adapters.offline import empty_response
from evals.experiments.runner import run_experiment

run_experiment(
    dataset=Path("datasets/tax-mini-poc"),
    adapter=empty_response,
    output_dir=Path("runs"),
    mode="smoke",
)
```

El adapter real será una función `run_task(task: TaskInput) -> object` en un módulo propio bajo `evals/adapters/`. Se pasa esa función en lugar de `empty_response`; no hace falta heredar una clase. `mode` es una etiqueta del reporte, no configura el harness ni convierte la ejecución en un benchmark validado. La CLI actual sólo expone smoke y replay; la inyección personalizada es mediante la API Python.

La función debe crear una sesión nueva, serializar el input con `dataclasses.asdict(task)`, entregar los PDF indicados e invocar la API o CLI del harness. Devuelve el objeto `{"values": ..., "evidence": ...}` de esa tarea. Sólo el evaluator recibe `Example.expected`. Todavía no implementamos esa llamada porque no conocemos la interfaz del harness.

El cliente, endpoint, modelo, ruta de extracción y raíz de documentos se configuran al construir el adapter, por ejemplo mediante un closure o `functools.partial`. Los `path` de `task.documents` son relativos a `datasets/tax-mini-poc/`; el adapter debe resolverlos y transportar o montar únicamente los documentos autorizados. Pasar una ruta local a una API remota no adjunta el PDF. La raíz completa del dataset no se entrega al agente.

La ruta de extracción se fija antes de ejecutar; el agente no recibe un selector. Las respuestas finales y el contrato de extracción son niveles distintos: esta versión implementa sólo las respuestas finales del dataset.

## Política de scoring v1

- `schema_valid`: campos completos, dinero/porcentajes como strings con dos decimales, booleanos reales, fechas ISO y referencias con página entera positiva. `bbox` y metadatos adicionales no se puntúan.
- `value_accuracy`: comparación del grader original, con `Decimal` y sin confundir ausencias con cero. Puede dar 1 aunque falle el schema, por ejemplo si un importe correcto viene como número.
- `evidence_accuracy`: igualdad del conjunto de referencias documento/página/casilla contra el GT; citas incorrectas adicionales fallan. No verifica texto de citas, bboxes ni trayectorias de herramientas.
- `task_pass`: ejecución exitosa, schema válido y todos los valores/evidencias correctos.
- `execution_status`: `success`, `invalid_response`, `timeout`, `unsupported` o `adapter_error`. Las excepciones de ejecución puntúan cero sin eliminar la tarea. El runner registra timeouts reportados por el adapter; todavía no impone un deadline a un proceso.

El resumen pondera por campos, con denominador explícito; todas las filas quedan disponibles por tarea, grupo de extracción/conciliación y documentos. No hay LLM juez.

## Separación del GT y próximos pasos

Se agregó `datasets/tax-mini-poc/manifest.json` con sólo ID, ruta, hash y número de páginas, derivados una vez del manifiesto original. El loader verifica cada PDF y filtra nuevamente esas cuatro claves. El adapter recibe una copia de `TaskInput`, sin referencias esperadas ni rutas al GT.

Esto es separación de datos en la interfaz, **no aislamiento de seguridad**: un callable Python puede leer el host. Antes de conectar un agente con herramientas de archivos hay que ejecutar su sesión en un entorno que monte exclusivamente los PDF y su tarea; `ground_truth/`, grader, tests, reportes y README deben quedar fuera. Copiar inputs a una carpeta o cambiar el cwd no alcanza.

La siguiente iteración conectará una sesión real a esta firma y confirmará su aislamiento. Después se agregan las dos rutas de extracción y Phoenix sobre los mismos evaluadores, con versiones/consumo/trazas reales. Repeticiones, concurrencia, políticas de retry y tarifas quedan para esa integración. El punto de partida es secuencial, una repetición, sin extracción ni servicios pagos.
