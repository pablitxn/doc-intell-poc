# Document evaluation POC

Evaluaciones contra un harness real, instalado como ejecutable mediante npm global y disponible en `PATH`. Python 3.10+ y biblioteca estándar. El runner construye un único texto por tarea, con la referencia al dataset, y se lo entrega al ejecutable.

El dataset contiene 5 PDF sintéticos, 6 tareas y 54 valores de un único expediente. Su grader se conserva sin cambios. El adapter de proceso está implementado; la comprobación con el harness real queda pendiente hasta disponer del ejecutable. Azure DI y Phoenix quedan para esa integración.

## Ejecutar

Una vez instalado y autenticado el harness, desde la raíz:

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
    schema.py            # Validación de la respuesta sin consultar GT
    tax_mini.py          # Política de scoring para tax-mini-poc
  experiments/
    prompt.py            # Texto de la tarea y referencia al dataset
    runner.py            # Ejecución y reportes
  __main__.py            # CLI
tests/                   # Tests unitarios y sus dobles
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

La siguiente iteración conectará una sesión real y confirmará su aislamiento. Después se agregan las dos rutas de extracción y Phoenix sobre los mismos evaluadores, con versiones, consumo y trazas reales. Repeticiones, concurrencia, retries y tarifas quedan para esa integración. Cada experimento comienza secuencialmente, con una repetición.
