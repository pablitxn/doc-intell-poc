# Comparaciones con código de harness distinto

Una corrida nueva guarda identidades separadas:

| Campo | Qué identifica | Exigido igual para comparar |
|---|---|---|
| `dataset_version` | Tareas, tipos, referencias y hashes verificados de los documentos de entrada | Sí |
| `contract_sha256` | `TaskInput`, loader, prompt y parseo JSON estricto | Sí |
| `scoring_sha256` | Rutas y bytes de `evals/evaluators/`, incluidos grader, schema y scoring | Sí |
| `runtime_code_sha256` | Resto de código Python de `evals/`, incluyendo adapters y reporting | No |
| `eval_code_sha256` | Hash histórico del conjunto de `evals/` | Solo entre reportes legacy |

También deben coincidir las versiones declaradas de prompt/evaluador, el escenario, el grader y la membresía exacta de tareas/repeticiones. El comparador rechaza reportes incompletos y metadatos ausentes. Un cambio de adapter o reporting ya no invalida una comparación; un cambio de prompt o scoring sí. Los hashes de fuente son conservadores: incluso un comentario en archivos de contrato/scoring cambia su identidad. Versión de CLI, imagen y modelo permanecen en `harness_metadata`; el hash de runtime no sustituye esos datos.

Para comparar reportes guardados, sin nuevas inferencias:

```sh
python3 -m evals.experiments.comparison \
  runs/ID_CON_CONTRATO_ACTUAL \
  runs/ID_DEL_CORPORATIVO \
  --output-dir runs/comparisons
```

Los reportes antiguos siguen bajo la regla estricta original: mismo hash global. No se mezclan directamente con reportes nuevos.

## Efecto del reordenamiento del código

El scorer activo vive ahora en [`evals/evaluators/grading.py`](../evals/evaluators/grading.py) y [`scoring.py`](../evals/evaluators/scoring.py). El archivo original `datasets/tax-mini-poc/grade.py` permanece intacto como CLI legado y evidencia. El cambio de rutas y módulos produce un **nuevo `scoring_sha256`**, aunque las reglas se mantienen; el comparador no infiere equivalencia sólo porque ambos se llamen `tax-mini-v2`.

Esta reorganización conserva los hashes de dataset y contrato del checkout anterior. La preparación sólo actualiza los hashes de sus módulos en `audit.json`; las tareas, entradas y referencias quedan idénticas. Runtime, adapters y telemetría cambian su procedencia de código sin modificar esa identidad de contrato.

Las 12 pruebas previas del dataset completo usaron prompt v5, pero tienen el scoring anterior. Para republicarlas, usar `--import-run`; `--upload-only` exige el scoring vigente. Se pueden comparar reportes compatibles dentro de cada grupo de versiones, pero no mezclar ejecuciones anteriores y posteriores al reordenamiento. Importar un reporte conserva sus identidades; no lo convierte en una corrida actual.

## Baseline auditado de GPT-5.6

El [manifiesto de compatibilidad](../artifacts/2026-09-13/baseline-compatibility.json) permite migrar **copias** de los nueve reportes auditados del 13 de septiembre. Fija el SHA256 exacto de cada reporte y sidecar, el archivo de respaldo y las fuentes de contrato/scoring revisadas en `f5d2419`. Ese baseline usó `tax-mini-text-v4`. El soporte posterior de varios expedientes y el prompt `tax-fields-text-v5` forman otro contrato: el manifiesto histórico permanece intacto.

Para conservar y publicar el baseline en este checkout, usar el modo histórico explícito:

```sh
python3 -m evals.experiments.fingerprints migrate-baseline \
  runs/20260913T130351Z-7bd233432940 \
  --historical-only \
  --output-dir runs/baseline-historical
```

Se pueden pasar las nueve carpetas en la misma invocación. En un checkout nuevo, restaurar primero el [respaldo de resultados](../artifacts/2026-09-13/README.md).

`--historical-only` verifica los hashes exactos de reporte y sidecars, el dataset completo, membresía, metadatos, scores por tarea y resumen. Para comprobar los scores carga las fuentes congeladas en [`baseline-scoring.json`](../artifacts/2026-09-13/architecture/baseline-scoring.json): verifica primero cada fuente y su identidad conjunta contra el manifiesto original intacto, y sólo entonces ejecuta sus funciones puras. No usa el scorer actual. Conserva `contract_sha256`, `scoring_sha256`, identidad del grader y versión original del prompt. El snapshot privado usa el texto de entrada guardado en el reporte verificado; no lo vuelve a renderizar con el prompt actual. Las referencias se incorporan sólo si el hash del dataset coincide con el histórico. El reporte marca `fingerprint_migration.mode=historical-only`.

Las copias históricas pueden compararse entre sí. El comparador rechaza mezclarlas con ejecuciones del contrato actual. Para llevarlas a un Phoenix nuevo, usar `--import-run` según la [guía de traslado](CORPORATE_READINESS.md); la publicación ordinaria exige compatibilidad con el contrato actual.

Sin `--historical-only`, la migración también exige que las fuentes completas de contrato y scoring coincidan con la revisión y compara cada prompt con el render actual. Ese modo conserva su rechazo estricto ante cualquier deriva de contrato o scoring; no está disponible para el baseline v4 desde este checkout con contrato v5. El modo histórico permite que el checkout tenga otro scorer, pero exige que las fuentes congeladas coincidan exactamente con el scoring histórico auditado.

Ambos modos escriben una carpeta nueva sólo después de validar todo. No modifican respuestas, tiempos, consumos, trazas ni checkpoints; conservan los originales y rechazan sobrescrituras. Un reporte desconocido o modificado no puede acogerse a esta migración.

Para el runtime histórico se conserva el único hash observado, el global de `evals/`, identificado con `runtime_fingerprint_basis=legacy-whole-evals`. No se atribuye al baseline un hash reconstruido del runtime posterior.

## Snapshot para otra máquina

Las corridas nuevas y las copias migradas incluyen `dataset-snapshot.json` con todo el dataset: texto exacto de entrada, referencias, tipos y metadatos por tarea. `dataset_snapshot_sha256` fija sus bytes en el reporte. Sirve para importar el historial en un Phoenix nuevo sin volver a llamar modelos.

El snapshot es un artefacto privado del evaluador. No está dentro de la carpeta de tarea montada en el harness ni se menciona en el prompt. Contiene referencias esperadas y debe conservar esa separación al trasladar el proyecto.
