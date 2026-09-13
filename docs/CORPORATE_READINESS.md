# Llevar el POC al harness corporativo

Esta iteración agrega diagnóstico del entorno, pruebas OTel con spans reales, fingerprints separados e importación de resultados a otra instancia de Phoenix. Mantiene el contrato de texto stdin / JSON stdout y las referencias fuera del harness. No agrega llamadas a modelos ni modifica las respuestas del benchmark anterior.

La [validación del 13 de septiembre](VALIDATION_PRE_CORPORATE.md) registra los 225 tests aprobados, el diagnóstico desde una copia limpia y la transferencia a Phoenix efímero.

## Preparar una máquina nueva

Usar un checkout completo, Docker y Python compatible con el proyecto. `run.py` usa `uv` para resolver las dependencias fijadas. El runtime requiere POSIX; en Windows usar WSL2 con integración Docker. La validación local de esta iteración se realiza en Darwin/arm64 con contenedores Linux/arm64; Linux nativo, WSL y la red del trabajo deben pasar su propio diagnóstico.

```bash
docker build -f containers/harnesses.Dockerfile \
  -t doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0 containers
docker compose up -d --wait
python3 -m evals --harness all --check
python3 -m evals --harness all --check --check-network
```

La reconstrucción incorpora el proxy actualizado; no cambia las versiones de Pi/Tau/Codex. Las imágenes utilizadas quedan identificadas por su ID en los reportes. Las versiones principales están fijadas, pero un build posterior puede resolver dependencias transitivas distintas; conservar una imagen para la arquitectura destino si hace falta reproducir exactamente su entorno.

`--check` valida dataset, presencia de credenciales configuradas, imagen, ejecutable corporativo, montaje de los cinco PDF, herramientas PDF y separación de referencias. Ejecuta un proceso Python de diagnóstico, omitiendo incluso el entrypoint de la imagen; no ejecuta el CLI del harness. No exporta credenciales de proveedor al proceso de diagnóstico.

`--check-network` agrega un handshake TLS a cada destino permitido y dos controles de Phoenix: disponibilidad desde el runner y transporte OTLP desde el worker. No envía prompts, no hace peticiones de inferencia ni publica scores. El probe OTLP contiene cero spans; la prueba del SDK con spans reales se ejecuta por separado. Las redirecciones del readiness se rechazan para no reenviar credenciales a otro destino.

El JSON distingue `ready`, controles individuales, advertencias y `model_access: not_tested`. **Ready no demuestra permisos efectivos para inferencia ni que el modelo declarado se haya utilizado.** Una versión sin label verificable y una configuración de modelo/reasoning no expresada en el comando se indican como declaraciones pendientes de verificar.

## Completar el perfil privado

Partir de [corporate.example.json](../harnesses/corporate.example.json). Reemplazar versión, proveedor, modelo y comando con los reales. El comando debe aplicar modelo y reasoning mediante los flags o configuración que soporte ese CLI; no se asume que nuestros nombres de flags existan en el corporativo.

- La imagen debe contener el ejecutable y conservar el contrato de ejecución. Para verificar la versión por label, usar `org.doc-intell.NOMBRE.version` con el nombre y versión del perfil.
- `forward_env` contiene solamente nombres de variables necesarias para autenticación/configuración, nunca valores secretos. El modo `auth: none` significa que no se utiliza el bridge de la cuenta Codex; las credenciales propias pueden llegar mediante esas variables.
- `allowed_hosts` debe enumerar los destinos DNS reales del proveedor. La salida actual usa CONNECT/TLS por puerto 443; el cliente del harness debe respetar el proxy del entorno.
- El proxy actual no encadena un proxy corporativo adicional ni monta credenciales SSO o certificados desde el host. Si ese entorno lo exige, configurar la imagen/transportes necesarios y repetir el diagnóstico. Las CA pueden necesitar instalación tanto en el host como en la imagen: [documentación de Docker](https://docs.docker.com/engine/network/ca-certs/).
- Un harness remoto por API necesita un puente explícito para este contrato y para el acceso a documentos. El perfil actual representa un proceso CLI; no presume ese puente.

```bash
./run.py --profile harnesses/mi-corporate.json --image mi-imagen-corporate \
  --check --check-network --phoenix-url http://127.0.0.1:6006
./run.py --profile harnesses/mi-corporate.json --image mi-imagen-corporate \
  --task extract_doc_001
```

La segunda instrucción sí hace una corrida real del harness. Confirmar configuración efectiva en sus metadatos/trazas antes de ampliar a las seis tareas.

## OTel nativo

El harness puede usar su SDK propio y devolver JSON simple. Debe extraer `TRACEPARENT`, crear sus spans bajo el contexto recibido y cerrar/exportar antes de terminar. El runner reserva las variables W3C de contexto, `DOC_INTELL_*` y `OTEL_*`; `forward_env` no puede sobrescribirlas. El proxy admite OTLP HTTP/protobuf con gzip, identity o sin compresión. Codificaciones distintas se rechazan explícitamente.

La prueba con SDK OpenTelemetry 1.44.0 crea un Phoenix efímero sin volumen, emite spans reales y comprueba la relación `task.execute → harness.execute → corporate.execute → corporate.read_document`. También verifica `force_flush`, gzip y ausencia de credenciales de proveedor. El SDK vive en una imagen de test derivada, no es una dependencia extra del runtime productivo.

```bash
DOC_INTELL_PHOENIX_TESTS=1 uv run --with opentelemetry-proto==1.44.0 \
  python -m unittest tests.test_runtime_integration.CorporateOtelConformanceTests -v
```

Esta prueba demuestra nuestro contrato/transporte usando un SDK real; la implementación privada debe ejecutar después su propia comprobación. La [propagación estándar](https://opentelemetry.io/docs/languages/python/propagation/) requiere que el proceso receptor extraiga el contexto.

## Comparar con la línea base

Los [fingerprints separados](FINGERPRINTS.md) permiten cambiar adapters/reporting sin confundir ese cambio con uno de consigna o evaluador. Las nueve corridas GPT-5.6 existentes tienen una migración explícita, verificada y sin inferencias, que crea copias compatibles y conserva las originales. El dataset y scoring de esa línea base permanecen intactos.

```bash
tar -xzf artifacts/2026-09-13/runs.tar.gz
python3 -m evals.experiments.fingerprints migrate-baseline \
  runs/20260913T130955Z-a5ece05863e2 --output-dir runs/baseline-compatible
python3 -m evals.experiments.comparison \
  runs/baseline-compatible/20260913T130955Z-a5ece05863e2 \
  runs/ID_DEL_CORPORATIVO --output-dir runs/comparisons
```

La extracción del respaldo se realiza en un checkout nuevo; sobrescribe nombres existentes. La migración, en cambio, rechaza sobrescrituras. Elegir modelo/reasoning comparables; si son distintos, el reporte lo conserva y no se debe atribuir toda diferencia al harness. Las rutas de reportes en comparaciones antiguas identifican la máquina original; regenerar la comparación con los directorios recuperados.

## Reconstruir el historial en Phoenix

```bash
./run.py --import-run runs/baseline-compatible/20260913T130955Z-a5ece05863e2 \
  --phoenix-url http://127.0.0.1:6006 --output-dir runs/restored
```

`--import-run` copia respuestas, scores, tiempos, consumo y trazas guardados. No llama al harness ni registra los evaluadores actuales como autores de scores históricos. Los archivos fuente y sus checkpoints quedan intactos; se crea un recibo aparte bajo `runs/restored/imports/`.

Las corridas nuevas y copias migradas llevan un snapshot privado de las referencias. Para un reporte antiguo sin snapshot, las referencias se indican como `unavailable`; nunca se sustituyen por las del checkout actual. Los resultados importados pertenecen al proyecto de tracing `doc-intell-poc-imported`.

Cada reintento comprueba contenido remoto, no solo IDs locales: recupera tras una respuesta perdida y puede importar a un Phoenix vacío aunque reutilice el mismo localhost. Conserva los IDs de traza y span; agrega un marcador de identidad al exportar, sin alterar el archivo fuente. La lectura de Phoenix tiene precisión de microsegundos, contemplada en la verificación frente a los nanosegundos originales.

`--upload-only` queda para publicación con el contrato/scoring vigentes. Para históricos usar `--import-run` o migrar primero el baseline auditado. No se reinterpreta automáticamente una versión antigua con el evaluador actual.

## Después de esta etapa

Suite completa, incluidos diagnóstico, SDK y transferencia a Phoenix vacío:

```bash
DOC_INTELL_DOCKER_TESTS=1 DOC_INTELL_PHOENIX_TESTS=1 \
  uv run --with arize-phoenix-client==3.5.0 --with opentelemetry-proto==1.44.0 \
  python -m unittest discover -s tests -q
```

Siguen separados el soporte de reanudar inferencias pendientes, casos adicionales para diferenciar calidad y el MCP de Document Intelligence. El siguiente dato necesario para conectar el corporativo es su SO/arquitectura, disponibilidad de Docker, interfaz CLI/API y mecanismo de autenticación/red.
