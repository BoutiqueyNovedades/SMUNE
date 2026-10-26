# Mantiene SMUNE y el túnel activos. Si alguno se cae, lo reinicia y actualiza link_remoto.txt.
Set-Location $PSScriptRoot
$env:SMUNE_PROXY = "1"

function Servidor-Activo { [bool](Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) }

function Iniciar-Servidor {
    Start-Process -FilePath .\venv\Scripts\python.exe -ArgumentList app.py `
        -RedirectStandardOutput server.out.log -RedirectStandardError server.err.log -WindowStyle Hidden | Out-Null
    Start-Sleep 6
}

function Iniciar-Tunel {
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Remove-Item tunel.log, link_remoto.txt -ErrorAction SilentlyContinue
    Start-Process -FilePath .\herramientas\cloudflared.exe `
        -ArgumentList "tunnel --url http://127.0.0.1:5000 --no-autoupdate --logfile tunel.log" -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep 2
        if (Test-Path tunel.log) {
            $m = Select-String -Path tunel.log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
            if ($m) { $m.Matches[0].Value | Set-Content link_remoto.txt; return }
        }
    }
}

while ($true) {
    if (-not (Servidor-Activo)) { Iniciar-Servidor }
    if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) { Iniciar-Tunel }
    Start-Sleep 30
}
