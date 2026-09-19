// Pure view helpers. Scores and ranks always come from the Python export.
export const directions = ['forward', 'reverse', 'combined'];
export const titleCase = value => value.charAt(0).toUpperCase() + value.slice(1);

export function parseRoute(hash) {
  const [page, query = ''] = hash.replace(/^#/, '').split('?');
  const params = new URLSearchParams(query);
  return {
    view: ['ranking', 'hall', 'rules', 'player'].includes(page) ? page : 'ranking',
    direction: directions.includes(params.get('direction')) ? params.get('direction') : 'forward',
    bonus: params.get('bonus') === '1',
    player: params.get('player') || '',
    from: params.get('from') === 'hall' ? 'hall' : 'ranking',
    search: params.get('q') || '',
  };
}

export function routeHash(state) {
  const params = new URLSearchParams();
  if (state.direction !== 'forward') params.set('direction', state.direction);
  if (state.bonus) params.set('bonus', '1');
  if (state.search) params.set('q', state.search);
  if (state.view === 'player') {
    params.set('player', state.player);
    if (state.from === 'hall') params.set('from', 'hall');
  }
  return `#${state.view}${params.size ? '?' + params.toString() : ''}`;
}

export const variant = state => `${state.direction}-${state.bonus ? 'with' : 'without'}-bonus`;

export function selectedBoards(data, state) {
  const tracks = new Map(data.tracks.map(track => [track.slug, track]));
  return data.boards.filter(board =>
    (state.bonus || !tracks.get(board.track).bonus) &&
    (state.direction === 'combined' || board.direction === state.direction)
  ).sort((a, b) => tracks.get(a.track).name.localeCompare(tracks.get(b.track).name, 'en') ||
    a.direction.localeCompare(b.direction, 'en'));
}

export function profileRows(data, playerKey, state) {
  const performances = data.players[playerKey].performances;
  return selectedBoards(data, state).map(board => ({
    board,
    performance: performances.find(p => p.track === board.track && p.direction === board.direction) || null,
  }));
}

export const number = (value, digits = 3) => value == null ? '—' : value.toLocaleString('en-US', {
  minimumFractionDigits: digits, maximumFractionDigits: digits,
});
export const points = value => value > 0 && value < .001 ? '<0.001' : number(value);
export const days = value => value > 0 && value < .1 ? '<0.1' : number(value, 1);

export function raceTime(us) {
  if (us == null) return '—';
  // Preserve sub-millisecond precision if a source ever supplies it.
  const seconds = Math.floor(us / 1_000_000);
  const fraction = String(us % 1_000_000).padStart(6, '0').replace(/0{1,3}$/, '');
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}.${fraction}`;
}

export function dateTime(value, includeTime = true) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown';
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
    ...(includeTime ? {hour: '2-digit', minute: '2-digit', timeZoneName: 'short'} : {}),
  }).format(date);
}

export function safeExternalURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.href : null;
  } catch { return null; }
}
