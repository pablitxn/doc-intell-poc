# Documentación del proyecto

[Volver al inicio](../README.md) · [Entender el proyecto](GUIA_DEL_PROYECTO.md) · [Operación diaria](OPERACION.md)

## Para trabajar ahora

| Documento | Cuándo abrirlo |
|---|---|
| [Guía del proyecto](GUIA_DEL_PROYECTO.md) | Primera lectura: conceptos, mapa de código, una tarea completa y dónde hacer cambios |
| [Operación diaria](OPERACION.md) | Preparar el entorno, interpretar scores y reportes, recuperar publicaciones y elegir tests |
| [Dataset completo: ejecución](FULL_DATASET_READINESS.md) | Verificar las fuentes y ejecutar una tarea, un harness o la matriz completa |
| [Conectar el corporativo](CORPORATE_READINESS.md) | Adaptar su CLI, red, autenticación y OTel; llevar reportes a otra instancia |
| [Compatibilidad de comparaciones](FINGERPRINTS.md) | Entender por qué dos corridas pueden compararse o se rechazan por sus versiones |
| [Plan y decisiones](PLAN.md) | Consultar las decisiones de integración y el lugar del futuro MCP de Document Intelligence |

Para aprender el proyecto, seguí **guía del proyecto → una tarea → lectura de su resultado**. Para trasladarlo, seguí **ejecución del dataset completo → guía corporativa**. Los comandos de la guía corporativa que omiten `--dataset` usan el minimal; la guía del completo incluye los equivalentes explícitos.

## Evidencia del dataset completo

Estos documentos registran la preparación y los resultados del 13 de septiembre de 2026. Los números corresponden a esa revisión; no son el resultado de volver a correr tests al abrir esta página.

| Documento | Qué respalda |
|---|---|
| [Auditoría completa](FULL_DATASET_AUDIT.md) | Campos seleccionados, etiquetas, procedencia, problemas de las fuentes y tratamiento |
| [Notebook de auditoría](FULL_DATASET_AUDIT.ipynb) | Controles de reconstrucción y del evaluador que se pueden ejecutar sin modelos |
| [Evidencia y respaldo](../artifacts/2026-09-13/full-dataset/README.md) | Logs, hashes, 256 tests y las 12 corridas reales con Sol medium |

## Historia del minimal

Se conservan para entender las decisiones y recuperar resultados. Sus cifras, versiones de prompt y comandos describen sus etapas; para una corrida nueva usá las guías de arriba.

| Documento | Etapa que describe |
|---|---|
| [Auditoría del minimal](DATASET_AUDIT.md) | Los cinco PDF, 54 valores y el criterio de evidencia de sus seis tareas |
| [Validación inicial](VALIDATION.md) | Pruebas previas con GPT-5.5 y sus límites |
| [Matriz GPT-5.6](VALIDATION_GPT56.md) | Luna, Sol y Terra en medium: 54 invocaciones sobre el minimal |
| [Reporte resumido](REPORTE_GPT56_2026-09-13.md) | Cierre de aquella matriz y de su auditoría |
| [Validación previa al corporativo](VALIDATION_PRE_CORPORATE.md) | Etapa de 225 tests, transporte OTel e importación, anterior al dataset completo |
| [Respaldo histórico](../artifacts/2026-09-13/README.md) | Archivos originales de las corridas y cómo restaurarlos |

El prompt actual es `tax-fields-text-v5`; las corridas minimal de la matriz anterior usaron `tax-mini-text-v4`. El scorer sigue llamándose `tax-mini-v2` y se reutiliza para ambos datasets. El nombre no selecciona el dataset: lo hace `--dataset`. Las reglas de comparación están en [fingerprints](FINGERPRINTS.md).
