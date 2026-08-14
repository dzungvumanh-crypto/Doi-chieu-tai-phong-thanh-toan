# Chuyen 1 file .docx sang .pdf bang Microsoft Word (COM).
#   -In  : duong dan .docx (tuyet doi)
#   -Out : duong dan .pdf  (tuyet doi)
#   -PidFile : ghi PID cua WINWORD do script nay sinh ra, de Python diet khi qua han
param([string]$In, [string]$Out, [string]$PidFile)
$ErrorActionPreference = "Stop"

# Word la ung dung single-instance: neu nguoi dung dang mo Word thi COM co the tra ve
# CHINH ban do. Ghi lai PID truoc khi tao de chi Quit khi minh la nguoi sinh ra no —
# lo Quit ban cua nguoi dung la mat het viec dang lam do.
$before = @(Get-Process winword -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

$after = @(Get-Process winword -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$mine  = @($after | Where-Object { $before -notcontains $_ })
if ($PidFile -and $mine.Count -gt 0) { Set-Content -Path $PidFile -Value ($mine -join ",") -Encoding ascii }

try {
    # ReadOnly + AddToRecentFiles=$false: khong dung file goc, khong lam ban danh sach
    # "Recent" cua nguoi van hanh.
    $doc = $word.Documents.Open($In, $false, $true, $false)
    $doc.SaveAs([ref]$Out, [ref]17)   # 17 = wdFormatPDF
    $doc.Close([ref]0)
} finally {
    if ($mine.Count -gt 0) { $word.Quit() }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
Write-Output "OK"
