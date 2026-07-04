#!/usr/bin/env node
// Génère frontend/src/assets/france-departements.json à partir du GeoJSON
// simplifié des départements (data/geo/departements-version-simplifiee.geojson,
// source: github.com/gregoiredavid/france-geojson, licence data.gouv.fr).
//
// Projection : équirectangulaire avec correction cos(latitude moyenne) —
// suffisant pour une choroplèthe métropole. Les coordonnées sont projetées
// dans un viewBox 520×500 et arrondies à 1 décimale pour garder l'asset léger.
//
// Usage : node scripts/build-france-map.mjs

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(root, "data/geo/departements-version-simplifiee.geojson");
const OUT = join(root, "frontend/src/assets/france-departements.json");

const WIDTH = 520;
const HEIGHT = 500;
const PADDING = 6;

const geo = JSON.parse(readFileSync(SRC, "utf8"));

// Le GeoJSON simplifié ne contient que la métropole (01-95, 2A/2B).
const features = geo.features;

// 1) Bounding box en coordonnées projetées (x = lon·cos(latMoy), y = -lat).
const latAvg =
  features
    .flatMap((f) => rings(f.geometry))
    .flat()
    .reduce((acc, [, lat]) => acc + lat, 0) /
  features.flatMap((f) => rings(f.geometry)).flat().length;
const kx = Math.cos((latAvg * Math.PI) / 180);

let minX = Infinity,
  maxX = -Infinity,
  minY = Infinity,
  maxY = -Infinity;
for (const f of features) {
  for (const ring of rings(f.geometry)) {
    for (const [lon, lat] of ring) {
      const x = lon * kx;
      const y = -lat;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }
}
const scale = Math.min(
  (WIDTH - 2 * PADDING) / (maxX - minX),
  (HEIGHT - 2 * PADDING) / (maxY - minY),
);
const offX = (WIDTH - (maxX - minX) * scale) / 2;
const offY = (HEIGHT - (maxY - minY) * scale) / 2;

// 2) Chaque département → path SVG "d".
const departements = features
  .map((f) => {
    const d = rings(f.geometry)
      .map(
        (ring) =>
          "M" +
          ring
            .map(([lon, lat]) => {
              const x = (lon * kx - minX) * scale + offX;
              const y = (-lat - minY) * scale + offY;
              return `${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join("L") +
          "Z",
      )
      .join("");
    return { code: f.properties.code, nom: f.properties.nom, d };
  })
  .sort((a, b) => a.code.localeCompare(b.code));

function rings(geometry) {
  if (geometry.type === "Polygon") return geometry.coordinates;
  if (geometry.type === "MultiPolygon") return geometry.coordinates.flat();
  throw new Error(`Géométrie non gérée: ${geometry.type}`);
}

writeFileSync(
  OUT,
  JSON.stringify({ viewBox: `0 0 ${WIDTH} ${HEIGHT}`, departements }),
);
console.log(
  `OK — ${departements.length} départements → ${OUT} (${(
    JSON.stringify({ departements }).length / 1024
  ).toFixed(0)} KB)`,
);
