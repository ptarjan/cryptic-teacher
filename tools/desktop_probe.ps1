# What tools/desktop_busy.py decides on, as one JSON line: the game processes
# running ($Names, and anything run from $GameDirs but not $NotGameDirs, set by the caller), the 3D engines' utilisation summed over
# every process but the VLM's ($Vlm, set by the caller: llama-server's
# CUDA work shows on the 3D engines, 50-1700% summed) and our OCR's, averaged
# over three one-second samples, the pids of the OCR sessions
# (tools/ocr_remote.py serve) and the GPU OCR server (tools/ocr_gpu.py serve)
# running here, the free physical memory in MB, and the VLC windows playing a
# video ($video: VLC titles its window "<file> - VLC media player" while a file
# is open, plain "VLC media player" when idle).
$ProgressPreference = 'SilentlyContinue'
$games = @(Get-Process -Name $Names -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
# Any program run from a game folder ($GameDirs, less $NotGameDirs) is a game too.
$games += @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $p = $_.Path; $p -and ($GameDirs | Where-Object { $p.StartsWith($_, 'OrdinalIgnoreCase') }) -and
    -not ($NotGameDirs | Where-Object { $p.StartsWith($_, 'OrdinalIgnoreCase') }) } | ForEach-Object { $_.Name })
$video = @(Get-Process -Name vlc -ErrorAction SilentlyContinue | Where-Object { $t = $_.MainWindowTitle; $t -and $t -ne 'VLC media player' } | ForEach-Object { $_.MainWindowTitle -replace ' - VLC media player$', '' })
$serving = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' AND (CommandLine LIKE '%ocr_remote.py serve%' OR CommandLine LIKE '%ocr_gpu.py serve%')" | ForEach-Object { $_.ProcessId })
$ours = @(Get-Process -Name $Vlm -ErrorAction SilentlyContinue | ForEach-Object { "pid_$($_.Id)_" }) + @($serving | ForEach-Object { "pid_$($_)_" })
$sets = @(Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage' -SampleInterval 1 -MaxSamples 3 -ErrorAction SilentlyContinue)
$others = $sets.CounterSamples | Where-Object { $i = $_.InstanceName; -not ($ours | Where-Object { $i.StartsWith($_) }) }
$gpu = ($others | Measure-Object -Property CookedValue -Sum).Sum / [math]::Max(1, $sets.Count)
$freeMB = [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
# The game-guard's flag: written when a game starts, before it drains and stops llama-server (up to 60s),
# removed once the game has ended and llama-swap is back.
$pending = [bool](Test-Path 'D:\llm\game-pending')
@{pending = $pending; games = $games; gpu3d = [math]::Round($gpu, 1); serving = $serving; freeMB = $freeMB; video = $video} | ConvertTo-Json -Compress
