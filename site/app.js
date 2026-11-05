import {
  trackRuns, podiumCounts, directions, titleCase, parseRoute, routeHash, variant, profileRows,
  number, points, days, raceTime, dateTime, safeExternalURL,
} from './model.mjs';

const main = document.querySelector('main');
const status = document.querySelector('#status');
let data;
let tracks;
let state = parseRoute(location.hash);
let renderedHash = location.hash;
history.scrollRestoration = 'manual';

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function link(text, next, className = '') {
  const node = el('a', text, `route-link ${className}`);
  node.href = routeHash(next);
  return node;
}

function externalLink(text, url) {
  const safe = safeExternalURL(url);
  if (!safe) return el('span', text);
  const node = el('a', text);
  node.href = safe;
  return node;
}

function playerLink(key, from = state.view) {
  const next = {...state, view: 'player', player: key, from: ['hall', 'tracks'].includes(from) ? from : 'ranking'};
  if (from === 'hall') Object.assign(next, {direction: 'forward', bonus: false});
  return link(data.players[key]?.name || data.hall_of_fame.players[key]?.name || key, next, 'player-link');
}

function heading(title, subtitle) {
  main.append(el('p', 'SuperTuxKart · 1.x individual levels', 'eyebrow'));
  const h1 = el('h1', title);
  h1.tabIndex = -1;
  main.append(h1, el('p', subtitle, 'subtitle'));
  document.title = `${title} · STK Rankings`;
}

function table(container, headers, caption, className = '') {
  const wrap = el('div', undefined, `table-wrap ${className === 'hall-table' ? 'hall-wrap' : ''}`);
  const table = el('table', undefined, className);
  table.append(el('caption', caption, 'sr-only'));
  const row = el('tr');
  for (const [text, cls] of headers) {
    const th = el('th', text, cls);
    th.scope = 'col';
    row.append(th);
  }
  const head = el('thead');
  head.append(row);
  const body = el('tbody');
  table.append(head, body);
  wrap.append(table);
  container.append(wrap);
  return body;
}

function controls({search = false} = {}) {
  const wrapper = el('div', undefined, 'controls');
  const segments = el('div', undefined, 'segments');
  segments.setAttribute('role', 'group');
  segments.setAttribute('aria-label', 'Direction');
  for (const direction of (state.view === 'tracks' ? directions.slice(0, 2) : directions)) {
    const a = link(titleCase(direction), {...state, direction});
    a.dataset.direction = direction;
    if (state.direction === direction) a.setAttribute('aria-current', 'true');
    segments.append(a);
  }
  const label = el('label', undefined, 'check');
  const checkbox = el('input');
  checkbox.id = 'bonus';
  checkbox.type = 'checkbox';
  checkbox.checked = state.bonus;
  checkbox.addEventListener('change', () => navigate(routeHash({...state, bonus: checkbox.checked}), 'bonus'));
  label.append(checkbox, el('span', 'Include bonus tracks'));
  label.title = 'Freytra Peaks and Drainage Dash';
  wrapper.append(segments);
  if (state.view !== 'tracks') wrapper.append(label);
  if (search) {
    const label = el('label', undefined, 'search');
    label.append(el('span', 'Find a player', 'sr-only'));
    const input = el('input');
    input.id = 'player-search';
    input.type = 'search';
    input.placeholder = 'Find a player…';
    input.autocomplete = 'off';
    input.value = state.search;
    input.addEventListener('input', () => {
      state.search = input.value;
      renderedHash = routeHash(state);
      history.replaceState(history.state, '', renderedHash);
      updateNav();
      renderRankingRows();
    });
    label.append(input);
    wrapper.append(label);
  }
  main.append(wrapper);
}

const scope = () => `${titleCase(state.direction)} · ${state.bonus ? 'Including bonus tracks' : 'Official tracks only'}`;

function renderRanking() {
  heading('Player ranking', 'A cross-track ranking based on distance from the world record.');
  controls({search: true});
  const container = el('div');
  container.id = 'ranking-results';
  main.append(container);
  renderRankingRows();
  main.append(el('p', 'Select a player for their points by track and world-record history. Scores use full precision; displayed values are rounded.', 'note'));
}

function renderRankingRows() {
  const container = document.querySelector('#ranking-results');
  container.replaceChildren();
  const ranking = data.rankings[variant(state)];
  const query = state.search.trim().toLocaleLowerCase('en');
  const matching = ranking.entries.filter(row => row.player_name.toLocaleLowerCase('en').includes(query));
  const caption = el('div', undefined, 'caption');
  const count = state.direction === 'combined' ? 'track / direction boards' : 'tracks';
  caption.append(el('span', `${query ? `${matching.length} of ` : ''}${ranking.entries.length} players · ${ranking.board_count} ${count}`),
    el('span', `Maximum ${ranking.max_points} points`));
  container.append(caption);
  const body = table(container, [
    ['Rank', 'rank'], ['Player', 'name'], ['Points', ''],
    [state.direction === 'combined' ? 'Boards' : 'Tracks', 'secondary'], ['Podiums', 'podium-cell'],
  ], `${scope()} player ranking`);
  for (const row of matching) {
    const tr = el('tr');
    const name = el('td', undefined, 'name');
    const player = playerLink(row.player_key);
    player.id = `ranking-player-${row.player_key}`;
    name.append(player, el('span', `${row.boards_played}/${ranking.board_count} ${state.direction === 'combined' ? 'boards' : 'tracks'}`, 'mobile-meta'));
    const score = el('td', points(row.points), 'points');
    score.title = `${row.points} points (unrounded)`;
    tr.append(el('td', row.rank, `rank ${row.rank <= 3 ? 'rank-top' : ''}`), name, score,
      el('td', `${row.boards_played} / ${ranking.board_count}`, 'secondary'), medalCell([row.world_records, row.second_places, row.third_places]));
    body.append(tr);
  }
  if (!matching.length) {
    const tr = el('tr');
    const cell = el('td', query ? 'No players match your search.' : 'No runs in this ranking yet.', 'empty');
    cell.colSpan = 5;
    tr.append(cell);
    body.append(tr);
  }
  status.textContent = `${matching.length} ${matching.length === 1 ? 'player' : 'players'}. ${scope()}.`;
}

function medals(counts) {
  const group = el('span', undefined, 'medals');
  counts.forEach((count, i) => {
    const badge = el('span', undefined, `medal medal-${i + 1}`);
    const label = `${count || 0} ${['first places (WRs)', 'second places', 'third places'][i]}`;
    badge.title = label;
    badge.setAttribute('aria-label', label);
    const icon = el('span', ['🥇', '🥈', '🥉'][i]);
    icon.setAttribute('aria-hidden', 'true');
    badge.append(icon, String(count || 0));
    group.append(badge);
  });
  return group;
}

function medalCell(counts) {
  const cell = el('td', undefined, 'podium-cell');
  cell.append(medals(counts));
  return cell;
}

function renderTracks() {
  heading('Tracks', 'Every track, every podium. Explore the fastest verified runs, then expand the full ranking.');
  controls();
  main.append(el('p', 'Bonus tracks always included · One personal best per player · Glitched and glitchless runs ranked together · Ties share places', 'note'));
  for (const track of [...data.tracks].sort((a, b) => a.name.localeCompare(b.name, 'en'))) {
    const runs = trackRuns(data, track.slug, state.direction);
    const section = el('section', undefined, 'track-card');
    const title = el('h2', track.name);
    if (track.bonus) title.append(el('span', 'Bonus', 'tag'));
    section.append(title);
    if (!runs.length) {
      section.append(el('p', 'No verified runs in this direction yet.', 'note'));
      main.append(section);
      continue;
    }
    const headers = [['Rank', 'rank'], ['Player', 'name']];
    if (track.has_glitches) headers.push(['Glitches', '']);
    headers.push(['Time', ''], ['+%', ''], ['Points', '']);
    const body = table(section, headers, `${track.name} · ${titleCase(state.direction)} ranking`, 'track-ranking');
    const extra = [];
    for (const run of runs) {
      const row = el('tr');
      const rank = el('td', run.board_rank <= 3 ? ['🥇', '🥈', '🥉'][run.board_rank - 1] : run.board_rank, 'rank');
      rank.setAttribute('aria-label', `Rank ${run.board_rank}`);
      const name = el('td', undefined, 'name');
      name.append(playerLink(run.player_key, 'tracks'));
      const time = el('td', undefined, 'run-time');
      time.append(externalLink(raceTime(run.time_us), run.source_url));
      row.append(rank, name);
      if (track.has_glitches) row.append(el('td', run.glitches || 'Unknown'));
      const gap = el('td', run.gap_percent > 0 && run.gap_percent < .001
        ? '<0.001%' : `${number(run.gap_percent)}%`, 'run-gap');
      gap.title = 'Percentage slower than the world record';
      const score = el('td', points(run.points), 'points');
      score.title = `${run.points} points (unrounded)`;
      row.append(time, gap, score);
      if (run.board_rank > 3) { row.hidden = true; extra.push(row); }
      body.append(row);
    }
    if (extra.length) {
      const button = el('button', `Show full ranking · ${runs.length} players`, 'expand-ranking');
      button.type = 'button';
      button.id = `expand-${track.slug}`;
      body.id = `track-ranking-${track.slug}`;
      button.setAttribute('aria-controls', body.id);
      button.setAttribute('aria-expanded', 'false');
      button.addEventListener('click', () => {
        const opening = button.getAttribute('aria-expanded') !== 'true';
        for (const row of extra) row.hidden = !opening;
        button.setAttribute('aria-expanded', String(opening));
        button.textContent = opening ? 'Show top 3' : `Show full ranking · ${runs.length} players`;
      });
      section.append(button);
    }
    main.append(section);
  }
  status.textContent = `${data.tracks.length} tracks. ${titleCase(state.direction)}. Bonus tracks included.`;
}

function renderHall() {
  heading('STK Hall of Fame', 'World-record achievement and online racing qualification, ranked by total lifetime WR-hours.');
  const intro = el('p', undefined, 'member-note');
  intro.append('Forward · 21 official tracks · 30-day reigns on at least 3 tracks · Confirmed online top 3. ',
    link('See the qualification rules', {...state, view: 'rules'}));
  main.append(intro);
  const caption = el('div', undefined, 'caption');
  caption.append(el('span', `${data.hall_of_fame.members.length} members`), el('span', `WR-hours as of ${dateTime(data.hall_of_fame.as_of)}`));
  main.append(caption);
  const body = table(main, [['Rank', 'rank'], ['Player', 'name'], ['Total WR-hours', ''], ['WR era', ''], ['Qualifying tracks', 'secondary']], 'Hall of Fame, ranked by total lifetime WR-hours', 'hall-table');
  const dates = data.hall_of_fame.members.map(row => Date.parse(row.median_wr_date)).filter(Number.isFinite);
  const oldest = Math.min(...dates), newest = Math.max(...dates);
  for (const row of data.hall_of_fame.members) {
    const name = el('td', undefined, 'name');
    const player = playerLink(row.player_key, 'hall');
    player.id = `hall-player-${row.player_key}`;
    name.append(player, el('span', `${row.qualifying_track_count} qualifying tracks`, 'mobile-meta'));
    const tr = el('tr');
    const hours = el('td', number(row.total_wr_hours, 0), 'points');
    hours.title = 'Rounded to whole hours; ranking uses full precision.';
    const era = el('td');
    if (row.median_wr_date) {
      const date = new Date(row.median_wr_date);
      const badge = el('time', String(date.getUTCFullYear()), 'era');
      badge.dateTime = row.median_wr_date;
      badge.title = `${String(date.getUTCMonth() + 1).padStart(2, '0')}/${date.getUTCFullYear()} · Median date of accrued WR-hours`;
      badge.tabIndex = 0;
      badge.setAttribute('aria-label', badge.title);
      const fraction = newest === oldest ? .5 : (date.getTime() - oldest) / (newest - oldest);
      badge.style.setProperty('--era-color', `hsl(${220 + 140 * fraction} 85% 77%)`);
      era.append(badge);
    } else era.textContent = '—';
    tr.append(el('td', row.rank, `rank ${row.rank <= 3 ? 'rank-top' : ''}`), name, hours, era,
      el('td', `${row.qualifying_track_count} / 21`, 'secondary'));
    body.append(tr);
  }
  if (!data.hall_of_fame.members.length) {
    const tr = el('tr');
    const cell = el('td', 'No players meet both qualification requirements yet.', 'empty');
    cell.colSpan = 5;
    tr.append(cell);
    body.append(tr);
  }
  main.append(el('p', 'All forward WR reigns on official tracks contribute hours, including reigns shorter than 30 days. Hours on different tracks add together. Qualifying tracks determine admission, not position. WR era is the date when half of a player’s lifetime WR-hours had accrued: blue is earlier, purple to red is more recent. Hover or focus a year for the month.', 'note'));
}

function renderProfile() {
  const player = data.players[state.player];
  const backState = {...state, view: state.from};
  const back = link(`← Back to ${state.from === 'hall' ? 'Hall of Fame' : state.from === 'tracks' ? 'Tracks' : 'ranking'}`, backState, 'back');
  const returnHash = history.state?.returnHash;
  if (returnHash && parseRoute(returnHash).view === state.from) back.href = returnHash;
  back.dataset.back = 'true';
  main.append(back);
  if (!player) {
    heading('Player not found', 'This player is not in the current snapshot. Return to the ranking to find a player.');
    return;
  }
  heading(player.name, 'Points by track and world-record history.');
  controls();
  const ranking = data.rankings[variant(state)];
  const entry = ranking.entries.find(row => row.player_key === state.player);
  const performances = profileRows(data, state.player, state).map(row => row.performance).filter(Boolean);
  const summary = el('div', undefined, 'summary');
  for (const [value, label] of [
    [entry ? `#${entry.rank}` : '—', 'Overall rank'], [points(performances.reduce((sum, p) => sum + p.points, 0)), 'Points'],
    [`${performances.length} / ${ranking.board_count}`, state.direction === 'combined' ? 'Boards with a PB' : 'Tracks with a PB'],

  ]) {
    const item = el('div');
    item.append(el('strong', value), el('span', label));
    summary.append(item);
  }
  const podium = el('div');
  podium.append(medals(podiumCounts(performances)), el('span', 'Current track podiums'));
  summary.append(podium);
  main.append(summary);
  const member = data.hall_of_fame.members.find(row => row.player_key === state.player);
  if (member) {
    const note = el('p', undefined, 'member-note');
    note.append(link(`Hall of Fame #${member.rank}`, {...state, view: 'hall'}),
      ` · ${member.qualifying_track_count} qualifying tracks · ${number(member.total_wr_hours, 0)} lifetime WR-hours. Forward, official tracks only.`);
    main.append(note);
  }
  const caption = el('div', undefined, 'caption');
  caption.append(el('span', scope()), externalLink('speedrun.com profile ↗', player.url));
  main.append(caption);
  const body = table(main, [
    ['Track', 'track-cell'], ['PB', ''], ['WR', ''], ['Behind WR (%)', ''], ['Points', ''], ['Total WR days', ''], ['Longest reign (days)', ''],
  ], `${player.name}: ${scope()} points and WR history`, 'profile-table');
  for (const {board, performance: p} of profileRows(data, state.player, state)) {
    const track = tracks.get(board.track);
    const row = el('tr', undefined, 'performance-row');
    const name = el('th', undefined, 'track-cell');
    name.scope = 'row';
    const button = el('button', track.name, 'track-button');
    button.type = 'button';
    const detailId = `detail-${board.track}-${board.direction}`;
    button.id = `toggle-${board.track}-${board.direction}`;
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', detailId);
    button.setAttribute('aria-label', `${track.name}, ${titleCase(board.direction)}: run details and WR reigns`);
    name.append(button);
    if (state.direction === 'combined') name.append(el('span', titleCase(board.direction), 'track-direction'));
    if (track.bonus) name.append(el('span', 'Bonus', 'tag'));
    row.append(name);
    const history = p?.wr_history;
    const cells = [
      ['PB', p ? raceTime(p.time_us) : 'No PB'], ['WR', raceTime(board.wr_time_us)],
      ['Behind WR (%)', p ? (p.gap_percent > 0 && p.gap_percent < .001 ? '<0.001%' : `${number(p.gap_percent)}%`) : '—'],
      ['Points', points(p?.points || 0)], ['Total WR days', days(p ? history.total_days : 0)],
      ['Longest reign (days)', days(p ? history.longest_reign_days : 0)],
    ];
    for (const [label, value] of cells) {
      const cell = el('td', value, label === 'Points' ? 'points' : '');
      cell.dataset.label = label;
      if (label === 'PB' && p?.is_wr) { cell.classList.add('record'); cell.title = 'Current world record'; }
      if (label === 'Points') cell.title = `${p?.points || 0} points (unrounded)`;
      if (value === '—' && history?.dates_complete === false) cell.title = 'Incomplete verification dates; WR duration is unknown.';
      row.append(cell);
    }
    const detailRow = el('tr', undefined, 'track-detail');
    detailRow.id = detailId;
    detailRow.hidden = true;
    const cell = el('td');
    cell.colSpan = 7;
    detailRow.append(cell);
    button.addEventListener('click', () => {
      const opening = detailRow.hidden;
      if (opening && !cell.childNodes.length) renderTrackDetails(cell, board, p);
      detailRow.hidden = !opening;
      button.setAttribute('aria-expanded', String(opening));
    });
    body.append(row, detailRow);
  }
  main.append(el('p', `Expand a track for source runs, dates, and each WR reign. WR days include every reign, even short ones. Ongoing reigns are counted through ${dateTime(data.generated_at)}.`, 'note'));
}

function renderTrackDetails(container, board, p) {
  const stats = el('dl', undefined, 'detail-summary');
  const stat = (label, value) => {
    const group = el('div');
    const dd = el('dd');
    dd.append(value);
    group.append(el('dt', label), dd);
    stats.append(group);
  };
  if (p) {
    stat('Board rank', `#${p.board_rank} of ${board.player_count}`);
    stat('Time behind WR', `+${number(p.gap_us / 1_000_000, 3)} seconds`);
    stat('Run played', dateTime(p.played_on, false));
    stat('Run verified', dateTime(p.verified_at));
    stat('Personal best', externalLink('View submitted run ↗', p.source_url));
  } else stat('Personal best', 'No submitted PB on this board. 0 points.');
  const holders = el('span');
  board.wr_holders.forEach((key, i) => {
    if (i) holders.append(', ');
    holders.append(playerLink(key, state.from));
  });
  stat('Current WR holders', holders);
  container.append(stats, el('h3', 'WR reigns'));
  if (p?.wr_history.dates_complete === false) {
    container.append(el('p', 'Verification dates are incomplete on this board. WR durations cannot be calculated reliably.'));
    return;
  }
  const history = p?.wr_history;
  if (!history?.reigns.length) {
    container.append(el('p', 'No WR reigns in the available history.'));
    return;
  }
  if (history.current_reign_days > 0) container.append(el('p', `Current reign: ${days(history.current_reign_days)} days.`, 'record'));
  const list = el('ol', undefined, 'reigns');
  for (const reign of history.reigns) {
    const item = el('li');
    item.append(el('span', `${dateTime(reign.started_at)} → ${reign.ended_at ? dateTime(reign.ended_at) : 'ongoing'}`, 'reign-dates'),
      el('strong', `${days(reign.days)} days`));
    const sources = el('span', undefined, 'reign-links');
    reign.records.forEach((run, i) => {
      if (i) sources.append(' · ');
      sources.append(externalLink(`Record ${i + 1} ↗`, run.source_url));
    });
    item.append(sources);
    list.append(item);
  }
  container.append(list);
}

function renderRules() {
  heading('How it works', 'Player ranking and Hall of Fame admission criteria');
  const rules = el('div', undefined, 'rules');
  // This template contains only authored text. All source data uses textContent.
  rules.innerHTML = `
    <section class="rule-section" aria-labelledby="speedrun-rules">
      <h2 id="speedrun-rules">Player ranking</h2>
      <p>The fastest verified 1.x run on each track and direction earns points based on its distance from the current world record. The points across the selected tracks are added up to get the total score.</p>
      <p>The distance <var>d</var> between a personal best (PB) time and the world record (WR) time is calculated as the percentage slower than the WR:</p>
      <p class="formula">d = 100 × (PB − WR) / WR</p>
      <p>The points are then calculated as an exponential function of <var>d</var>:</p>
      <p class="formula">Points = 10 × 10<sup>−d/3</sup></p>
      <p>The function is calibrated such that the WR gives 10 points, while a run 3% slower than the WR gives 1 point.</p>
      <div class="example-table table-wrap"><table>
        <caption class="sr-only">Points at different distances behind the world record</caption>
        <thead><tr><th scope="col">Behind WR</th><th scope="col">Points</th></tr></thead>
        <tbody><tr><td>0% · World record</td><td>10</td></tr><tr><td>0.5%</td><td>6.813</td></tr><tr><td>1%</td><td>4.642</td></tr><tr><td>3%</td><td>1</td></tr><tr><td>5%</td><td>0.2154</td></tr><tr><td>10%</td><td>0.0046</td></tr></tbody>
      </table></div>
      <p>The exponential function rewards runs close to the WR. Under the speedrun.com submission guidelines used for this ranking, runs within 2% require the strongest evidence. Runs more than 10% behind can be accepted without evidence unless they are top 3, so the scoring was designed such that the contribution of these runs is negligible.</p>
      <p>Players with fewer than 0.01 total points are omitted from the player ranking. Their runs remain visible in Tracks. Gold, silver, and bronze count current first, second, and third places on the selected boards; ties share competition ranks (1, 1, 3).</p>
      <ul>
        <li><strong>Run submission.</strong> Submit runs via <a href="https://www.speedrun.com/stk">speedrun.com/stk</a>. This site uses verified runs from speedrun.com and does not independently verify any runs. New runs are incorporated into the ranking within seven days after verification.</li>
        <li><strong>Track selection.</strong> The ranking is based on the 21 official tracks in both forward and reverse directions. The two bonus tracks, Freytra Peaks and Drainage Dash, can be added using the toggle on the ranking site. Forward and reverse rankings can be displayed separately or combined.</li>
        <li><strong>Missing PBs.</strong> The ranking is designed to encourage speedrunners to submit their PBs even if they are not a WR or a top 3 run. If no PB is submitted for a track, no points are awarded for that track.</li>
        <li><strong>WR updates.</strong> Since the WR is the benchmark, a newly submitted WR will lower the points of all runs behind it.</li>
        <li><strong>Glitches.</strong> If a track has a separate category for glitchless runs (variable: Glitches on speedrun.com), those runs are ranked together with glitched runs. If a player has both a glitched and a glitchless run, only the faster run counts.</li>
      </ul>
    </section>
    <section class="rule-section" aria-labelledby="hall-rules">
      <h2 id="hall-rules">STK Hall of Fame</h2>
      <p>Hall of Fame membership recognises outstanding speedrun achievements and online ranked racing ability. Two requirements must be met for admission to the Hall of Fame:</p>
      <ol>
        <li><strong>Hold a WR for at least 30 continuous days on each of three different tracks.</strong> Only the forward direction on the 21 official tracks counts. Bonus tracks are excluded. Two separate 15-day reigns do not qualify. Multiple qualifying reigns on the same track still count as one qualifying track. Losing a record later does not undo an earlier qualifying reign. WR reigns can be from any time and do not need to overlap.</li>
        <li><strong>Reach the top 3 of the STK online ranking after its first three months.</strong> The site tracks the <a href="https://online.supertuxkart.net/rankings.php">STK ranking</a>, but some past top 3 players may have been missed. If you believe you fulfilled both criteria but are not listed in the Hall of Fame, please send a DM to Haenschen on speedrun.com.</li>
      </ol>
      <p><strong>Members are ranked by total lifetime WR-hours.</strong> Every forward WR reign on every official track contributes, including reigns shorter than 30 days and reigns before Hall of Fame admission. The qualifying-track count determines admission, not the order of the table. Equal exact hour totals share a rank.</p>
      <p>Once admitted to the Hall of Fame, membership is permanent.</p>
    </section>
    <section class="rule-section" aria-labelledby="history-rules">
      <h2 id="history-rules">Reading WR history</h2>
      <p>WR reigns start and end at the runs’ <strong>verification timestamps</strong>, rather than the dates they were played. Improving your own record continues the same reign. Losing and later reclaiming the record starts a new one. Tied record holders each receive their full reign time.</p>
      <p><strong>Total WR days</strong> adds all reigns on that track and direction. <strong>Longest reign</strong> is the longest uninterrupted reign. Player profiles include short reigns in both figures, without applying the 30-day Hall of Fame qualification threshold. Ongoing reigns are counted up to the snapshot time below.</p>
    </section>`;
  const section = el('section', undefined, 'rule-section');
  section.append(el('h2', 'Data updates'),
    el('p', `Snapshot and WR-hour cutoff: ${dateTime(data.generated_at)}. The source-check times below show when each track was last synced.`),
    el('p', 'This static website displays a published snapshot, updated every Sunday at 2:00 AM Eastern Time.'));
  const details = el('details');
  details.append(el('summary', 'Source-check times by track'));
  const body = table(details, [['Track', ''], ['Last checked (UTC)', '']], 'Last successful source sync by track');
  for (const track of data.tracks) {
    const row = el('tr');
    row.append(el('td', track.name), el('td', dateTime(track.last_synced_at)));
    body.append(row);
  }
  section.append(details);
  rules.append(section);
  main.append(rules);
}

function updateNav() {
  for (const a of document.querySelectorAll('.segments a[data-direction]')) {
    a.href = routeHash({...state, direction: a.dataset.direction});
  }
  for (const a of document.querySelectorAll('nav a[data-view]')) {
    a.href = routeHash({...state, view: a.dataset.view});
    const active = state.view === 'player' ? state.from : state.view;
    if (a.dataset.view === active) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
}

function render({restore = false, focusId = null} = {}) {
  if (!data) return;
  state = parseRoute(location.hash);
  renderedHash = location.hash;
  main.replaceChildren();
  updateNav();
  ({ranking: renderRanking, tracks: renderTracks, hall: renderHall, player: renderProfile, rules: renderRules}[state.view])();
  if (restore) {
    const saved = history.state;
    if (saved?.focusId) document.getElementById(saved.focusId)?.focus({preventScroll: true});
    window.scrollTo(0, saved?.scrollY || 0);
  } else {
    (document.getElementById(focusId) || main.querySelector('h1')).focus({preventScroll: true});
    window.scrollTo(0, 0);
  }
}

function navigate(hash, focusId = null) {
  if (hash === location.hash) return;
  history.replaceState({...history.state, scrollY: window.scrollY, focusId: document.activeElement?.id}, '', location.href);
  history.pushState({returnHash: location.hash || '#ranking'}, '', hash);
  render({focusId});
}

document.addEventListener('click', event => {
  if (event.target.closest('a.skip-link')) {
    event.preventDefault();
    main.focus();
    main.scrollIntoView();
    return;
  }
  const a = event.target.closest('a.route-link');
  if (!a || !data || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  if (a.dataset.back && history.state?.returnHash === a.hash) history.back();
  else navigate(a.hash);
});
window.addEventListener('popstate', () => render({restore: true}));
window.addEventListener('hashchange', () => {
  if (location.hash !== renderedHash) render();
});

async function load() {
  try {
    const response = await fetch('./data/rankings.json', {cache: 'no-cache'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (payload.schema_version !== 1 || !payload.players || !payload.hall_of_fame?.members ||
        !directions.every(direction => [false, true].every(bonus => payload.rankings?.[variant({direction, bonus})]))) {
      throw new Error('Unsupported ranking snapshot');
    }
    data = payload;
    tracks = new Map(data.tracks.map(track => [track.slug, track]));
    const times = data.tracks.map(track => track.last_synced_at).filter(Boolean).sort();
    const firstCheck = dateTime(times[0]);
    const lastCheck = dateTime(times.at(-1));
    document.querySelector('#freshness').textContent = times.length ?
      `Source checked ${firstCheck}${firstCheck === lastCheck ? '' : ' – ' + lastCheck}` : 'Source-check time unknown';
    render({restore: true});
    document.querySelector('#loading')?.remove();
  } catch (error) {
    data = null;
    main.replaceChildren();
    heading('Rankings could not be loaded', 'Please try again. If the problem persists, the published data may need to be refreshed.');
    const retry = el('button', 'Try again');
    retry.type = 'button';
    retry.addEventListener('click', () => { retry.disabled = true; retry.textContent = 'Loading…'; load(); });
    main.append(retry);
    status.textContent = 'Rankings could not be loaded.';
    console.error('Could not load rankings:', error);
  }
}

load();
