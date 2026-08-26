param(
    [int]$Port = 8013
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$server = Start-Process -FilePath "$root\.venv\Scripts\robot-nxt-control-mcp-http.exe" `
    -ArgumentList '--port', $Port -WorkingDirectory $root -WindowStyle Hidden -PassThru

try {
    $url = "http://127.0.0.1:$Port/mcp"
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $client = [System.Net.Sockets.TcpClient]::new()
            $client.Connect('127.0.0.1', $Port)
            $client.Dispose()
            break
        } catch {
            if ($attempt -eq 29) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
    npx --yes @modelcontextprotocol/conformance server --url $url --suite active `
        --expected-failures "$root\conformance-baseline.yml" --verbose
    if ($LASTEXITCODE -ne 0) { throw "MCP conformance runner failed with exit code $LASTEXITCODE" }
} finally {
    if (-not $server.HasExited) { Stop-Process -Id $server.Id }
}
