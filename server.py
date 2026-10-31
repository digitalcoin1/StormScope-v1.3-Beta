"""StormScope KLOT: NOAA public NEXRAD Level II viewer. Run with uvicorn server:app."""
import io, os, time, threading, tempfile
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
import boto3
from botocore import UNSIGNED
from botocore.config import Config
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm, Normalize
import pyart

ROOT=Path(__file__).parent
app=FastAPI(title='StormScope KLOT Level II')

s3 = boto3.client(
    "s3",
    region_name="us-east-1",
    config=Config(signature_version=UNSIGNED)
)

BUCKET="unidata-nexrad-level2"; STATION='KLOT'
lock=threading.Lock(); cache={'key':None,'checked':0,'scan':None,'images':{}}

# Native dBZ palette; low/no return is transparent. No simulated clutter.
REF_COLORS=['#164baf','#237de1','#20b8c5','#22a84b','#78cf35','#d9df29','#f4b02b','#ec6426','#d52d36','#ad26a0','#ef7bda','#ffffff']
REF_BOUNDS=[5,10,15,20,25,30,35,40,45,50,55,60,65]
VEL_COLORS=['#7a1d35','#bf3038','#ec7b4b','#f2b78d','#dddddd','#8acdc0','#39a782','#176f62','#144a58']
VEL_BOUNDS=[-45,-35,-25,-15,-5,5,15,25,35,45]

def newest():
    now=datetime.now(timezone.utc)
    # Check current UTC day and previous UTC day (midnight rollover).
    for day in (now,now.replace(hour=0,minute=0,second=0,microsecond=0)-__import__('datetime').timedelta(days=1)):
        prefix=f'{day:%Y/%m/%d}/{STATION}/'
        pages=s3.get_paginator('list_objects_v2').paginate(Bucket=BUCKET,Prefix=prefix)
        keys=[]
        for page in pages:
            keys += [v['Key'] for v in page.get('Contents',[]) if v['Key'].split('/')[-1].startswith(STATION) and not v['Key'].endswith('_MDM')]
        if keys:return sorted(keys)[-1]
    raise RuntimeError('No recent KLOT Level II scan found in NOAA archive')

def load():
    with lock:
        if cache['scan'] is not None and time.time()-cache['checked']<120:return
        key=newest();cache['checked']=time.time()
        if key==cache['key'] and cache['scan'] is not None:return
        with tempfile.NamedTemporaryFile(suffix='.ar2v',delete=False) as f:path=f.name
        try:
            s3.download_file(BUCKET,key,path)
            radar=pyart.io.read_nexrad_archive(path)
            cache.update(key=key,scan=radar,images={})
        finally:
            os.unlink(path)

def render(product):
    load()
    if product not in ('reflectivity','velocity'):raise HTTPException(400,'Unknown product')
    with lock:
        if product in cache['images']:return cache['images'][product]
        radar=cache['scan']; field=product
        if field not in radar.fields:raise HTTPException(404,f'{field} not present in this volume')
        # Lowest sweep containing requested field; actual radar ray/gate geometry.
        sweep=None
        for i in range(radar.nsweeps):
            a=int(radar.sweep_start_ray_index['data'][i]);b=int(radar.sweep_end_ray_index['data'][i])+1
            if not np.ma.getmaskarray(radar.fields[field]['data'][a:b]).all():sweep=i;break
        if sweep is None:raise HTTPException(404,'No usable sweep')
        a=int(radar.sweep_start_ray_index['data'][sweep]);b=int(radar.sweep_end_ray_index['data'][sweep])+1
        vals=np.ma.array(radar.fields[field]['data'][a:b],copy=True)
        x=np.asarray(radar.gate_x['data'][a:b])/1000;y=np.asarray(radar.gate_y['data'][a:b])/1000
        vals=np.ma.masked_invalid(vals)
        if product=='reflectivity':
            vals=np.ma.masked_less(vals,5);cmap=ListedColormap(REF_COLORS);norm=BoundaryNorm(REF_BOUNDS,cmap.N,clip=True)
        else:
            vals=np.ma.masked_where(np.abs(vals)<1,vals);cmap=ListedColormap(VEL_COLORS);norm=BoundaryNorm(VEL_BOUNDS,cmap.N,clip=True)
        cmap.set_bad((0,0,0,0))
        fig=plt.figure(figsize=(8,8),dpi=140,facecolor='none');ax=fig.add_axes([0,0,1,1]);ax.set_axis_off();ax.set_facecolor('none')
        # Native ray/gate coordinates in local radar tangent plane. No fisheye or lat/lon stretching.
        ax.pcolormesh(x,y,vals,cmap=cmap,norm=norm,shading='nearest',rasterized=True,antialiased=False)
        ax.set_xlim(-230,230);ax.set_ylim(-230,230);ax.set_aspect('equal')
        bio=io.BytesIO();fig.savefig(bio,format='png',transparent=True,dpi=140,pad_inches=0);plt.close(fig)
        data=bio.getvalue();cache['images'][product]=data;return data

@app.get('/api/status')
def status():
    try:
        load();r=cache['scan'];return {'ok':True,'station':STATION,'source':'NOAA NEXRAD Level II public AWS archive','key':cache['key'],'scan_time_utc':pyart.util.datetime_from_radar(r).isoformat()+' UTC','latitude':float(r.latitude['data'][0]),'longitude':float(r.longitude['data'][0]),'fields':list(r.fields),'sweeps':int(r.nsweeps),'refresh_seconds':120,'tvs':'Not inferred: official TVS requires a separate validated algorithm/product'}
    except Exception as e:return {'ok':False,'error':str(e)}
@app.get('/api/image/{product}')
def image(product:str):
    try:return Response(render(product),media_type='image/png',headers={'Cache-Control':'no-store'})
    except HTTPException:raise
    except Exception as e:raise HTTPException(503,str(e))
@app.get('/')
def index():return FileResponse(ROOT/'index.html')
