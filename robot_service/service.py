"""工单与设备关联：剔除已撤销误报，并区分首次失效与同一问题的返修。"""
from .evidence import at
from .fleet import installed


def events(db, known_at):
    """有效工单事件列表与待核工单列表。

    返回 (events, unmatched)。events 中每条带 kind 字段：
    '首次失效' 表示该设备该类故障的第一次有效报修，其后为 '返修'。
    state=='retracted' 的工单是已撤销的误报，不计故障也不占维修暴露。
    """
    devices = installed(db, known_at)
    rows = []
    unmatched = []
    for row in at(db, 'ticket', known_at):
        p = row['payload']
        if p.get('state') == 'retracted':
            continue
        device = devices.get(p['device'])
        item = {
            'ticket': row['id'],
            'device': p['device'],
            'cohort': device['cohort'] if device else None,
            'fault': p['fault'],
            'part': p['part'],
            'state': p['state'],
            'occurred_on': p['occurred_on'],
            'returned_on': p.get('returned_on'),
            'source': row['digest'],
        }
        if device is None:
            item['status'] = '设备待核'
            unmatched.append(item)
            continue
        rows.append(item)
    rows.sort(key=lambda r: (r['device'], r['fault'], r['occurred_on'], r['ticket']))
    seen = set()
    for r in rows:
        key = (r['device'], r['fault'])
        r['kind'] = '首次失效' if key not in seen else '返修'
        seen.add(key)
    return rows, unmatched
