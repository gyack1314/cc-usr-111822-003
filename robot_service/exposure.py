"""按投用、停用、维修与配置有效期形成可比的设备暴露区间。

暴露量只统计设备实际在役且未停机维修的时间；配置（固件/部件）变更
会把暴露切成不同区间，使升级前后可以分开比较。尚未投用或暴露不足
观察期的设备只贡献其真实暴露，不会被当作零故障样本。
"""
from datetime import date, datetime


def to_day(value):
    """ISO 日期或日期时间统一为 date。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    if 'T' in text:
        return datetime.fromisoformat(text).date()
    return date.fromisoformat(text)


def _subtract(window, blocks):
    """从窗口 [s,e) 中扣除若干停机区间。"""
    parts = [window]
    for bs, be in blocks:
        nxt = []
        for s, e in parts:
            if be <= s or bs >= e:
                nxt.append((s, e))
                continue
            if bs > s:
                nxt.append((s, bs))
            if be < e:
                nxt.append((be, e))
        parts = nxt
    return parts


def _tag(segments, configs):
    """把暴露区间按配置有效期切分并打标；无配置覆盖的区间标 None。"""
    tagged = []
    for s, e in segments:
        hits = []
        for cs, ce, key in configs:
            lo, hi = max(s, cs), min(e, ce)
            if lo < hi:
                hits.append((lo, hi, key))
        hits.sort(key=lambda h: (h[0], h[1]))
        cursor = s
        for lo, hi, key in hits:
            if cursor < lo:
                tagged.append((cursor, lo, None))
            tagged.append((lo, hi, key))
            cursor = hi
        if cursor < e:
            tagged.append((cursor, e, None))
    return tagged


def repair_windows(tickets, start, end, today):
    """设备停机维修区间（已撤销的误报由调用方剔除，不占暴露）。

    未登记归还时间的工单按设备仍在维修计，暴露扣到观察截止日。
    """
    blocks = []
    for t in tickets:
        occ = to_day(t['occurred_on'])
        ret = to_day(t['returned_on']) if t.get('returned_on') else today
        lo, hi = max(occ, start), min(ret, end)
        if lo < hi:
            blocks.append((lo, hi))
    return blocks


def device_segments(device, tickets, configs, today):
    """单台设备的在役暴露区间，扣除维修停机并按配置有效期切分。

    device/tickets/configs 均为 payload 字典；返回
    [{'start','end','days','config'}]，config 为 {'firmware','drive'} 或 None。
    """
    start = to_day(device['installed_on'])
    if start > today:
        return []
    end = today
    if device.get('retired_on'):
        end = min(end, to_day(device['retired_on']))
    if end <= start:
        return []
    at_risk = _subtract((start, end), repair_windows(tickets, start, end, today))
    windows = []
    for c in configs:
        cs = to_day(c['effective_from'])
        ce = to_day(c['effective_to']) if c.get('effective_to') else date.max
        windows.append((cs, ce, {'firmware': c.get('firmware'), 'drive': c.get('drive')}))
    return [
        {'start': s, 'end': e, 'days': (e - s).days, 'config': key}
        for s, e, key in _tag(at_risk, windows)
    ]


def exposure_until(segments, until):
    """截至某日（不含）的暴露天数，用于首次失效前的暴露。"""
    total = 0
    for s in segments:
        if s['start'] >= until:
            continue
        total += (min(s['end'], until) - s['start']).days
    return total


def config_at(configs, day):
    """某日生效的配置 {'firmware','drive'}，无覆盖返回 None。"""
    for c in configs:
        cs = to_day(c['effective_from'])
        ce = to_day(c['effective_to']) if c.get('effective_to') else date.max
        if cs <= day < ce:
            return {'firmware': c.get('firmware'), 'drive': c.get('drive')}
    return None
