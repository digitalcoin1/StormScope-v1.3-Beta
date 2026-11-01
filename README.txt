Welcome to StormScope!
StormScope Version 1.3 BETA — Live NOAA Level II radar scans

Requires Windows 10/11 64-bit (prefer Windows 11 Pro 64-bit), VSCode, Python 3.11.9 and a stable internet connection.

1. Open a terminal in this extracted folder.
2. Run: python -m pip install -r requirements.txt
3. Run: .\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8765
4. Open http://127.0.0.1:8765 in your browser.

Do NOT double-click index.html: it needs the local Python decoder.
First scan may take a while to download and decode. The app checks for a new scan every 2 minutes. NOAA archive publication can lag the radar station. Reflectivity and velocity are derived from the lowest available sweeps in the same Level II volume. TVS is deliberately NOT claimed without a validated detection algorithm/product. No simulated data, pincushion distortion, or fake storm movement is used.

Data source: NOAA public AWS NEXRAD Level II archive, bucket unidata-nexrad-level2, KLOT/KTLX/KINX/KDDC/KGLD/KICT/KAMA/KFDR/KMAF/KUEX/KOAX.

Any problems? Refresh your page or restart the application.

Copyright (C) 2026 SkywaveDX | Thanks for using my software!
