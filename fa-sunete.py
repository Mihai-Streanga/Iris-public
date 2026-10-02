"""Face cele patru sunete ale dictării, ca fișiere WAV.

De ce nu se iau din `C:\\Windows\\Media`: alea sunt notificări de sistem —
scurte, ascuțite, făcute să întrerupă. Aici sunt semnalele unei unelte pe care o
folosești de zeci de ori pe zi, deci trebuie să nu obosească: o invitație de a
vorbi la pornire, ceva liniștitor la sfârșit — nu bipul clasic.

Nimic din folderul Windows nu seamănă a apă. Se sintetizează.

Se rulează o dată, din folderul proiectului:

    .venv\\Scripts\\python.exe fa-sunete.py

Fișierele rezultate intră în depozit alături de scriptul care le face — ca pe o
mașină nouă să meargă fără să rulezi nimic, dar să se poată și reface.

Nivelul nu contează aici: programul renormalizează după RMS la încărcare. Ce
contează e **caracterul**.
"""
import wave
from pathlib import Path

import numpy as np

RATA = 44100
ACASA = Path(__file__).resolve().parent / "sunete"


def infasoara(n: int, atac: float, caderea: float) -> np.ndarray:
    """Plic fără discontinuități. Orice colț ascuțit se aude ca un pocnet."""
    a = max(1, int(atac * RATA))
    c = max(1, int(caderea * RATA))
    sustinut = max(0, n - a - c)
    return np.concatenate([
        (1 - np.cos(np.linspace(0, np.pi, a))) / 2,      # urcare lină
        np.ones(sustinut),
        (1 + np.cos(np.linspace(0, np.pi, c))) / 2,      # coborâre lină
    ])[:n]


def nota(frecventa: float, durata: float, atac=0.012, caderea=None) -> np.ndarray:
    """Un ton cald: fundamentala plus două armonice slabe.

    Sinusul curat sună electronic. Armonicele îl apropie de un instrument cu
    ciocănele — lemn lovit moale — care e exact registrul „invitație", nu „alarmă".
    """
    n = int(durata * RATA)
    t = np.arange(n) / RATA
    unda = (np.sin(2 * np.pi * frecventa * t)
            + 0.32 * np.sin(2 * np.pi * frecventa * 2 * t)
            + 0.10 * np.sin(2 * np.pi * frecventa * 3 * t))
    # Stingere exponențială peste plic: armonicele mor înaintea fundamentalei,
    # ca la orice corp care sună.
    return unda * np.exp(-t * 3.2) * infasoara(n, atac, caderea or durata * 0.5)


def amesteca(bucati: list[tuple[float, np.ndarray]]) -> np.ndarray:
    """Suprapune bucăți la momente date, în secunde."""
    lungime = max(int(cand * RATA) + len(u) for cand, u in bucati)
    iesire = np.zeros(lungime)
    for cand, unda in bucati:
        i = int(cand * RATA)
        iesire[i:i + len(unda)] += unda
    return iesire


def apa(durata: float, taiere: int = 90) -> np.ndarray:
    """Zgomot filtrat: un val care vine și se retrage.

    Zgomot alb trecut printr-o fereastră Hann (adică un filtru trece-jos) sună a
    apă. Ce-l face *val* și nu *sâsâit* e plicul lung — urcare de o treime din
    durată, coborâre de două treimi — plus o respirație lentă deasupra.
    """
    n = int(durata * RATA)
    zgomot = np.random.default_rng(11).normal(0, 1, n + taiere)
    nucleu = np.hanning(taiere)
    filtrat = np.convolve(zgomot, nucleu / nucleu.sum(), mode="same")[:n]

    t = np.arange(n) / RATA
    respiratie = 0.75 + 0.25 * np.sin(2 * np.pi * 0.9 * t - np.pi / 2)
    plic = infasoara(n, durata * 0.33, durata * 0.62)
    return filtrat * respiratie * plic


def drona(f0: float, f1: float, durata: float, atac=0.05, caderea=None,
          armonice=(1.0, 0.50, 0.26, 0.14, 0.07), batai=0.006) -> np.ndarray:
    """Un motor care se ambalează sau se stinge: fundamentală care alunecă.

    Trei lucruri o fac să sune a mașină, nu a fluier:

    **Alunecarea e exponențială**, nu liniară. Urechea aude raportul dintre
    frecvențe, nu diferența — o rampă liniară s-ar auzi grăbită la început și
    lălâie la sfârșit.

    **Armonicele intră pe rând**, nu deodată. Un corp care se încarcă își
    scoate parțialele treptat; toate din prima ar suna a orgă apăsată.

    **Bătăile.** Un al doilea corp la 0,6% distanță produce o pulsație lentă
    de câțiva herți — exact ce se aude într-o sală de mașini, și ce lipsește
    dintr-un ton sintetizat curat.
    """
    n = int(durata * RATA)
    t = np.arange(n) / RATA
    frecventa = f0 * (f1 / f0) ** (t / durata)
    # Faza se integrează; altfel, la frecvență variabilă, sin(2πft) sare.
    faza = 2 * np.pi * np.cumsum(frecventa) / RATA

    unda = np.zeros(n)
    for k, amplitudine in enumerate(armonice, start=1):
        intrare = np.clip((t / durata - (k - 1) * 0.11) / 0.22, 0, 1)
        unda += amplitudine * intrare * np.sin(k * faza)
    unda += 0.32 * np.sin(faza * (1 + batai))
    return unda * infasoara(n, atac, caderea if caderea is not None
                            else durata * 0.45)


def ciripit(f0: float, f1: float, durata: float = 0.07) -> np.ndarray:
    """Baleiajul subțire de deasupra: consola care confirmă, nu motorul.

    Scurt și slab dinadins. Dus mai tare, devine bipul de care unealtă asta a
    fugit de la prima oră de folosire.
    """
    n = int(durata * RATA)
    t = np.arange(n) / RATA
    faza = 2 * np.pi * np.cumsum(f0 * (f1 / f0) ** (t / durata)) / RATA
    return np.sin(faza) * np.hanning(n)


def scrie(nume: str, unda: np.ndarray) -> None:
    ACASA.mkdir(exist_ok=True)
    varf = np.abs(unda).max()
    date = np.int16(np.clip(unda / varf * 0.85, -1, 1) * 32767)
    cale = ACASA / f"{nume}.wav"
    with wave.open(str(cale), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATA)
        w.writeframes(date.tobytes())
    rms = np.sqrt((date.astype(np.float32) ** 2).mean()) / 32768
    print(f"  {nume:8} {len(date) / RATA:4.2f} s  RMS {rms:5.3f}  {cale}")


# ── Cele patru ───────────────────────────────────────────────────────────
#
# Intervalele nu sunt la întâmplare. „ascult" urcă o cvintă perfectă — intervalul
# deschis, care cere continuare; de-asta sună a întrebare, adică a invitație.
# „stop" e aceeași cvintă coborâtă: aceeași familie, sens invers, și le
# deosebești fără să te uiți la ecran.

def main() -> None:
    print("se fac:")

    # invitație de a vorbi: re → la, cvintă urcătoare, moale
    scrie("ascult", amesteca([(0.00, nota(587.33, 0.42)),
                              (0.13, nota(880.00, 0.55))]))

    # oglinda ei: la → re, coborâtoare
    scrie("stop", amesteca([(0.00, nota(880.00, 0.40)),
                            (0.13, nota(587.33, 0.60))]))

    # sfârșitul transcrierii: un val. Vine când te uiți deja la text, deci n-are
    # voie să cheme — doar să confirme.
    val = apa(1.35)
    scrie("gata", amesteca([(0.00, val * 1.0),
                            # un pic de corp sub el, ca să nu fie doar sâsâit
                            (0.15, nota(196.00, 0.9, atac=0.25) * 0.16)]))

    # eroare: tot moale, dar coborâtoare și minoră — se înțelege fără să sperie
    scrie("eroare", amesteca([(0.00, nota(440.00, 0.35)),
                              (0.16, nota(369.99, 0.55))]))

    # ── Al doilea set: sala de mașini ────────────────────────────────────
    #
    # Un motor care pornește și se oprește, ca pe puntea unei nave. Nu se
    # copiază nimic — se sintetizează ceva din aceeași familie.
    #
    # Fișierele vechi RĂMÂN. Care set e în uz spune `iris.json`, iar
    # alegerea se face cu urechea, nu aici.

    # Pornire: cvintă în sus, 110 → 165 Hz, cu consola confirmând la vârf.
    scrie("ascult-motor", amesteca([
        (0.00, drona(110.0, 165.0, 0.62, atac=0.05, caderea=0.30)),
        (0.40, ciripit(1500.0, 2500.0) * 0.09),
    ]))

    # Oprire: aceeași cvintă în jos, cu stingere mai lungă. Un motor nu se
    # oprește în același timp în care pornește.
    scrie("stop-motor", amesteca([
        (0.00, drona(165.0, 104.0, 0.95, atac=0.02, caderea=0.62)),
        (0.03, ciripit(2500.0, 1400.0) * 0.07),
    ]))

    # Consola: două impulsuri joase, la secundă mică — dizarmonice fără să
    # sperie. Moale, ca restul; e o unealtă folosită de zeci de ori pe zi.
    #
    # E **semnalul principal**: se aude și la pornirea urechii, și la oprire.
    def impulsuri(momente, durata) -> list:
        bucati = []
        for cand in momente:
            bucati.append((cand, nota(196.00, durata, atac=0.008,
                                      caderea=durata * 0.65)))
            bucati.append((cand, nota(207.65, durata, atac=0.008,
                                      caderea=durata * 0.65) * 0.8))
        return bucati

    scrie("consola", amesteca(impulsuri((0.00, 0.16), 0.11)))

    # Varianta lungă, pentru sfârșitul transcrierii: trei impulsuri mai late și
    # o rezonanță joasă sub ele, în locul valului de apă.
    scrie("consola-lung", amesteca(
        impulsuri((0.00, 0.20, 0.40), 0.17)
        + [(0.06, nota(98.00, 0.85, atac=0.22) * 0.13)]))

    # Refuzul devine cvinta urcătoare — sunetul care era la „ascultă". Sună a
    # întrebare, nu a alarmă, și acum e singurul lucru care întrerupe registrul
    # de consolă, deci se remarcă tocmai fiindcă e altfel.
    scrie("refuz", amesteca([(0.00, nota(587.33, 0.42)),
                             (0.13, nota(880.00, 0.55))]))

    print("\ngata. Pune-le în iris.json sub `sunete_fisiere`.")


if __name__ == "__main__":
    main()
