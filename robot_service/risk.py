"""按批次汇总暴露量、首次失效与返修，并给出故障风险区间。

暴露量按设备实际投用、停用、维修停机与配置有效期计算；首次失效的
暴露只计到该设备该类故障第一次发生为止。暴露不足观察期的设备不计入
零故障样本，只贡献其真实暴露天数。
"""
from .evidence import at
from .fleet import installed
from .service import events
from .exposure import device_segments, exposure_until, config_at, to_day
from ._stats import poisson_interval

STATUS = ('在役', '已停用', '未投用')


def fleet_view(db, known_at, min_observation_days=28):
    """设备级暴露与工单事件的一次性汇总，供风险与备件模块共用。"""
    today = to_day(known_at)
    devices = installed(db, known_at)
    rows, unmatched = events(db, known_at)
    configs = {}
    for row in at(db, 'config', known_at):
        configs.setdefault(row['payload']['device'], []).append(row['payload'])
    tickets_by_device = {}
    for r in rows:
        tickets_by_device.setdefault(r['device'], []).append(r)
    device_views = {}
    for dev_id, dev in devices.items():
        segs = device_segments(dev, tickets_by_device.get(dev_id, []), configs.get(dev_id, []), today)
        at_risk = sum(s['days'] for s in segs)
        if to_day(dev['installed_on']) > today:
            status = '未投用'
        elif dev.get('retired_on') and to_day(dev['retired_on']) <= today:
            status = '已停用'
        else:
            status = '在役'
        firsts = []
        recurrences = 0
        for r in tickets_by_device.get(dev_id, []):
            if r['kind'] == '首次失效':
                firsts.append(r['fault'])
            else:
                recurrences += 1
        device_views[dev_id] = {
            'device': dev_id,
            'cohort': dev['cohort'],
            'model': dev['model'],
            'installed_on': dev['installed_on'],
            'retired_on': dev.get('retired_on'),
            'status': status,
            'at_risk_days': at_risk,
            'observed': at_risk >= min_observation_days,
            'first_failures': sorted(firsts),
            'recurrences': recurrences,
            'segments': segs,
        }
    return {
        'known_at': known_at,
        'today': today,
        'min_observation_days': min_observation_days,
        'devices': device_views,
        'events': rows,
        'unmatched': unmatched,
        'configs': configs,
    }


def _config_key(config):
    if not config:
        return ('未登记', '未登记')
    return (config.get('firmware') or '未登记', config.get('drive') or '未登记')


def _rate_per_1000(events_count, exposure_days, confidence):
    got = poisson_interval(events_count, exposure_days, confidence)
    if got is None:
        return None, None
    rate, lo, hi = got
    return round(rate * 1000, 3), [round(lo * 1000, 3), round(hi * 1000, 3)]


def cohort_risk(view, confidence=0.95):
    """批次风险表：暴露量、首次失效/返修分类与故障风险区间。"""
    devices = view['devices']
    configs = view['configs']
    cohorts = {}
    for dv in devices.values():
        c = cohorts.setdefault(dv['cohort'], {
            'cohort': dv['cohort'],
            'devices': 0,
            'status': {s: 0 for s in STATUS},
            'observed_devices': 0,
            'under_observation': 0,
            'zero_failure_observed': 0,
            'exposure_days': 0,
            'first_failures': 0,
            'recurrences': 0,
            'fault_map': {},
            'config_map': {},
            'units': [],
        })
        c['devices'] += 1
        c['status'][dv['status']] += 1
        c['exposure_days'] += dv['at_risk_days']
        if dv['observed']:
            c['observed_devices'] += 1
            if not dv['first_failures']:
                c['zero_failure_observed'] += 1
        elif dv['status'] != '未投用':
            c['under_observation'] += 1
        c['units'].append({k: dv[k] for k in (
            'device', 'model', 'installed_on', 'retired_on', 'status',
            'at_risk_days', 'observed', 'first_failures', 'recurrences')})
        for seg in dv['segments']:
            key = _config_key(seg['config'])
            entry = c['config_map'].setdefault(key, {'exposure_days': 0, 'first_failures': 0, 'recurrences': 0})
            entry['exposure_days'] += seg['days']

    first_event_day = {}
    for r in view['events']:
        if r['cohort'] is None:
            continue
        c = cohorts[r['cohort']]
        fault = c['fault_map'].setdefault(r['fault'], {
            'fault': r['fault'], 'parts': set(),
            'first_failures': 0, 'first_failure_exposure_days': 0, 'recurrences': 0,
        })
        fault['parts'].add(r['part'])
        key = _config_key(config_at(configs.get(r['device'], []), to_day(r['occurred_on'])))
        entry = c['config_map'].setdefault(key, {'exposure_days': 0, 'first_failures': 0, 'recurrences': 0})
        if r['kind'] == '首次失效':
            fault['first_failures'] += 1
            c['first_failures'] += 1
            entry['first_failures'] += 1
            first_event_day[(r['device'], r['fault'])] = to_day(r['occurred_on'])
        else:
            fault['recurrences'] += 1
            c['recurrences'] += 1
            entry['recurrences'] += 1

    result = []
    for cohort_id in sorted(cohorts):
        c = cohorts[cohort_id]
        faults = []
        for fault_name in sorted(c['fault_map']):
            f = c['fault_map'][fault_name]
            exposure = 0
            for dv in devices.values():
                if dv['cohort'] != cohort_id:
                    continue
                day = first_event_day.get((dv['device'], fault_name))
                exposure += exposure_until(dv['segments'], day) if day else dv['at_risk_days']
            f['first_failure_exposure_days'] = exposure
            rate, interval = _rate_per_1000(f['first_failures'], exposure, confidence)
            rec_rate, rec_interval = _rate_per_1000(f['recurrences'], c['exposure_days'], confidence)
            faults.append({
                'fault': fault_name,
                'parts': sorted(f['parts']),
                'first_failures': f['first_failures'],
                'first_failure_exposure_days': exposure,
                'first_failure_rate_per_1000_days': rate,
                'first_failure_interval_per_1000_days': interval,
                'recurrences': f['recurrences'],
                'recurrence_rate_per_1000_days': rec_rate,
                'recurrence_interval_per_1000_days': rec_interval,
            })
        config_rows = []
        for (firmware, drive) in sorted(c['config_map']):
            entry = c['config_map'][(firmware, drive)]
            total = entry['first_failures'] + entry['recurrences']
            rate, interval = _rate_per_1000(total, entry['exposure_days'], confidence)
            config_rows.append({
                'firmware': firmware,
                'drive': drive,
                'exposure_days': entry['exposure_days'],
                'first_failures': entry['first_failures'],
                'recurrences': entry['recurrences'],
                'event_rate_per_1000_days': rate,
                'event_interval_per_1000_days': interval,
            })
        row = {
            'cohort': cohort_id,
            'devices': c['devices'],
            'status': c['status'],
            'observed_devices': c['observed_devices'],
            'under_observation': c['under_observation'],
            'zero_failure_observed': c['zero_failure_observed'],
            'exposure_days': c['exposure_days'],
            'first_failures': c['first_failures'],
            'recurrences': c['recurrences'],
            'faults': faults,
            'configs': config_rows,
            'units': sorted(c['units'], key=lambda u: u['device']),
        }
        if c['under_observation']:
            row['note'] = '{} 台设备未到 {} 天观察期，未计入零故障样本'.format(
                c['under_observation'], view['min_observation_days'])
        result.append(row)
    return result
