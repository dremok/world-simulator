import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

const CONFLICT = ['fight', 'assault', 'coerce', 'threaten', 'force_posture', 'mass_violence', 'reduce_relations'];
const COOPERATION = ['diplomatic_cooperation', 'material_cooperation', 'provide_aid', 'intent_to_cooperate', 'yield', 'consult', 'appeal'];

const TYPE_COLOR = [
  'case',
  ['==', ['get', 'event_type'], 'earthquake'], '#e8b04b',
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

  map.on('click', 'events', (e) => {
    const p = e.features[0].properties;
    const when = new Date(p.occurred_at).toUTCString().replace(':00 GMT', ' UTC');
    const head = p.event_type === 'earthquake'
      ? `<span class="popup-mag">M ${p.magnitude}</span> ${p.place ?? ''}`
      : `<span class="popup-mag">${p.event_type.replace(/_/g, ' ')}</span> ${[p.actor1, p.actor2].filter(Boolean).join(' &rarr; ') || ''}`;
    new maplibregl.Popup()
      .setLngLat(e.features[0].geometry.coordinates)
      .setHTML(`${head}<br>${when}<br><a href="${p.url}" target="_blank" rel="noopener">source</a>`)
      .addTo(map);
  });

  map.on('click', 'country-fill', (e) => {
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
});
