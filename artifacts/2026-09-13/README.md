# Respaldo de corridas — 2026-09-13

`runs.tar.gz` conserva los **243 archivos JSON/CSV** presentes en `runs/` al cerrar esta revisión, con 1.952.071 bytes sin comprimir. `manifest.json` registra tamaño y SHA256 de cada archivo, además del hash del comprimido. Se verificó que los 243 contenidos del archivo coinciden exactamente con sus originales.

Incluye reportes, scores, trazas, eventos normalizados, comparaciones, comprobantes de publicación y sus versiones originales. Se conservan tanto diagnósticos históricos como matrices completas; no deben mezclarse al interpretar calidad:

- [Resumen GPT-5.6](../../docs/REPORTE_GPT56_2026-09-13.md) y [matriz final](../../docs/VALIDATION_GPT56.md): nueve experimentos, 54 tareas, prompt v4 y evaluador v2. Comparación `runs/comparison-d3fcfe522ebd.json`; comprobante `runs/validation-live-gpt56-20260913.json`.
- [Matriz histórica GPT-5.5](../../docs/VALIDATION.md): tres experimentos con tres repeticiones, prompt v3 y evaluador v1. Comparación `runs/comparison-5d71d993637f.json`; comprobante `runs/validation-live-20260913.json`.
- Las demás corridas conservan sus errores y metadatos de diagnóstico originales.

Para recuperar los archivos en un checkout nuevo, ejecutar desde la raíz del repositorio:

```bash
tar -xzf artifacts/2026-09-13/runs.tar.gz
```

En un checkout que ya contenga esos nombres, la extracción los sobrescribe. El respaldo contiene datos sintéticos y metadatos; no incluye credenciales, entornos virtuales ni caches. Algunas rutas de los reportes identifican el host original.

Los IDs/checkpoints de Phoenix documentan la instancia local original. Extraer este archivo recupera los artefactos, **no restaura la base de Phoenix**. Esa base permanece en su volumen Docker persistente. Las futuras corridas siguen excluidas de Git; este respaldo es una instantánea explícita y versionada.

La preparación posterior para el corporativo mantiene ese comprimido y su manifiesto intactos. Agrega:

- `baseline-compatibility.json`: fuentes y archivos permitidos para migrar copias de los nueve reportes GPT-5.6, sin inferencias.
- `pre-corporate-diagnostics.json`: diagnóstico exitoso desde una copia limpia, para los tres perfiles y sus conexiones.
- `pre-corporate-import-validation.json`: verificación de resultados históricos y un fixture en Phoenix efímero, con reintento sin duplicados.
- `pre-corporate-tests.txt`: salida de la suite completa de 225 tests.
- `pre-corporate-validation.json`: alcance, entorno, fingerprints y hashes de la evidencia de esta etapa.

Ver [resultados y límites](../../docs/VALIDATION_PRE_CORPORATE.md). Para reconstruir experimentos en otra instancia de Phoenix, seguir la [guía de importación](../../docs/CORPORATE_READINESS.md#reconstruir-el-historial-en-phoenix); no reutilizar los checkpoints antiguos como si identificaran la instancia nueva.
