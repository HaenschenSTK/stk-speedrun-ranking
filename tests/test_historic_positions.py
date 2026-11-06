import unittest
from datetime import datetime, timezone
from stk_rankings.historic_positions import best_positions


class HistoricPositionsTests(unittest.TestCase):
    def test_pbs_ties_simultaneous_verifications_and_best_placement(self):
        def run(player, time, day, board='forward'):
            return dict(player_key=player, time_us=time, verified_at=f'2024-01-{day:02}T00:00:00Z',
                        track_id='track', category_id='1.x', board_key=board)
        runs = [run('a', 100, 1), run('a', 99, 2), run('b', 101, 2),
                run('c', 101, 2), run('d', 103, 2), run('d', 100, 3),
                run('e', 98, 3), run('d', 98, 4), run('b', 110, 5),
                run('future', 1, 30), run('b', 100, 1, 'reverse')]
        ranks = best_positions(runs, datetime(2024, 1, 10, tzinfo=timezone.utc))
        self.assertEqual({key[0]: rank for key, rank in ranks.items() if key[-1] == 'forward'},
                         {'a': 1, 'b': 2, 'c': 2, 'd': 1, 'e': 1})
        self.assertEqual(ranks['b', 'track', '1.x', 'reverse'], 1)

    def test_simultaneous_faster_run_prevents_phantom_gold(self):
        runs = [dict(player_key=player, time_us=time, verified_at='2024-01-01T00:00:00Z',
                     track_id='track', category_id='1.x', board_key='forward')
                for player, time in [('a', 102), ('b', 100), ('c', 100)]]
        ranks = best_positions(runs, datetime(2024, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(ranks['a', 'track', '1.x', 'forward'], 3)
