# Tax document dataset — acquisition kit v0.1

Fuentes revisadas el 2026-09-12. Leer primero Dataset-fiscal-investigacion.md y SPEC-evaluaciones.md.

Incluye 50 expedientes TaxCalcBench (264 PDF + 50 JSON input + 50 XML esperados), cinco pares Fake W-2 y 39 PDF oficiales. ExtractBench se incluye como manifiesto de 77 tareas y descargador, sin sus PDF/GT de registros públicos.

## Verificar sin red

Desde este directorio, con Python 3.10 o posterior:

~~~bash
python scripts/verify_sources.py --release
~~~

El notebook audit.ipynb reproduce la comprobación de hashes de las fuentes y sus cantidades. SHA256SUMS contiene todos los archivos del snapshot salvo a sí mismo. La verificación acredita integridad, no validez completa de etiquetas fiscales.

## Adquirir el subconjunto ExtractBench

~~~bash
python scripts/fetch_extractbench_tax.py --manifest extractbench/tax_manifest.json --output external/extractbench
~~~

Usar --metadata-only para descargar sólo los labels seleccionados. Se transfieren unos 253 MB de splits y se conservan unos 22 MB de etiquetas; el modo completo añade los PDF. Revisión y hashes fijados. Detalles y alcance de la validación del script en scripts/fetch_extractbench_tax.md.

## Reproducir las otras fuentes

TaxCalcBench: taxcalc/REPRODUCE.md. Los scripts son portables y conservan el commit fijado. Para los formularios oficiales, los scripts scripts/acquire_official_sources.py y scripts/acquire_additional_sources.py requieren pypdf; ejecutarlos en una copia del kit si se desea una nueva adquisición. Las URL current pueden cambiar: comparar hashes y no sobrescribir el snapshot de referencia sin versionarlo. Los scripts originales conservan también los tres intentos anuales fallidos.

Fake W-2: cinco muestras del split test en fake_w2/, revisión y filas registradas en manifest.json. El corpus HF completo se consigue en https://huggingface.co/datasets/singhsays/fake-w2-us-tax-form-dataset ; no se descargaron sus 2.000 filas en esta versión. El upstream Kaggle se enlaza en la auditoría.

## Alcance de los datos

- taxcalc/download/: entradas y respuestas esperadas upstream. Los XML no son el GT de nuestro leadsheet.
- official/: plantillas vacías, instrucciones y un libro educativo; no casos etiquetados generados.
- fake_w2/: imágenes sintéticas de prueba de lectura, sin asumir coherencia fiscal de importes.
- extractbench/: manifiesto, licencia y auditoría del corpus externo, con limitaciones por fuente/año.
- references/: fuentes estatales y semántica de pagos.
- coverage.json: estado de cobertura por familia.

El kit completo contiene respuestas esperadas. Para evaluar un agente, montar únicamente los inputs y la tarea en su entorno aislado; mantener XML, GT, auditorías, notebooks y graders fuera de su alcance. No se ejecutó aquí ninguna evaluación de modelos. Los nuevos expedientes y sus labels propuestos en SPEC-evaluaciones.md siguen pendientes de generación.

Conservar licencias y procedencia de cada componente: MIT TaxCalcBench, declaración Apache-2.0 ExtractBench y CC0 declarado por Kaggle para Fake W-2 upstream. Los formularios oficiales mantienen sus fuentes y versiones. Esta compilación no cambia los avisos de origen y no contiene material corporativo aportado en las fotos.
