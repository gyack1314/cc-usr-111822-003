from collections import Counter
from .service import cases
def demand(db, known_at):
    counts=Counter((r['cohort'],r['part']) for r in cases(db,known_at) if r.get('state')=='open')
    return [{'cohort':cohort,'part':part,'open_cases':count} for (cohort,part),count in sorted(counts.items())]
