"""StormScope KLOT: NOAA NEXRAD Level II viewer.

Run from this folder:
python -m uvicorn server:app --host 127.0.0.1 --port 8765
"""
import io
import os
import re
import time
import tempfile
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
import pyart
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, FileResponse

ROOT = Path(__file__).parent
STATION = os.environ.get("STORMSCOPE_STATION", "KLOT").upper()
BUCKET = os.environ.get("STORMSCOPE_BUCKET", "unidata-nexrad-level2")
S3 = boto3.client(
    "s3",
    region_name="us-east-1",
    config=Config(
        signature_version=UNSIGNED,
        connect_timeout=10,
        read_timeout=45,
        retries={"max_attempts": 3, "mode": "standard"},
    ),
)

app = FastAPI(title=f"StormScope {STATION} NEXRAD Level II")

state_lock = threading.RLock()
state = {
    "latest_key": None,
    "latest_checked": 0.0,
    "loaded_key": None,
    "radar": None,
    "images": {},
    "loading": False,
    "load_error": None,
}

REF_COLORS = [
    "#164baf", "#237de1", "#20b8c5", "#22a84b", "#78cf35",
    "#d9df29", "#f4b02b", "#ec6426", "#d52d36", "#ad26a0",
    "#ef7bda", "#ffffff",
]
REF_BOUNDS = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65]
VEL_COLORS = [
    "#7a1d35", "#bf3038", "#ec7b4b", "#f2b78d", "#dddddd",
    "#8acdc0", "#39a782", "#176f62", "#144a58",
]
VEL_BOUNDS = [-45, -35, -25, -15, -5, 5, 15, 25, 35, 45]


def key_scan_time(key):
    """Parse KLOTYYYYMMDD_HHMMSS... from an archive object key."""
    name = key.rsplit("/", 1)[-1]
    match = re.search(rf"{STATION}(\d{{8}})_(\d{{6}})", name)
    if not match:
        return None
    try:
        return datetime.strptime(
            match.group(1) + match.group(2), "%Y%m%d%H%M%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def find_latest_key(force=False):
    """Find the newest completed volume without downloading or decoding it."""
    now = time.time()
    with state_lock:
        if not force and state["latest_key"] and now - state["latest_checked"] < 45:
            return state["latest_key"]

    utc_now = datetime.now(timezone.utc)
    days = [
        utc_now.date(),
        (utc_now - timedelta(days=1)).date(),
    ]

    found = []
    for day in days:
        prefix = f"{day:%Y/%m/%d}/{STATION}/"
        paginator = S3.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=BUCKET, Prefix=prefix, PaginationConfig={"PageSize": 1000}
        ):
            for item in page.get("Contents", []):
                key = item["Key"]
                filename = key.rsplit("/", 1)[-1]
                if (
                    filename.startswith(STATION)
                    and not filename.endswith("_MDM")
                    and item.get("Size", 0) > 100_000
                ):
                    found.append(key)
        if found:
            break

    if not found:
        raise RuntimeError(
            f"No completed {STATION} Level II volume found for today or yesterday (UTC)."
        )

    newest_key = max(found, key=lambda k: key_scan_time(k) or datetime.min.replace(tzinfo=timezone.utc))
    with state_lock:
        state["latest_key"] = newest_key
        state["latest_checked"] = time.time()
    return newest_key


def load_volume():
    """Download and decode the latest volume only when an image is requested."""
    key = find_latest_key()
    with state_lock:
        if state["loaded_key"] == key and state["radar"] is not None:
            return state["radar"]
        if state["loading"]:
            raise HTTPException(503, "A radar volume is already downloading/decoding. Retry shortly.")
        state["loading"] = True
        state["load_error"] = None

    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ar2v", delete=False) as tmp:
            path = tmp.name
        S3.download_file(BUCKET, key, path)
        radar = pyart.io.read_nexrad_archive(path)
        with state_lock:
            state["loaded_key"] = key
            state["radar"] = radar
            state["images"] = {}
        return radar
    except Exception as exc:
        with state_lock:
            state["load_error"] = str(exc)
        raise
    finally:
        if path and os.path.exists(path):
            os.unlink(path)
        with state_lock:
            state["loading"] = False


def render(product):
    if product not in ("reflectivity", "velocity"):
        raise HTTPException(400, "Unknown radar product")

    radar = load_volume()
    with state_lock:
        if product in state["images"]:
            return state["images"][product]

    if product not in radar.fields:
        available = ", ".join(radar.fields.keys())
        raise HTTPException(
            404, f"{product} is not present in this volume. Available fields: {available}"
        )

    sweep = None
    for i in range(radar.nsweeps):
        start = int(radar.sweep_start_ray_index["data"][i])
        end = int(radar.sweep_end_ray_index["data"][i]) + 1
        field_data = radar.fields[product]["data"][start:end]
        if not np.ma.getmaskarray(field_data).all():
            sweep = i
            break
    if sweep is None:
        raise HTTPException(404, f"No usable {product} sweep in this volume")

    start = int(radar.sweep_start_ray_index["data"][sweep])
    end = int(radar.sweep_end_ray_index["data"][sweep]) + 1
    values = np.ma.array(radar.fields[product]["data"][start:end], copy=True)
    x = np.asarray(radar.gate_x["data"][start:end]) / 1000.0
    y = np.asarray(radar.gate_y["data"][start:end]) / 1000.0
    values = np.ma.masked_invalid(values)

    if product == "reflectivity":
        values = np.ma.masked_less(values, 5)
        cmap = ListedColormap(REF_COLORS)
        norm = BoundaryNorm(REF_BOUNDS, cmap.N, clip=True)
    else:
        values = np.ma.masked_where(np.abs(values) < 1, values)
        cmap = ListedColormap(VEL_COLORS)
        norm = BoundaryNorm(VEL_BOUNDS, cmap.N, clip=True)
    cmap.set_bad((0, 0, 0, 0))

    fig = plt.figure(figsize=(8, 8), dpi=140, facecolor="none")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_facecolor("none")
    ax.pcolormesh(
        x, y, values, cmap=cmap, norm=norm,
        shading="nearest", rasterized=True, antialiased=False
    )
    ax.set_xlim(-230, 230)
    ax.set_ylim(-230, 230)
    ax.set_aspect("equal")

    output = io.BytesIO()
    fig.savefig(output, format="png", transparent=True, dpi=140, pad_inches=0)
    plt.close(fig)
    png = output.getvalue()

    with state_lock:
        state["images"][product] = png
    return png


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/api/status")
def status():
    """Fast archive-only check. Does not download or decode the radar volume."""
    try:
        key = find_latest_key()
        scan_time = key_scan_time(key)
        with state_lock:
            is_loaded = state["loaded_key"] == key and state["radar"] is not None
            is_loading = state["loading"]
        return {
            "ok": True,
            "phase": "ready" if is_loaded else ("decoding" if is_loading else "scan_found"),
            "station": STATION,
            "bucket": BUCKET,
            "key": key,
            "scan_time_utc": scan_time.isoformat() if scan_time else "Time unavailable",
            "loaded": is_loaded,
            "loading": is_loading,
            "refresh_seconds": 45,
            "source": "Unidata public NEXRAD Level II archive",
        }
    except Exception as exc:
        return {"ok": False, "phase": "error", "error": str(exc), "bucket": BUCKET}


@app.get("/api/image/{product}")
def image(product: str):
    try:
        png = render(product)
        return Response(
            png,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, f"Radar download/decode failed: {exc}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
