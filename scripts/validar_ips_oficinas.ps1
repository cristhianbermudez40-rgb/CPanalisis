param(
    [Parameter(Mandatory=$true)]
    [string]$CsvPath,
    [int]$TimeoutMs = 1200
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $CsvPath)) {
    throw "No existe el archivo CSV: $CsvPath"
}

$rows = Import-Csv -Path $CsvPath
if (-not $rows -or $rows.Count -eq 0) {
    throw "El CSV no tiene filas."
}

# Required columns: oficina, ip
foreach ($r in $rows) {
    if (-not $r.ip) {
        throw "Cada fila debe tener columna 'ip'."
    }
    if (-not $r.oficina) {
        $r | Add-Member -MemberType NoteProperty -Name oficina -Value "N/A" -Force
    }
}

function Test-TcpPort {
    param([string]$Ip, [int]$Port, [int]$Timeout = 1200)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($Ip, $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne($Timeout, $false)
        if (-not $ok) { return $false }
        $client.EndConnect($iar)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

$results = foreach ($row in $rows) {
    $ip = $row.ip.Trim()
    $pingOk = Test-Connection -ComputerName $ip -Count 1 -Quiet -ErrorAction SilentlyContinue

    [PSCustomObject]@{
        Oficina  = $row.oficina
        IP       = $ip
        Ping     = if ($pingOk) { "OK" } else { "FAIL" }
        TCP161   = if (Test-TcpPort -Ip $ip -Port 161 -Timeout $TimeoutMs) { "OPEN" } else { "CLOSED" }
        TCP9100  = if (Test-TcpPort -Ip $ip -Port 9100 -Timeout $TimeoutMs) { "OPEN" } else { "CLOSED" }
        TCP80    = if (Test-TcpPort -Ip $ip -Port 80 -Timeout $TimeoutMs) { "OPEN" } else { "CLOSED" }
        TCP443   = if (Test-TcpPort -Ip $ip -Port 443 -Timeout $TimeoutMs) { "OPEN" } else { "CLOSED" }
    }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outPath = Join-Path (Split-Path -Parent $CsvPath) "resultado_ips_$stamp.csv"
$results | Export-Csv -Path $outPath -NoTypeInformation -Encoding UTF8

$results | Format-Table -AutoSize
Write-Output ""
Write-Output "Resultado guardado en: $outPath"
