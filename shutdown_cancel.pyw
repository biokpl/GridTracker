"""shutdown_cancel.pyw — akşam otomasyonu PC'yi kapatırken çıkan "İptal Et" penceresi.

evening_automation.pyw, 'shutdown /s /t N' verdikten hemen sonra bunu ayrı süreç olarak açar.
Pencere geri sayımı gösterir; "İptal Et" → 'shutdown /a' (kapatma iptal).
Süre dolarsa pencere kendiliğinden kapanır (Windows kapatmaya devam eder).

Test: python shutdown_cancel.pyw 30 --dry   (shutdown komutu çalıştırmaz)
"""
import subprocess, sys, time
import tkinter as tk
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).parent / "evening_automation.log"
NO_WIN = 0x08000000


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [INFO] {msg}\n")
    except Exception:
        pass


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    seconds = int(args[0]) if args else 120
    deadline = time.time() + seconds

    root = tk.Tk()
    root.title("GridTracker — PC kapanıyor")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.configure(bg="#0f172a")
    w, h = 380, 190
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 3}")

    tk.Label(root, text="Akşam analizi bitti", fg="#94a3b8", bg="#0f172a",
             font=("Segoe UI", 10)).pack(pady=(16, 0))
    lbl = tk.Label(root, text="", fg="#f8fafc", bg="#0f172a", font=("Segoe UI", 15, "bold"))
    lbl.pack(pady=(4, 14))

    def cancel():
        if not dry:
            subprocess.run(["shutdown", "/a"], creationflags=NO_WIN)
        log("PC kapatma kullanıcı tarafından İPTAL edildi (İptal Et butonu)." + (" [DRY]" if dry else ""))
        lbl.config(text="Kapatma iptal edildi ✓", fg="#4ade80")
        btn.config(state="disabled")
        root.after(2500, root.destroy)

    btn = tk.Button(root, text="İptal Et", command=cancel, font=("Segoe UI", 12, "bold"),
                    bg="#ef4444", fg="white", activebackground="#dc2626", activeforeground="white",
                    relief="flat", padx=28, pady=6, cursor="hand2")
    btn.pack()
    root.protocol("WM_DELETE_WINDOW", lambda: None)   # X ile kapatılıp yanlışlıkla iptal sanılmasın

    def tick():
        if str(btn["state"]) == "disabled":
            return
        left = int(deadline - time.time())
        if left <= 0:
            root.destroy()
            return
        lbl.config(text=f"PC {left // 60}:{left % 60:02d} sonra kapanacak")
        root.after(500, tick)

    tick()
    root.lift()
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    main()
