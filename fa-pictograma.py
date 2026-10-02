"""Face `iris.ico` din același pulsar care se vede în fereastră.

De ce e nevoie de un `.ico` și nu ajunge pictograma pusă din Tk: Tk o pune pe
fereastră, dar bara de activități are nevoie de una și pentru **scurtătura**
fixată acolo, iar scurtăturile Windows citesc doar `.ico`.

De ce se face aici și nu se ține un fișier binar în depozit: dacă se schimbă
culorile pulsarului, pictograma se reface dintr-o comandă și rămâne aceeași
familie. Fișierul rezultat intră totuși în git, ca pe o mașină nouă scurtătura
să meargă fără să rulezi nimic.

    .venv\\Scripts\\python.exe fa-pictograma.py
"""
import struct
from pathlib import Path

import numpy as np

import pulsar

ACASA = Path(__file__).resolve().parent
# Windows alege singur mărimea potrivită. 256 e cea din „pictograme mari",
# 16 cea din colțul ferestrei; fără ele, sistemul scalează una singură și iese
# pastă exact la mărimea pe care o folosești mai des.
MARIMI = (16, 24, 32, 48, 64, 128, 256)


def cadru_transparent(latura: int) -> np.ndarray:
    """Pulsarul pe fundal gol: RGBA, cu alfa lui adevărată.

    Nu premultiplicat — PNG-ul cere componente drepte. Premultiplicat, sub o
    pictogramă pe fundal deschis ar apărea un halou negru.
    """
    p = pulsar.Pulsar(latura, latura * 0.30)
    a, col = p.alfa(0.0, "gata")
    iesire = np.empty((latura, latura, 4), dtype=np.uint8)
    for i in range(3):
        iesire[:, :, i] = int(col[i])
    iesire[:, :, 3] = (np.clip(a, 0.0, 1.0) * 255.0).astype(np.uint8)
    return iesire


def main() -> None:
    poze = [pulsar.png(cadru_transparent(m)) for m in MARIMI]

    # Antetul ICO, apoi un rând de director per mărime, apoi pozele. Windows
    # Vista încolo acceptă PNG întreg în locul unui BMP — de-asta încap 256x256
    # într-un fișier de câțiva kiloocteți.
    cap = struct.pack("<HHH", 0, 1, len(poze))
    director, corp, decalaj = b"", b"", len(cap) + 16 * len(poze)
    for marime, poza in zip(MARIMI, poze):
        director += struct.pack("<BBBBHHII",
                                marime % 256, marime % 256, 0, 0, 1, 32,
                                len(poza), decalaj)
        corp += poza
        decalaj += len(poza)

    cale = ACASA / "iris.ico"
    cale.write_bytes(cap + director + corp)
    print(f"{cale} — {len(MARIMI)} mărimi, {cale.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
