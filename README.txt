Welcome to StormScope!
StormScope KLOT — real NOAA Level II radar

Requires Windows 10/11 64-bit, VSCode, Python 3.11.9 and a stable internet connection.

1. Open a terminal in this extracted folder.
2. Run: python -m pip install -r requirements.txt
3. Run: python -m uvicorn server:app --host 127.0.0.1 --port 8765
4. Open http://127.0.0.1:8765 in your browser.

Do NOT double-click index.html: it needs the local Python decoder.
First scan may take a while to download and decode. The app checks for a new scan every 2 minutes. NOAA archive publication can lag the radar station. Reflectivity and velocity are derived from the lowest available sweeps in the same Level II volume. TVS is deliberately NOT claimed without a validated detection algorithm/product. No simulated data, pincushion distortion, or fake storm movement is used.

Data: NOAA public AWS NEXRAD Level II archive, bucket unidata-nexrad-level2, KLOT.

Any errors that occured can be asked to me how to fix. Thanks for using my software!

Known errors:

----------------------------------------------------------------------------------------------------------------------------
cannot be loaded because running scripts is disabled on this system. For more information, see about_Execution_Policies at 
https://...
At line:2 char:1
+ .\.venv\Scripts\Activate.ps1
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : SecurityError: (:) [], PSSecurityException
    + FullyQualifiedErrorId : UnauthorizedAccess

Info: It is a Windows Terminal security restriction.
Fixes available:

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

Successful result:

(.venv) PS C:\...

----------------------------------------------------------------------------------------------------------------------------
