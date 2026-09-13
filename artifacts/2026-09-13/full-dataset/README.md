# Evidencia del dataset completo

Los archivos de esta carpeta describen la preparación del kit original para `datasets/tax-document-eval-v1`. El [informe de auditoría](../../../docs/FULL_DATASET_AUDIT.md) explica qué verifica cada control; la [guía de ejecución](../../../docs/FULL_DATASET_READINESS.md) contiene los comandos.

- `taxcalc-source-audit.json`: inventario, hashes, parseo, duplicados y límites de los XML.
- `taxcalc-visible-fields.json`: 649 importes en 214 PDF, motores independientes y muestras visuales por familia.
- `fake-w2-source-audit.json`: cinco imágenes y sus 125 campos revisados; semántica de filas y copias.
- `independent-preparation-review.json`: 50 JSON, 50 PDF 1040 y tensiones entre flags e importes.
- `reproduction.json`: reconstrucción byte por byte del dataset preparado.
- `diagnostics.json`: diagnóstico con los tres perfiles, sin inferencias.
- `clean-reproduction.json` y `clean-diagnostics.json`: los mismos controles desde una copia del proyecto en otra ruta con espacios, usando el Docker y la autenticación del host actual.
- `tests.txt`: salida de la suite completa, incluidos Docker, SDK OTel y dos instancias efímeras de Phoenix; sin inferencias.
- `live-smoke.json`: las cuatro tareas ejecutadas en los tres harnesses con Sol medium; 12 invocaciones reales.
- `live-validation.json`: lectura posterior de Phoenix; 147 campos correctos, 60 scores y 77 spans, y las 366 referencias publicadas.
- `verify_live.py`: reproduce esa lectura sobre la instancia original, sin modelos ni recalcular scores. Necesita los runs restaurados y las dependencias de `tests/requirements.txt`.
- `runs.tar.gz` y `runs-manifest.json`: los 84 archivos originales de las 12 corridas, con snapshot completo, respuestas, scores, eventos y trazas; SHA256 del archivo y de cada miembro.
- `validation.json`: resumen del alcance verificado y hashes de las evidencias guardadas.

Las referencias ejecutables se encuentran en `datasets/tax-document-eval-v1/ground_truth/`, con procedencia por campo. El runner monta únicamente los documentos asignados bajo `inputs/`; los archivos de esta carpeta y las respuestas esperadas no son entradas del harness.

Para recuperar estas corridas desde una copia nueva, ejecutar desde la raíz del repositorio:

```bash
# Verificar primero el SHA256 de runs.tar.gz contra runs-manifest.json.
shasum -a 256 artifacts/2026-09-13/full-dataset/runs.tar.gz
tar -xzf artifacts/2026-09-13/full-dataset/runs.tar.gz

# Publicar una corrida guardada en la nueva instancia, conservando sus scores.
./run.py --import-run runs/20260913T172846Z-1ba05d55b04d \
  --phoenix-url http://127.0.0.1:6006 --output-dir runs/restored
```

La importación no llama al modelo. Los IDs de las otras once corridas están en `runs-manifest.json`. `verify_live.py` utiliza los checkpoints de la instancia original; los recibos creados por `--import-run` verifican la importación a un destino nuevo.
