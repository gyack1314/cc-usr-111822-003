from .evidence import at


def installed(db, known_at):
    """已知时点已登记的装机设备（含停用日期）。"""
    result = {}
    for row in at(db, 'device', known_at):
        p = row['payload']
        result[row['id']] = {
            'device': row['id'],
            'cohort': p['cohort'],
            'model': p['model'],
            'installed_on': p['installed_on'],
            'retired_on': p.get('retired_on'),
            'active': p['active'],
            'source': row['digest'],
        }
    return result
