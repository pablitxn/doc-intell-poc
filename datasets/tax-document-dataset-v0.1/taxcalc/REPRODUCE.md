# Reproducir la auditoría TaxCalcBench TY25

Los tres scripts resuelven sus rutas respecto de su propio directorio con `Path(__file__).resolve().parent`. Se puede mover esta carpeta completa y ejecutarlos desde cualquier directorio. Mantener `ty25_tree.json` y `download/` al lado de los scripts; no renombrar los archivos del corpus.

Entorno comprobado: Python 3.12.14, pypdf 6.10.0 y pdfplumber 0.11.8. Las dependencias directas están fijadas en `requirements-audit.txt`; las transitivas no están fijadas. No hacen falta claves de API de modelos. Poppler sólo se usó para las vistas PNG opcionales y no es necesario para estos tres scripts.

Desde esta carpeta, con Python 3.12 disponible:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-audit.txt
python generate_audit.py
python validate_label_samples.py
```

En Windows, activar el entorno con `.venv\Scripts\activate` o usar directamente `.venv\Scripts\python.exe`.

Los dos últimos comandos son **locales y no acceden a la red**. Regeneran `manifest.json`, `taxcalc_findings.json` y `sample_label_validation.json`. El primero coteja los 364 archivos con los SHA Git del árbol fijado y registra SHA-256, páginas y claves. El segundo comprueba 11 importes en cinco pares PDF/XML; ese muestreo no certifica todos los campos del corpus.

Resultados de referencia: 364 archivos verificados, cero fallos de integridad, 264 PDF y 314 páginas; cinco pares con 11/11 importes coincidentes. `generate_audit.py` registra archivos faltantes o hashes diferentes en `failures`; revisar que esa lista esté vacía. Fallos de lectura o parseo interrumpen el script. `validate_label_samples.py` devuelve código distinto de cero si un importe no coincide o una asociación es ambigua.

## Recuperar archivos que falten

La descarga ya está incluida. Este paso opcional necesita acceso a `raw.githubusercontent.com` y sólo usa la biblioteca estándar de Python:

```bash
python audit_download.py --all
```

Los archivos existentes se omiten sin volver a descargarlos; su integridad se valida después con `generate_audit.py`. Para reemplazar un archivo identificado como corrupto, quitar sólo ese archivo y volver a ejecutar la descarga. `audit_download.py` no altera el commit de origen ni descarga resultados de modelos. El árbol de origen es `ty25_tree.json`, ya incluido en el kit; no necesita obtener un árbol completo del repositorio.

`--initial` selecciona los 100 JSON/XML y los PDF de CA001/CA008. `--remaining-pdfs` selecciona los otros PDF. `--workers N` ajusta la concurrencia. La salida `downloaded` cuenta archivos disponibles al terminar, incluidos los omitidos por existir previamente. Los tres scripts aceptan `--help`.

## Rutas del manifiesto y separación de entradas

`manifest.json[].path` es relativo a `download/`; por ejemplo, `ty25-ca-001/input/w2_1.pdf` se encuentra en `download/ty25-ca-001/input/w2_1.pdf`. `case_id` no depende de la ruta del equipo. Los campos `source_url` son enlaces al commit fijado; no son ubicaciones locales.

Para una evaluación, exponer únicamente `download/<case_id>/input/` al agente. `output.xml`, los manifiestos derivados y los resultados de auditoría deben quedarse en el lado del evaluador. El ground truth del Tax Payment Leadsheet todavía no está creado; los XML son resultados del benchmark de declaraciones fiscales.
