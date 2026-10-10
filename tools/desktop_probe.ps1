# What tools/desktop_busy.py decides on, as one JSON line: the game processes
# running ($Names, set by the caller), the 3D engines' utilisation summed over
# every process but the VLM's ($Vlm, set by the caller: llama-server's
# CUDA work shows on the 3D engines, 50-1700% summed) and averaged over three
# one-second samples, the pids of the OCR sessions (tools/ocr_remote.py
# serve) running here, and the free physical memory in MB.
$ProgressPreference = 'SilentlyContinue'
$games = @(Get-Process -Name $Names -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
$vlmPids = @(Get-Process -Name $Vlm -ErrorAction SilentlyContinue | ForEach-Object { "pid_$($_.Id)_" })
$sets = @(Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage' -SampleInterval 1 -MaxSamples 3 -ErrorAction SilentlyContinue)
$others = $sets.CounterSamples | Where-Object { $i = $_.InstanceName; -not ($vlmPids | Where-Object { $i.StartsWith($_) }) }
$gpu = ($others | Measure-Object -Property CookedValue -Sum).Sum / [math]::Max(1, $sets.Count)
$serving = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' AND CommandLine LIKE '%ocr_remote.py serve%'" | ForEach-Object { $_.ProcessId })
$freeMB = [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
@{games = $games; gpu3d = [math]::Round($gpu, 1); serving = $serving; freeMB = $freeMB} | ConvertTo-Json -Compress
