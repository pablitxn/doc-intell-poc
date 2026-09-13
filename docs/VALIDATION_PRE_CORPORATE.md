# Validación previa al harness corporativo — 2026-09-13

Las cuatro mejoras acordadas están implementadas: diagnóstico del entorno, conformance OTel, fingerprints separados e importación de resultados a otro Phoenix. **225 tests aprobados, cero omisiones, cero llamadas nuevas a modelos.** La matriz anterior de 54/54 tareas se conserva como evidencia de inferencias; los resultados de esta etapa verifican integración y portabilidad local.

## Evidencia

| Comprobación | Resultado observado |
|---|---|
| Suite completa | 225 tests en 29,426 segundos; sin errores, fallos ni tests omitidos |
| Copia limpia del código | Diagnóstico `ready: true` para Pi, Tau y Codex, sin advertencias |
| Documentos y red | Cinco PDF legibles, referencias fuera del worker, herramientas PDF, TLS a los destinos permitidos y transporte OTLP correctos |
| SDK OTel real | Dos trazas, diez spans; padres verificados con y sin gzip, incluyendo cierre/exportación del SDK |
| Importación a Phoenix efímero | 24 respuestas históricas y una respuesta fixture; 125 scores y 160 spans verificados |
| Reintento de importación | Sin duplicados ni cambios en los originales; no se registraron los evaluadores actuales |
| Línea base GPT-5.6 | Nueve copias compatibles, 54 tareas; respuestas y resúmenes idénticos a los originales |
| Respaldo original | `runs.tar.gz` y `manifest.json` idénticos a los guardados en `f5d2419` |

El [manifiesto de validación](../artifacts/2026-09-13/pre-corporate-validation.json) registra fingerprints, entorno y hashes de la evidencia. Incluye enlaces relativos mediante los nombres de los archivos conservados junto a él: [diagnóstico](../artifacts/2026-09-13/pre-corporate-diagnostics.json), [importación](../artifacts/2026-09-13/pre-corporate-import-validation.json) y [salida de tests](../artifacts/2026-09-13/pre-corporate-tests.txt).

El diagnóstico se ejecutó desde una copia de las fuentes sin `.git`, `runs/`, `.env` ni credenciales dentro de esa copia. Reutilizó el Docker del host, la imagen reconstruida, Phoenix local y la presencia de autenticación del host para el preflight. **No representa una instalación en la PC corporativa ni comprueba permisos de inferencia.** El proceso de diagnóstico no ejecutó los harnesses ni recibió credenciales de proveedor.

Entorno observado: host Darwin/arm64, Python 3.14.6; workers Linux/arm64, Python 3.12.12. Imagen de runtime:

```text
doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0
sha256:4ef9c523c9e83460597c0cc1e344fa1efea392e8272949821b882c6f1c674962
```

Esa imagen incorpora el proxy actualizado. Los reportes históricos conservan el ID de la imagen con la que se ejecutaron; no se les atribuye el runtime nuevo.

## Qué verifican las pruebas

La prueba OTel usa OpenTelemetry SDK 1.44.0 en una imagen exclusiva de tests y Phoenix 20.11.0 efímero. Comprueba IDs y parentesco de `task.execute`, `harness.execute`, `corporate.execute`, `corporate.read_document` y `evaluate`. Demuestra el contrato ofrecido a una implementación privada; esa implementación todavía debe extraer el contexto y exportar correctamente.

La transferencia usa 18 respuestas históricas con prompt v3/evaluador v1, seis con prompt v4/evaluador v2 y un fixture con snapshot de referencias. Los históricos sin snapshot se identifican con referencias `unavailable`. Se conservan sus scores y versiones sin sustituirlos por los del checkout actual. La verificación contempla la precisión de microsegundos de Phoenix frente a los timestamps originales en nanosegundos. Las pruebas cubren también recuperación tras respuestas perdidas y rechazo de contenido remoto modificado.

La compatibilidad del baseline verifica fuentes de contrato/scoring, hashes de archivos, dataset, prompts exactos, scores y resúmenes. Es una migración explícita de copias de las nueve corridas auditadas; un reporte distinto o un cambio del evaluador requiere otra revisión. La publicación normal rechaza reportes incompletos o de un contrato/scoring incompatible antes de escribir en Phoenix.

## Reproducir

Desde la raíz, con Docker e imagen de harnesses disponibles:

```bash
python3 -m evals --harness all --check --check-network
DOC_INTELL_DOCKER_TESTS=1 DOC_INTELL_PHOENIX_TESTS=1 \
  uv run --with arize-phoenix-client==3.5.0 --with opentelemetry-proto==1.44.0 \
  python -m unittest discover -s tests -q
```

La [guía de traslado](CORPORATE_READINESS.md) contiene los comandos de build, perfil privado, migración, comparación e importación. Los contenedores efímeros de esta validación se eliminaron; el Phoenix persistente original sigue disponible.

## Pendiente en la máquina corporativa

Confirmar SO/arquitectura, Docker, autenticación y restricciones de red. Completar el perfil del CLI privado, verificar sus ajustes efectivos de modelo/reasoning y correr una tarea real con su implementación OTel. Un harness accesible únicamente por API requiere un puente para stdin/stdout y documentos.

Linux nativo, WSL y la red corporativa no fueron probados aquí. El dataset sigue siendo cinco PDF digitales sintéticos y seis tareas: esta preparación no amplía su representatividad ni convierte el 54/54 anterior en una garantía de calidad general. Reanudar inferencias interrumpidas, ampliar los casos y agregar MCP → Document Intelligence quedan para las próximas etapas.
