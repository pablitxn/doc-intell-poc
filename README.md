# Document evaluation POC

Este proyecto compara cómo **Pi, Tau, Codex y, después, el harness corporativo** resuelven tareas sobre documentos. Cada harness recibe una consigna y los documentos asignados, devuelve JSON y obtiene scores de valores y evidencias. Phoenix permite explorar los resultados y las trazas.

## Por dónde empezar

| Quiero… | Abrir |
|---|---|
| Entender las piezas y seguir una tarea completa | [Guía del proyecto](docs/GUIA_DEL_PROYECTO.md) |
| Preparar el entorno, leer un resultado o investigar un fallo | [Operación diaria](docs/OPERACION.md) |
| Ejecutar el dataset completo | [Guía de ejecución](docs/FULL_DATASET_READINESS.md) |
| Conectar el harness del trabajo y su OTel | [Guía corporativa](docs/CORPORATE_READINESS.md) |
| Revisar la validación o encontrar un reporte anterior | [Índice de documentación y evidencia](docs/README.md) |

La guía del proyecto incluye **qué archivo tocar según el cambio que quieras hacer**, un glosario y una tarea real recorrida desde el PDF hasta su score.

## Elegir el dataset

| Carpeta | Para qué sirve | Alcance |
|---|---|---|
| [`datasets/tax-document-eval-v1/`](datasets/tax-document-eval-v1/) | Dataset completo preparado, listo para el runner | 319 documentos, 55 casos, 366 tareas, 1.465 campos |
| [`datasets/tax-mini-poc/`](datasets/tax-mini-poc/README.md) | Ejemplo pequeño para familiarizarse con el flujo | 5 PDF, 1 caso, 6 tareas, 54 campos |
| [`datasets/tax-document-dataset-v0.1/`](datasets/tax-document-dataset-v0.1/README.md) | Kit original del que se preparó el conjunto completo | Fuentes y material de referencia; no se ejecuta directamente |

**La CLI selecciona el minimal por defecto.** Usá `--dataset` explícito para trabajar con el completo. `--harness all` selecciona los tres harnesses; no cambia el dataset. Omitir `--task` ejecuta todas las tareas del dataset elegido.

## Primera prueba

Desde la raíz del repositorio, con Docker, `uv`, la imagen de harnesses, Phoenix y una sesión de Codex autenticada. La [preparación del entorno](docs/OPERACION.md#preparar-el-entorno) contiene los comandos si es una máquina nueva.

```bash
# Verificar fuentes y referencias sin llamar a modelos.
uv run scripts/prepare_full_dataset.py --check

# Comprobar el entorno de los tres harnesses, sin inferencias.
python3 -m evals --dataset datasets/tax-document-eval-v1 \
  --harness all --check --check-network

# Ejecutar UNA tarea real con Codex + Sol medium y publicar en Phoenix.
./run.py --dataset datasets/tax-document-eval-v1 --harness codex \
  --model gpt-5.6-sol --thinking medium \
  --task extract_taxcalc_ty25_ca_001_w2_1 --timeout 300
```

El resultado queda en `runs/<id>/report.json` y en [Phoenix local](http://127.0.0.1:6006). Para saber si la tarea aprobó, mirá `summary.tasks_passed` y `rows[].scores.task_pass`: un proceso que termina con código 0 puede contener respuestas incorrectas.

`./run.py` ejecuta y publica resultados. `python3 -m evals` ejecuta y guarda reportes locales; un harness con OTel propio puede seguir enviando sus spans. Los dos usan el mismo runner y los mismos evaluadores.

## Dónde vive cada cosa

| Ruta | Responsabilidad |
|---|---|
| [`run.py`](run.py) | Entrada habitual: ejecución y publicación en Phoenix |
| [`evals/`](evals/) | Cargar tareas, renderizar el prompt, ejecutar adapters, evaluar y reportar |
| [`harnesses/`](harnesses/) | Perfiles de Pi, Tau, Codex y ejemplo corporativo |
| [`containers/`](containers/) | Imagen, proceso del worker y proxy de salida |
| [`datasets/`](datasets/) | Documentos, tareas y referencias del evaluador |
| [`scripts/`](scripts/) | Preparar y verificar el dataset completo desde las fuentes |
| [`tests/`](tests/) | Contratos, casos adversariales e integración |
| `runs/` | Resultados locales; Git los ignora |
| [`artifacts/`](artifacts/) | Evidencias y respaldos de corridas guardados en Git |
| [`docs/`](docs/README.md) | Guías, decisiones y auditorías |

## Qué está validado

La [auditoría del conjunto completo](docs/FULL_DATASET_AUDIT.md) registra **256 tests aprobados y 12/12 corridas reales con Sol medium**: cuatro tareas en cada harness, cubriendo PDF, imagen, JSON y conciliación. La matriz completa de 3.294 invocaciones y el CLI corporativo quedan pendientes.

Los campos evaluados y las sumas tienen un alcance explícito; no representan una declaración fiscal completa. Los resultados históricos del minimal conservan su contrato original. El [índice](docs/README.md) permite encontrar cada evidencia sin confundirla con las instrucciones actuales.
