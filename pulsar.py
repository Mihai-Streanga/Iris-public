"""Pulsarul: corpul ceresc care spune starea uneltei, desenat cu numpy.

De ce nu din primitivele Tk: canvas-ul lui Tk n-are alfa, n-are elipsă rotită și
n-are margini netede. Un halou făcut din cercuri concentrice bandează, iar o
elipsă rotită s-ar face din poligoane cu colțuri. Aici se randează un cadru RGB
în numpy — dependență pe care unealta o are deja — și i se dă lui Tk ca PNG.

**Cifrele geometriei sunt fixe, și nu din capriciu:** halou de la R*0.2 la R*1.9,
două elipse care se rotesc în sensuri opuse, particule pe o sferă turtită la
0.74, miez la R*0.08. Au fost reglate la vedere, una câte una, până desenul a
arătat cum trebuie. Rezultatul nu se poate verifica din cod — deci cine schimbă
una plătește aceeași rundă de privit pe ecran.

Două mecanisme spun starea prin mișcare, nu prin culoare:

    burst  — particulele zboară în afară cu nivelul microfonului (factor 7)
    strang — elipsele se strâng spre centru cât se lucrează (oprit în iris.py:
             diferența de mărime se citea ca „altă unealtă", nu „altă stare")

Modulul nu știe nimic despre dictare. Primește o stare și două numere.
"""
import struct
import zlib

import numpy as np

# ── Paleta ───────────────────────────────────────────────────────────────

HULL = (0x06, 0x08, 0x0C)          # fundalul, aproape negru

# Ce culoare are pulsarul în fiecare stare. Repartiția NU urmează convenția
# obișnuită, unde chihlimbariul înseamnă „aprins" și roșul „stricat". Criteriul
# e altul: **roșul e cel mai spectaculos, deci merge unde te uiți cel mai des**
# — la ascultat. Chihlimbariul trece la transcriere. Starea în care unealta stă
# cel mai mult e „gata", deci acolo merge culoarea care merită privită, violetul;
# eroarea primește o nuanță rece, ca să nu semene cu nicio stare de lucru.
MIEZ = {
    "incarc": (70, 88, 104),        # gri stins: încă nu trăiește
    "gata": (150, 138, 232),        # violet rece
    "ascult": (192, 86, 58),        # roșu
    "transcriu": (240, 163, 66),    # chihlimbariu
    "eroare": (120, 165, 200),      # gheață
}


def culoare_stare(stare: str) -> tuple[int, int, int]:
    return MIEZ.get(stare, MIEZ["incarc"])


# ── PNG, ca să nu intre o dependență pentru un antet de 8 octeți ─────────
#
# Tk 8.6 citește PNG nativ. Comprimarea e la nivel 1 dinadins: cadrul se
# aruncă în 50 ms, deci mărimea lui nu contează, timpul da.

def png(rgb: np.ndarray) -> bytes:
    """(h, w, 3) sau (h, w, 4) uint8 → octeții unui PNG.

    Cu patru canale iese un PNG cu transparență (tip 6), de care are nevoie
    pictograma: o pictogramă pe fundal negru ar fi un pătrat pe bara de
    activități, nu un pulsar.
    """
    h, w, canale = rgb.shape
    tip = 6 if canale == 4 else 2
    # Un octet de filtru (0 = niciunul) în fața fiecărui rând.
    brut = np.zeros((h, w * canale + 1), dtype=np.uint8)
    brut[:, 1:] = rgb.reshape(h, w * canale)

    def bucata(eticheta: bytes, date: bytes) -> bytes:
        return (struct.pack(">I", len(date)) + eticheta + date
                + struct.pack(">I", zlib.crc32(eticheta + date) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + bucata(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, tip, 0, 0, 0))
            + bucata(b"IDAT", zlib.compress(brut.tobytes(), 1))
            + bucata(b"IEND", b""))


def ppm(rgb: np.ndarray) -> bytes:
    """(h, w, 3) uint8 → octeții unui PPM binar (P6), pe care Tk îl citește tot.

    Fără comprimare: mai mulți octeți de dus, dar niciun zlib de desfăcut la
    celălalt capăt.
    """
    h, w, _ = rgb.shape
    return b"P6\n%d %d\n255\n" % (w, h) + rgb.tobytes()


class Pulsar:
    """Un corp ceresc, la dimensiunea unei ferestre de unealtă.

    **Particulele se nasc o dată, la construcție** (`th`, `ph`, `rr`, `sp`, `sz`,
    `tw`), din aceeași sămânță. Dacă s-ar naște la fiecare cadru, corpul ar
    scânteia aleator în loc să se rotească — și scânteierea aleatoare nu se
    citește ca mișcare, se citește ca zgomot.
    """

    def __init__(self, latura: int = 240, raza: float = 60.0,
                 fundal: tuple[int, int, int] = HULL, samanta: int = 5,
                 taria: float = 1.0):
        self.latura = latura
        self.raza = raza
        self.fundal = np.array(fundal, dtype=np.float32)
        self.taria = taria
        # Grosimea liniilor crește cu raza. Cifra de la care s-a pornit era 0,9 px
        # pe un disc de 115 px, la scara 1. Aici pulsarul e desenat la pixeli
        # FIZICI, deci pe un ecran la 175% aceleași 1,5 px ies de două ori mai
        # subțiri decât trebuie — și exact asta se vedea: elipse care dispăreau
        # pe fundaluri deschise. Găsit prin folosire, nu prin citit codul.
        self.gros = max(1.0, raza / 52.0)

        gen = np.random.default_rng(samanta)
        n = int(round(raza * 2.3))          # câte particule: crește cu raza
        self.th = gen.random(n) * 2 * np.pi
        self.ph = gen.random(n) * 2 * np.pi
        self.rr = 0.5 + gen.random(n) * 0.62
        self.sp = ((0.15 + gen.random(n) * 0.5)
                   * np.where(gen.random(n) < 0.5, -1.0, 1.0))
        self.sz = 0.7 + gen.random(n) * 1.8
        self.tw = gen.random(n) * 2 * np.pi

        # Grila de coordonate se face o dată. La 240x240 sunt 57.600 de puncte;
        # refăcute la fiecare cadru ar fi singura risipă reală din buclă.
        y, x = np.mgrid[0:latura, 0:latura].astype(np.float32)
        self.c = (latura - 1) / 2.0
        self.x = x - self.c
        self.y = y - self.c
        self.dist = np.hypot(self.x, self.y).astype(np.float32)

        # Peticul unei particule, o dată. Raza maximă e sz*(0.5+0.9) = 3,5 px,
        # deci 11x11 acoperă orice particulă cu tot cu marginea netedă.
        self.petic = 11
        o = np.arange(self.petic, dtype=np.float32) - self.petic // 2
        self.oy = o[None, :, None]
        self.ox = o[None, None, :]

    # ── desenul ──────────────────────────────────────────────────────────

    def alfa(self, t: float, stare: str = "gata", nivel: float = 0.0,
             strang: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """Harta de transparență a pulsarului, plus culoarea lui.

        **Toate cele patru straturi au aceeași culoare**, deci nu se compun pe
        rând peste imagine — se adună într-o singură hartă, iar culoarea se pune
        o dată, la sfârșit. Suprapunerea „peste" se scrie atunci ca un produs:
        ce rămâne din fundal e produsul lui (1-alfa). Prima versiune compunea de
        cinci ori peste 172.800 de numere și costa 13,8 ms pe cadru — 27%
        dintr-un nucleu, degeaba.

        Se întoarce harta, nu imaginea, fiindcă are doi clienți: fereastra
        obișnuită, care o pune peste culoarea cocii, și fereastra liberă, care o
        dă Windows-ului ca transparență adevărată.
        """
        col = np.array(culoare_stare(stare), dtype=np.float32)
        aprins = stare != "incarc"
        R = self.raza
        # Respirația: doar cât stă degeaba. În lucru, mișcarea o dau burst-ul
        # și strângerea, iar o a treia pulsație peste ele face pastă.
        if stare == "gata":
            R *= 1.0 + 0.018 * float(np.sin(t * 1.1))

        # `ramas` = cât se vede din fundal. Începe întreg și scade cu fiecare strat.
        interior, exterior = R * 0.2, R * 1.9
        halou = np.clip((exterior - self.dist) / (exterior - interior), 0.0, 1.0)
        ramas = 1.0 - halou * (0.26 if aprins else 0.08)

        sg = 1.0 - strang * 0.28
        self._elipsa(ramas, R * 1.18 * sg, R * 0.44 * sg, t * 0.10,
                     0.68 if aprins else 0.30, 1.5 * self.gros)
        self._elipsa(ramas, R * 0.90 * sg, R * 1.12 * sg, -t * 0.07 + 0.9,
                     0.46 if aprins else 0.18, 1.2 * self.gros)
        ramas *= 1.0 - self._particule(t, R, nivel, aprins)
        self._miez(ramas, max(3.0, R * 0.08), 1.0 if aprins else 0.45)

        return np.clip((1.0 - ramas) * self.taria, 0.0, 1.0), col

    def cadru(self, t: float, stare: str = "gata", nivel: float = 0.0,
              strang: float = 0.0) -> np.ndarray:
        """Un cadru RGB, pus peste culoarea cocii. Pentru fereastra cu fundal.

        Culoarea se pune printr-un tabel de 256 de trepte, nu cu o înmulțire pe
        fiecare din cele 172.800 de componente. Ieșirea are oricum 8 biți, deci
        treptele nu se văd — se văd doar în cronometru.
        """
        a, col = self.alfa(t, stare, nivel, strang)
        trepte = np.linspace(0.0, 1.0, 256, dtype=np.float32)[:, None]
        tabel = (self.fundal + (col - self.fundal) * trepte
                 ).clip(0, 255).astype(np.uint8)
        return tabel[(a * 255.0).astype(np.uint8)]

    # ── unelte de desen: fiecare lucrează pe loc, în dreptunghiul ei ─────

    def _fereastra(self, ax: float, ay: float, margine: float
                   ) -> tuple[slice, slice] | None:
        """Dreptunghiul din jurul centrului în care are rost să se calculeze."""
        mx = int(ax + margine) + 1
        my = int(ay + margine) + 1
        i0, i1 = max(0, int(self.c) - my), min(self.latura, int(self.c) + my + 1)
        j0, j1 = max(0, int(self.c) - mx), min(self.latura, int(self.c) + mx + 1)
        if i0 >= i1 or j0 >= j1:
            return None
        return slice(i0, i1), slice(j0, j1)

    def _elipsa(self, ramas: np.ndarray, rx: float, ry: float, unghi: float,
                alfa: float, grosime: float) -> None:
        """Contur de elipsă rotită, cu margini netede.

        `f` e distanța normalizată: 1 exact pe curbă. Înmulțită cu semiaxa
        mică dă o distanță aproximativă în pixeli — suficient pentru o linie
        de un pixel și jumătate, și mult mai ieftin decât distanța adevărată
        până la o elipsă, care n-are formulă închisă.

        Se calculează doar în dreptunghiul elipsei. La R=60 aia e mai puțin de
        jumătate din imagine, și e o elipsă care se rotește, deci dreptunghiul
        se recalculează la fiecare cadru — din cosinusuri, nu din pixeli.
        """
        c, s = float(np.cos(unghi)), float(np.sin(unghi))
        f = self._fereastra(np.hypot(rx * c, ry * s), np.hypot(rx * s, ry * c),
                            grosime + 1.0)
        if f is None:
            return
        x, y = self.x[f], self.y[f]
        u = (x * c + y * s) / max(rx, 1e-6)
        v = (y * c - x * s) / max(ry, 1e-6)
        d = np.abs(np.sqrt(u * u + v * v) - 1.0) * min(rx, ry)
        ramas[f] *= 1.0 - np.clip(grosime - d, 0.0, 1.0) * alfa

    def _miez(self, ramas: np.ndarray, raza: float, alfa: float) -> None:
        f = self._fereastra(raza, raza, 1.0)
        if f is not None:
            ramas[f] *= 1.0 - np.clip(raza - self.dist[f] + 0.5, 0.0, 1.0) * alfa

    def _particule(self, t: float, R: float, nivel: float,
                   aprins: bool) -> np.ndarray:
        """Sfera turtită de particule, toate deodată.

        Peticele celor 138 de particule se calculează ca un singur bloc
        (138, 11, 11) și se varsă în hartă cu `bincount`. Varianta cu o buclă
        Python peste particule costa 9 ms din cele 13,8: nu aritmetica, ci
        cele o mie și ceva de apeluri numpy pe petice de 5x5.

        Transparențele se **adună**, nu se compun: particulele aproape nu se
        suprapun, iar unde o fac, două scântei una peste alta arată la fel.
        """
        th = self.th + t * self.sp
        sinph = np.sin(self.ph)
        adanc = (np.sin(th) * sinph + 1.0) / 2.0
        rr = R * self.rr * (1.0 + nivel * 0.55)
        xs = self.c + np.cos(th) * sinph * rr
        ys = self.c + np.cos(self.ph) * 0.74 * rr

        raze = (self.sz * (0.5 + adanc * 0.9))[:, None, None]
        licar = 0.6 + 0.4 * np.sin(t * 2 + self.tw)
        tarie = ((0.24 + adanc * 0.76) * licar
                 * (1.0 if aprins else 0.5))[:, None, None]

        # Centrul întreg al peticului, plus abaterea până la centrul adevărat:
        # așa marginea rămâne netedă chiar dacă peticul stă pe pixeli întregi.
        iy = np.rint(ys).astype(np.int32)
        ix = np.rint(xs).astype(np.int32)
        dy = self.oy - (ys - iy)[:, None, None]
        dx = self.ox - (xs - ix)[:, None, None]
        alfa = np.clip(raze - np.sqrt(dy * dy + dx * dx) + 0.5, 0.0, 1.0) * tarie

        rand = iy[:, None, None] + self.oy.astype(np.int32)
        col = ix[:, None, None] + self.ox.astype(np.int32)
        bun = ((rand >= 0) & (rand < self.latura)
               & (col >= 0) & (col < self.latura))
        indici = np.where(bun, rand * self.latura + col, 0).ravel()
        greutati = np.where(bun, alfa, 0.0).ravel()
        harta = np.bincount(indici, greutati, minlength=self.latura ** 2)
        return np.clip(harta.reshape(self.latura, self.latura), 0.0, 1.0
                       ).astype(np.float32)
