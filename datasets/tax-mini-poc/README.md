# Tax Mini POC

**5 PDF de una página, 1 contribuyente ficticio, 6 tareas y 54 valores esperados.** Todo es sintético y coherente entre documentos. Datos en inglés; guía en español.

| Archivo | Ejemplo elegido |
|---|---|
| inputs/01_w2.pdf | W-2: salarios, retenciones federales/estatales, Medicare y CASDI. |
| inputs/02_1099_int.pdf | 1099-INT: intereses y backup withholding. |
| inputs/03_k1_1065.pdf | K-1 de partnership (1065), limited partner. |
| inputs/04_form_8959.pdf | Additional Medicare Tax y conciliación de retenciones. |
| inputs/05_ca_sdi_summary.pdf | Resumen anual de aportes del empleado a SDI de California. |

Se eligió **un representante por cada familia de la lista inicial**, no cada subtipo: 1099-INT representa 1099; K-1 (1065) representa K-1; CA SDI representa aportes de seguro del empleado. El último es un resumen de nómina, no un supuesto formulario universal “SUI/DUI”. “DUI” sigue pendiente de aclaración.

Los PDF usan layouts simplificados con casillas y líneas identificadas. No son reproducciones completas de formularios oficiales ni una prueba de cobertura de layouts reales. Sirven para conectar lectura de PDF, navegación entre documentos, extracción, evidencia y grading sin manejar un corpus grande.

## Uso rápido

1. Dale al agente sólo inputs/ y tasks.json, o los documentos y la tarea concreta que quieras ejecutar.
2. Pedile que devuelva un JSON con la estructura indicada en tasks.json. Hay cinco tareas de extracción y una de conciliación entre documentos.
3. Guardá su respuesta en model-output.json y ejecutá el grader desde un proceso externo:

~~~bash
python grade.py --predictions model-output.json
~~~

Para una sola tarea:

~~~bash
python grade.py --predictions model-output.json --task extract_doc_001
~~~

grade.py usa sólo Python estándar y debe ejecutarse desde este checkout completo: comparte la validación de datos y esquema con el runner. No ejecuta un modelo ni se conecta a APIs. `tasks_passed` exige esquema válido, valores y citas correctos; `value_accuracy` es independiente y puede reconocer un valor numérico aunque su formato sea inválido. Puntúa citas document_id/page/box como conjuntos; no exige una secuencia de herramientas ni puntúa bbox. Usar strings decimales sin símbolos ni separadores de miles, por ejemplo “3000.00”. Los porcentajes están en puntos porcentuales: “1.20” significa 1,20%.

**ground_truth/, grade.py y este README quedan fuera del entorno accesible al agente.** Copiar una carpeta no basta si el agente sigue pudiendo leer el resto del host: montar únicamente los inputs y la tarea en su contenedor. El grader mantiene las respuestas esperadas fuera de ese montaje.

## Qué comprueba la tarea conjunta

- Retención federal W-2: 42.000,00; 1099: 300,00; retención Additional Medicare: 450,00. Crédito combinado: **42.750,00**.
- Retención de impuesto sobre la renta de California: **16.000,00**.
- SDI del empleado: **3.000,00**, aparece en el W-2 y en el resumen de nómina y se cuenta una vez.
- La línea 18 de 8959 es impuesto calculado; la línea 24 es retención. No sumar ambas como pagos. Los 4.075,00 de Medicare del W-2 incluyen 3.625,00 regulares y 450,00 adicionales.

La revisión 0.2 pide explícitamente usar/citar el total de línea 24 en la conciliación y en el crédito combinado. La línea 22 es el componente sobre salarios; coincide con la 24 sólo porque este fixture excluye RRTA. La igualdad de importes no sustituye la casilla requerida. Los valores esperados y los PDF no cambiaron. Ver [auditoría y cobertura](../../docs/DATASET_AUDIT.md).

El resultado se deriva de datos explícitos y aritmética revisada, no de respuestas generadas por el modelo que se va a medir. La parte tributaria está acotada: esto no calcula una declaración completa, saldo a pagar, deducciones o créditos estatales.

## Contenido técnico

- tasks.json: instrucciones, campos, tipos y formato de respuesta, sin valores esperados.
- manifest.json: IDs, rutas, hashes y número de páginas de los PDF, sin respuestas esperadas.
- ground_truth/expected.json: respuestas y evidencia por campo.
- ground_truth/documents.json: manifiesto, hashes, coordenadas y labels.
- ground_truth/relationships.json: hechos compartidos y controles aritméticos.
- grade.py: scorer determinista.
- provenance.json: fuentes oficiales para las casillas, reglas y exclusiones.
- SHA256SUMS: hashes para verificar la integridad de los archivos del dataset.

El dataset se conserva como fixture estático. Los tests actuales de los evaluadores están en ../../tests/; los resultados de cada ejecución se guardan en ../../runs/.

No se reutilizaron identidades, PDF o etiquetas de registros públicos. Todos los nombres, identificadores e importes se crearon para esta prueba. No contiene material corporativo. Se puede ampliar luego con otros 1099, K-1 (1120-S/1041), W-2c, PTET y comprobantes de pagos; no están incluidos en esta versión mínima.
