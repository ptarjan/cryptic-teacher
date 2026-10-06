# What tools/desktop_busy.py decides on, as one JSON line: the game processes
# running ($Names, set by the caller), the 3D engines' utilisation summed over
# every process and averaged over three one-second samples, and the pids of
# the OCR sessions (tools/ocr_remote.py serve) running here.
$ProgressPreference = 'SilentlyContinue'
$games = @(Get-Process -Name $Names -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
$sets = @(Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage' -SampleInterval 1 -MaxSamples 3 -ErrorAction SilentlyContinue)
$gpu = ($sets.CounterSamples | Measure-Object -Property CookedValue -Sum).Sum / [math]::Max(1, $sets.Count)
$serving = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' AND CommandLine LIKE '%ocr_remote.py serve%'" | ForEach-Object { $_.ProcessId })
@{games = $games; gpu3d = [math]::Round($gpu, 1); serving = $serving} | ConvertTo-Json -Compress
