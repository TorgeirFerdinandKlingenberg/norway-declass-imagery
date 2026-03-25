"""
declass_search.py  –  Declass I / II / III  via USGS M2M API
Oppdager gyldige datasett-navn automatisk ved oppstart.

pip install requests geopandas folium matplotlib pandas shapely numpy
"""

import json
import time
import requests
import pandas as pd
import geopandas as gpd
import folium
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec
from shapely.geometry import shape, mapping, box
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  KONFIGURASJON
# ══════════════════════════════════════════════════════════════════════════════
USERNAME     = "din-user"
APP_TOKEN    = "din-token"   # <- lim inn token fra USGS ERS
GEOJSON_PATH = "map.geojson"

BASE_URL    = "https://m2m.cr.usgs.gov/api/api/json/stable/"
MONTH_START   = "08-01"
MONTH_END     = "10-31"
MAX_RESULTS   = 500

# Sett til en datasetName-streng for aa kun kjoere ett datasett (raskere testing)
# Eksempel: "declassii"   ->  kun Hexagon/KH-9  (46 scener, ~1 min)
# Sett til None for aa kjoere alle tre
TEST_DATASET  = None

# Nokkelbegreper for aa matche mot USGS datasett-svar
DATASET_CONFIGS = [
    {
        "hint":       "Declass I (Corona/KH-1-4)",
        "keywords":   ["corona", "declass1", "declassi", "declass i", "kh-1", "kh-4"],
        "year_start": 1960,
        "year_end":   1972,
        "color_map":  "#3498db",
    },
    {
        "hint":       "Declass II (Hexagon/KH-9)",
        "keywords":   ["hexagon", "declass2", "declassii", "declass ii", "kh-9"],
        "year_start": 1971,
        "year_end":   1986,
        "color_map":  "#2ecc71",
    },
    {
        "hint":       "Declass III (Gambit/KH-7-8)",
        "keywords":   ["gambit", "declass3", "declassiii", "declass iii", "kh-7", "kh-8"],
        "year_start": 1963,
        "year_end":   1984,
        "color_map":  "#e67e22",
    },
]

COLOR_DOWNLOAD = "#2ecc71"
COLOR_ORDER    = "#e67e22"
COLOR_UNKNOWN  = "#95a5a6"


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════════════════════

def login() -> str:
    print("Logger inn ...")
    r = requests.post(
        BASE_URL + "login-token",
        json={"username": USERNAME, "token": APP_TOKEN},
        timeout=30
    )
    r.raise_for_status()
    data = r.json()
    if data.get("errorCode"):
        raise RuntimeError(f"Innlogging feilet: {data.get('errorMessage')}")
    token = data.get("data")
    if not token:
        raise RuntimeError(f"Ingen token i svar: {data}")
    print("Logget inn OK\n")
    return token


def logout(token: str):
    try:
        requests.post(BASE_URL + "logout",
                      headers={"X-Auth-Token": token}, timeout=10)
        print("\nLogget ut")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  DATASET-OPPDAGELSE
# ══════════════════════════════════════════════════════════════════════════════

def get_dataset_name(ds: dict) -> str:
    """Henter datasett-navn robust fra ulike feltnavnvarianter."""
    for key in ("datasetName", "dataset_name", "datasetAlias",
                "datasetId", "collectionName", "datasetFullName"):
        v = ds.get(key)
        if v and isinstance(v, str) and len(v) > 2:
            return v
    return ""


def discover_datasets(token: str) -> list:
    """
    Kaller dataset-search og printer RAW respons saa vi ser
    eksakt hvilke feltnavn og verdier USGS returnerer.
    Matcher deretter mot DATASET_CONFIGS.
    """
    print("=" * 60)
    print("  OPPDAGER TILGJENGELIGE DECLASS-DATASETT")
    print("=" * 60)

    r = requests.post(
        BASE_URL + "dataset-search",
        json={"datasetName": "declass"},
        headers={"X-Auth-Token": token},
        timeout=30
    )
    r.raise_for_status()
    raw = r.json()

    if raw.get("errorCode"):
        raise RuntimeError(
            f"dataset-search feilet: {raw.get('errorMessage')}"
        )

    all_ds = raw.get("data", [])
    print(f"\nAPI returnerte {len(all_ds)} datasett.\n")

    # Skriv ut RAW saa vi ser eksakt struktur
    if all_ds:
        print(f"Feltnavn i svaret: {list(all_ds[0].keys())}\n")

    print("Alle declass-datasett funnet:")
    for i, ds in enumerate(all_ds):
        name    = get_dataset_name(ds)
        abst    = str(ds.get("abstractText", ""))[:60]
        coll    = str(ds.get("collectionName", ""))
        full    = str(ds.get("datasetFullName", ""))
        print(f"  [{i}] name={name!r:30}  coll={coll!r:20}  full={full!r}")

    # Match direkte paa collectionName ("Declass 1", "Declass 2", "Declass 3")
    coll_map = {}
    for ds in all_ds:
        coll = str(ds.get("collectionName", "")).strip().lower()
        for variant in ("declass 1", "declass1", "declass i "):
            if variant in coll:
                coll_map[1] = ds
        for variant in ("declass 2", "declass2", "declass ii "):
            if variant in coll:
                coll_map[2] = ds
        for variant in ("declass 3", "declass3", "declass iii"):
            if variant in coll:
                coll_map[3] = ds

    resolved = []
    for num, cfg in zip([1, 2, 3], DATASET_CONFIGS):
        ds = coll_map.get(num)
        if ds:
            name = get_dataset_name(ds)
            resolved.append({
                **cfg,
                "datasetName": name,
                "label":       cfg["hint"],
            })
            print(f"\n  -> Declass {num}: {cfg['hint']}")
            print(f"     datasetName    = {name!r}")
            print(f"     collectionName = {ds.get('collectionName','')!r}")
        else:
            print(f"\n  ADVARSEL: Ingen match for Declass {num} ('{cfg['hint']}')")

    print()

    if not resolved:
        raise RuntimeError(
            "Ingen declass-datasett matchet. "
            "Sjekk debug-output ovenfor og oppdater 'keywords' i DATASET_CONFIGS."
        )

    return resolved


# ══════════════════════════════════════════════════════════════════════════════
#  SOK OG STATUS
# ══════════════════════════════════════════════════════════════════════════════

def scene_search(token: str, dataset_name: str,
                 spatial_filter: dict, year: int) -> list:
    payload = {
        "datasetName": dataset_name,
        "maxResults":  MAX_RESULTS,
        "startingNumber": 1,
        "includeNullGeometryResults": False,
        "sceneFilter": {
            "spatialFilter": spatial_filter,
            "acquisitionFilter": {
                "start": f"{year}-{MONTH_START}",
                "end":   f"{year}-{MONTH_END}"
            }
        }
    }
    r = requests.post(
        BASE_URL + "scene-search",
        json=payload,
        headers={"X-Auth-Token": token},
        timeout=60
    )
    r.raise_for_status()
    data = r.json()
    if data.get("errorCode"):
        print(f"    {year}: feil – {data.get('errorMessage')}")
        return []
    results = data.get("data", {}).get("results", [])
    total   = data.get("data", {}).get("totalHits", 0)
    if total > 0:
        print(f"    {year}: {total} treff  ({len(results)} returnert)")
    return results


def get_download_options(token: str, dataset_name: str,
                         entity_ids: list) -> dict:
    if not entity_ids:
        return {}
    try:
        r = requests.post(
            BASE_URL + "download-options",
            json={"datasetName": dataset_name, "entityIds": entity_ids},
            headers={"X-Auth-Token": token},
            timeout=60
        )
        if r.status_code == 403:
            print(f"  [i] download-options: 403 for {dataset_name}"
                  " – bruker metadata-fallback")
            return {}
        r.raise_for_status()
        status_map = {}
        for opt in r.json().get("data", []):
            eid = opt.get("entityId", "")
            if opt.get("available") and opt.get("downloadSystem", "") != "dds":
                status_map[eid] = "download"
            else:
                status_map[eid] = "order"
        return status_map
    except requests.HTTPError:
        return {}


def status_from_metadata(scene: dict) -> str:
    opts = scene.get("options", {})
    if isinstance(opts, dict):
        if opts.get("download"):
            return "download"
        if opts.get("order") or opts.get("bulkorder"):
            return "order"
    if scene.get("available") is True:
        return "download"
    if scene.get("available") is False:
        return "order"
    if scene.get("publishDate"):
        return "download"
    return "unknown"


# ══════════════════════════════════════════════════════════════════════════════
#  GEOJSON + FOOTPRINT
# ══════════════════════════════════════════════════════════════════════════════

def load_spatial_filter(path: str) -> dict:
    with open(path) as f:
        gj = json.load(f)
    feat   = gj["features"][0] if gj.get("features") else gj
    geom   = feat.get("geometry", feat)
    coords = geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        coords = [coords[0][0]]
    else:
        coords = [coords[0]]
    return {"filterType": "geojson",
            "geoJson": {"type": "Polygon", "coordinates": coords}}


def aoi_geometry(path: str):
    with open(path) as f:
        gj = json.load(f)
    feat = gj["features"][0] if gj.get("features") else gj
    return shape(feat.get("geometry", feat))


def parse_footprint(scene: dict):
    # spatialCoverage er faktisk polygon – foretrekk denne over bbox
    for key in ("spatialCoverage", "spatialBounds"):
        val = scene.get(key)
        if val:
            try:
                return shape(val)
            except Exception:
                pass
    ll = scene.get("lowerLeftCoordinate")
    ur = scene.get("upperRightCoordinate")
    if ll and ur:
        try:
            return box(ll["longitude"], ll["latitude"],
                       ur["longitude"], ur["latitude"])
        except Exception:
            pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  KART
# ══════════════════════════════════════════════════════════════════════════════

def build_folium_map(gdf: gpd.GeoDataFrame, aoi_geom,
                     datasets: list) -> folium.Map:
    bounds = aoi_geom.bounds
    center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
    m = folium.Map(location=center, zoom_start=5, tiles="CartoDB dark_matter")

    folium.GeoJson(
        mapping(aoi_geom), name="Sokeomrade (AOI)",
        style_function=lambda x: {
            "color": "#f1c40f", "weight": 2.5,
            "fillOpacity": 0.04, "dashArray": "6 4"}
    ).add_to(m)

    for ds in datasets:
        ds_sub = gdf[gdf["datasetName"] == ds["datasetName"]]
        short  = ds["label"].split("(")[0].strip()

        for status, color, slabel in [
            ("download", COLOR_DOWNLOAD, "nedlasting"),
            ("order",    COLOR_ORDER,    "bestilling"),
            ("unknown",  COLOR_UNKNOWN,  "ukjent"),
        ]:
            subset = ds_sub[ds_sub["status"] == status]
            if subset.empty:
                continue

            layer = folium.FeatureGroup(
                name=f"{short} – {slabel} ({len(subset)})")

            for _, row in subset.iterrows():
                if row.geometry is None:
                    continue
                popup_html = (
                    f"<div style='font-family:monospace;font-size:12px;"
                    f"min-width:230px'>"
                    f"<b>{row.get('displayId', row.get('entityId',''))}</b><br>"
                    f"Dataset: <b>{ds['label']}</b><br>"
                    f"Dato: {row.get('acquisitionDate','–')}<br>"
                    f"Status: <span style='color:{color}'><b>{slabel}</b></span><br>"
                    f"Skydekning: {row.get('cloudCover','–')}%"
                    f"</div>"
                )
                folium.GeoJson(
                    mapping(row.geometry),
                    style_function=lambda x, c=color: {
                        "color": c, "weight": 1.2,
                        "fillColor": c, "fillOpacity": 0.20},
                    highlight_function=lambda x, c=color: {
                        "fillOpacity": 0.55, "weight": 2.5},
                    tooltip=folium.Tooltip(
                        f"{row.get('acquisitionDate','–')} | {short} | {slabel}",
                        sticky=False),
                    popup=folium.Popup(popup_html, max_width=300)
                ).add_to(layer)

            layer.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(folium.Element(
        "<div style='position:fixed;top:12px;left:50%;"
        "transform:translateX(-50%);z-index:9999;"
        "background:rgba(0,0,0,0.78);color:white;"
        "padding:8px 20px;border-radius:6px;font-family:monospace;"
        "font-size:13px;letter-spacing:1px;pointer-events:none;'>"
        "Declass I / II / III  –  Aug-Okt  –  Norge"
        "</div>"
    ))
    return m


# ══════════════════════════════════════════════════════════════════════════════
#  STATISTIKK-FIGUR
# ══════════════════════════════════════════════════════════════════════════════

def build_stats_figure(df: pd.DataFrame, datasets: list, output_path: str):
    all_years = sorted(df["year"].unique())
    fig = plt.figure(figsize=(18, 12), facecolor="#0d0d0d")
    gs  = GridSpec(2, 3, figure=fig, hspace=0.50, wspace=0.38)
    ax1 = fig.add_subplot(gs[0, :])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])
    ax4 = fig.add_subplot(gs[1, 2])
    txt  = "#e8e8e8"
    grid = "#2a2a2a"

    # Gruppert soylediagram
    n   = len(datasets)
    w   = 0.22
    x   = np.arange(len(all_years))
    for i, ds in enumerate(datasets):
        counts = df[df["datasetName"] == ds["datasetName"]].groupby("year").size()
        vals   = [counts.get(y, 0) for y in all_years]
        offset = (i - n / 2 + 0.5) * w
        ax1.bar(x + offset, vals, w, color=ds["color_map"],
                label=ds["label"], zorder=3, alpha=0.85)
    ax1.set_facecolor("#111111")
    ax1.set_xticks(x)
    ax1.set_xticklabels(all_years, color=txt, fontsize=8, rotation=45)
    ax1.set_ylabel("Antall scener", color=txt)
    ax1.set_title("Declass I / II / III  –  Aug-Okt per ar",
                  color=txt, fontsize=13, fontweight="bold", pad=10)
    ax1.tick_params(colors=txt)
    ax1.yaxis.grid(True, color=grid, zorder=0)
    ax1.set_axisbelow(True)
    ax1.legend(facecolor="#1a1a1a", labelcolor=txt, framealpha=0.9, fontsize=9)
    for sp in ax1.spines.values(): sp.set_edgecolor("#333")

    # Kakediagram
    dl  = (df["status"] == "download").sum()
    ord_= (df["status"] == "order").sum()
    unk = (df["status"] == "unknown").sum()
    nz  = [(t, l, c) for t, l, c in [
        (dl,  "Nedlasting", COLOR_DOWNLOAD),
        (ord_,"Bestilling", COLOR_ORDER),
        (unk, "Ukjent",     COLOR_UNKNOWN),
    ] if t > 0]
    if nz:
        t_, l_, c_ = zip(*nz)
        _, texts, ats = ax2.pie(
            t_, labels=l_, colors=c_, autopct="%1.0f%%",
            startangle=140, pctdistance=0.78,
            wedgeprops={"edgecolor": "#0d0d0d", "linewidth": 1.5})
        for at in ats: at.set_color("#0d0d0d"); at.set_fontweight("bold")
        for t in texts: t.set_color(txt)
    ax2.set_facecolor("#111111")
    ax2.set_title(f"Status totalt  (n={dl+ord_+unk})",
                  color=txt, fontsize=11, pad=10)

    # Akkumulert
    for ds in datasets:
        counts = df[df["datasetName"] == ds["datasetName"]].groupby("year").size()
        vals   = [counts.get(y, 0) for y in all_years]
        cum    = np.cumsum(vals)
        lbl    = ds["label"].split("(")[0].strip()
        ax3.plot(all_years, cum, color=ds["color_map"],
                 lw=2, marker="o", ms=3, label=lbl)
        ax3.fill_between(all_years, cum, alpha=0.15, color=ds["color_map"])
    ax3.set_facecolor("#111111")
    ax3.set_xticks(all_years)
    ax3.set_xticklabels(all_years, color=txt, fontsize=7, rotation=45)
    ax3.set_ylabel("Akkumulert", color=txt)
    ax3.set_title("Akkumulert per datasett", color=txt, fontsize=11, pad=10)
    ax3.tick_params(colors=txt)
    ax3.yaxis.grid(True, color=grid, zorder=0)
    ax3.legend(facecolor="#1a1a1a", labelcolor=txt, framealpha=0.9, fontsize=8)
    for sp in ax3.spines.values(): sp.set_edgecolor("#333")

    # Per datasett horisontalt
    ds_labels = [ds["label"].split("(")[0].strip() for ds in datasets]
    ds_totals = [len(df[df["datasetName"] == ds["datasetName"]]) for ds in datasets]
    ds_colors = [ds["color_map"] for ds in datasets]
    bars = ax4.barh(range(len(datasets)), ds_totals,
                    color=ds_colors, zorder=3, alpha=0.85)
    for bar, val in zip(bars, ds_totals):
        ax4.text(bar.get_width() + 0.3,
                 bar.get_y() + bar.get_height() / 2,
                 str(val), va="center", color=txt, fontsize=10)
    ax4.set_facecolor("#111111")
    ax4.set_yticks(range(len(datasets)))
    ax4.set_yticklabels(ds_labels, color=txt, fontsize=9)
    ax4.set_xlabel("Totalt antall", color=txt)
    ax4.set_title("Totalt per datasett", color=txt, fontsize=11, pad=10)
    ax4.tick_params(colors=txt)
    ax4.xaxis.grid(True, color=grid, zorder=0)
    ax4.set_axisbelow(True)
    for sp in ax4.spines.values(): sp.set_edgecolor("#333")

    plt.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"Statistikkfigur lagret: {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    token = login()

    try:
        datasets = discover_datasets(token)

        spatial_filter = load_spatial_filter(GEOJSON_PATH)
        aoi_geom       = aoi_geometry(GEOJSON_PATH)
        print(f"AOI lastet fra {GEOJSON_PATH}\n")

        all_records = []

        # Filtrer til TEST_DATASET hvis satt
        if TEST_DATASET:
            datasets = [d for d in datasets if d["datasetName"] == TEST_DATASET]
            if not datasets:
                raise RuntimeError(f"TEST_DATASET={TEST_DATASET!r} ikke funnet blant oppdagede datasett")
            print("TEST-MODUS: kun " + datasets[0]['label'])

        for ds in datasets:
            print(f"{'='*55}")
            print(f"  {ds['label']}")
            print(f"  datasetName: {ds['datasetName']}")
            print(f"  Ar: {ds['year_start']}-{ds['year_end']}  |  Aug-Okt")
            print(f"{'='*55}")

            ds_scenes = []
            for year in range(ds["year_start"], ds["year_end"] + 1):
                scenes = scene_search(token, ds["datasetName"],
                                      spatial_filter, year)
                for s in scenes:
                    s["_year"] = year
                ds_scenes.extend(scenes)
                time.sleep(0.25)

            print(f"  -> {len(ds_scenes)} scener totalt\n")
            if not ds_scenes:
                continue

            print(f"  Henter nedlastingsstatus ...")
            entity_ids = [s["entityId"] for s in ds_scenes]
            status_map = {}
            for i in range(0, len(entity_ids), 50):
                batch = entity_ids[i:i + 50]
                status_map.update(
                    get_download_options(token, ds["datasetName"], batch))
                time.sleep(0.25)

            for s in ds_scenes:
                eid = s.get("entityId", "")

                # acquisitionDate ligger i temporalCoverage
                tc = s.get("temporalCoverage", {})
                acq_date = ""
                if isinstance(tc, dict):
                    acq_date = (tc.get("startDate") or tc.get("endDate") or "")
                    if acq_date:
                        acq_date = str(acq_date)[:10]

                # geometri fra spatialCoverage (faktisk polygon, ikke bbox)
                geom        = parse_footprint(s)
                geom_geojson = mapping(geom) if geom else None

                all_records.append({
                    "entityId":        eid,
                    "displayId":       s.get("displayId", eid),
                    "acquisitionDate": acq_date,
                    "year":            s.get("_year"),
                    "datasetName":     ds["datasetName"],
                    "datasetLabel":    ds["label"],
                    "cloudCover":      s.get("cloudCover"),
                    "status":          status_map.get(eid) or status_from_metadata(s),
                    "geometry":        geom,
                    "geometry_geojson": geom_geojson,
                })

        if not all_records:
            print("Ingen scener funnet.")
            return

        df  = pd.DataFrame(all_records)
        gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
        total = len(df)

        print(f"\n{'='*55}")
        print(f"  SAMLET OVERSIKT  –  Declass I/II/III  Aug-Okt")
        print(f"{'='*55}")
        for ds in datasets:
            n = len(df[df["datasetName"] == ds["datasetName"]])
            print(f"  {ds['label']:<40}: {n:>4} scener")
        print(f"  {'-'*46}")
        print(f"  Totalt                                  : {total:>4}\n")
        for status, label, sym in [
            ("download", "Klar for nedlasting  ", "[DL] "),
            ("order",    "Krever bestilling    ", "[ORD]"),
            ("unknown",  "Ukjent status        ", "[?]  "),
        ]:
            n   = (df["status"] == status).sum()
            pct = 100 * n / total if total else 0
            print(f"  {sym} {label}: {n:>4}  ({pct:.0f}%)")
        print(f"{'='*55}\n")

        print("  Per ar og datasett:")
        pivot = (df.groupby(["year", "datasetName"])
                   .size().unstack(fill_value=0))
        pivot["TOTAL"] = pivot.sum(axis=1)
        print(pivot.to_string())

        with open("declass_resultater.json", "w") as f:
            json.dump(
                [{k: v for k, v in r.items() if k != "geometry"}
                 for r in all_records],   # geometry_geojson (dict) lagres, shapely-obj ikke
                f, indent=2, default=str)
        print("\nRadata lagret: declass_resultater.json")

        (df.groupby(["year", "datasetName", "status"])
           .size().reset_index(name="count")
           .to_csv("declass_statistikk.csv", index=False))
        print("Statistikk lagret: declass_statistikk.csv")

        print("\nBygger kart ...")
        build_folium_map(gdf, aoi_geom, datasets).save("declass_kart.html")
        print("Kart lagret: declass_kart.html")

        print("\nBygger statistikkfigur ...")
        build_stats_figure(df, datasets, "declass_statistikk.png")

    finally:
        logout(token)

    print("\nFerdig! Filer:")
    for fname in ["declass_resultater.json", "declass_statistikk.csv",
                  "declass_kart.html", "declass_statistikk.png"]:
        p = Path(fname)
        size = p.stat().st_size if p.exists() else 0
        print(f"   {fname}  ({size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
