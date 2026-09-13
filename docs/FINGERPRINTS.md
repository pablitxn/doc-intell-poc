# Comparaciones con código de harness distinto

Una corrida nueva guarda identidades separadas:

| Campo | Qué identifica | Exigido igual para comparar |
|---|---|---|
| `dataset_version` | Tareas, tipos, referencias y hashes verificados de PDF | Sí |
| `contract_sha256` | `TaskInput`, loader, prompt y parseo JSON estricto | Sí |
| `scoring_sha256` | Grader, schema y módulos de evaluadores | Sí |
| `runtime_code_sha256` | Resto de código Python de `evals/`, incluyendo adapters y reporting | No |
| `eval_code_sha256` | Hash histórico del conjunto de `evals/` | Solo entre reportes legacy |

También deben coincidir las versiones declaradas de prompt/evaluador, el escenario, el grader y la membresía exacta de tareas/repeticiones. El comparador rechaza reportes incompletos y metadatos ausentes. Un cambio de adapter o reporting ya no invalida una comparación; un cambio de prompt o scoring sí. Los hashes de fuente son conservadores: incluso un comentario en archivos de contrato/scoring cambia su identidad. Versión de CLI, imagen y modelo permanecen en `harness_metadata`; el hash de runtime no sustituye esos datos.

Para comparar reportes guardados, sin nuevas inferencias:

```sh
python3 -m evals.experiments.comparison \
  runs/baseline-compatible/20260913T130351Z-7bd233432940 \
  runs/ID_DEL_CORPORATIVO \
  --output-dir runs/comparisons
```

Los reportes antiguos siguen bajo la regla estricta original: mismo hash global. No se mezclan directamente con reportes nuevos.

## Baseline auditado de GPT-5.6

El [manifiesto de compatibilidad](../artifacts/2026-09-13/baseline-compatibility.json) permite migrar **copias** de los nueve reportes auditados del 13 de septiembre. Fija el SHA256 exacto de cada reporte y sidecar, el archivo de respaldo y las fuentes de contrato/scoring revisadas en `f5d2419`. El cambio posterior a aquella ejecución estaba en el comparador; no modificó el contrato ni el scoring.

```sh
python3 -m evals.experiments.fingerprints migrate-baseline \
  runs/20260913T130351Z-7bd233432940 \
  --output-dir runs/baseline-compatible
```

Se pueden pasar las nueve carpetas en la misma invocación. En un checkout nuevo, restaurar primero el [respaldo de resultados](../artifacts/2026-09-13/README.md).

La migración verifica archivos contra el manifiesto, fuentes actuales contra la revisión, dataset, membresía, prompts exactos, scores por tarea y resumen. Solo después escribe una carpeta nueva. No modifica respuestas, tiempos, consumos, trazas ni checkpoints; conserva los originales y rechaza sobrescrituras. Un reporte desconocido o modificado no puede acogerse a esta equivalencia. Si cambia el contrato o el evaluador, esta migración se rechaza: hace falta revisar una nueva cohorte.

Para el runtime histórico se conserva el único hash observado, el global de `evals/`, identificado con `runtime_fingerprint_basis=legacy-whole-evals`. No se atribuye al baseline un hash reconstruido del runtime posterior.

## Snapshot para otra máquina

Las corridas nuevas y las copias migradas incluyen `dataset-snapshot.json` con todo el dataset: texto exacto de entrada, referencias, tipos y metadatos por tarea. `dataset_snapshot_sha256` fija sus bytes en el reporte. Sirve para importar el historial en un Phoenix nuevo sin volver a llamar modelos.

El snapshot es un artefacto privado del evaluador. No está dentro de la carpeta de tarea montada en el harness ni se menciona en el prompt. Contiene referencias esperadas y debe conservar esa separación al trasladar el proyecto.
