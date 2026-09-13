# Verificación de la reorganización del código

La reorganización separó la coordinación de las CLI, runtime Docker, protocolos de eventos, telemetría, preparación de datasets y scoring. Las pruebas ahora se encuentran en `tests/unit/`, `tests/datasets/` y `tests/integration/`, con utilidades en `tests/support/`.

- **264 tests aprobados, sin omisiones**: `tests.txt`. Incluyen Docker, OTel real y publicación/importación en Phoenix efímero.
- **372 tareas con scoring equivalente** entre las fuentes antiguas y las actuales: mini + completo, mutaciones de cada campo/referencia, respuestas malformadas y fallos de ejecución. Los cinco evaluadores exportados a Phoenix son byte idénticos.
- **849 archivos de fuentes y evidencias anteriores idénticos**. Sólo cambió `datasets/tax-document-eval-v1/audit.json`, en `preparation_source_sha256`, para registrar la nueva ubicación del código.
- **Dataset y contrato de tareas conservan sus hashes**. La identidad de fuente del scoring cambió explícitamente al moverlo; no se presenta como el hash anterior.
- **12 corridas reales históricas recuperadas de Phoenix**, con 147 campos, 60 scores y 77 spans. Esta comprobación no vuelve a ejecutar modelos.
- **Cero inferencias nuevas** durante el refactor. Los tests usan los dobles de prueba existentes y SDKs de integración.

## Archivos

| Archivo | Evidencia |
|---|---|
| `validation.json` | Alcance, hashes antes/después y hashes de los controles guardados |
| `tests.txt` | Suite completa final |
| `test-layout.json` | Mapeo de pruebas originales a su nueva ubicación; sustitución explícita del control histórico |
| `diagnostics.json` | Diagnóstico de los tres perfiles sobre el dataset completo |
| `preparation-migration.json` | Comparación de los 325 archivos preparados: 324 idénticos y sólo procedencia actualizada en el restante |
| `preparation-check.json` | Reconstrucción final byte por byte y 485 checksums de fuentes verificados |
| `historical-live-readback.json` | Lectura de las 12 corridas originales en Phoenix |
| `baseline-scoring.json` | Fuentes exactas del evaluador histórico, verificadas contra el manifiesto original antes de ejecutarlas |

El [manifiesto histórico](../baseline-compatibility.json) y los respaldos anteriores permanecen intactos. `--historical-only` verifica y utiliza las fuentes congeladas para conservar las identidades originales; no emplea el scorer actual para reinterpretar esos resultados.

Las corridas guardadas antes de esta reorganización se pueden recuperar con `--import-run`. Para `--upload-only` o una comparación nueva se exige la identidad de scoring correspondiente; el cambio de ubicación no habilita mezclar cohortes automáticamente. Ver [fingerprints](../../../docs/FINGERPRINTS.md).
