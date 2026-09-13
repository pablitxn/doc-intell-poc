# Auditoría del dataset y evaluadores — 2026-09-13

**Apto dentro del alcance revisado; revisión completa de este fixture.** Se revisaron los cinco PDF, los 54 valores y sus evidencias, los cálculos de conciliación, el contrato de entrada y las cinco métricas de evaluación. Se corrigieron los defectos demostrados. No hay una garantía absoluta de corrección ni una validación de documentos corporativos: es un caso fiscal sintético con PDF digitales simplificados.

## Hallazgos corregidos

1. **Consigna y criterio de citas desalineados.** El grader exigía la línea 24 de Form 8959, pero la tarea no lo decía. Según el [formulario oficial 2025](https://www.irs.gov/pub/irs-prior/f8959--2025.pdf), la 22 es el componente de retención sobre salarios; la 24 agrega el componente RRTA de la 23. El fixture excluye RRTA. La cita 22 respaldaba el importe bajo la consigna anterior, aunque fallaba la referencia canónica. La tarea ahora pide explícitamente el total y la cita 24, también para la suma federal. La línea 18 representa obligación tributaria y sigue siendo una evidencia incorrecta para retención, aunque tenga el mismo importe. No se cambiaron importes ni PDF para favorecer respuestas observadas.
2. **Campos omitidos silenciosamente por el scorer.** El grader recorre los campos del ground truth. El loader anterior permitía que una tarea pidiera campos ausentes allí. Ahora se rechaza cualquier desalineación entre tareas, respuestas y tipos antes de llamar a un modelo, además de IDs duplicados, rutas inválidas, documentos no asignados, referencias mal formadas y páginas fuera del rango declarado por el manifest. La existencia física de cada página/casilla se verificó contra los PDF durante esta auditoría; el loader no interpreta sus etiquetas ni recalcula su cantidad de páginas. `field_types.json` se incorporó al fingerprint para detectar divergencias con el grader CLI.
3. **Aprobación distinta en el CLI.** `grade.py` podía aprobar dinero representado como número mientras runner/Phoenix exigían string decimal. Su CLI ahora comparte validación de dataset y esquema, y calcula aprobación con el mismo criterio. Los créditos parciales de exactitud numérica se conservan como diagnóstico, separados de la aprobación de la tarea.
4. **JSON ambiguo aceptado.** Claves duplicadas podían sobrescribir respuestas sin error. Loader y adapters ahora comparten un parser que rechaza duplicados y números no finitos, sin registrar contenido privado en el error. El esquema exige las dos secciones superiores exactas.
5. **Reportes sin versiones aceptados en comparación.** Dos reportes con metadatos ausentes podían coincidir por `None == None`. El comparador ahora exige `complete: true`, versiones/hashes no vacíos y repeticiones enteras positivas. Tres tests adicionales cubren 64 mutaciones que el código anterior aceptaba. Se aplicó después de las 54 corridas para mantener congelado su código; todos sus reportes ya tenían estos datos válidos y sus resultados no cambiaron.

## Evidencia y cobertura

Los totales son unidades del inventario revisado; no se suman las categorías para producir un porcentaje global de confiabilidad.

### Claridad y cobertura del fixture

| Categoría | Defectos restantes observados | Evaluación |
| --- | ---: | --- |
| Legibilidad y correspondencia visual | 0 / 5 PDF | Se renderizaron e inspeccionaron las cinco páginas completas; etiquetas, importes, notas y signos son legibles. |
| Consignas y campos solicitados | 0 / 6 tareas | Contrato de formatos común y cita de total explícita; membresía validada automáticamente. |
| Límites declarados | 0 / 1 fixture | Un contribuyente, texto digital y layouts simplificados; no se extrapola a OCR, variantes reales ni cálculo de declaración completa. |
| Controles interactivos | N/A | No es un dashboard. |

### Corrección analítica y robustez

| Categoría | Defectos restantes observados | Evaluación |
| --- | ---: | --- |
| Valores y evidencia canónica | 0 / 54 campos | Transcripción desde PDF y derivación de conciliación comparadas campo a campo con GT; no se usó el grader para obtener los valores de control. |
| Ubicación de evidencia | 0 / 57 referencias | 48 recortes de extracción contienen etiqueta y valor; nueve referencias de conciliación apuntan a esos recortes verificados. El scoring no evalúa bbox. |
| Integridad de archivos | 0 / 14 archivos | Recibo SHA256 actualizado al congelar los cambios; hashes de los cinco PDF sin cambios. |
| Consistencia de métricas | 0 / 5 métricas | Tests adversariales comparan runner y código Phoenix compilado; el CLI comparte el criterio de aprobación. |
| Denominadores y fallos | 0 / 6 tareas | Campos y tareas no desaparecen ante respuestas vacías, campos ausentes o errores; comprobado también con repeticiones. |
| Interpretación de resultados | 0 / 2 versiones | Historial v1 conservado; v2 usa consigna explícita y nuevos hashes. No se mezclan las dos versiones ni se presenta el pass rate antiguo como fallo tributario demostrado. |

**175 tests pasaron sin skips antes de la matriz y 178 al cierre**, incluidos los de aislamiento Docker, transporte OTel nativo a Phoenix, catálogos Luna/Sol/Terra, JSON estricto, mutaciones adversariales, transcripción independiente y el control final del comparador. Es evidencia de los casos cubiertos, no una demostración matemática de ausencia de todo defecto.

## Evidencia reproducible

- [Transcripción de las 54 respuestas](../tests/fixtures/tax_mini_pdf_audit.json): valores, etiquetas, fuentes y fórmulas. Ya se conocían los seis GT de conciliación por la investigación previa; no se afirma cegamiento completo. Los cálculos se rehacen desde los PDF, independientemente del grader.
- [Recortes y comprobaciones documentales](dataset-audit-evidence.json): observaciones de palabras y bboxes reales. El checksum inicial de la consigna pertenece a la versión anterior; el recibo vigente está en el dataset.
- [Tests del oracle y aritmética](../tests/test_dataset_source_audit.py), [tests adversariales](../tests/test_evaluator_adversarial.py), [checksums vigentes](../datasets/tax-mini-poc/SHA256SUMS).
- [Provenance revisada](../datasets/tax-mini-poc/provenance.json), con año/página por regla y [California DE44 de 2025](https://edd.ca.gov/siteassets/files/pdf_pub_ctr/de44-25.pdf) para evitar usar tasas de otro año.

```bash
DOC_INTELL_DOCKER_TESTS=1 DOC_INTELL_PHOENIX_TESTS=1 \
  uv run --with opentelemetry-proto==1.44.0 python -m unittest discover -s tests -q
```

## Versión congelada para la comparación 5.6

- Dataset revisión `0.2`, SHA256 `0cc394dfbe7f4a18d7fda9265f7b6b0bc3137904f0e59719c53843ac7879720e`.
- Prompt `tax-mini-text-v4`; evaluador `tax-mini-v2`.
- Grader SHA256 `3ce6de9cd299525801449fa67197b219548199f5507353872e95151b08ee515a`.
- Código de `evals/` durante los nueve experimentos: `be2528cf68cfd10cc6cbf15afdece83e20786565c37b987e5ee00e3d6dc79c65`. El ajuste posterior del comparador cambia el hash del paquete para futuras corridas, sin modificar consigna, grader, adapters ni resultados de esta matriz.
- Modelos exactos `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, todos `medium`; la [documentación oficial de modelos](https://learn.chatgpt.com/docs/models) y los catálogos instalados respaldan estas selecciones. La disponibilidad efectiva de cuenta se comprueba en las corridas, sin sustitución silenciosa.
- Los tres harnesses usan el mismo dataset y prompt por tarea. Comparaciones de reportes exigen hashes de dataset y código de evaluación iguales.

La [matriz real GPT-5.6](VALIDATION_GPT56.md) completó las 54 invocaciones y su publicación se contrastó con la API de Phoenix. Los resultados de modelos son evidencia adicional separada de esta auditoría.

## Límites que siguen siendo importantes

La extracción correcta de estos PDF no demuestra cobertura de documentos escaneados, páginas múltiples, datos faltantes, fuentes contradictorias u otros casos fiscales. Tres repeticiones del mismo fixture no crean tres contribuyentes independientes. La precisión de evidencias mide el conjunto solicitado de documento/página/casilla; no demuestra el razonamiento interno ni la ruta de herramientas del agente. La integración del harness corporativo privado y el MCP de Document Intelligence siguen requiriendo sus propias pruebas.
