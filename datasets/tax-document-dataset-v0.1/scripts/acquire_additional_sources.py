"""Additional official templates; explicit revision/year roles, no automatic GT."""
import concurrent.futures
import json
from acquire_official_sources import acquire, DEST

SOURCES = [
 ('irs_1099INT_rev2024_current','1099INT',None,'https://www.irs.gov/pub/irs-pdf/f1099int.pdf'),
 ('irs_1099DIV_rev2024_current','1099DIV',None,'https://www.irs.gov/pub/irs-pdf/f1099div.pdf'),
 ('ca_K1_565_2025','CA_K1_565',2025,'https://www.ftb.ca.gov/forms/2025/2025-565-k-1.pdf'),
 ('ca_592B_2025','CA_withholding_592B',2025,'https://www.ftb.ca.gov/forms/2025/2025-592-b.pdf'),
 ('ca_3804_2025','CA_PTET_entity_3804',2025,'https://www.ftb.ca.gov/forms/2025/2025-3804.pdf'),
 ('ca_3804CR_2025','CA_PTET_credit_3804CR',2025,'https://www.ftb.ca.gov/forms/2025/2025-3804-cr.pdf'),
 ('nj_NJK1_current_2025','NJ_K1',2025,'https://www.nj.gov/treasury/taxation/pdf/current/part/njk1.pdf'),
 ('nj_1065_instructions_current_2025','NJ_K1_instructions',2025,'https://www.nj.gov/treasury/taxation/pdf/current/part/1065i.pdf'),
 ('nj_2450_current_2025','NJ_UI_DI_FLI',2025,'https://www.nj.gov/treasury/taxation/pdf/current/2450.pdf'),
 ('ca_540ES_2025','CA_estimated_voucher',2025,'https://www.ftb.ca.gov/forms/2025/2025-540-es.pdf'),
 ('ca_3519_2025','CA_extension_voucher',2025,'https://www.ftb.ca.gov/forms/2025/2025-3519.pdf'),
 ('ca_540_2025','CA_return_refund_credit',2025,'https://www.ftb.ca.gov/forms/2025/2025-540.pdf'),
]

def main():
    records=[dict(source_id=i, form_family=f, requested_year=y,
        role=('reference_instructions' if 'instructions' in f else 'blank_template'), url=u)
        for i,f,y,u in SOURCES]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        result=list(pool.map(acquire,records))
    path=DEST/'additional_inventory.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'requested':len(result),'downloaded':sum(r['status']=='downloaded_and_parsed' for r in result),
        'failed':[{k:r.get(k) for k in ('source_id','error')} for r in result if r['status']!='downloaded_and_parsed']},indent=2))

if __name__=='__main__': main()
