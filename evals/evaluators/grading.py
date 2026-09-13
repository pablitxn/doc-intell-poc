"""Deterministic comparison of selected values and exact supporting references."""

from decimal import Decimal, InvalidOperation


def equal_value(actual, expected, kind):
    if kind in ('money', 'percent'):
        if isinstance(actual, bool) or actual is None: return False
        try:
            a, e = Decimal(str(actual)), Decimal(str(expected))
            return a.is_finite() and a == e
        except (InvalidOperation, ValueError): return False
    if kind == 'boolean': return isinstance(actual, bool) and actual == expected
    return type(actual) is type(expected) and actual == expected


def reference_key(ref):
    if not isinstance(ref, dict) or type(ref.get('page')) is not int: return None
    return str(ref.get('document_id')), ref['page'], str(ref.get('box'))


def grade(predictions, expected, types, task_id=None):
    actual_answers = predictions.get('answers', {})
    if not isinstance(actual_answers, dict): actual_answers={}
    rows=[]
    targets=expected['answers']
    if task_id and task_id not in targets: raise ValueError('Unknown task: '+task_id)
    for tid, answer in targets.items():
        if task_id and tid != task_id: continue
        predicted=actual_answers.get(tid, {})
        if not isinstance(predicted,dict):predicted={}
        values=predicted.get('values',{});evidence=predicted.get('evidence',{})
        if not isinstance(values,dict):values={}
        if not isinstance(evidence,dict):evidence={}
        fields=[]
        for key, value in answer['values'].items():
            ok=equal_value(values.get(key),value,types[tid][key])
            refs=evidence.get(key,[])
            if not isinstance(refs,list):refs=[]
            actual_refs={reference_key(r) for r in refs}
            expected_refs={reference_key(r) for r in answer['evidence'][key]}
            # Require the specified supporting boxes without rewarding extra incorrect citations.
            supported=actual_refs==expected_refs
            fields.append({'field':key,'value_correct':ok,'evidence_correct':supported})
        rows.append({'task_id':tid,'passed':all(f['value_correct'] and f['evidence_correct'] for f in fields),
                     'fields':fields})
    all_fields=[f for r in rows for f in r['fields']]
    count=len(all_fields)
    return {'tasks_evaluated':len(rows),'tasks_passed':sum(r['passed'] for r in rows),
            'fields_evaluated':count,
            'value_accuracy':sum(f['value_correct'] for f in all_fields)/count,
            'evidence_accuracy':sum(f['evidence_correct'] for f in all_fields)/count,
            'per_task':rows,
            'scope':'Exact selected values and document/page/box evidence. Bboxes, prose and tool trajectories are not scored.'}
