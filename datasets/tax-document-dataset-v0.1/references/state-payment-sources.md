# Fuentes estatales y pagos: verificación de cobertura

Investigación 2026-09-12. California, New Jersey y New York son candidatos propuestos para PoC, no estados atribuidos al proyecto. Esta colección de fuentes oficiales cubre estructura y reglas para producir mocks. No es un dataset de documentos cumplimentados con ground truth. No se verificó un corpus público etiquetado para estos gaps. No usar las cifras/reglas de páginas actuales como si fueran automáticamente de 2024/2025; versionar por ejercicio y conservar hash del PDF.

## Material primario accesible y útil

| Familia | Fuente exacta | Material confirmado | Campos/relaciones aprovechables | Trabajo pendiente |
|---|---|---|---|---|
| K-1 estatal CA partnership | https://www.ftb.ca.gov/forms/2025/2025-565-k-1.pdf | PDF oficial 2025, 4 páginas, vacío | identidad entidad/partner; columnas federal, ajuste CA, total CA y fuente CA; línea 15a retención total, explícitamente igual a 592-B para partnership calendar-year | Rellenar con eventos coherentes y etiquetar. Línea 15a + 592-B son dos evidencias de la misma retención, no dos pagos. |
| Retención estatal CA | https://www.ftb.ca.gov/forms/2025/2025-592-b.pdf | PDF oficial 2025, 3 páginas, formulario vacío + instrucciones | Año; amended; withholding agent; payee; tipo de renta; Part IV 1 ingreso sujeto; 2 withholding; 3 backup withholding | Generar valores, amended y fechas en supporting statements. Los pies extraídos mencionan 2024 aunque el encabezado taxable year dice 2025: controlar versión visualmente. |
| PTET CA cálculo entidad | https://www.ftb.ca.gov/forms/2025/2025-3804.pdf | PDF oficial 2025, 2 páginas, vacío | Part I línea 3 impuesto total de entidad; Part II por contribuyente: a base cualificada, b crédito individual. | Generar entidad de varios socios: evitar atribuir total de entidad al contribuyente. La obligación calculada no es evidencia de cuándo se pagó. |
| PTET CA crédito individual | https://www.ftb.ca.gov/forms/2025/2025-3804-cr.pdf | PDF oficial 2025, 1 página, vacío | Part I entidad/EIN/crédito por entidad; Part II crédito corriente, carryover previo, disponible, reclamado y carryover futuro. | Generar crédito y carryover separados; no sumar crédito recibido y reclamado como dos pagos. |
| K-1 estatal NJ partnership | https://www.nj.gov/treasury/taxation/pdf/current/part/njk1.pdf | PDF oficial verificado como 2025, 1 página, vacío | identidades, amended, member of composite return; Part III 1 share of NJ tax para nonresident; Part III 4 share of BAIT; Part IV supplemental | Rellenar + anexos propios. URL current es mutable: descargar/hash/fijar año al adquirir. Formulario dice This Form May be Reproduced. |
| Instrucciones NJ partnership | https://www.nj.gov/treasury/taxation/pdf/current/part/1065i.pdf | PDF oficial verificado 2025 | Reglas NJK-1 y referencias de transferencias | Revisar reglas detalladas si se computa fiscalidad en lugar de extraer valores declarados. |
| BAIT NJ, composite y pagos | https://www.nj.gov/treasury/taxation/baitpte/index.shtml | HTML oficial, actualizado 2026-04-16, no dataset | Crédito por socio sobre tax pagado por entidad; PTE-150 estimados; PTE-200-T extensión; PTE-100 declaración; NJ-1080-C composite compatible pero pagos a cuentas distintos. | Mocks de recibos electrónicos y anexo de distribución. Reglas por año deben verificarse. Fuente anterior https://www.nj.gov/treasury/taxation/baitpte.shtml muestra tabla de tasas distinta: no mezclar versiones. |
| UI/DI/FLI NJ | https://www.nj.gov/treasury/taxation/njit16.shtml | Guía oficial, explicita máximos para 2025 | Aportaciones del trabajador en W-2, ID empleador/plan; excesos entre varios empleadores; cónyuges en forms separados. | Generar W-2 con UI/WF/SWF, DI, FLI y paystubs correspondientes. No son equivalentes a retención de income tax. DUI sigue sin resolver. |
| Crédito exceso UI/DI/FLI NJ | https://www.nj.gov/treasury/taxation/pdf/current/2450.pdf | PDF oficial verificado como 2025, 1 página, vacío | NJ-2450 para exceso de contribuciones | Útil como ground truth de reconciliation con múltiples W-2; crear ejemplos sintéticos y revisar reglas. |
| UI/SDI CA | https://edd.ca.gov/en/payroll_taxes/what_are_state_payroll_taxes/ | Guía oficial, no formulario etiquetado | UI/ETT son aportes empleador; SDI/PIT retenidos a empleado. | Mocks de nómina/W-2; no convertir UI employer en impuesto personal por semejanza de etiqueta. |
| Anticipos CA | https://www.ftb.ca.gov/forms/2025/2025-540-es.pdf | PDF oficial 2025, 2 páginas, vouchers vacíos | Año, identificador persona/cónyuge, payment number, amount, vencimiento. Q4 2025 vence enero 2026. | Vouchers NO acreditan liquidación. Añadir recibo y extracto/ledger sintéticos. Pies extraídos mencionan 2024: validar visualmente antes de generar. |
| Extensión CA | https://www.ftb.ca.gov/forms/2025/2025-3519.pdf | PDF oficial 2025, 2 páginas, voucher + instrucciones | Periodo fiscal, identidad, importe; worksheet retenciones, estimated y applied previo. | Evidencia de pago efectiva adicional. Distinguir importe estimado, solicitud, pago y obligación. |
| Declaración, refund y crédito CA | https://www.ftb.ca.gov/forms/2025/2025-540.pdf | PDF oficial 2025, 6 páginas, vacío | Línea 98 aplicado a estimated 2026; línea 115 refund; líneas 71/72/73 retenciones/estimados/592-B separadas. | Cumplimentar relación entre años. Refund declarado tampoco confirma recibido; añadir ledger/notice/banco. |
| Pagos federales | https://www.irs.gov/payments/direct-pay-help | HTML oficial, instrucciones, no recibos reales ni GT | Reasons 1040 balance, 1040-ES estimated, 4868 extension; confirmation ID; pending/scheduled/canceled/returned/processed; impuesto/año/fecha | Generar recibos y statement/ledger con estados y vínculos deterministas. |

## Gaps que no quedaron descargables/verificados

- New York: candidatos concretos IT-204-IP (K-1 de partner), IT-653 (PTET crédito), IT-2658 (estimados de nonresident por entidad). Las búsquedas oficiales los identifican pero al abrir páginas/PDF de tax.ny.gov el acceso falló en esta sesión. NO presentar como descargados ni versión validada. Necesitan adquisición posterior desde índice oficial.
- NJ composite: NJ-1080-C confirmado como documento relevante por NJK-1 y guía BAIT; no se logró recuperar PDF 2025 desde el enlace ensayado. Necesita URL oficial verificada y mock de allocation statement.
- PTE-K-1 NJ: referencia localizada en instrucciones oficiales, pero no se recuperó plantilla concreta verificada. No confundir con NJK-1 que sí está accesible.
- No se encontró en esta búsqueda acotada un dataset público de recibos bancarios/pagos estatales realmente liquidados con ground truth por contribuyente/ejercicio/categoría. Falta render propio de confirmaciones, extractos, avisos de devolución y ledgers. No podemos declarar inexistencia global.
- No se verificó ejemplo oficial cumplimentado de Tax Account Transcript. La ayuda IRS sí distingue account transcript de return transcript para pagos; el primero es el candidato correcto para futuras fuentes.

## Reglas de generación sugeridas (inferencia de ingeniería, no nuevas reglas fiscales)

1. Evento de dinero canónico único con payer, beneficiary, entity, jurisdiction, tax_year, tax_type, amount y currency; estados/requested_at/scheduled_date/effective_date/posted_at separados.
2. Evidencias múltiples apuntan a event_id: voucher, confirmation, bank debit, tax account entry. El resultado expected cuenta el evento una vez.
3. El formulario declara valor fiscal, la fecha de liquidación procede de recibo/ledger. Si sólo hay confirmación, output payment_state=requested/unknown, no settled inventado.
4. Conservar tax-year, año calendario de pago y filing-year separados. Q4 de 2025 puede pagarse en enero 2026 sin cambiar tax-year.
5. Separar entity_total, allocated_to_taxpayer, credit_claimed y carryforward. FTB 3804 hace explícito total de entidad frente a crédito por socio; 3804-CR agrega claimed/carryover.
6. No interpretar estado IRS Pending como ya procesado. La ayuda oficial dice que confirmation acredita intento, consultar banco/account; permite returned/reversed. Si retiro tiene éxito, IRS puede acreditar día seleccionado aunque banco procese después: effective_date y posted_at no deben colapsarse.
7. Corpus no sólo templates: crear expedientes coherentes, evidencia insuficiente, amended, duplicados, múltiples socios, pago cruzado de año, pago cancelado/returned, refund solicitado vs recibido, créditos aplicados vs devolución.

## Evidencias exactas más valiosas para una demo

- CA K-1(565) 15a + CA 592-B Part IV 2: mismo withholding, dos documentos.
- CA 3804 Part I 3 total entidad 93.000, Part II b contribuyente 18.600 (cifras sintéticas a generar): agente debe escoger allocated_to_taxpayer y no 93.000.
- IRS Direct Pay submission + returned notice + banco sin debit/ledger returned: suma pagada cero, obligación puede persistir.
- CA 540 98 crédito applied next-year + 115 refund: dos conceptos, nunca asumir que todo overpayment salió en cash.

Licencias: accesibilidad pública no prueba automáticamente términos de redistribución. NJK-1 declara reproducible; para empaquetado público del resto registrar condiciones de uso/licencias por fuente y preferir un downloader que conserve URL/hash si permisos no están claros.
