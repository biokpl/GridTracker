' bist100_fiyat_guncelle.vbs
' MatriksIQ DDE baglantisini guncelleyip Excel dosyasini kaydeder.
' Her 1 dakikada bir calisir (Task Scheduler ile tetiklenir).

Dim xl, wb
Dim dosya : dosya = "C:\Users\BioCSI\CLAUDE\GridTracker\Bist100 - Anlık Fiyat.xlsx"

On Error Resume Next

Set xl = CreateObject("Excel.Application")
xl.Visible = False
xl.DisplayAlerts = False
xl.AskToUpdateLinks = False

Set wb = xl.Workbooks.Open(dosya, UpdateLinks:=1)

If Err.Number <> 0 Then
    WScript.Quit 1
End If

' DDE baglantilarini guncelle
wb.UpdateLinks

' 3 saniye bekle (DDE verilerinin gelmesi icin)
WScript.Sleep 3000

' Kaydet
wb.Save
wb.Close False
xl.Quit

Set wb = Nothing
Set xl = Nothing

WScript.Quit 0
