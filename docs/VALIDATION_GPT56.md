# Validación GPT-5.6 — 2026-09-13

**Completada: 54/54 tareas aprobadas, 486/486 valores y sus evidencias correctos.** Se ejecutaron Pi, Tau y Codex con `gpt-5.6-luna`, `gpt-5.6-sol` y `gpt-5.6-terra`, todos en `medium`, usando la cuenta Codex existente. Una pasada: seis tareas por combinación, nueve experimentos. Sin errores de ejecución, respuestas inválidas ni timeouts.

La [auditoría previa](DATASET_AUDIT.md) revisó las 54 respuestas esperadas, sus evidencias y cálculos antes de esta comparación. Los cinco PDF y los valores esperados permanecieron intactos. La consigna v4 exige explícitamente la cita del total Form 8959 línea 24; los fallos del [historial v3/v1](VALIDATION.md) no se reetiquetaron ni mezclaron con estas nuevas respuestas.

## Calidad, tiempo y consumo

| Modelo | Harness | Aprobadas | Valores | Evidencias | Mediana/tarea | Total | Tokens entrada | Entrada cacheada | Tokens salida |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| gpt-5.6-luna | Pi | 6/6 | 100% | 100% | 20,73 s | 120,34 s | 23.153 | 1.536 | 4.031 |
| gpt-5.6-luna | Tau | 6/6 | 100% | 100% | 21,77 s | 129,57 s | 31.422 | 4.608 | 4.059 |
| gpt-5.6-luna | Codex | 6/6 | 100% | 100% | 18,27 s | 112,76 s | 156.418 | 116.736 | 3.489 |
| gpt-5.6-sol | Pi | 6/6 | 100% | 100% | 18,40 s | 114,71 s | 23.036 | 3.968 | 3.052 |
| gpt-5.6-sol | Tau | 6/6 | 100% | 100% | 19,36 s | 112,15 s | 23.057 | 2.816 | 3.059 |
| gpt-5.6-sol | Codex | 6/6 | 100% | 100% | 19,54 s | 123,07 s | 173.244 | 109.056 | 3.626 |
| gpt-5.6-terra | Pi | 6/6 | 100% | 100% | 16,07 s | 98,19 s | 22.629 | 0 | 2.695 |
| gpt-5.6-terra | Tau | 6/6 | 100% | 100% | 15,48 s | 106,09 s | 25.214 | 1.536 | 2.775 |
| gpt-5.6-terra | Codex | 6/6 | 100% | 100% | 17,32 s | 100,96 s | 173.590 | 139.264 | 2.859 |

Todas las combinaciones aprobaron las cinco extracciones y la conciliación. Los tiempos abarcan la invocación completa, incluyendo preparación y limpieza de contenedores. Las ejecuciones fueron secuenciales en orden Luna → Sol → Terra y Pi → Tau → Codex; no hubo aleatorización ni repeticiones para estimar variabilidad. Estas medianas describen esta pasada, no una clasificación general de velocidad.

Los tokens corresponden a lo informado por cada CLI. La entrada cacheada ya está incluida en el total de entrada. Cada harness conserva sus instrucciones, herramientas y comportamiento nativos. Los costes monetarios permanecen desconocidos (`null`) para esta suscripción; no se infieren de precios API.

## Publicación comprobada

La API real de Phoenix coincide con las respuestas, prompts, versiones, metadatos, 270 scores y los IDs/relaciones de 326 spans locales. Hay 54 trazas únicas y nueve experimentos completos, todos contra la misma versión del dataset. Los denominadores se recalcularon desde las filas: 486 campos, 432 de extracción y 54 de conciliación.

| Modelo | Harness | Reporte local | Experimento Phoenix | Spans |
| --- | --- | --- | --- | ---: |
| gpt-5.6-luna | Pi | [20260913T130351Z-7bd233432940](../runs/20260913T130351Z-7bd233432940/report.json) | `RXhwZXJpbWVudDoxNA==` | 45 |
| gpt-5.6-luna | Tau | [20260913T130552Z-e833633356e7](../runs/20260913T130552Z-e833633356e7/report.json) | `RXhwZXJpbWVudDoxNQ==` | 48 |
| gpt-5.6-luna | Codex | [20260913T130802Z-4af026df085c](../runs/20260913T130802Z-4af026df085c/report.json) | `RXhwZXJpbWVudDoxNg==` | 24 |
| gpt-5.6-sol | Pi | [20260913T130955Z-a5ece05863e2](../runs/20260913T130955Z-a5ece05863e2/report.json) | `RXhwZXJpbWVudDoxNw==` | 44 |
| gpt-5.6-sol | Tau | [20260913T131150Z-fa07fa278f28](../runs/20260913T131150Z-fa07fa278f28/report.json) | `RXhwZXJpbWVudDoxOA==` | 41 |
| gpt-5.6-sol | Codex | [20260913T131342Z-79f4d256ee00](../runs/20260913T131342Z-79f4d256ee00/report.json) | `RXhwZXJpbWVudDoxOQ==` | 24 |
| gpt-5.6-terra | Pi | [20260913T131546Z-ebd6a3fe8527](../runs/20260913T131546Z-ebd6a3fe8527/report.json) | `RXhwZXJpbWVudDoyMA==` | 38 |
| gpt-5.6-terra | Tau | [20260913T131724Z-b04cd83e4581](../runs/20260913T131724Z-b04cd83e4581/report.json) | `RXhwZXJpbWVudDoyMQ==` | 38 |
| gpt-5.6-terra | Codex | [20260913T131911Z-f727f56f2657](../runs/20260913T131911Z-f727f56f2657/report.json) | `RXhwZXJpbWVudDoyMg==` | 24 |

[Comparación JSON](../runs/comparison-d3fcfe522ebd.json) · [CSV](../runs/comparison-d3fcfe522ebd.csv) · [Verificación de publicación](../runs/validation-live-gpt56-20260913.json). Phoenix local: [abrir](http://127.0.0.1:6006).

Los archivos de `runs/` están ignorados por Git. Para trasladar el historial, copiar esos artefactos además del código; esta documentación conserva el resumen.

## Reproducir el escenario

```bash
./run.py --harness all \
  --models gpt-5.6-luna gpt-5.6-sol gpt-5.6-terra \
  --thinking medium --repetitions 1 --timeout 180
```

- Harnesses: Pi 0.85.1, Tau 0.4.3 y Codex 0.145.0; proveedor `openai-codex`.
- Dataset SHA256: `0cc394dfbe7f4a18d7fda9265f7b6b0bc3137904f0e59719c53843ac7879720e`.
- Prompt `tax-mini-text-v4`; evaluador `tax-mini-v2`.
- Grader SHA256: `3ce6de9cd299525801449fa67197b219548199f5507353872e95151b08ee515a`.
- Código de `evals/` durante la matriz: `be2528cf68cfd10cc6cbf15afdece83e20786565c37b987e5ee00e3d6dc79c65`.
- Imagen: `sha256:6a8995acb6f0e6bc61bf1bd296f64e624153a4e61e4fa331bcbb8ae5576f5583`.

El código permaneció congelado durante las nueve combinaciones. Al terminar se reforzó únicamente el rechazo de reportes incompletos o sin metadatos en el comparador; la comparación de estos nueve reportes también pasó ese control y produjo el mismo contenido. Esa modificación cambia el hash de `evals/` en futuras corridas. No se modificaron el scoring, el prompt ni las respuestas de esta matriz.

**178 tests pasaron al cierre, sin skips**, incluidos Docker real, transporte OTel a Phoenix y regresiones adversariales. Los tests no invocan modelos; las 54 invocaciones anteriores sí fueron reales.

## Interpretación y límites

Hay empate en las métricas de calidad de este conjunto. El resultado confirma que la integración y el contrato auditado funcionan con las nueve combinaciones, pero no distingue su calidad general. Son cinco PDF digitales simplificados de un único caso fiscal, sin OCR, páginas múltiples ni contradicciones. Una pasada no permite estimar fiabilidad estadística o diferencias de rendimiento estables.

La evidencia se evalúa por conjunto documento/página/casilla; no mide bbox ni razonamiento interno. Pi/Tau exponen mensajes y herramientas; Codex expone herramientas y uso agregado del turno. La cantidad de spans depende de esa granularidad. El harness corporativo privado y el MCP de Document Intelligence requieren su siguiente etapa de pruebas.
