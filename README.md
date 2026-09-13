# Document evaluation POC

Evaluaciones contra un harness real, instalado como ejecutable mediante npm global y disponible en `PATH`. El runner construye un único texto por tarea, con la referencia al dataset, y se lo entrega al ejecutable. El núcleo usa Python estándar; `run.py` usa `uv` para resolver el cliente de Phoenix y sus dependencias fijadas en `run.py.lock`.

El dataset contiene 5 PDF sintéticos, 6 tareas y 54 valores de un único expediente. Su grader se conserva sin cambios. El adapter de proceso y la publicación a Phoenix están implementados; la comprobación con el harness real y sus proveedores queda pendiente hasta disponer del ejecutable.

## Ejecutar

Requisitos: Docker con Compose, `uv` y el ejecutable del harness instalado y autenticado. Desde la raíz:

```bash
docker compose up -d --wait
./run.py --harness-command nombre-del-harness
```

Phoenix queda disponible en [http://127.0.0.1:6006](http://127.0.0.1:6006). El Compose fija Phoenix `20.11.0`, publica el puerto únicamente en loopback y conserva SQLite en el volumen `phoenix_data`. `docker compose stop` detiene el servicio conservando sus datos.

`run.py` comprueba el ejecutable y publica el dataset y los evaluadores antes de llamar al harness. Luego ejecuta las tareas, guarda el reporte local y publica sus resultados. Una corrida de las seis tareas produce seis ejecuciones y treinta scores. Para seleccionar una tarea o configurar su timeout:

```bash
./run.py --harness-command nombre-del-harness --task reconcile_case --timeout 180
./run.py --harness-command nombre-del-harness --dataset datasets/tax-mini-poc
```

Si se interrumpe la publicación, el reporte local permite retomarla sin volver a llamar al harness:

```bash
./run.py --upload-only runs/ID-DE-LA-CORRIDA
```

`phoenix.json` guarda los IDs remotos y el progreso de carga. Se reutilizan las ejecuciones confirmadas y se actualizan sus scores; cada ejecución nueva del harness crea otro experimento. `--phoenix-url` o `PHOENIX_ENDPOINT` cambia el destino; `PHOENIX_API_KEY` es opcional para un servidor con autenticación. Estas credenciales se comparten entre el cliente REST y el registro GraphQL.

En Phoenix se guardan:

- **Dataset:** las seis tareas, sus textos, referencias esperadas y metadatos. La misma versión se reutiliza incluso al evaluar una sola tarea. Los PDF permanecen locales y se referencian desde los inputs.
- **Evaluadores:** cinco definiciones CODE con código Python, descripción y nombre versionado por contenido, visibles en Evaluators. El código se exporta de las mismas funciones usadas localmente. El registro utiliza el runtime Python WASM incluido en la imagen de Phoenix, sin servicios adicionales.
- **Experimentos:** respuesta del harness, estado, tiempos, scores y versiones. En la salida remota, `answer` contiene la respuesta original y `execution_status` conserva el estado del proceso, previo a validar el schema. Así los evaluadores registrados conservan la distinción entre un error de ejecución y un valor correcto con tipo incorrecto.

El harness y el scoring se ejecutan localmente. Las definiciones registradas quedan disponibles en Phoenix; este script no les configura ejecuciones automáticas. Los errores permanecen en el denominador y los costes desconocidos quedan `null`.

La CLI local sigue disponible para trabajar sin publicación:

```bash
python3 -m evals --harness-command nombre-del-harness
python3 -m evals --harness-command nombre-del-harness --task reconcile_case --timeout 180
python3 -m evals --harness-command nombre-del-harness --dataset datasets/tax-mini-poc
```

`nombre-del-harness` se reemplaza por el nombre real del ejecutable. `--harness-command` es obligatorio y admite argumentos fijos entre comillas, por ejemplo `"nombre-del-harness run"` si ese comando existe en su CLI. Se ejecuta sin shell: no se interpretan tuberías ni expansiones. La aplicación no instala paquetes npm ni incluye modos smoke/replay. Un ejecutable ausente o un timeout inválido detiene la CLI antes de crear un experimento.

**Contrato de proceso inicial:** el input text entra por `stdin`; la respuesta final sale como un único JSON por `stdout`. Los logs deben ir a `stderr`. Es una convención de esta integración, pendiente de confirmar con la CLI real. Si el ejecutable requiere un flag para recibir el texto, el cambio queda localizado en `evals/adapters/command.py`.

Cada ejecución genera `runs/<timestamp>-<id>/report.json` y `scores.csv`. El JSON conserva el nombre del ejecutable, el texto exacto enviado, la versión del prompt, respuestas, errores, checks por campo, denominadores y hashes del dataset y código. El CSV tiene una fila por tarea. El tiempo mide la llamada completa al proceso; los costes no medidos son `null`. La CLI retorna 0 cuando produce el reporte, aunque los scores fallen: es una herramienta exploratoria, no un quality gate de CI.

Los tests unitarios se ejecutan por separado:

```bash
python3 -m unittest discover -s tests -v
```

Sus dobles viven exclusivamente en `tests/`. Las pruebas del adapter lanzan procesos Python locales para verificar transporte y errores, sin servicios ni credenciales reales. No constituyen ejecuciones de evaluación contra un modelo.

## Arquitectura y estilo

```text
datasets/
  tax-mini-poc/           # PDF, tareas, manifiesto, GT y grader original
evals/
  contracts.py           # TaskInput, Example y firma del adapter
  datasets/
    loader.py            # Carga y validación del dataset
  adapters/
    command.py           # Ejecutable: texto por stdin, JSON por stdout
  evaluators/
    definitions.py       # Definiciones exportables a Phoenix
    schema.py            # Validación de la respuesta sin consultar GT
    tax_mini.py          # Política de scoring para tax-mini-poc
  experiments/
    prompt.py            # Texto de la tarea y referencia al dataset
    runner.py            # Ejecución y reportes
  __main__.py            # CLI
  reporting/             # Datasets, evaluadores y resultados en Phoenix
tests/                   # Tests unitarios y sus dobles
docker-compose.yml       # Phoenix local con almacenamiento persistente
run.py                   # Ejecutar y publicar a Phoenix
run.py.lock              # Dependencias fijadas del script
```

`datasets/` contiene los datos; `evals/datasets/` contiene el código que los carga. Cada futuro dataset tendrá su propio directorio. El loader y el runner actuales siguen usando el formato y la política de tax-mini-poc; alojar otro dataset no lo hace automáticamente compatible.

```text
tasks + manifest ──> texto ──> ejecutable del harness
                                      │
ground_truth ──> Example.expected ──> evaluate <── JSON
                                       │
                                  JSON / CSV
```

Funciones pequeñas, nombres explícitos y dependencias pasadas por parámetros. Usamos dataclasses para distinguir el input público del ejemplo con GT, y diccionarios para el JSON del dominio. Una función callable basta para el adapter; no hay clases base ni framework propio. Un evaluador no llama al harness, no persiste archivos y no modifica la respuesta.

Para sumar un check, escribir una función en `evals/evaluators/`, incluir su resultado en `tax_mini.evaluate` y agregar una prueba positiva y otra negativa. Cambiar la política implica incrementar `EVALUATOR_VERSION`; ambas rutas deberán usar la misma versión.

## Qué recibe el harness

Un único string. `build_prompt` agrega el nombre del dataset, la ruta absoluta de `inputs/`, los documentos de esa tarea, instrucciones, campos solicitados y formato de respuesta. No incluye valores esperados ni referencias al GT. `TaskInput` y `Example` son estructuras internas de evaluación; no se entregan al ejecutable.

La inyección por Python usa el mismo adapter de proceso:

```python
from pathlib import Path

from evals.adapters.command import command_harness
from evals.experiments.runner import run_experiment

run_experiment(
    dataset=Path("datasets/tax-mini-poc"),
    adapter=command_harness(["nombre-del-harness"], timeout_seconds=120),
    adapter_name="nombre-del-harness",
    output_dir=Path("runs"),
)
```

El contrato interno del adapter es `Callable[[str], object]`. Cada llamada inicia un proceso nuevo, escribe el texto en stdin y cierra la entrada. El harness debe devolver `{"values": ..., "evidence": ...}` con todos los campos de esa tarea. El adapter parsea ese JSON; el runner lo evalúa. El proceso nuevo no garantiza por sí mismo que un harness con memoria persistida cree una sesión aislada: eso se confirma con su CLI real.

El ejecutable hereda el entorno del runner y usa sus propias credenciales y API keys. El proyecto no lee ni serializa esas claves, no define sus nombres ni carga `.env`. No incluirlas en el texto ni en `--harness-command`. Los fallos de proceso y autenticación se registran como errores, sin sustituirlos por respuestas de prueba. No se persisten stderr ni mensajes arbitrarios de excepciones.

La ruta de extracción se configura en el harness antes de ejecutar. El texto referencia archivos locales: el ejecutable debe poder leer esos PDF y hacerse cargo de enviarlos a sus proveedores. El runner no adjunta archivos ni llama directamente a sus APIs.

## Política de scoring v1

- `schema_valid`: campos completos, dinero/porcentajes como strings con dos decimales, booleanos reales, fechas ISO y referencias con página entera positiva. `bbox` y metadatos adicionales no se puntúan.
- `value_accuracy`: comparación del grader original, con `Decimal` y sin confundir ausencias con cero. Puede dar 1 aunque falle el schema, por ejemplo si un importe correcto viene como número.
- `evidence_accuracy`: igualdad del conjunto de referencias documento/página/casilla contra el GT; citas incorrectas adicionales fallan. No verifica texto de citas, bboxes ni trayectorias de herramientas.
- `task_pass`: ejecución exitosa, schema válido y todos los valores/evidencias correctos.
- `execution_status`: `success`, `invalid_response`, `timeout`, `unsupported` o `adapter_error`. Las excepciones de ejecución puntúan cero sin eliminar la tarea. Una salida no JSON falla como `invalid_response`; un código de salida no cero, como `adapter_error`. El adapter impone un timeout por llamada, de 120 segundos por defecto.

El resumen pondera por campos, con denominador explícito; todas las filas quedan disponibles por tarea, grupo de extracción/conciliación y documentos. No hay LLM juez.

## Separación del GT y próximos pasos

`datasets/tax-mini-poc/manifest.json` contiene sólo ID, ruta, hash y número de páginas. El loader verifica cada PDF y filtra esas cuatro claves. El prompt se construye exclusivamente a partir de los inputs de la tarea.

Esto es separación de datos en el texto, **no aislamiento del filesystem**: el ejecutable hereda el acceso del usuario al host. Para un benchmark válido, su entorno debe permitir únicamente los PDF y la tarea; `ground_truth/`, grader, tests, reportes y README deben quedar fuera. El adapter de proceso no implementa ese sandbox.

La siguiente iteración conectará una sesión real y confirmará su aislamiento. Después se integran las dos rutas de extracción, consumo y trazas internas del harness. Repeticiones, concurrencia, retries y tarifas quedan para esa integración. Cada experimento comienza secuencialmente, con una repetición.

La integración se verificó contra [Phoenix 20.11.0](https://github.com/Arize-ai/phoenix/releases/tag/arize-phoenix-v20.11.0) y el [cliente Python 3.5.0](https://pypi.org/project/arize-phoenix-client/3.5.0/). Utiliza las APIs de [datasets](https://arize-phoenix.readthedocs.io/projects/client/api/datasets.html) y [experimentos](https://arize-phoenix.readthedocs.io/projects/client/api/experiments.html), y el esquema GraphQL incluido en esa versión para registrar código.
