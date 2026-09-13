# Validación local — 2026-09-13

Registro histórico con GPT-5.5, prompt v3 y evaluador v1. La [auditoría posterior](DATASET_AUDIT.md) aclara la consigna y fortalece los controles; estos resultados originales se conservan sin reetiquetarlos ni mezclarlos con la nueva matriz GPT-5.6.

## Integración

- 137 tests pasaron, sin skips, con protobuf y las dos pruebas Docker activadas.
- Se verificó en Docker real que el worker puede leer su PDF asignado, pero no otros documentos, ground truth ni la API de lectura de Phoenix.
- Un proceso de prueba con respuesta JSON simple recibió contexto OTel y envió un mensaje OTLP válido al Phoenix real mediante el proxy. Phoenix respondió HTTP 200. La prueba no invocó modelos ni creó spans; valida el transporte, no la implementación privada del harness corporativo.
- Pi 0.85.1, Tau 0.4.3 y Codex 0.145.0 se ejecutaron realmente con la cuenta ChatGPT existente, sin exportar su refresh token.
- La API real de Phoenix confirmó la recuperación por ID de ejecuciones existentes y sus jerarquías de spans. Un `--upload-only` real sobre Pi conservó los mismos 18 runs y sus 90 scores, sin duplicar ejecuciones ni invocar modelos.

Comando de verificación:

```bash
DOC_INTELL_DOCKER_TESTS=1 DOC_INTELL_PHOENIX_TESTS=1 \
  uv run --with opentelemetry-proto==1.44.0 python -m unittest discover -s tests -q
```

## Matriz nativa

Estado: completada. 54 invocaciones reales, sin errores de ejecución ni timeouts; 486 valores evaluados. Los tres harnesses acertaron todos los valores y pasaron las 15 extracciones. Las tres conciliaciones de cada harness recibieron la misma penalización por el criterio de citas descrito abajo.

| Harness | Tareas aprobadas | Valores correctos | Evidencias correctas | Mediana por tarea | Duración total | Tokens entrada | Entrada cacheada | Tokens salida |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pi | 15/18 | 100% | 96,30% | 18,82 s | 348,33 s | 70.471 | 1.536 | 9.880 |
| Tau | 15/18 | 100% | 96,30% | 21,49 s | 388,32 s | 84.224 | 10.752 | 10.589 |
| Codex | 15/18 | 100% | 96,30% | 19,98 s | 396,18 s | 528.194 | 410.496 | 10.429 |

La entrada cacheada ya está incluida en tokens de entrada. No representa tokens adicionales ni permite deducir el coste de esta suscripción. Los spans internos observados tienen diferente granularidad por CLI: su cantidad tampoco sirve por sí sola como indicador de calidad o complejidad.

La consulta final de la API confirmó que respuestas, repeticiones, 270 scores e IDs de los 345 spans coinciden exactamente con los artefactos locales. Las 54 trazas son únicas; los tres experimentos usaron la misma imagen, código y prompt por tarea.

| Harness | Reporte local | Experimento Phoenix | Spans |
| --- | --- | --- | ---: |
| Pi | [20260913T115937Z-3ffe3d7663c1](../runs/20260913T115937Z-3ffe3d7663c1/report.json) | `RXhwZXJpbWVudDoxMQ==` | 118 |
| Tau | [20260913T120526Z-6e7139306e2c](../runs/20260913T120526Z-6e7139306e2c/report.json) | `RXhwZXJpbWVudDoxMg==` | 130 |
| Codex | [20260913T121155Z-39577b0826dc](../runs/20260913T121155Z-39577b0826dc/report.json) | `RXhwZXJpbWVudDoxMw==` | 97 |

[Comparación JSON](../runs/comparison-5d71d993637f.json) · [CSV](../runs/comparison-5d71d993637f.csv) · [Verificación de publicación](../runs/validation-live-20260913.json).
Los archivos de `runs/` son artefactos locales ignorados por Git; copiarlos por separado si se quiere llevar también este historial. La tabla anterior conserva el resumen en la documentación del proyecto.

Comando histórico, ejecutado con las versiones de dataset, prompt, evaluador y perfiles indicadas abajo. El checkout actual contiene la revisión posterior y no reproduce esta versión con solo repetir el comando.

```bash
./run.py --harness all --repetitions 3 --timeout 180
```

- Modelo `gpt-5.5`, proveedor `openai-codex`, razonamiento `medium`.
- Cinco PDF, seis tareas, tres repeticiones por harness; 162 valores evaluados por harness.
- Dataset SHA256: `35e9d03b0abcb8a25455d705c1b917351e0d8b9d74b184dae28c0536766a517c`.
- Prompt `tax-mini-text-v3`; evaluador `tax-mini-v1`.
- Imagen: `sha256:6a8995acb6f0e6bc61bf1bd296f64e624153a4e61e4fa331bcbb8ae5576f5583`.
- Código de evaluación/adapters: `85403d2c71817c494e235dc9e1499436246b59758c7c3a14fddb1ffa1de2ee95`.
- Ejecuciones secuenciales, entorno nuevo por tarea. La latencia incluye preparación y limpieza; no equivale a tiempo puro de inferencia.

## Pruebas previas a esta matriz

Se conservan en `runs/` y Phoenix, separadas de los resultados definitivos:

1. El acceso de esta cuenta rechazó `gpt-5.4` en los tres harnesses. La configuración se cambió explícitamente a `gpt-5.5`.
2. El adapter inicialmente rechazaba los IDs opacos de herramientas de Pi/Tau. Se corrigió el parser con un test que reprodujo el fallo; esas corridas no comparan calidad de modelos.
3. La conciliación del prompt v2 omitía la regla de formato de importes y produjo fallos de esquema. El prompt v3 hace explícito el contrato público para todas las tareas, sin cambiar el ground truth ni flexibilizar el evaluador.

## Límites

Es una muestra sintética pequeña de un único caso fiscal. El mismo modelo ayuda a comparar los harnesses, pero sus instrucciones internas, herramientas y retries propios siguen siendo diferentes. Los resultados no establecen una clasificación general ni una diferencia estadísticamente significativa.

Los tokens dependen de lo reportado por cada CLI. El consumo agregado de Codex está en los metadatos del span harness; sus eventos no exponen cada petición LLM. El coste monetario queda desconocido para la suscripción. El harness corporativo privado y el MCP de Document Intelligence siguen pendientes de su siguiente etapa.

### Criterio de citas observado en esta versión histórica

En DOC-004, la casilla 22 muestra `Additional Medicare withholding` y la 24 muestra `Total Additional Medicare Tax withholding`; ambas tienen el mismo importe en este fixture. El ground truth exige la 24 por coincidencia exacta. Los tres harnesses citaron la 22 para el importe adicional y para la suma federal en sus tres repeticiones, obteniendo los valores correctos pero fallando evidencia según esa referencia canónica.

La instrucción v3 no explicitaba que debía citarse la 24. Por eso este fallo no demuestra por sí solo que el harness haya usado evidencia semánticamente incorrecta. Conservamos el criterio v1 durante toda aquella matriz. La revisión v4 posterior aclara la casilla requerida y se prueba con nuevas respuestas; no se cambia el scoring de este historial después de observarlo. Ver la [auditoría posterior](DATASET_AUDIT.md).
