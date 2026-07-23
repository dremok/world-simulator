import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

const CONFLICT = ['fight', 'assault', 'coerce', 'threaten', 'force_posture', 'mass_violence', 'reduce_relations'];
const COOPERATION = ['diplomatic_cooperation', 'material_cooperation', 'provide_aid', 'intent_to_cooperate', 'yield', 'consult', 'appeal'];

const TYPE_COLOR = [
  'case',
  ['in', ['get', 'event_type'], ['literal', CONFLICT]], '#d64541',
  ['in', ['get', 'event_type'], ['literal', COOPERATION]], '#3e8e8c',
  ['==', ['get', 'event_type'], 'protest'], '#e07b39',
  '#6a7683', // statements, appeals, everything else
];

const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/dark',
  center: [10, 25],
  zoom: 1.6,
  attributionControl: { compact: true },
});

const status = document.getElementById('hud-status');
window.__map = map; // for browser test harness

function toneColor(stats) {
  // Negative tone leans red, positive leans teal; intensity from volume.
  const alpha = Math.min(0.55, 0.08 + 0.09 * Math.log1p(stats.count));
  const tone = stats.avg_tone ?? 0;
  return tone < -1.5 ? `rgba(214, 69, 65, ${alpha})`
    : tone > 1.5 ? `rgba(62, 142, 140, ${alpha})`
    : `rgba(138, 148, 158, ${alpha})`;
}

map.on('load', async () => {
  const [eventsResp, statsResp, countriesResp] = await Promise.all([
    fetch('/layers/events.geojson?hours=48&min_importance=0.35'),
    fetch('/layers/country_stats.json?hours=24'),
    fetch('/countries.geojson'),
  ]);
  const events = await eventsResp.json();
  const stats = await statsResp.json();
  const countries = await countriesResp.json();

  // Choropleth: color countries by 24h news volume and tone
  const fillColor = ['case'];
  for (const f of countries.features) {
    const s = f.properties.iso && stats[f.properties.iso];
    if (s) {
      fillColor.push(['==', ['get', 'iso'], f.properties.iso], toneColor(s));
    }
  }
  fillColor.push('rgba(0,0,0,0)');

  map.addSource('countries', { type: 'geojson', data: countries });
  const firstSymbolLayer = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;
  map.addLayer({
    id: 'country-fill',
    type: 'fill',
    source: 'countries',
    paint: { 'fill-color': fillColor.length > 2 ? fillColor : 'rgba(0,0,0,0)' },
  }, firstSymbolLayer);

  map.addSource('events', { type: 'geojson', data: events });
  map.addLayer({
    id: 'events',
    type: 'circle',
    source: 'events',
    paint: {
      'circle-radius': [
        'interpolate', ['linear'], ['get', 'importance'],
        0.35, 2,
        0.6, 5,
        1.0, 12,
      ],
      'circle-color': TYPE_COLOR,
      'circle-opacity': 0.8,
      'circle-stroke-width': 0.5,
      'circle-stroke-color': 'rgba(255,255,255,0.25)',
    },
  });

  // News URLs usually carry the headline as a slug; far more honest than
  // GDELT's machine-coded event type.
  function slugHeadline(url) {
    try {
      const seg = new URL(url).pathname.split('/').filter(Boolean).pop() ?? '';
      const words = seg
        .replace(/\.(html?|php|aspx?)$/, '')
        .split('-')
        .filter((w) => !/^\d+$/.test(w) && !/^[a-f0-9]{6,}$/.test(w));
      if (words.length < 3) return null;
      const s = words.join(' ');
      return s.charAt(0).toUpperCase() + s.slice(1);
    } catch {
      return null;
    }
  }

  map.on('click', 'events', (e) => {
    if (window.__relArmed) return;
    const p = e.features[0].properties;
    const when = new Date(p.occurred_at).toUTCString().replace(':00 GMT', ' UTC');
    let body;
    if (p.summary) {
      body = `${p.summary}<br><span class="popup-code">severity ${p.severity ?? '?'} &middot; coded ${p.event_type.replace(/_/g, ' ')}</span>`;
    } else {
      const headline = slugHeadline(p.url);
      const actors = [p.actor1, p.actor2].filter(Boolean).join(' &rarr; ');
      body = headline
        ? `${headline}<br><span class="popup-code">coded ${p.event_type.replace(/_/g, ' ')}${actors ? ' &middot; ' + actors : ''}</span>`
        : `<span class="popup-mag">${p.event_type.replace(/_/g, ' ')}</span> ${actors}`;
    }
    new maplibregl.Popup()
      .setLngLat(e.features[0].geometry.coordinates)
      .setHTML(`${body}<br>${when}<br><a href="${p.url}" target="_blank" rel="noopener">source</a>`)
      .addTo(map);
  });

  map.on('click', 'country-fill', (e) => {
    if (window.__relArmed) return;
    if (map.queryRenderedFeatures(e.point, { layers: ['events'] }).length) return;
    const p = e.features[0].properties;
    const s = p.iso && stats[p.iso];
    if (!s) return;
    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setHTML(`<span class="popup-mag">${p.name}</span><br>${s.count} events, 24h<br>avg tone ${s.avg_tone}`)
      .addTo(map);
  });

  map.on('mouseenter', 'events', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'events', () => { map.getCanvas().style.cursor = ''; });

  status.textContent = `${events.features.length} events, past 48h`;

  // Storyline panel: click a narrative to isolate its events on the map
  const CLASS_COLOR = { conflict: '#d64541', cooperation: '#3e8e8c', protest: '#e07b39' };
  const list = document.getElementById('storyline-list');
  const clearBtn = document.getElementById('storyline-clear');
  let selectedLi = null;

  function clearSelection() {
    map.setFilter('events', null);
    map.setPaintProperty('country-fill', 'fill-opacity', 1);
    selectedLi?.classList.remove('selected');
    selectedLi = null;
    clearBtn.hidden = true;
  }

  const storylines = await (await fetch('/storylines?status=active&limit=25')).json();
  for (const s of storylines) {
    if (s.heat <= 0) continue;
    const li = document.createElement('li');
    const color = CLASS_COLOR[s.verb_class] ?? '#6a7683';
    li.innerHTML =
      `<i class="dot" style="background:${color}"></i>${s.title}` +
      `<div class="storyline-meta">${s.event_count} events &middot; heat ${s.heat}${s.summary ? '' : ' &middot; unnarrated'}</div>` +
      (s.summary ? `<div class="storyline-meta">${s.summary}</div>` : '');
    li.addEventListener('click', async () => {
      if (selectedLi === li) { clearSelection(); return; }
      const detail = await (await fetch(`/storylines/${s.id}`)).json();
      map.setFilter('events', ['in', ['get', 'id'], ['literal', detail.event_ids]]);
      map.setPaintProperty('country-fill', 'fill-opacity', 0.25);
      selectedLi?.classList.remove('selected');
      li.classList.add('selected');
      selectedLi = li;
      clearBtn.hidden = false;
    });
    list.appendChild(li);
  }
  clearBtn.addEventListener('click', clearSelection);

  // ---- Relation mode: click two countries, map becomes their relationship ----
  const relToggle = document.getElementById('relation-toggle');
  const relCard = document.getElementById('relation-card');
  const CLASS_COLORS = { conflict: '#d64541', cooperation: '#3e8e8c', protest: '#e07b39', other: '#6a7683' };
  let relArmed = false;
  let relPick = [];
  Object.defineProperty(window, '__relArmed', { get: () => relArmed, configurable: true });

  const centroids = {};
  for (const f of countries.features) {
    if (!f.properties.iso3) continue;
    let minX = 180, minY = 90, maxX = -180, maxY = -90;
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const poly of polys) for (const [x, y] of poly[0]) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    centroids[f.properties.iso3] = [(minX + maxX) / 2, (minY + maxY) / 2];
  }

  function arcLine(from, to, bend) {
    const mx = (from[0] + to[0]) / 2, my = (from[1] + to[1]) / 2;
    const dx = to[0] - from[0], dy = to[1] - from[1];
    const len = Math.hypot(dx, dy) || 1;
    const cx = mx - (dy / len) * bend, cy = my + (dx / len) * bend;
    const pts = [];
    for (let t = 0; t <= 1.001; t += 0.05) {
      pts.push([
        (1 - t) ** 2 * from[0] + 2 * (1 - t) * t * cx + t ** 2 * to[0],
        (1 - t) ** 2 * from[1] + 2 * (1 - t) * t * cy + t ** 2 * to[1],
      ]);
    }
    return pts;
  }

  function exitRelation() {
    relArmed = false;
    relPick = [];
    relToggle.classList.remove('armed');
    relCard.hidden = true;
    for (const id of ['relation-arcs', 'relation-events']) {
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
    }
    map.setPaintProperty('events', 'circle-opacity', 0.8);
    map.setPaintProperty('country-fill', 'fill-opacity', 1);
  }

  relToggle.addEventListener('click', () => {
    if (relArmed || !relCard.hidden) { exitRelation(); return; }
    relArmed = true;
    relToggle.classList.add('armed');
    relCard.hidden = false;
    relCard.innerHTML = '<span class="rel-title">relation mode</span><br>click two countries';
  });

  async function showRelation(a, b) {
    const rel = await (await fetch(`/relation?a=${a}&b=${b}&hours=168`)).json();
    map.setPaintProperty('events', 'circle-opacity', 0.06);
    map.setPaintProperty('country-fill', 'fill-opacity', 0.15);

    const arcFeatures = Object.entries(rel.verb_mix).map(([cls, n], i) => ({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: arcLine(centroids[a], centroids[b], 6 + i * 5) },
      properties: { verb_class: cls, count: n },
    }));
    map.addSource('relation-arcs', { type: 'geojson', data: { type: 'FeatureCollection', features: arcFeatures } });
    map.addLayer({
      id: 'relation-arcs', type: 'line', source: 'relation-arcs',
      paint: {
        'line-color': ['match', ['get', 'verb_class'],
          'conflict', CLASS_COLORS.conflict, 'cooperation', CLASS_COLORS.cooperation,
          'protest', CLASS_COLORS.protest, CLASS_COLORS.other],
        'line-width': ['interpolate', ['linear'], ['get', 'count'], 1, 1.5, 30, 7],
        'line-opacity': 0.85,
      },
    });
    map.addSource('relation-events', { type: 'geojson', data: rel.events });
    map.addLayer({
      id: 'relation-events', type: 'circle', source: 'relation-events',
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['get', 'importance'], 0.25, 3, 1.0, 11],
        'circle-color': ['match', ['get', 'verb_class'],
          'conflict', CLASS_COLORS.conflict, 'cooperation', CLASS_COLORS.cooperation,
          'protest', CLASS_COLORS.protest, CLASS_COLORS.other],
        'circle-stroke-width': 1,
        'circle-stroke-color': 'rgba(255,255,255,0.4)',
      },
    });
    const mix = Object.entries(rel.verb_mix)
      .map(([k, v]) => `<span style="color:${CLASS_COLORS[k]}">${k} ${v}</span>`).join(' · ');
    relCard.innerHTML =
      `<span class="rel-title">${a} &harr; ${b}</span><br>` +
      `${rel.count} events, 7 days<br>${mix}<br>` +
      `avg goldstein ${rel.avg_goldstein ?? 'n/a'} <span style="color:#5a646e">(&minus;10 hostile &rarr; +10 cooperative)</span>` +
      `<div class="rel-clear">&times; exit relation mode</div>`;
    relCard.querySelector('.rel-clear').addEventListener('click', exitRelation);
  }

  map.on('click', 'country-fill', (e) => {
    if (!relArmed) return;
    const iso3 = e.features[0].properties.iso3;
    if (!iso3 || relPick.includes(iso3)) return;
    relPick.push(iso3);
    relCard.innerHTML = `<span class="rel-title">relation mode</span><br>${relPick.join(' &harr; ')}${relPick.length < 2 ? '<br>click a second country' : ''}`;
    if (relPick.length === 2) {
      relArmed = false;
      relToggle.classList.remove('armed');
      showRelation(relPick[0], relPick[1]);
    }
  });

  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') exitRelation(); });
});
