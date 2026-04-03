# Muestra qué proceso escucha en un puerto (p. ej. 8000). Si no es tu app.py/manage.py, matas el PID equivocado.
param([int]$Port = 8000)
$lines = netstat -ano | Select-String ":$Port\s"
if (-not $lines) {
    Write-Host "Nadie escucha en el puerto $Port"
    exit 0
}
Write-Host "Conexiones que mencionan :$Port :"
$lines | ForEach-Object { $_.Line }
$pids = @{}
foreach ($line in $lines) {
    if ($line -match '\s+LISTENING\s+(\d+)\s*$') {
        $pids[$Matches[1]] = $true
    }
}
foreach ($procId in $pids.Keys) {
    Write-Host "`n--- PID $procId ---"
    Get-CimInstance Win32_Process -Filter "ProcessId = $procId" | ForEach-Object {
        Write-Host "Name: $($_.Name)"
        Write-Host "Executable: $($_.ExecutablePath)"
        Write-Host "CommandLine: $($_.CommandLine)"
    }
}
