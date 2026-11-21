# Danksy DroidOps: read-only Windows restart diagnostics. Does not start Droid Watch.
$ErrorActionPreference = 'Continue'
$reportFolder = Join-Path $env:LOCALAPPDATA 'DroidTycoonAutoClicker\diagnostics'
New-Item -ItemType Directory -Path $reportFolder -Force -ErrorAction Stop | Out-Null
$reportPath = Join-Path $reportFolder ('DroidOps-Diagnostics-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt')
$lines = New-Object 'System.Collections.Generic.List[string]'
function Add-Section($Title, [scriptblock]$Query) {
    $lines.Add('')
    $lines.Add($Title)
    try {
        $value = (& $Query | Format-List | Out-String -Width 220).Trim()
        $lines.Add($value)
    } catch { $lines.Add('Unavailable: ' + $_.Exception.Message) }
}
$lines.Add('Danksy DroidOps restart diagnostics')
$lines.Add('Created: ' + (Get-Date -Format o))
$lines.Add('No watcher, controller input, stress test or system settings changes were performed.')
Add-Section 'Windows' {
    Get-CimInstance Win32_OperatingSystem -ErrorAction Stop |
        Select-Object Caption, Version, BuildNumber, LastBootUpTime
}
Add-Section 'Processor' {
    Get-CimInstance Win32_Processor -ErrorAction Stop |
        Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
}
Add-Section 'Memory' {
    Get-CimInstance Win32_ComputerSystem -ErrorAction Stop |
        Select-Object @{Name='RAM_GB';Expression={[math]::Round($_.TotalPhysicalMemory / 1GB, 2)}}
}
Add-Section 'Graphics' {
    Get-CimInstance Win32_VideoController -ErrorAction Stop |
        Select-Object Name, DriverVersion, DriverDate
}
Add-Section 'Virtual controller driver' {
    Get-CimInstance Win32_SystemDriver -Filter "Name LIKE '%ViGEm%'" -ErrorAction Stop |
        Select-Object Name, State, StartMode
}
Add-Section 'Recent restart, hardware and display events (last 3 days, newest 80)' {
    Get-WinEvent -FilterHashtable @{
        LogName='System'; StartTime=(Get-Date).AddDays(-3); Id=41,1001,6008,18,19,4101,46
    } -MaxEvents 80 -ErrorAction Stop | ForEach-Object {
        $item = $_
        $xml = [xml]$item.ToXml()
        $details = @($xml.Event.EventData.Data | ForEach-Object {
            if ($_.Name) { $_.Name + '=' + $_.'#text' }
        }) -join '; '
        [pscustomobject]@{
            Time=$item.TimeCreated; Id=$item.Id; Provider=$item.ProviderName
            Message=$item.Message; EventData=$details
        }
    }
}
Add-Section 'Minidump file dates (contents are not read)' {
    Get-ChildItem (Join-Path $env:WINDIR 'Minidump') -Filter '*.dmp' -ErrorAction Stop |
        Select-Object -Last 5 Name, LastWriteTime, Length
}
Add-Section 'Recent Droid Watch log (last 100 lines)' {
    $watchLog = Join-Path $env:LOCALAPPDATA 'DroidTycoonAutoClicker\droid-watch.log'
    Get-Content -LiteralPath $watchLog -Tail 100 -ErrorAction Stop
}
$content = $lines -join [Environment]::NewLine
# Remove user-profile and computer names from paths and event message text.
$content = $content -replace '(?i)[A-Z]:\\Users\\[^\\\s]+', 'C:\Users\[user]'
if ($env:COMPUTERNAME) { $content = $content -replace [regex]::Escape($env:COMPUTERNAME), '[computer]' }
if ($env:USERNAME) { $content = $content -replace ('(?i)\b' + [regex]::Escape($env:USERNAME) + '\b'), '[user]' }
try {
    [IO.File]::WriteAllText($reportPath, $content, (New-Object Text.UTF8Encoding($false)))
    Write-Host ('Saved: ' + $reportPath)
    Write-Host 'Review the report before sharing it. Keep Droid Watch off on the affected PC.'
    Start-Process notepad.exe -ArgumentList ('"{0}"' -f $reportPath)
} catch {
    Write-Error ('Could not save diagnostics: ' + $_.Exception.Message)
    exit 1
}
