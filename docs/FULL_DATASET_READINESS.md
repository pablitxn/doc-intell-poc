# Dataset completo: preparación y ejecución

`datasets/tax-document-eval-v1` es la versión ejecutable preparada a partir de `datasets/tax-document-dataset-v0.1`. Los originales se conservan íntegros. El runner sigue recibiendo documentos y una consigna por stdin, con respuesta JSON `values/evidence`; las referencias permanecen fuera del harness.

## Alcance que se puede ejecutar

| Elemento | Cantidad |
|---|---:|
| Expedientes | 55: 50 TaxCalcBench y 5 Fake W-2 |
| Documentos de entrada | 319: 264 PDF, 50 JSON y 5 JPG |
| Tareas de extracción | 319 |
| Tareas de conciliación | 47 |
| Total de tareas | 366 |
| Campos evaluados | 1.465: 1.253 monetarios, 162 booleanos y 50 strings |

Todos los inputs de TaxCalcBench y los cinco JPG tienen una tarea de extracción. Cada tarea pide campos seleccionados y observables; no se califica cada casilla de cada formulario ni una declaración fiscal completa. La conciliación suma salarios W-2 y retenciones federales explícitamente impresas, según las fuentes enumeradas en su consigna.

Las 39 fuentes oficiales son 37 plantillas vacías y dos documentos de consulta. Los 77 registros ExtractBench sólo tienen manifiesto: sus PDF/GT no están en el kit. Los 50 XML TaxCalcBench son resultados fiscales candidatos, no un oracle general de extracción. Esos elementos quedan como material de referencia, fuera del scoring. El [informe de auditoría](FULL_DATASET_AUDIT.md) explica los hallazgos y sus consecuencias.

## Verificar antes de usar

Desde la raíz del repositorio, con Docker y `uv` disponibles:

```bash
# Verificación íntegra sin modelos; reconstruye temporalmente y compara todos los bytes.
uv run scripts/prepare_full_dataset.py --check

# Levantar Phoenix y verificar los tres perfiles en esta máquina.
docker compose up -d --wait
python3 -m evals --dataset datasets/tax-document-eval-v1 \
  --harness all --check --check-network
```

La imagen de harnesses es la misma de la [guía corporativa](CORPORATE_READINESS.md). Si no existe localmente:

```bash
docker build -f containers/harnesses.Dockerfile \
  -t doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0 containers
```

El diagnóstico confirma montaje, hashes y conexiones. La comprobación de etiquetas y páginas pertenece a `prepare_full_dataset.py --check`; un diagnóstico `ready` solo no certifica referencias ni permisos efectivos de inferencia. Para reconstruir el dataset desde cero usar `uv run scripts/prepare_full_dataset.py --output RUTA_NUEVA`; el builder rechaza sobrescrituras y escribe el resultado final sólo tras completarlo.

## Primera corrida real

Sol con razonamiento medium y el harness elegido:

```bash
./run.py --dataset datasets/tax-document-eval-v1 --harness codex \
  --model gpt-5.6-sol --thinking medium \
  --task extract_taxcalc_ty25_ca_001_w2_1 --timeout 300
```

Para probar formatos distintos, reemplazar `--task` por:

- `extract_fake_w2_test_000`: W-2 en imagen, 25 campos; lectura de la copia superior una sola vez.
- `extract_taxcalc_ty25_va_004_remaining_data`: importes y flags declarados en JSON, con evidencia por JSON pointer.
- `reconcile_ty25_ca_007`: conciliación con varios documentos, incluyendo distractores explícitos.

`--harness all` aplica la tarea a Pi, Tau y Codex. Las credenciales existentes de Codex se usan como en el minimal; no se copian secretos al proyecto. Una respuesta equivocada se conserva y recibe su score; el runner no la repara.

En esta preparación aprobaron **12/12 pruebas reales con Sol en medium**: las cuatro tareas anteriores sobre Pi, Tau y Codex. Una copia del proyecto en una ruta con espacios también pasó `prepare_full_dataset.py --check` y el diagnóstico. La matriz completa de 3.294 invocaciones no se ejecutó; estas pruebas cubren la integración y los formatos seleccionados.

Si una corrida termina pero falla su publicación, reintentar indicando el mismo dataset. Este comando recupera la publicación sin repetir inferencias:

```bash
./run.py --dataset datasets/tax-document-eval-v1 --upload-only runs/ID_DE_LA_CORRIDA
```

## Corridas completas

Un modelo y un harness: **366 invocaciones**.

```bash
./run.py --dataset datasets/tax-document-eval-v1 --harness codex \
  --model gpt-5.6-sol --thinking medium --repetitions 1 --timeout 300
```

Luna, Sol y Terra en medium sobre Pi, Tau y Codex: **3.294 invocaciones por repetición**. Los tiempos y límites de cuenta deben dimensionarse con las pruebas previas.

```bash
./run.py --dataset datasets/tax-document-eval-v1 --harness all \
  --models gpt-5.6-luna gpt-5.6-sol gpt-5.6-terra \
  --thinking medium --repetitions 1 --timeout 300
```

El modo sin publicación es `python3 -m evals` con los mismos argumentos. El dataset por defecto sigue siendo el minimal; especificar `--dataset` evita una corrida accidental sobre otro conjunto.

## En la máquina corporativa

Completar el perfil y la imagen del harness privado. El perfil debe recibir el texto stdin y devolver el JSON acordado. Para una primera tarea:

```bash
./run.py --dataset datasets/tax-document-eval-v1 \
  --profile harnesses/mi-corporate.json --image mi-imagen-corporate \
  --check --check-network
./run.py --dataset datasets/tax-document-eval-v1 \
  --profile harnesses/mi-corporate.json --image mi-imagen-corporate \
  --task extract_taxcalc_ty25_ca_001_w2_1 --timeout 300
```

Repetir la comprobación con JPG y JSON: el montaje los admite, pero la implementación privada necesita herramientas capaces de leerlos. El SO/arquitectura, Docker, red corporativa y SDK OTel privado requieren validación allí. El MCP de Document Intelligence sigue siendo una etapa posterior.

## Contrato, trazas e históricos

El prompt vigente es `tax-fields-text-v5`: permite identificadores canónicos explícitos de fila/casilla, encabezado y JSON pointer. Cada tarea tiene expediente y ejercicio propios; los 1040 previos son 2024, las imágenes W-2 son 2010 y el contexto de los demás inputs TaxCalcBench es 2025. Se mantiene `tax-mini-v2` como scorer exacto reutilizable; el nombre histórico no cambia sus tipos ni su política de evaluación.

Los nuevos reportes tienen otro hash de dataset/contrato. No deben mezclarse con la matriz minimal v4. Para recuperar copias históricas con su contrato original se agregó `migrate-baseline --historical-only`; su importación usa `--import-run`. Ver [fingerprints](FINGERPRINTS.md). Todos los scores y trazas deben interpretarse con sus versiones originales.

## Validación técnica reproducible

```bash
DOC_INTELL_DOCKER_TESTS=1 DOC_INTELL_PHOENIX_TESTS=1 \
  uv run --with-requirements tests/requirements.txt \
  python -m unittest discover -s tests -q
```

El [notebook de auditoría](FULL_DATASET_AUDIT.ipynb) reúne los controles de integridad, reconstrucción y pruebas negativas. No llama modelos. La evidencia y los resultados reales de esta preparación se conservan en [artifacts/2026-09-13/full-dataset](../artifacts/2026-09-13/full-dataset/README.md).
