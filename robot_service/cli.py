"""读取业务资料并输出批次风险、备件需求与决策复核。"""
import argparse
import json
from pathlib import Path
from .evidence import connect, receive
from .report import snapshot, decision_review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('--decision-at', help='复核该时点决策所用的证据与结论')
    parser.add_argument('--min-observation-days', type=int, default=28)
    parser.add_argument('--horizon-days', type=int, default=30)
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding='utf-8'))
    db = connect()
    for item in data['documents']:
        receive(db, item)
    known_at = data['known_at']
    report = snapshot(db, known_at, args.min_observation_days, args.horizon_days)
    if args.decision_at:
        report['decision_review'] = decision_review(
            db, args.decision_at, known_at, args.min_observation_days, args.horizon_days)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    db.close()


if __name__ == '__main__':
    main()
