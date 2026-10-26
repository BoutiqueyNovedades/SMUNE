# Cierra el vigilante, el túnel y el servidor (el link deja de funcionar).
param([switch]$Silencioso)
Set-Location $PSScriptRoot
if (Test-Path .vigilante.pid) {
    Stop-Process -Id ([int](Get-Content .vigilante.pid)) -Force -ErrorAction SilentlyContinue
    Remove-Item .vigilante.pid
}
foreach ($c in (Get-Process cloudflared -ErrorAction SilentlyContinue)) { Stop-Process -Id $c.Id -Force -ErrorAction SilentlyContinue }
$p = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
foreach ($x in $p) { Stop-Process -Id $x.OwningProcess -Force -ErrorAction SilentlyContinue }
Remove-Item link_remoto.txt, .remoto.pid -ErrorAction SilentlyContinue
if (-not $Silencioso) { Write-Host "Acceso remoto y servidor detenidos." }
