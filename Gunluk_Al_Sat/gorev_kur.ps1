# gorev_kur.ps1 — PowerShell'de çalıştırın (Admin gerekmez)
$py  = "C:\Users\BioCSI\AppData\Local\Programs\Python\Python313\pythonw.exe"
$dir = "C:\Users\BioCSI\CLAUDE\GridTracker"

# server.py görevi
schtasks /Create /F /TN "GridTracker\server" `
  /TR "`"$py`" `"$dir\server.py`"" `
  /SC ONLOGON /DELAY 0000:15

# monitor.pyw görevi
schtasks /Create /F /TN "GridTracker\Gunluk_Al_Sat_Monitor" `
  /TR "`"$py`" `"$dir\Gunluk_Al_Sat\monitor.pyw`"" `
  /SC ONLOGON /DELAY 0000:45

# Hemen başlat
schtasks /Run /TN "GridTracker\server"
Start-Sleep 2
schtasks /Run /TN "GridTracker\Gunluk_Al_Sat_Monitor"

Write-Host "`nKontrol:" -ForegroundColor Cyan
Get-Process pythonw | ForEach-Object {
  $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
  Write-Host "  PID $($_.Id): $cmd"
}
