# May chu chuyen .docx -> .pdf: giu MOT ban Word song giua cac lan goi.
#   -PidFile : ghi PID cua WINWORD do script nay sinh ra, de Python diet khi qua han
#
# Giao thuc (moi dong la mot viec):
#   stdin :  <duong dan .docx>|<duong dan .pdf>   hoac  QUIT
#   stdout:  READY (luc san sang) | OK | ERR <mo ta>
#
# Mo roi dong Word ton ~3,5 giay; chuyen mot file chi ton ~0,25 giay. Giu Word song
# giua cac lan goi lam bien mat gan het thoi gian cho cua man xem truoc don nghi phep.
#
# CANH BAO QUAN TRONG — doc ky truoc khi sua phan Quit o cuoi file:
# Neu ban Word nay la ban WINWORD duy nhat dang chay tren may, thi khi nguoi van hanh
# double-click mot file .docx, Windows dieu tai lieu do vao DUNG tien trinh nay. Da do
# that: tien trinh khong doi, nhung MainWindowHandle tu 0 nhay len khac 0 va tieu de
# cua so thanh ten tai lieu cua ho. Luc do goi $word.Quit() la DONG TAI LIEU CUA HO —
# ma DisplayAlerts=0 thi dong luon, khong hoi "co luu khong". Mat viec dang lam.
param([string]$PidFile)
$ErrorActionPreference = "Stop"

# stdin/stdout la ong noi voi Python -> ep UTF-8 ca hai chieu. Khong ep thi duong dan
# co dau tieng Viet ve sai ben kia va Word bao "khong tim thay file".
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding  = $utf8

# Word la ung dung single-instance: COM co the tra ve CHINH ban nguoi van hanh dang mo.
# Ghi lai PID truoc khi tao de chi Quit ban do minh sinh ra.
$before = @(Get-Process winword -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)

$word = New-Object -ComObject Word.Application
$word.Visible = $false

$after = @(Get-Process winword -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$mine  = @($after | Where-Object { $before -notcontains $_ })
if ($PidFile -and $mine.Count -gt 0) { Set-Content -Path $PidFile -Value ($mine -join ",") -Encoding ascii }

# Viet thang ra [Console]::Out, KHONG dung Write-Output: Write-Output di qua bo dinh dang
# cua PowerShell va nam lai trong bo dem, Python doc dong se cho mai khong thay gi.
function Say([string]$s) { [Console]::Out.WriteLine($s); [Console]::Out.Flush() }

Say "READY"

try {
    while ($true) {
        $line = [Console]::In.ReadLine()
        if ($null -eq $line) { break }              # Python dong ong -> thoat
        $line = $line.Trim()
        if ($line -eq "") { continue }
        if ($line -eq "QUIT") { break }
        $i = $line.IndexOf("|")
        if ($i -lt 1) { Say "ERR dong lenh sai dinh dang"; continue }
        $in  = $line.Substring(0, $i)
        $out = $line.Substring($i + 1)
        $doc = $null
        try {
            # Tat hop thoai CHI trong luc lam viec cua minh. De tat suot phien thi tai
            # lieu cua nguoi van hanh (neu bi dieu vao day) cung mat luon hop thoai
            # "co luu khong" — ho bam dong cua so la mat bai.
            $word.DisplayAlerts = 0
            # ReadOnly + AddToRecentFiles=$false: khong dung file goc, khong lam ban
            # danh sach "Recent" cua nguoi van hanh.
            $doc = $word.Documents.Open($in, $false, $true, $false)
            # Open tra ve $null MA KHONG nem loi khi Word chay o phien 0 (khong co ai
            # dang nhap). Khong bat o day thi dong duoi bao "You cannot call a method on
            # a null-valued expression" — nguoi van hanh doc xong khong biet lam gi.
            if ($null -eq $doc) {
                throw ("Word mo len duoc nhung KHONG mo duoc tai lieu. Thuong gap khi backend " +
                       "chay o phien khong co nguoi dang nhap (Windows Service, hoac Task Scheduler " +
                       "dat 'chay ca khi khong ai dang nhap'). Word can mot phien co nguoi dang nhap " +
                       "tren may chu. Xem muc 'Word doi phien dang nhap' trong README.")
            }
            $doc.SaveAs([ref]$out, [ref]17)         # 17 = wdFormatPDF
            $doc.Close([ref]0)
            $doc = $null
            Say "OK"
        } catch {
            # Chi dong DUNG tai lieu cua minh. Truoc day quet sach Documents — gap dung
            # luc nguoi van hanh co tai lieu trong cung ban Word nay la dong ca cua ho.
            try { if ($null -ne $doc) { $doc.Close([ref]0) } } catch { }
            Say ("ERR " + $_.Exception.Message.Replace([char]13, ' ').Replace([char]10, ' '))
        } finally {
            try { $word.DisplayAlerts = -1 } catch { }   # -1 = wdAlertsAll, tra lai binh thuong
        }
    }
} finally {
    # Chi Quit khi ban Word nay VAN CON LA CUA MINH: do minh sinh ra, khong giu tai lieu
    # nao, va khong co cua so nao hien ra (co cua so = da bi dieu tai lieu cua nguoi
    # van hanh vao day). Nghi ngo thi de nguyen — bo mac mot WINWORD chay tiep con hon
    # dong mat ban Word co nguoi dang go do.
    $giu_lai = $false
    try { if ($word.Documents.Count -gt 0) { $giu_lai = $true } } catch { $giu_lai = $true }
    if ($mine.Count -gt 0) {
        try {
            $wp = Get-Process -Id $mine[0] -ErrorAction Stop
            if ($wp.MainWindowHandle -ne 0) { $giu_lai = $true }
        } catch { }
    }
    if ($mine.Count -gt 0 -and -not $giu_lai) {
        try { $word.Quit() } catch { }
    } elseif ($PidFile) {
        # De lai cho nguoi van hanh -> xoa PID di, dung de lan khoi dong sau diet nham.
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
