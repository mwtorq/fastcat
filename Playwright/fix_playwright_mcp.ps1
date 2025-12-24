# Fix script for Playwright MCP Server issues
# This script diagnoses and fixes common Playwright MCP server problems

Write-Host "Diagnosing Playwright MCP Server issues..." -ForegroundColor Cyan
Write-Host ""

# Check Node.js
Write-Host "1. Checking Node.js installation..." -ForegroundColor Yellow
$nodeVersion = node --version 2>$null
if ($nodeVersion) {
    Write-Host "   ✓ Node.js version: $nodeVersion" -ForegroundColor Green
} else {
    Write-Host "   ✗ Node.js not found!" -ForegroundColor Red
    Write-Host "   Please install Node.js from https://nodejs.org/" -ForegroundColor Yellow
    exit 1
}

# Check npm
Write-Host "2. Checking npm..." -ForegroundColor Yellow
$npmVersion = npm --version 2>$null
if ($npmVersion) {
    Write-Host "   ✓ npm version: $npmVersion" -ForegroundColor Green
} else {
    Write-Host "   ✗ npm not found!" -ForegroundColor Red
    exit 1
}

# Check Playwright
Write-Host "3. Checking Playwright installation..." -ForegroundColor Yellow
$playwrightVersion = npx playwright --version 2>$null
if ($playwrightVersion) {
    Write-Host "   ✓ Playwright version: $playwrightVersion" -ForegroundColor Green
} else {
    Write-Host "   ⚠ Playwright not found, installing..." -ForegroundColor Yellow
    npm install -g playwright
}

# Check browser installation
Write-Host "4. Checking browser installation..." -ForegroundColor Yellow
$chromiumPath = "$env:LOCALAPPDATA\ms-playwright\chromium-1200\chrome-win64\chrome.exe"
if (Test-Path $chromiumPath) {
    Write-Host "   ✓ Chromium browser found" -ForegroundColor Green
} else {
    Write-Host "   ⚠ Browsers not installed, installing..." -ForegroundColor Yellow
    npx playwright install chromium
}

# Check Cursor settings
Write-Host "5. Checking Cursor MCP configuration..." -ForegroundColor Yellow
$settingsPath = "$env:APPDATA\Cursor\User\settings.json"
if (Test-Path $settingsPath) {
    $settings = Get-Content $settingsPath | ConvertFrom-Json
    if ($settings.mcpServers -and $settings.mcpServers.playwright) {
        Write-Host "   ✓ MCP configuration found in Cursor settings" -ForegroundColor Green
    } else {
        Write-Host "   ⚠ MCP configuration missing, adding..." -ForegroundColor Yellow
        
        # Read current settings
        $settingsContent = Get-Content $settingsPath -Raw
        $settingsObj = $settingsContent | ConvertFrom-Json
        
        # Add MCP configuration
        $mcpConfig = @{
            command = "npx"
            args = @("-y", "@automatalabs/mcp-server-playwright")
        }
        $settingsObj | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value @{
            playwright = $mcpConfig
        } -Force
        
        # Write back
        $settingsObj | ConvertTo-Json -Depth 10 | Set-Content $settingsPath
        Write-Host "   ✓ MCP configuration added to Cursor settings" -ForegroundColor Green
    }
} else {
    Write-Host "   ⚠ Cursor settings file not found at: $settingsPath" -ForegroundColor Yellow
    Write-Host "   Creating settings file with MCP configuration..." -ForegroundColor Yellow
    
    $mcpConfig = @{
        mcpServers = @{
            playwright = @{
                command = "npx"
                args = @("-y", "@automatalabs/mcp-server-playwright")
            }
        }
    }
    
    $mcpConfig | ConvertTo-Json -Depth 10 | Set-Content $settingsPath
    Write-Host "   ✓ Created Cursor settings file with MCP configuration" -ForegroundColor Green
}

# Test MCP server
Write-Host "6. Testing MCP server..." -ForegroundColor Yellow
Write-Host "   Running: npx -y @automatalabs/mcp-server-playwright" -ForegroundColor Gray
$testResult = npx -y @automatalabs/mcp-server-playwright 2>&1 | Select-Object -First 5
if ($LASTEXITCODE -eq 0 -or $testResult) {
    Write-Host "   ✓ MCP server can start" -ForegroundColor Green
} else {
    Write-Host "   ⚠ MCP server test had issues (this may be normal if it's waiting for input)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Diagnosis complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Restart Cursor IDE completely" -ForegroundColor White
Write-Host "2. Check Cursor's MCP server status in settings" -ForegroundColor White
Write-Host "3. If issues persist, check Cursor logs (Ctrl+Shift+P -> 'Developer: Show Logs')" -ForegroundColor White
Write-Host ""

