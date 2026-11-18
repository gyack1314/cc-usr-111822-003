"""核对暴露量、故障风险区间、备件需求与决策复核。"""
import json
import unittest
from datetime import date
from pathlib import Path
from robot_service.evidence import connect, receive
from robot_service.exposure import device_segments, exposure_until
from robot_service.risk import fleet_view, cohort_risk
from robot_service.parts import demand
from robot_service.report import snapshot, decision_review
from robot_service._stats import poisson_interval

DATA = json.loads((Path(__file__).resolve().parents[1] / 'data' / 'example.json').read_text(encoding='utf-8'))
NOW = DATA['known_at']
DECISION = '2026-09-10T00:00:00+08:00'


def load(db):
    for item in DATA['documents']:
        receive(db, item)


class Stats(unittest.TestCase):
    def test_poisson_interval_known_values(self):
        rate, lo, hi = poisson_interval(10, 1000)
        self.assertAlmostEqual(rate, 0.01)
        self.assertAlmostEqual(lo, 0.5 * 9.5907774 / 1000, places=9)
        self.assertAlmostEqual(hi, 0.5 * 36.7807123 / 1000, places=9)

    def test_zero_events_and_zero_exposure(self):
        rate, lo, hi = poisson_interval(0, 1000)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.5 * 7.3777589 / 1000, places=9)
        self.assertIsNone(poisson_interval(0, 0))


class Exposure(unittest.TestCase):
    def test_repair_downtime_and_retirement_cut_exposure(self):
        device = {'installed_on': '2026-06-01', 'retired_on': '2026-09-01'}
        tickets = [{'occurred_on': '2026-07-05', 'returned_on': '2026-07-12'}]
        configs = [
            {'firmware': 'F1', 'drive': 'J1', 'effective_from': '2026-06-01', 'effective_to': '2026-08-01'},
            {'firmware': 'F2', 'drive': 'J2', 'effective_from': '2026-08-01'},
        ]
        segs = device_segments(device, tickets, configs, date(2026, 10, 8))
        self.assertEqual(sum(s['days'] for s in segs), 85)
        by_config = {}
        for s in segs:
            by_config.setdefault(s['config']['firmware'], 0)
            by_config[s['config']['firmware']] += s['days']
        self.assertEqual(by_config, {'F1': 54, 'F2': 31})
        self.assertEqual(exposure_until(segs, date(2026, 7, 5)), 34)

    def test_open_ticket_blocks_until_today(self):
        device = {'installed_on': '2026-06-01'}
        tickets = [{'occurred_on': '2026-09-20'}]
        segs = device_segments(device, tickets, [], date(2026, 10, 8))
        self.assertEqual(sum(s['days'] for s in segs), 129 - 18)

    def test_not_yet_commissioned_has_no_exposure(self):
        segs = device_segments({'installed_on': '2026-11-01'}, [], [], date(2026, 10, 8))
        self.assertEqual(segs, [])


class BusinessChain(unittest.TestCase):
    def setUp(self):
        self.db = connect()
        load(self.db)

    def tearDown(self):
        self.db.close()

    def test_conflicting_revision(self):
        item = DATA['documents'][0]
        changed = json.loads(json.dumps(item))
        changed['payload']['conflict'] = True
        with self.assertRaises(ValueError):
            receive(self.db, changed)

    def test_first_failure_vs_recurrence(self):
        view = fleet_view(self.db, NOW)
        kinds = {r['ticket']: r['kind'] for r in view['events']}
        self.assertEqual(kinds, {
            'T1': '首次失效', 'T2': '返修', 'T3': '首次失效',
            'T4': '首次失效', 'T6': '首次失效',
        })
        self.assertNotIn('T5', kinds)  # 已撤销的误报不计入
        self.assertEqual(view['unmatched'], [])

    def test_retraction_restores_exposure(self):
        now = fleet_view(self.db, NOW)
        then = fleet_view(self.db, DECISION)
        self.assertEqual(now['devices']['R2']['at_risk_days'], 85)
        self.assertEqual(then['devices']['R2']['at_risk_days'], 63)  # 误报未撤销时按停机计

    def test_cohort_exposure_and_risk_interval(self):
        cohorts = {c['cohort']: c for c in cohort_risk(fleet_view(self.db, NOW))}
        old = cohorts['2026-06']
        self.assertEqual(old['exposure_days'], 425)
        self.assertEqual(old['observed_devices'], 4)
        self.assertEqual(old['zero_failure_observed'], 2)
        self.assertEqual(old['first_failures'], 3)
        self.assertEqual(old['recurrences'], 1)
        self.assertEqual(old['status'], {'在役': 3, '已停用': 1, '未投用': 0})
        joint = next(f for f in old['faults'] if f['fault'] == 'joint')
        self.assertEqual(joint['first_failures'], 2)
        self.assertEqual(joint['first_failure_exposure_days'], 317)
        self.assertAlmostEqual(joint['first_failure_rate_per_1000_days'], 6.309, places=3)
        lo, hi = joint['first_failure_interval_per_1000_days']
        self.assertAlmostEqual(lo, 0.764, places=3)
        self.assertAlmostEqual(hi, 22.791, places=3)
        sensor = next(f for f in old['faults'] if f['fault'] == 'sensor')
        self.assertEqual(sensor['first_failure_exposure_days'], 396)
        configs = {(c['firmware'], c['drive']): c['exposure_days'] for c in old['configs']}
        self.assertEqual(configs, {('F1', 'J1'): 215, ('F2', 'J2'): 210})

    def test_under_observation_not_zero_failure(self):
        cohorts = {c['cohort']: c for c in cohort_risk(fleet_view(self.db, NOW))}
        new = cohorts['2026-10']
        self.assertEqual(new['observed_devices'], 0)
        self.assertEqual(new['under_observation'], 3)
        self.assertEqual(new['zero_failure_observed'], 0)  # 未到观察期不算零故障
        self.assertEqual(new['status']['未投用'], 1)
        self.assertIn('未计入零故障样本', new['note'])
        self.assertEqual(new['faults'], [])

    def test_parts_demand(self):
        rows = {(r['cohort'], r['part']): r for r in demand(self.db, NOW)}
        self.assertEqual(rows[('2026-06', 'J2')]['open_cases'], 1)
        self.assertAlmostEqual(rows[('2026-06', 'J1')]['expected_in_horizon'], 0.42)
        self.assertAlmostEqual(rows[('2026-09', 'W1')]['expected_in_horizon'], 0.9)
        self.assertFalse(any(c == '2026-10' for c, _ in rows))  # 新批次不产生预计需求
        self.assertIn('open_cases', json.dumps(demand(self.db, NOW), ensure_ascii=False))

    def test_decision_review(self):
        review = decision_review(self.db, DECISION, NOW)
        affected = {a['cohort']: a for a in review['affected_cohorts']}
        self.assertEqual(set(affected), {'2026-06', '2026-09', '2026-10'})
        self.assertEqual(affected['2026-06']['before'],
                         {'first_failures': 2, 'recurrences': 1, 'exposure_days': 344})
        self.assertEqual(affected['2026-06']['after'],
                         {'first_failures': 3, 'recurrences': 1, 'exposure_days': 425})
        self.assertIsNone(affected['2026-10']['before'])

        evidence_ids = {(e['kind'], e['id']) for e in review['evidence_at_decision']}
        self.assertIn(('ticket', 'T5'), evidence_ids)  # 决策时误报尚未撤销，是当时的证据
        self.assertIn(('ticket', 'T1'), evidence_ids)
        self.assertNotIn(('ticket', 'T3'), evidence_ids)  # 补录单决策时不可用
        self.assertNotIn(('device', 'R7'), evidence_ids)
        for e in review['evidence_at_decision']:
            self.assertLessEqual(e['received_at'], DECISION)
            self.assertTrue(e['digest'])

        late = {(d['kind'], d['id'], d['revision']): d for d in review['received_after_decision']}
        self.assertEqual(late[('ticket', 'T3', 'r1')]['effect'], '补录工单')
        self.assertEqual(late[('ticket', 'T3', 'r1')]['failure_kind'], '首次失效')
        self.assertEqual(late[('ticket', 'T5', 'r2')]['effect'], '撤销误报')
        self.assertEqual(late[('ticket', 'T2', 'r1')]['failure_kind'], '返修')

        delta = {(d['cohort'], d['part']) for d in review['parts_delta']}
        self.assertIn(('2026-06', 'S1'), delta)  # 补录的传感器故障带来新备件需求

    def test_snapshot_is_json_serializable(self):
        report = snapshot(self.db, NOW)
        report['decision_review'] = decision_review(self.db, DECISION, NOW)
        self.assertIn('cohorts', json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
