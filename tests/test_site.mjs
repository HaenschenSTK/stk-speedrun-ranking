import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  parseRoute, routeHash, variant, profileRows, selectedBoards,
  points, days, raceTime, safeExternalURL,
} from '../site/model.mjs';

const data = JSON.parse(readFileSync(new URL('../site/data/rankings.json', import.meta.url)));

test('shareable URLs preserve filters, searches, and player IDs through reloads', () => {
  const route = {view: 'player', direction: 'combined', bonus: true,
    player: 'guest:A & B?#雪', from: 'hall', search: 'a+b & 雪'};
  assert.deepEqual(parseRoute(routeHash(route)), route);
  assert.deepEqual(parseRoute('#bogus?direction=other&bonus=false'), parseRoute(''));
  assert.equal(variant(parseRoute('')), 'forward-without-bonus');
});

test('all six profile breakdowns reproduce every exported player total and coverage', () => {
  for (const ranking of Object.values(data.rankings)) {
    const state = {direction: ranking.direction, bonus: ranking.include_bonus};
    assert.equal(selectedBoards(data, state).length, ranking.board_count);
    for (const entry of ranking.entries) {
      const rows = profileRows(data, entry.player_key, state);
      const total = rows.reduce((sum, row) => sum + (row.performance?.points || 0), 0);
      assert.ok(Math.abs(total - entry.points) < 1e-10, `${variant(state)}: ${entry.player_name}`);
      assert.equal(rows.filter(row => row.performance).length, entry.boards_played);
      assert.equal(rows.filter(row => row.performance?.is_wr).length, entry.world_records);
      for (const row of rows) {
        if (row.performance) assert.equal(row.performance.wr_time_us, row.board.wr_time_us);
      }
    }
  }
});

test('combined keeps directions separate and never invents empty reverse bonus boards', () => {
  const rows = selectedBoards(data, {direction: 'combined', bonus: true});
  const keys = rows.map(row => `${row.track}/${row.direction}`);
  assert.equal(new Set(keys).size, rows.length);
  assert.equal(rows.length, data.boards.length);
  assert.ok(keys.includes('old-mine/forward'));
  assert.ok(keys.includes('old-mine/reverse'));
});

test('missing PBs remain visible while unavailable history stays unknown', () => {
  const rows = profileRows(data, 'user:x72mkqq8', {direction: 'forward', bonus: false});
  assert.ok(rows.some(row => row.performance === null));
  assert.equal(days(null), '—');
  assert.equal(days(0), '0.0');
  assert.equal(points(.0001), '<0.001');
  assert.equal(points(0), '0.000');
  assert.equal(raceTime(61_234_000), '1:01.234');
  assert.equal(raceTime(61_234_567), '1:01.234567');
});

test('source links reject active and local URL schemes', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,x', 'file:///tmp/example', '//example.com', null]) {
    assert.equal(safeExternalURL(value), null);
  }
  assert.equal(safeExternalURL('https://www.speedrun.com/stk'), 'https://www.speedrun.com/stk');
});

test('published Hall of Fame is ordered by hours and contains only eligible members', () => {
  const hall = data.hall_of_fame;
  assert.deepEqual(hall.rules.ordering, ['total_wr_hours descending']);
  for (const [i, member] of hall.members.entries()) {
    const audit = hall.players[member.player_key];
    assert.ok(audit.online_top_three_confirmed);
    assert.ok(audit.qualifying_track_count >= 3);
    assert.equal(member.total_wr_hours, audit.total_wr_hours);
    if (i) assert.ok(hall.members[i - 1].total_wr_hours >= member.total_wr_hours);
  }
  assert.equal('apprentices' in hall, false);
});
