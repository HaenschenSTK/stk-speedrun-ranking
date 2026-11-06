"""Best accepted positions reconstructed from available verified run history."""

from collections import defaultdict
from datetime import datetime
from itertools import groupby


def best_positions(runs, now):
    """Return best competition ranks per player/board, or null for undated boards.

    All verifications at the same instant enter together. Each player contributes
    only their fastest accepted run, so self-improvements never occupy extra places.
    """
    boards = defaultdict(list)
    for run in runs:
        boards[run['track_id'], run['category_id'], run['board_key']].append(run)
    result = {}
    for board, history in boards.items():
        if any(r['verified_at'] is None for r in history):
            result.update({(r['player_key'], *board): None for r in history})
            continue
        dated = [(datetime.fromisoformat(r['verified_at']), r) for r in history]
        dated = sorted(((date, run) for date, run in dated if date <= now), key=lambda item: item[0])
        pbs = {}
        for _, batch in groupby(dated, key=lambda item: item[0]):
            for _, run in batch:
                player = run['player_key']
                pbs[player] = min(pbs.get(player, run['time_us']), run['time_us'])
            previous_time, rank = None, 0
            for position, (player, time) in enumerate(sorted(pbs.items(), key=lambda item: item[1]), 1):
                if time != previous_time:
                    rank, previous_time = position, time
                key = player, *board
                result[key] = min(result.get(key, rank), rank)
    return result
