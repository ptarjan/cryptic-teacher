# What tools/vlm_health.py reports when the desktop VLM is down, as one JSON
# line. "game" uses D:\llm\game-guard.ps1's own rule (a process run from D:\
# outside D:\llm), because that guard is what takes llama-swap down for one.
$ProgressPreference = 'SilentlyContinue'
$game = Get-Process | Where-Object { $_.Path -like 'D:\*' -and $_.Path -notlike 'D:\llm\*' } | Select-Object -First 1
$swap = @(Get-Process -Name llama-swap, llama-server -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name) $($_.Id)" })
$tasks = @(foreach ($t in 'llamaswap-boot', 'gameguard') {
    $i = Get-ScheduledTaskInfo -TaskName $t -ErrorAction SilentlyContinue
    $s = (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue).State
    "{0} {1}, last result 0x{2:X} at {3}" -f $t, $s, $i.LastTaskResult, $i.LastRunTime
})
$log = @(Get-Content -Path 'D:\llm\game-guard.log' -Tail 6 -ErrorAction SilentlyContinue | ForEach-Object { "$_" })
@{game = $(if ($game) { "$($game.Name) [$($game.Path)]" } else { '' }); procs = $swap; tasks = $tasks; log = $log} | ConvertTo-Json -Compress
