import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/dark',
  center: [10, 25],
  zoom: 1.6,
  attributionControl: { compact: true },
});

const status = document.getElementById('hud-status');

map.on('load', async () => {
  const resp = await fetch('/layers/events.geojson?hours=168&min_importance=0.3');
  const events = await resp.json();

  map.addSource('events', { type: 'geojson', data: events });

  map.addLayer({
    id: 'events',
    type: 'circle',
    source: 'events',
    paint: {
      // radius and color scale with importance (mag/8 for quakes)
      'circle-radius': [
        'interpolate', ['linear'], ['get', 'importance'],
        0.3, 2,
        0.6, 5,
        1.0, 14,
      ],
      'circle-color': [
        'interpolate', ['linear'], ['get', 'importance'],
        0.3, '#4a5a6a',
        0.5, '#c9a14b',
        0.75, '#d96f32',
        1.0, '#e0342f',
      ],
      'circle-opacity': 0.75,
      'circle-stroke-width': 0.5,
      'circle-stroke-color': 'rgba(255,255,255,0.25)',
    },
  });

  map.on('click', 'events', (e) => {
    const f = e.features[0];
    const p = f.properties;
    const when = new Date(p.occurred_at).toUTCString().replace(':00 GMT', ' UTC');
    new maplibregl.Popup()
      .setLngLat(f.geometry.coordinates)
      .setHTML(
        `<span class="popup-mag">M ${p.magnitude}</span> ${p.place ?? ''}<br>` +
        `${when}<br>` +
        `<a href="${p.url}" target="_blank" rel="noopener">USGS detail</a>`
      )
      .addTo(map);
  });

  map.on('mouseenter', 'events', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'events', () => { map.getCanvas().style.cursor = ''; });

  status.textContent = `${events.features.length} events, past 7 days`;
});
