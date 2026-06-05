# -*- coding: utf-8 -*-
"""
ensure_dde.py — BIST100 DDE Excel'ini GÖRÜNMEZ açıp canlı fiyat feed'ini sağlar.

Neden: Canlı fiyatlar, MatriksIQ'nun "Bist100 - Anlık Fiyat.xlsx" dosyasına DDE
ile akıttığı verilerden okunur. Bu Excel normalde sabah otomasyonunda (Adım-6)
GÖRÜNMEZ açılır. PC gün ortasında çöker/yeniden başlarsa o görünmez Excel kapanır
ve sabah otomasyonu tekrar çalışmadığı için DDE feed'i geri gelmez → sistem Yahoo
(gecikmeli) fiyata düşer.

Bu modül self-healing sağlar: DDE düşmüşse ve MatriksIQ açıksa Excel'i tekrar
görünmez açar. monitor.pyw bunu periyodik çağırır; ayrıca elle de çalıştırılabilir:
    python ensure_dde.py
"""
import sys
import time
import subprocess
from pathlib import Path

EXCEL = Path(r"C:\Users\BioCSI\CLAUDE\GridTracker\Bist100 - Anlık Fiyat.xlsx")


def _matriks_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq MatriksIQ.exe"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "MatriksIQ.exe" in (out.stdout or "")
    except Exception:
        return False


def _valid(v) -> bool:
    return isinstance(v, (int, float)) and 0.01 <= v <= 100000


def dde_live() -> bool:
    """Açık 'Fiyat' workbook'unda C2:C7'de en az 3 geçerli fiyat var mı?"""
    import pythoncom
    import win32com.client as win32
    pythoncom.CoInitialize()
    try:
        xl = win32.GetObject(Class="Excel.Application")
        for wb in xl.Workbooks:
            if "Fiyat" in wb.Name:
                ws = wb.Sheets(1)
                ok = sum(1 for r in range(2, 8) if _valid(ws.Cells(r, 3).Value))
                return ok >= 3
        return False
    except Exception:
        return False
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def ensure(open_if_needed: bool = True):
    """
    DDE canlıysa (True, 'zaten-canli'); değilse ve MatriksIQ açıksa Excel'i
    görünmez açıp dener. Döner: (ok: bool, mesaj: str).
    """
    if dde_live():
        return True, "zaten-canli"
    if not open_if_needed:
        return False, "dde-yok"
    if not _matriks_running():
        return False, "matriks-kapali"
    if not EXCEL.exists():
        return False, "excel-dosyasi-yok"

    import pythoncom
    import win32com.client as win32
    pythoncom.CoInitialize()
    try:
        for deneme in range(1, 4):
            try:
                xl = win32.Dispatch("Excel.Application")
                xl.Visible = False
                xl.DisplayAlerts = False
                xl.AskToUpdateLinks = False
                # Aynı dosya yarım/bozuk açıksa kapat (temiz başlangıç)
                for w in list(xl.Workbooks):
                    if "Fiyat" in w.Name:
                        w.Close(SaveChanges=False)
                time.sleep(2)
                wb = xl.Workbooks.Open(str(EXCEL), UpdateLinks=3)
                xl.Visible = False
                time.sleep(8)  # DDE advise loop dolsun
                ws = wb.Sheets(1)
                ok = sum(1 for r in range(2, 8) if _valid(ws.Cells(r, 3).Value))
                if ok >= 3:
                    return True, f"acildi-canli({ok}/6,deneme{deneme})"
                time.sleep(10)  # MatriksIQ hazırlansın, tekrar dene
            except Exception as e:
                time.sleep(5)
                _last = str(e)
        return False, "dde-baglanamadi"
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


if __name__ == "__main__":
    ok, msg = ensure()
    print(f"DDE: {'OK' if ok else 'HATA'} — {msg}")
    sys.exit(0 if ok else 1)
