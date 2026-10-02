"""Legătura cu Windows: scrisul în fereastra activă și tasta globală.

Totul prin `ctypes`, deliberat. `keyboard` și `pynput` ar face același lucru și
ar aduce două dependențe în plus, plus un hook global de tastatură — adică un
program de fundal care vede fiecare tastă apăsată în tot sistemul. Aici nu e
nevoie: `RegisterHotKey` cere sistemului să anunțe O combinație, nu să dea
acces la toate.
"""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ── Scrisul: SendInput cu KEYEVENTF_UNICODE ──────────────────────────────
#
# De ce nu „clipboard + Ctrl+V": ar presupune că Ctrl+V înseamnă „lipește" în
# aplicația țintă — fals în destule terminale — și ți-ar șterge clipboard-ul de
# fiecare dată. Unicode direct nu atinge nimic din afara ferestrei active.
#
# Măsurat pe 3 august, într-o casetă Tk: 400 de caractere, identice, cu
# diacritice și ghilimele curbe, în 0,78 s.

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _UNIUNE(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _UNIUNE)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def _unitati_utf16(text: str):
    """Caracter → unități UTF-16. Ce trece de BMP cere două evenimente, nu unul."""
    for ch in text:
        octeti = ch.encode("utf-16-le")
        for i in range(0, len(octeti), 2):
            yield int.from_bytes(octeti[i:i + 2], "little")


def _trimite(lot: list) -> None:
    vector = (INPUT * len(lot))(*lot)
    n = user32.SendInput(len(lot), vector, ctypes.sizeof(INPUT))
    if n != len(lot):
        raise OSError(f"SendInput a trimis {n} din {len(lot)} evenimente "
                      f"(eroare {ctypes.get_last_error()})")


def scrie(text: str, per_lot: int = 32, pauza: float = 0.002) -> None:
    """Textul, caracter cu caracter, în fereastra care are focusul.

    În loturi, nu tot dintr-o dată: unele aplicații pierd evenimente dintr-un
    bloc mare, iar o pauză de 2 ms per lot costă 24 ms pe 400 de caractere.
    """
    lot = []
    for unitate in _unitati_utf16(text):
        for sus in (0, KEYEVENTF_KEYUP):
            ev = INPUT(type=INPUT_KEYBOARD)
            ev.u.ki = KEYBDINPUT(wVk=0, wScan=unitate,
                                 dwFlags=KEYEVENTF_UNICODE | sus,
                                 time=0, dwExtraInfo=0)
            lot.append(ev)
        if len(lot) >= per_lot * 2:
            _trimite(lot)
            lot = []
            time.sleep(pauza)
    if lot:
        _trimite(lot)


# ── Focusul: unde ajunge textul ──────────────────────────────────────────
#
# Capcana: dacă apeși butonul „Stop" cu mouse-ul, fereastra ASTA primește
# focusul, și textul s-ar scrie în ea, nu în caseta în care dictai. Două apărări,
# fiindcă niciuna singură nu acoperă tot:
#
#   1. WS_EX_NOACTIVATE — clickul pe butoane nu mai activează fereastra deloc;
#   2. ținem minte fereastra din care s-a pornit dictarea și i-o dăm înapoi.
#
# A doua e cea care chiar contează, iar SetForegroundWindow are voie exact în
# cazul ăsta: un proces care E în prim-plan poate ceda prim-planul altcuiva.

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000

# WS_EX_NOACTIVATE scoate fereastra de pe bara de activități — Windows nu dă
# buton unei ferestre care nu poate fi activată. Consecința: minimizată,
# unealta a dispărut fără urmă, părea închisă și a fost pornită a doua oară. A doua instanță n-a mai avut memorie pentru
# model și s-a plâns de `mkl_malloc` — o eroare care trimite pe oricine să caute
# RAM, nu o fereastră pierdută.
#
# WS_EX_APPWINDOW e remediul documentat: forțează butonul înapoi pe bară, fără
# să atingă NOACTIVATE, deci apărarea pentru care există NOACTIVATE rămâne.
WS_EX_APPWINDOW = 0x00040000


def fereastra_activa() -> int:
    return user32.GetForegroundWindow()


def titlu(hwnd: int) -> str:
    """Titlul ferestrei, ca omul să VADĂ unde se va scrie, nu să ghicească."""
    if not hwnd:
        return ""
    lungime = user32.GetWindowTextLengthW(hwnd)
    if lungime <= 0:
        return ""
    tampon = ctypes.create_unicode_buffer(lungime + 1)
    user32.GetWindowTextW(hwnd, tampon, lungime + 1)
    return tampon.value


def activeaza(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.SetForegroundWindow(hwnd))


def fara_activare(hwnd: int) -> None:
    """Fereastra nu mai fură focusul când dai click în ea, dar rămâne pe bară.

    Cele două flaguri merg împreună: fără APPWINDOW, NOACTIVATE ar face unealta
    să dispară complet la minimizare (vezi comentariul de la constante).

    **Doar stilurile.** Bara de activități are nevoie și de un ciclu
    ascunde/arată ca să reevalueze lista — dar acela se face prin Tk
    (`withdraw`/`deiconify`), nu cu `ShowWindow` de aici. Prima versiune îl
    făcea de aici și a înghețat fereastra la 136x45, cu 6 pixeli de conținut:
    `ShowWindow` a prins-o înainte ca Tk să-și fi așezat geometria, iar Tk n-a
    aflat niciodată. **Ce mută fereastra pe la spatele lui Tk, Tk nu poate
    repara.**
    """
    stil = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                          stil | WS_EX_NOACTIVATE | WS_EX_APPWINDOW)


def hwnd_toplevel(id_tkinter: int) -> int:
    """`root.winfo_id()` dă fereastra-copil. Cadrul cu bara de titlu e părintele."""
    return user32.GetParent(id_tkinter) or id_tkinter


# ── O singură instanță ───────────────────────────────────────────────────
#
# A doua pornire costa 4 GB de memorie rezervată pe care mașina nu-i avea, și
# cădea cu `mkl_malloc: failed to allocate memory`. Verificarea se face ÎNAINTE
# de încărcarea modelului, fiindcă tocmai încărcarea e cea care cade.
#
# Mutex numit, nu „caut o fereastră cu titlul Iris": mutexul e ținut de
# sistem și dispare singur când procesul moare, oricum ar muri. Un fișier de
# blocare ar supraviețui unei căderi și ar refuza pornirea următoare.
#
# `Local\` — vizibil doar în sesiunea utilizatorului curent, nu în tot sistemul.

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ERROR_ALREADY_EXISTS = 183

_mutex = None


def suntem_singura_instanta(nume: str = r"Local\Iris_instanta_unica") -> bool:
    """True dacă suntem primii. Mutexul se ține până moare procesul."""
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, nume)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS

# Cum cere a doua instanță ca prima să se arate: prin `arata.semnal`, citit de
# bucla Tk a primeia. NU prin `ShowWindow` din afară.
#
# `ShowWindow(SW_RESTORE)` dintr-un alt proces pare să meargă și eșuează în
# două feluri: pe o fereastră minimizată de Tk (`iconify`) lasă Tk convins că e
# tot minimizată, iar `SetForegroundWindow` nu are dreptul să dea prim-planul
# altcuiva decât dintr-un proces care e deja în prim-plan — a doua instanță nu e
# niciodată. Restaurarea o face Tk, din firul lui, unde e singurul loc în care
# starea rămâne întreagă.


# ── Tasta globală: RegisterHotKey ────────────────────────────────────────
#
# Combinația e prinsă de sistem ÎNAINTE să ajungă la aplicația activă, deci nu
# se bate cu scurtăturile din VS Code. Mesajele vin în coada firului care a
# făcut înregistrarea — de-asta bucla de mai jos trăiește pe firul ei, separat
# de tkinter, și vorbește cu fereastra printr-o funcție de anunț.

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_MODIFICATORI = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
                 "shift": MOD_SHIFT, "win": MOD_WIN}

_TASTE = {"space": 0x20, "spatiu": 0x20, "enter": 0x0D, "esc": 0x1B,
          "escape": 0x1B, "tab": 0x09, "backspace": 0x08, "insert": 0x2D,
          "delete": 0x2E, "home": 0x24, "end": 0x23,
          **{f"f{n}": 0x70 + n - 1 for n in range(1, 13)}}


def descifreaza_tasta(combinatie: str) -> tuple[int, int]:
    """„ctrl+alt+space" → (modificatori, cod). Ridică ValueError la ce nu știe."""
    bucati = [b.strip().lower() for b in combinatie.split("+") if b.strip()]
    if not bucati:
        raise ValueError("combinație goală")
    modificatori, cod = 0, None
    for bucata in bucati:
        if bucata in _MODIFICATORI:
            modificatori |= _MODIFICATORI[bucata]
        elif bucata in _TASTE:
            cod = _TASTE[bucata]
        elif len(bucata) == 1 and (bucata.isalpha() or bucata.isdigit()):
            cod = ord(bucata.upper())
        else:
            raise ValueError(f"tastă necunoscută: {bucata!r}")
    if cod is None:
        raise ValueError("lipsește tasta, sunt numai modificatori")
    if not modificatori:
        # Fără modificator, ai fura o tastă obișnuită din tot sistemul.
        raise ValueError("combinația are nevoie de cel puțin un modificator")
    return modificatori | MOD_NOREPEAT, cod


class TasteGlobale:
    """Bucla de mesaje pentru tastele globale. Se rulează pe firul ei."""

    def __init__(self):
        self._legaturi: dict[int, callable] = {}
        self._cereri: list[tuple[int, int, int, callable]] = []
        self.erori: list[str] = []

    def adauga(self, combinatie: str, ce_face) -> None:
        """Se cheamă ÎNAINTE de `ruleaza`. Înregistrarea se face pe firul buclei."""
        id_ = len(self._cereri) + 1
        modificatori, cod = descifreaza_tasta(combinatie)
        self._cereri.append((id_, modificatori, cod, ce_face))

    def ruleaza(self) -> None:
        """Înregistrează, apoi așteaptă mesaje. Blochează firul; e treaba lui."""
        for id_, modificatori, cod, ce_face in self._cereri:
            if user32.RegisterHotKey(None, id_, modificatori, cod):
                self._legaturi[id_] = ce_face
            else:
                # Combinația e deja luată de alt program. Nu e motiv de oprire:
                # butoanele din fereastră rămân singura ușă, ca înainte.
                self.erori.append(f"cod {ctypes.get_last_error()}")

        mesaj = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(mesaj), None, 0, 0) > 0:
            if mesaj.message == WM_HOTKEY:
                ce_face = self._legaturi.get(mesaj.wParam)
                if ce_face:
                    ce_face()
