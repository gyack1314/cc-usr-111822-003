"""批次风险快照与决策复核。

补录维修单或撤销误报后，decision_review 对比决策时点与当前两个快照，
说明受影响批次、备件需求变化、决策时可用的证据（含内容摘要），以及
决策后才到达的资料（补录工单、撤销误报、新装设备等）。
"""
from .evidence import at, documents
from .exposure import to_day
from .risk import fleet_view, cohort_risk
from .parts import demand_from_view


def _snapshot_from_view(view, horizon_days, confidence):
    return {
        'known_at': view['known_at'],
        'min_observation_days': view['min_observation_days'],
        'cohorts': cohort_risk(view, confidence),
        'parts': demand_from_view(view, horizon_days, confidence),
        'unmatched_tickets': view['unmatched'],
    }


def snapshot(db, known_at, min_observation_days=28, horizon_days=30, confidence=0.95):
    view = fleet_view(db, known_at, min_observation_days)
    return _snapshot_from_view(view, horizon_days, confidence)


def _summary(doc):
    kind = doc['kind']
    p = doc['payload']
    if kind == 'device':
        text = '设备 {}：{} 批次 {}，{} 投用'.format(doc['id'], p['cohort'], p['model'], p['installed_on'])
        if p.get('retired_on'):
            text += '，{} 停用'.format(p['retired_on'])
        return text
    if kind == 'ticket':
        return '工单 {}：{} {} / {}，{} 发生，状态 {}'.format(
            doc['id'], p['device'], p['fault'], p['part'], p['occurred_on'], p['state'])
    if kind == 'config':
        return '配置 {}：{} 固件 {} 部件 {}，{} 起生效'.format(
            doc['id'], p['device'], p.get('firmware'), p.get('drive'), p['effective_from'])
    return '{} {}'.format(kind, doc['id'])


def _effect(doc, decision_at):
    p = doc['payload']
    if doc['kind'] == 'device':
        return '设备停用' if p.get('active') is False else '设备登记'
    if doc['kind'] == 'config':
        return '配置变更'
    if doc['kind'] == 'ticket':
        if p.get('state') == 'retracted':
            return '撤销误报'
        if to_day(p['occurred_on']) < to_day(decision_at):
            return '补录工单'
        return '新开工单'
    return '资料更新'


def _cohort_totals(cohorts):
    return {
        c['cohort']: {
            'first_failures': c['first_failures'],
            'recurrences': c['recurrences'],
            'exposure_days': c['exposure_days'],
        }
        for c in cohorts
    }


def decision_review(db, decision_at, now_at, min_observation_days=28, horizon_days=30, confidence=0.95):
    before = _snapshot_from_view(fleet_view(db, decision_at, min_observation_days), horizon_days, confidence)
    after_view = fleet_view(db, now_at, min_observation_days)
    after = _snapshot_from_view(after_view, horizon_days, confidence)

    bmap = _cohort_totals(before['cohorts'])
    amap = _cohort_totals(after['cohorts'])
    affected = []
    for cohort in sorted(set(bmap) | set(amap)):
        b, a = bmap.get(cohort), amap.get(cohort)
        if b != a:
            affected.append({'cohort': cohort, 'before': b, 'after': a})

    bp = {(p['cohort'], p['part']): p for p in before['parts']}
    ap = {(p['cohort'], p['part']): p for p in after['parts']}
    parts_delta = []
    for key in sorted(set(bp) | set(ap)):
        b, a = bp.get(key), ap.get(key)
        pair = (
            (b['open_cases'] if b else 0, a['open_cases'] if a else 0),
            (b['expected_in_horizon'] if b else 0.0, a['expected_in_horizon'] if a else 0.0),
        )
        if pair[0][0] != pair[0][1] or pair[1][0] != pair[1][1]:
            parts_delta.append({
                'cohort': key[0],
                'part': key[1],
                'open_cases': list(pair[0]),
                'expected_in_horizon': list(pair[1]),
            })

    cohort_ids = {item['cohort'] for item in affected}
    device_ids = {d for d, dv in after_view['devices'].items() if dv['cohort'] in cohort_ids}

    def related(doc):
        if doc['kind'] == 'device':
            return doc['id'] in device_ids
        return doc['payload'].get('device') in device_ids

    evidence = []
    for kind in ('device', 'ticket', 'config'):
        for doc in at(db, kind, decision_at):
            row = {'kind': kind, **doc}
            if related(row):
                evidence.append({
                    'kind': kind,
                    'id': doc['id'],
                    'revision': doc['revision'],
                    'received_at': doc['received_at'],
                    'digest': doc['digest'],
                    'summary': _summary(row),
                })

    failure_kind = {r['ticket']: r['kind'] for r in after_view['events']}
    late = []
    for doc in documents(db, received_after=decision_at, received_by=now_at):
        if not related(doc):
            continue
        entry = {
            'kind': doc['kind'],
            'id': doc['id'],
            'revision': doc['revision'],
            'received_at': doc['received_at'],
            'digest': doc['digest'],
            'effect': _effect(doc, decision_at),
            'summary': _summary(doc),
        }
        if doc['kind'] == 'ticket' and doc['id'] in failure_kind:
            entry['failure_kind'] = failure_kind[doc['id']]
        late.append(entry)

    return {
        'decision_at': decision_at,
        'reviewed_at': now_at,
        'affected_cohorts': affected,
        'parts_delta': parts_delta,
        'evidence_at_decision': evidence,
        'received_after_decision': late,
    }
