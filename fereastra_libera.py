"""Fereastră fără nicio formă: pixelii ei au transparență adevărată.

De ce nu `overrideredirect(True)` — drumul evident. Fiindcă e un steag al lui
**Tk**, iar Tk refuză apoi să-și mai minimizeze propria fereastră: „can't
iconify: override-redirect flag is set" (măsurat 3 august). Minimizarea ar fi
trebuit făcută cu `ShowWindow`, pe la spatele lui Tk — exact drumul care a
înghețat fereastra la 136x45 cu o zi înainte.

Aici cadrul se scoate din **stilurile Windows**, nu din Tk. Tk rămâne convins că
are o fereastră obișnuită, deci `iconify`/`deiconify`, butonul de pe bara de
activități și restaurarea din a doua instanță merg neatinse.

De ce nu `-transparentcolor` — cealaltă cale evidentă. Aia e transparență pe
DA/NU: un pixel ori dispare de tot, ori rămâne întreg. Marginea netedă a
pulsarului ar fi ieșit dințată, sau cu un halou din culoarea-cheie. Cu
`UpdateLayeredWindow` fiecare pixel are transparența lui, deci haloul se stinge
lin în desktop, cum se stinge la marginea unui desen adevărat.

Bonus care nu se putea altfel: **zonele transparente lasă clickul să treacă**.
Colțurile din jurul discului nu mai sunt fereastră, sunt aer.
"""
import ctypes
from ctypes import wintypes

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_APPWINDOW = 0x00040000
SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER = 0x0002, 0x0001, 0x0004
SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0010, 0x0020
BI_RGB, DIB_RGB_COLORS = 0, 0
AC_SRC_OVER, AC_SRC_ALPHA, ULW_ALPHA = 0x00, 0x01, 0x02


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


# Prototipurile NU sunt zel. Fără ele, ctypes ghicește `c_int` pentru fiecare
# mâner, iar pe 64 de biți asta merge exact până când sistemul dă un mâner mai
# mare de 2³¹ — și atunci cade cu „int too long to convert", într-un loc care
# funcționase de zeci de ori. Prins pe 3 august, la a doua pornire.
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = (wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD)
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
gdi32.DeleteDC.argtypes = (wintypes.HDC,)
gdi32.SetBkMode.argtypes = (wintypes.HDC, ctypes.c_int)
gdi32.SetTextColor.argtypes = (wintypes.HDC, wintypes.DWORD)
gdi32.SetTextCharacterExtra.argtypes = (wintypes.HDC, ctypes.c_int)
gdi32.TextOutW.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int,
                           wintypes.LPCWSTR, ctypes.c_int)
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = (wintypes.HWND,)
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
user32.UpdateLayeredWindow.argtypes = (
    wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p,
    wintypes.HDC, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD)


class Panza:
    """Suprafața de desen a unei ferestre libere. Se face o dată, la pornire.

    DIB-ul se alocă **o singură dată** și se rescrie în loc. Un `CreateDIBSection`
    la fiecare cadru ar fi 20 de alocări pe secundă de câte 700 KB, și fiecare
    cere sistemului memorie de desen — nu memoria procesului, care e ieftină.
    """

    def __init__(self, hwnd: int, latime: int, inaltime: int | None = None):
        inaltime = latime if inaltime is None else inaltime
        self.hwnd = wintypes.HWND(hwnd)
        self.latime, self.inaltime = latime, inaltime

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = latime
        # Negativ = rândurile stau de sus în jos, ca în numpy. Pozitiv ar
        # însemna de jos în sus, iar desenul ar ieși răsturnat — o eroare care
        # arată a bug de geometrie, nu de format.
        info.bmiHeader.biHeight = -inaltime
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB

        self.biti = ctypes.c_void_p()
        self.hdc = gdi32.CreateCompatibleDC(None)
        self.harta = gdi32.CreateDIBSection(
            self.hdc, ctypes.byref(info), DIB_RGB_COLORS,
            ctypes.byref(self.biti), None, 0)
        if not self.harta:
            raise OSError(f"CreateDIBSection: {ctypes.get_last_error()}")
        self.vechea = gdi32.SelectObject(self.hdc, self.harta)

        self.amestec = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        self.marimea = SIZE(latime, inaltime)
        self.origine = wintypes.POINT(0, 0)

    def scoate_cadrul(self) -> None:
        """Distruge stilurile ferestrei? Nu — doar eliberează desenul."""
        if self.harta:
            gdi32.SelectObject(self.hdc, self.vechea)
            gdi32.DeleteObject(self.harta)
            gdi32.DeleteDC(self.hdc)
            self.harta = None

    def arata(self, bgra: np.ndarray) -> None:
        """Un cadru BGRA premultiplicat, direct pe ecran.

        Nu trece prin Tk deloc: Windows compune el fereastra din harta asta.
        Consecința e că `tk.Canvas` de dedesubt nu se mai vede — de-asta tot ce
        se arată, inclusiv textul, trebuie să fie în harta asta.
        """
        ctypes.memmove(self.biti, bgra.ctypes.data, bgra.nbytes)
        ecran = user32.GetDC(None)
        try:
            ok = user32.UpdateLayeredWindow(
                self.hwnd, ecran, None, ctypes.byref(self.marimea),
                self.hdc, ctypes.byref(self.origine), 0,
                ctypes.byref(self.amestec), ULW_ALPHA)
            if not ok:
                raise OSError(f"UpdateLayeredWindow: {ctypes.get_last_error()}")
        finally:
            user32.ReleaseDC(None, ecran)


# ── Textul ───────────────────────────────────────────────────────────────
#
# Pe o fereastră compusă de Windows din harta noastră, Tk nu mai desenează
# nimic: nici `create_text`, nici un `Label`. Deci textul se desenează tot aici.
#
# GDI, nu o bibliotecă de imagini: fonturile instalate sunt deja în sistem, cu
# hinting și anti-aliasing făcute de Windows. O bibliotecă în plus ar fi adus
# altă randare decât restul sistemului, pentru un rând de text.

CLEARTYPE_QUALITY = 5
DEFAULT_CHARSET = 1
FW_NORMAL, FW_SEMIBOLD = 400, 600
TRANSPARENT_BK = 1

gdi32.CreateFontW.restype = wintypes.HGDIOBJ
gdi32.GetTextExtentPoint32W.argtypes = (wintypes.HDC, wintypes.LPCWSTR,
                                        ctypes.c_int, ctypes.POINTER(SIZE))


def masca_text(text: str, familie: str, inaltime: int,
               gros: bool = False, spatiat: float = 0.0) -> np.ndarray:
    """Textul, ca hartă de transparență (h, w) în 0..1. Fără culoare.

    Culoarea se pune la compunere, ca la pulsar: aceeași hartă poate fi scrisă
    o dată în gheață și o dată în chihlimbariu, fără s-o redesenăm.

    `spatiat` e rărirea dintre litere, în fracțiuni din înălțime — Tk n-are
    letter-spacing, GDI are (`SetTextCharacterExtra`). Fără el, rândul de stare,
    care e scris cu majuscule, arată înghesuit.
    """
    if not text:
        return np.zeros((1, 1), dtype=np.float32)

    hdc = gdi32.CreateCompatibleDC(None)
    font = gdi32.CreateFontW(-int(inaltime), 0, 0, 0,
                             FW_SEMIBOLD if gros else FW_NORMAL,
                             0, 0, 0, DEFAULT_CHARSET, 0, 0,
                             CLEARTYPE_QUALITY, 0, familie)
    vechiul_font = gdi32.SelectObject(hdc, font)
    gdi32.SetTextCharacterExtra(hdc, int(spatiat * inaltime))

    marime = SIZE()
    gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(marime))
    # Marginea: anti-aliasingul iese uneori cu un pixel în afara casetei
    # măsurate, iar acolo textul s-ar tăia exact pe diagonala unei litere.
    w = max(1, marime.cx + int(spatiat * inaltime) + 2)
    h = max(1, marime.cy + 2)

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = BI_RGB
    biti = ctypes.c_void_p()
    harta = gdi32.CreateDIBSection(hdc, ctypes.byref(info), DIB_RGB_COLORS,
                                   ctypes.byref(biti), None, 0)
    vechea = gdi32.SelectObject(hdc, harta)

    # Alb pe negru: cât de aprins e un pixel = cât de plin e de literă. Asta e
    # exact transparența căutată, fără să ne intereseze culoarea de aici.
    gdi32.SetBkMode(hdc, TRANSPARENT_BK)
    gdi32.SetTextColor(hdc, 0x00FFFFFF)
    gdi32.TextOutW(hdc, 1, 1, text, len(text))
    gdi32.GdiFlush()

    brut = np.ctypeslib.as_array(
        ctypes.cast(biti, ctypes.POINTER(ctypes.c_ubyte)), shape=(h, w, 4))
    # Cel mai aprins canal, nu media: ClearType colorează marginile pe
    # subpixeli, iar media ar subția literele.
    masca = brut[:, :, :3].max(axis=2).astype(np.float32) / 255.0

    gdi32.SelectObject(hdc, vechea)
    gdi32.DeleteObject(harta)
    gdi32.SelectObject(hdc, vechiul_font)
    gdi32.DeleteObject(font)
    gdi32.DeleteDC(hdc)
    return masca


class Scena:
    """Straturi cu culori diferite, compuse într-un singur cadru BGRA.

    Pulsarul singur n-avea nevoie de asta — avea o singură culoare, deci
    transparențele se puteau înmulți între ele. Cu text de altă culoare
    deasupra, compunerea trebuie făcută cum se cuvine: `sursă PESTE ce era`,
    în ordinea desenării.

    Fiecare strat se compune **doar în dreptunghiul lui**. Un rând de text de
    200x30 pus peste tot cadrul ar costa de patruzeci de ori mai mult decât
    costă.
    """

    def __init__(self, latime: int, inaltime: int):
        self.latime, self.inaltime = latime, inaltime
        self.rgb = np.zeros((inaltime, latime, 3), dtype=np.float32)
        self.a = np.zeros((inaltime, latime), dtype=np.float32)

    def curata(self) -> None:
        self.rgb[:] = 0.0
        self.a[:] = 0.0

    def pune(self, masca: np.ndarray, culoare, x: int, y: int,
             taria: float = 1.0) -> None:
        """`x`, `y` sunt colțul din stânga-sus. Se taie la marginile cadrului."""
        h, w = masca.shape
        i0, j0 = max(0, y), max(0, x)
        i1, j1 = min(self.inaltime, y + h), min(self.latime, x + w)
        if i0 >= i1 or j0 >= j1:
            return
        sa = masca[i0 - y:i1 - y, j0 - x:j1 - x] * taria
        if sa.max() <= 0.0:
            return
        col = np.asarray(culoare, dtype=np.float32)
        rgb = self.rgb[i0:i1, j0:j1]
        a = self.a[i0:i1, j0:j1]
        ramas = 1.0 - sa
        rgb *= ramas[:, :, None]
        rgb += sa[:, :, None] * col
        a *= ramas
        a += sa

    def centrat(self, masca: np.ndarray, culoare, y: int,
                taria: float = 1.0) -> None:
        self.pune(masca, culoare, (self.latime - masca.shape[1]) // 2, y, taria)

    def bgra(self) -> np.ndarray:
        """Premultiplicat, cum cere `AC_SRC_ALPHA`.

        `self.rgb` e deja înmulțit cu transparența lui la fiecare compunere,
        deci aici nu se mai înmulțește nimic — se doar reordonează canalele.
        """
        iesire = np.empty((self.inaltime, self.latime, 4), dtype=np.uint8)
        for i, canal in enumerate((2, 1, 0)):
            iesire[:, :, i] = np.clip(self.rgb[:, :, canal], 0, 255)
        iesire[:, :, 3] = np.clip(self.a * 255.0, 0, 255)
        return iesire


def dezbraca(hwnd: int) -> None:
    """Scoate bara de titlu și rama, la nivel de Windows, nu de Tk.

    `WS_CAPTION` ține bara de titlu, `WS_THICKFRAME` marginea de redimensionat.
    Ce **rămâne** e la fel de important: `WS_MINIMIZEBOX` și `WS_SYSMENU`, adică
    dreptul ferestrei de a fi minimizată și de a avea buton pe bară.

    `SWP_FRAMECHANGED` e obligatoriu: fără el Windows păstrează rama veche în
    cache și fereastra rămâne cu un contur fantomă până la prima redimensionare.
    """
    stil = user32.GetWindowLongW(hwnd, GWL_STYLE)
    user32.SetWindowLongW(hwnd, GWL_STYLE, stil & ~(WS_CAPTION | WS_THICKFRAME))
    extins = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                          extins | WS_EX_LAYERED | WS_EX_APPWINDOW)
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                        | SWP_NOACTIVATE | SWP_FRAMECHANGED)
