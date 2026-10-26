# Activa SMUNE y el acceso remoto (con reinicio automático). Muestra el link para los celulares.
Set-Location $PSScriptRoot
& "$PSScriptRoot\pausar_remoto.ps1" -Silencioso

$v = Start-Process -FilePath powershell -ArgumentList "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSScriptRoot\vigilante_remoto.ps1`"" `
    -WindowStyle Hidden -PassThru
$v.Id | Set-Content .vigilante.pid

$link = $null
for ($i = 0; $i -lt 40 -and -not $link; $i++) {
    Start-Sleep 2
    if (Test-Path link_remoto.txt) { $link = (Get-Content link_remoto.txt -Raw).Trim() }
}
if ($link) { Write-Host "LINK PARA CELULARES: $link" } else { Write-Host "No se obtuvo el link; revisa tunel.log" }
