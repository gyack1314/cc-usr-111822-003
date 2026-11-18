"""备件需求：未结维修单的即时需求 + 按故障率外推的预计需求。

预计需求 = 批次该备件的单位暴露故障率 × 在役设备未来 horizon 天的
计划暴露；故障率用泊松精确区间给出上下限。没有故障历史的批次不产生
预计需求，但也不会被当作零故障（见 risk 模块的观察期说明）。
"""
from collections import Counter
from .risk import fleet_view
from ._stats import poisson_interval


def demand_from_view(view, horizon_days=30, confidence=0.95):
    exposure = Counter()
    active = Counter()
    for dv in view['devices'].values():
        exposure[dv['cohort']] += dv['at_risk_days']
        if dv['status'] == '在役':
            active[dv['cohort']] += 1
    open_counts = Counter()
    event_counts = Counter()
    for r in view['events']:
        event_counts[(r['cohort'], r['part'])] += 1
        if r['state'] == 'open':
            open_counts[(r['cohort'], r['part'])] += 1
    rows = []
    for cohort, part in sorted(set(open_counts) | set(event_counts)):
        n = event_counts[(cohort, part)]
        t = exposure[cohort]
        future = active[cohort] * horizon_days
        got = poisson_interval(n, t, confidence) if t > 0 else None
        rate, lo, hi = got if got else (0.0, 0.0, 0.0)
        rows.append({
            'cohort': cohort,
            'part': part,
            'open_cases': open_counts[(cohort, part)],
            'expected_in_horizon': round(rate * future, 2),
            'interval_in_horizon': [round(lo * future, 2), round(hi * future, 2)],
            'horizon_days': horizon_days,
        })
    return rows


def demand(db, known_at, horizon_days=30):
    return demand_from_view(fleet_view(db, known_at), horizon_days)
