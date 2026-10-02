"""Iris — vorbești, se scrie în caseta în care ai cursorul.

Iris e mesagera zeilor: **poartă** cuvintele fără să le compună. Ăsta e tot
contractul uneltei — nu răspunde, nu trimite, nu completează. Și e curcubeul,
iar culoarea e chiar felul în care fereastra spune în ce stare e.

Local, fără internet, fără tokeni: Whisper (`faster-whisper`) rulează pe CPU-ul
acestei mașini. Ce spui nu pleacă nicăieri.

Ciclul: click pe „Ascultă" (sau tasta globală) → vorbești, cu pauze cât vrei →
click pe „Stop" → textul se scrie singur în fereastra din care ai pornit.
**Nu se trimite nimic.** `Enter` rămâne al tău, deliberat: apuci să citești ce a
ieșit înainte să pleci mai departe.

Mediu Python propriu (`.venv`): un `pip install` de aici nu are voie să schimbe
ce văd celelalte programe de pe mașină, nici ele ce vede Iris.
"""
import ctypes
import io
import json
import queue
import re
import sys
import threading
import time
import tkinter as tk
import traceback
import wave
import winsound
from pathlib import Path

import numpy as np
import sounddevice as sd

# ÎNAINTE de tkinter, și înainte de orice fereastră. Fără asta, Windows minte
# procesul despre ecran — îi spune 1646x1029 în loc de 2880x1800 — și apoi îi
# **întinde** fereastra cu 1,75. Tot ce se vedea era interpolat. Măsurat pe 3
# august; o bună parte din „arată ca un program vechi" era asta, nu widget-urile.
DPI_RAPORT = ""
try:
    _hr = ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
    _a = ctypes.c_int()
    ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(_a))
    DPI_RAPORT = f"HRESULT 0x{_hr & 0xFFFFFFFF:08X}, conștiență {_a.value}"
except Exception as _ex:
    DPI_RAPORT = f"{type(_ex).__name__}: {_ex}"

# Identitatea aplicației pentru bara de activități — tot înainte de orice
# fereastră, fiindcă Windows o citește o singură dată, când apare butonul.
#
# Fără ea, Windows deduce cine suntem din executabil, iar executabilul e
# `pythonw.exe`. **Găsit prin folosire:** fixarea butonului din bară a
# creat un pin numit `IDLE (Python 3.14).lnk` — scurtătura din Start Menu care
# are aceeași țintă —, iar clicul de a doua zi deschidea IDLE. Butonul arăta
# Iris tot timpul; abia pin-ul salvat pe disc a spus ce credea Windows despre
# noi. Același șir trebuie pus și pe scurtătura din Start Menu
# (`System.AppUserModel.ID`), altfel cele două jumătăți nu se recunosc și
# pin-ul rămâne al altcuiva.
APLICATIE = "Mihai.Iris"
APLICATIE_RAPORT = ""
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APLICATIE)
    APLICATIE_RAPORT = APLICATIE
except Exception as _ex:
    APLICATIE_RAPORT = f"{type(_ex).__name__}: {_ex}"

import fereastra_libera
import ferestre
import pulsar

ACASA = Path(__file__).resolve().parent
CONFIG = ACASA / "iris.json"
STARE = ACASA / "stare.json"

# Cum îi spune a doua pornire primeia „arată-te". Fișier gol, viață de cel mult
# 120 ms — cât o tură din bucla `_pompa`, care îl citește și îl șterge.
SEMNAL = ACASA / "arata.semnal"

IMPLICITE = {
    "model": "large-v3-turbo",
    "device": "cpu",
    "compute_type": "int8",
    "cpu_threads": 8,
    "limba": "ro",
    "beam_size": 5,
    "prompt_initial": "",

    # Ruta pe lungime. Audio de până la atâtea secunde se transcrie pe iGPU,
    # restul pe CPU. **0 stinge ruta** și lasă tot pe CPU, calea de dinainte —
    # care e și ce se întâmplă singur dacă `openvino-genai` nu e instalat.
    #
    # Granița e la 30 s fiindcă acolo e defectul: pe clipul de 43,6 s, iGPU-ul a
    # produs o inversiune de sens („nu am să luăm" dintr-un „luăm"), iar o negație
    # inventată nu se prinde recitind. Sub 30 s, unde audio-ul intră într-o
    # singură fereastră, nu s-a văzut. Din cele 52 de clipuri ale corpusului, 45
    # sunt sub 30 s (mediana lor 15,2 s), deci ruta rapidă prinde majoritatea și
    # cea sigură costă puțin.
    "granita_igpu": 30.0,
    "model_igpu": "OpenVINO/whisper-large-v3-turbo-fp16-ov",
    "dispozitiv_igpu": "GPU",

    # Numai pentru iGPU, și nu e opțional acolo: `initial_prompt` condiționează
    # DOAR prima fereastră, iar `WhisperPipeline` nu duce contextul mai departe
    # ca `faster-whisper`. Fără `hotwords`, de la a doua fereastră dispare
    # vocabularul casei și 12 clipuri din 32 intră în buclă („cloud cloud cloud").
    "hotwords": "",

    # Encodarea primei ferestre, luată înainte — vezi clasa `Devans`. `false` o
    # stinge, și atunci se transcrie exact ca înainte. Nu are efect pe dictările
    # sub 30 s: acolo nu există o primă fereastră plină.
    "devans": True,
    "dispozitiv_intrare": None,
    "esantionare": 16000,
    "plafon_secunde": 600,
    "spatiu_final": True,
    "per_lot": 32,
    "pauza_lot": 0.002,
    "tasta_comuta": "ctrl+alt+space",
    "tasta_anuleaza": "ctrl+alt+x",
    "intensitate": 1.0,
    "voal": 0.5,
    "contur_text": 0.55,
    "sunete": True,
    "sunete_fisiere": {},
    "volum_sunete": 0.9,
    "volum_pe_sunet": {},
    "balbe": [],
    "halucinatii": [],
}


def incarca_config() -> dict:
    """Configurarea, cu `utf-8-sig`.

    BOM-ul pus de PowerShell 5.1 a oprit deja o dată un program din pornire, cu
    „JSON stricat la linia 1, coloana 1" — pe un fișier care arăta perfect.

    **Contopirea merge un nivel în adâncime**, nu doar la rădăcină. Un `update`
    simplu înlocuiește `volum_pe_sunet` cu totul: cine scrie în configurare
    `{"gata": 0.05}` pierde orice altă excepție din implicite, fără nicio
    plângere. Azi implicitele acelea sunt goale, deci nu se vede — și de-asta se
    repară acum, nu când se va vedea.
    """
    reglaje = dict(IMPLICITE)
    if not CONFIG.exists():
        return reglaje
    for cheie, valoare in json.loads(
            CONFIG.read_text(encoding="utf-8-sig")).items():
        if isinstance(valoare, dict) and isinstance(reglaje.get(cheie), dict):
            reglaje[cheie] = {**reglaje[cheie], **valoare}
        else:
            reglaje[cheie] = valoare
    return reglaje


# ── Curățenia textului ───────────────────────────────────────────────────

def scoate_halucinatii(text: str, tipare: list[str]) -> str:
    """Scoate propozițiile care sunt, întregi, un artefact cunoscut de Whisper.

    Whisper e antrenat și pe subtitrări de YouTube, iar pe tăcere nu poate spune
    „n-am auzit nimic" — prezice text, deci scoate resturi din antrenament.
    „Mulțumim pentru vizionare" e cel prins în prima oră de folosire reală, pe o
    pauză lungă de gândire.

    **Se taie doar propoziția ÎNTREAGĂ**, niciodată o bucată dintr-una reală.
    Diferența e tot: o potrivire pe subșir ar mânca mijlocul unei fraze bune, iar
    un text din care lipsește o bucată sună perfect.
    """
    if not tipare:
        return text
    propozitii = re.findall(r"[^.!?]+[.!?]*", text)
    ramase = [p for p in propozitii
              if not any(re.fullmatch(rf"\s*(?:{t})\s*[.!?]*\s*", p,
                                      flags=re.IGNORECASE) for t in tipare)]
    return "".join(ramase).strip() if ramase else ""


def curata(text: str, balbe: list[str], halucinatii: list[str] = ()) -> str:
    """Un rând de text, fără balbe. Determinist, nu „înțeles" de un model.

    Linia nouă dispare prima, și nu din estetică: în caseta unui chat `Enter`
    trimite mesajul. Un `\\n` scris cu SendInput ar trimite fraza pe jumătate.
    """
    text = re.sub(r"\s+", " ", text).strip()
    text = scoate_halucinatii(text, list(halucinatii))

    for tipar in balbe:
        # (?<!\w) / (?!\w) în loc de \b: interjecțiile sunt scurte și lipite de
        # virgule, iar \b se poartă altfel lângă diacritice.
        text = re.sub(rf"(?<!\w)(?:{tipar})(?!\w)", "", text, flags=re.IGNORECASE)

    # Resturile de punctuație rămase în locul balbei: „Deci, ăăă, mergem" ar
    # ieși „Deci, , mergem".
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(\s*[,;:])+", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"^[\s,;:.]+", "", text)
    return text.strip()


# ── Sunetul ──────────────────────────────────────────────────────────────

SUNETE: dict[str, bytes] = {}


def pregateste_sunete(reglaje: dict) -> None:
    """Încarcă fișierele o dată, la pornire, și le amplifică.

    Sunetele de sistem ale Windows-ului sunt normalizate **încet** dinadins: sunt
    făcute să nu deranjeze când apar de o sută de ori pe zi din alte programe.
    Aici sunt singurul semnal că urechea s-a deschis, deci trebuie auzite —
    inclusiv din camera cealaltă.

    **Normalizare după RMS, cu vârful doar ca plafon.** Nu după vârf: urechea
    aude energia, nu maximul. Două fișiere aduse la același vârf sună diferit
    dacă unul e un pocnet scurt și celălalt un ton plin — găsit prin folosire:
    „Stop" se auzea tare și „Ascultă" încet, deși erau la același vârf.

    Nici multiplicator fix nu merge: măsurat în `C:\\Windows\\Media`, vârfurile
    merg de la **0,01** (`Windows Menu Command`) la **0,35**
    (`Windows Background`) — raport 35×. Orice cifră unică ori lăsa unul
    inaudibil, ori îl tăia pe celălalt.

    Vârful rămâne ca limitator: un fișier cu mult relief („crest factor" mare)
    ar cere o amplificare care i-ar turti maximele. Acolo câștigă plafonul, și
    sunetul iese puțin mai încet decât ținta — corect, fiindcă alternativa e
    distorsiunea.
    """
    SUNETE.clear()
    implicit = float(reglaje.get("volum_sunete") or 0.9)
    # Volum pe fiecare sunet, nu unul singur: găsit prin folosire. Același
    # reglaj bun pentru „ascult" și „stop" era strident la „gata" — sunetul de
    # sfârșit vine când te uiți deja la text, deci n-are nevoie să te cheme.
    pe_sunet = reglaje.get("volum_pe_sunet") or {}
    for nume, cale in (reglaje.get("sunete_fisiere") or {}).items():
        if not cale:
            continue
        if not Path(cale).exists():
            if not EROARE_SUNET:
                EROARE_SUNET.append(f"„{nume}” lipsește: {cale}")
            continue
        volum = min(float(pe_sunet.get(nume, implicit)), 1.0)
        try:
            with wave.open(cale, "rb") as w:
                canale, latime, rata = w.getnchannels(), w.getsampwidth(), w.getframerate()
                cadre = w.readframes(w.getnframes())
            if latime == 2:
                date = np.frombuffer(cadre, dtype="<i2").astype(np.float32)
                varf = float(np.abs(date).max())
                rms = float(np.sqrt((date ** 2).mean()))
                if varf > 0 and rms > 0:
                    # 0,20 din scala întreagă la volum 1.0: ținta de energie
                    # peste care sunetele de sistem încep să pară strigate.
                    castig = (volum * 0.20 * 32767.0) / rms
                    date *= min(castig, 0.99 * 32767.0 / varf)
                cadre = np.clip(date, -32768, 32767).astype("<i2").tobytes()
            tampon = io.BytesIO()
            with wave.open(tampon, "wb") as w:
                w.setnchannels(canale)
                w.setsampwidth(latime)
                w.setframerate(rata)
                w.writeframes(cadre)
            SUNETE[nume] = tampon.getvalue()
        except Exception as ex:
            # Un fișier stricat nu oprește nimic: celelalte sunete merg, iar
            # fereastra spune care tace.
            if not EROARE_SUNET:
                EROARE_SUNET.append(f"„{nume}” nu se citește: {type(ex).__name__}: {ex}")


EROARE_SUNET: list[str] = []


def _canta(date: bytes) -> None:
    """Redare sincronă, pe firul ei.

    **`SND_MEMORY` NU merge cu `SND_ASYNC`**: `winsound` ridică
    `RuntimeError: Cannot play asynchronously from memory`. Prima versiune de
    aici le-a pus pe amândouă și a înghițit excepția într-un `except` orb — deci
    programul a amuțit complet și **nimic nu s-a plâns**. Trei runde de „nu se
    aude" au fost puse pe seama volumului, care era în regulă.

    Lecția nu e despre `winsound`. E despre `except: pass` pe o cale pe care
    nimeni n-o verifică: o unealtă care tace la eroare fabrică defectul pe care
    apoi îl cauți în altă parte. De-asta eroarea se ține minte în
    `EROARE_SUNET`, iar fereastra o arată.
    """
    try:
        winsound.PlaySound(date, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception as ex:
        if not EROARE_SUNET:
            EROARE_SUNET.append(f"{type(ex).__name__}: {ex}")


def suna(nume: str, reglaje: dict) -> None:
    """Un sunet, fără să blocheze cine l-a cerut.

    Nu `winsound.Beep`: aia scoate o undă pătrată brută pe difuzor și la a treia
    dictare devine enervantă — unealta se folosește de zeci de ori pe zi.
    """
    if not reglaje.get("sunete") or nume not in SUNETE:
        return
    threading.Thread(target=_canta, args=(SUNETE[nume],), daemon=True).start()


# ── Encodarea primei ferestre, luată înainte ─────────────────────────────

FEREASTRA = 30.0        # cât macină Whisper odată. Nu e un reglaj, e modelul


class Devans:
    """Encodează prima fereastră cât încă vorbești, ca la Stop să fie gata.

    Whisper macină audio în ferestre de 30 s **oricum**. Pentru o dictare de 70 s,
    prima fereastră e cunoscută cu mult înainte de Stop, iar encoder-ul ei costă
    7,0–7,6 s dintr-o așteptare de 18,6–28,2 s. Nu e streaming și nu schimbă ce
    vede modelul: e exact același calcul, făcut mai devreme.

    Două lucruri fac ideea posibilă, și amândouă au fost aflate, nu presupuse:

    1. **Prima fereastră e determinată de un prefix.** VAD-ul taie liniștea
       înainte de fereastruire, deci cele 30 s se măsoară pe vorbire lipită — de
       unde teama că ar depinde de o pauză de la secunda 50. Nu depinde:
       look-ahead de 1,5–8,5 s pe corpus.
    2. **Podeaua mel-ului se ia însă din maximul întregii dictări.**
       `FeatureExtractor` face `log_spec.max() - 8.0`, iar maximul acela e peste
       tot audio-ul filtrat. Dacă cea mai tare silabă vine după fereastră,
       fereastra **se schimbă retroactiv** — pe 3 clipuri din 7. Argumentul de la
       punctul 1 nu acoperă asta; e un al doilea blocaj, găsit la implementare.

    De aici vin cele două reguli ale clasei, și nu sunt prudență, sunt mecanismul:

    - **Cheia se compară pe biți** (`np.array_equal` pe mel), nu pe „e același
      audio". Dacă podeaua s-a mutat, cheia nu lovește și se encodează normal.
      Ce livrează Iris rămâne bit cu bit ce livra înainte — nu „aproape".
    - **Se reencodează cât fereastra se mai mută.** Maximul numai crește, deci
      după ce cea mai tare silabă a trecut, fereastra se așază. Fiecare encodare
      costă 7 s de CPU pe o mașină care oricum stă degeaba cât vorbești.

    Costul, dacă nu lovește: câteva secunde de CPU în fundal, plătite de nimeni.
    Costul dacă lovește: zero — încă și mai bine, apelul adevărat nu se mai face.
    """

    def __init__(self, model, reglaje: dict):
        from faster_whisper.audio import pad_or_trim
        from faster_whisper.vad import (VadOptions, collect_chunks,
                                        get_speech_timestamps)
        self._taie = pad_or_trim
        self._bucatile = get_speech_timestamps
        self._aduna = collect_chunks
        # Implicitele căii lui Iris, luate din bibliotecă, nu scrise de mână:
        # `transcribe` face `VadOptions()` când nu i se dă nimic, și nu i se dă.
        self._vad = VadOptions()

        self.model = model
        self.esantionare = int(reglaje["esantionare"])
        self.granita = float(reglaje.get("granita_igpu") or 0)
        self.pas_secunde = 1.0

        self._blocaj = threading.Lock()
        self._cheie = None
        self._iesire = None
        self._incheiat = threading.Event()      # nicio encodare în aer
        self._incheiat.set()
        self._stop = threading.Event()
        self.encodari = 0
        self.lovit = None                       # None cât n-a fost întrebat
        self.nota = ""
        # Câte apeluri la encoder a mai făcut transcrierea, și cât au costat.
        # **Ăsta e instrumentul care nu minte:** o lovitură scoate exact un apel,
        # iar numărul se citește la fel oricât ar aluneca ceasul mașinii — pe
        # aceleași clipuri, aceeași rundă a dat 5,3 s și 7,3 s pe un `encode`.
        self.apeluri = 0
        self.timp_encode = 0.0

        # Se pune pe **instanță**, nu pe clasă: modelul e al acestui Iris.
        # `WhisperModel` e o clasă Python obișnuită, deci merge — spre deosebire
        # de `WhisperPipeline`, care e o legătură C++ cu `generate` read-only.
        self._encode = model.encode
        model.encode = self.encode

    # ── ce cheamă faster-whisper ─────────────────────────────────────────

    def encode(self, cadre):
        """Ține locul lui `WhisperModel.encode`. Lovește numai la egalitate pe biți.

        **O encodare în aer se așteaptă, nu se ocolește.** CTranslate2 serializează
        apelurile pe același model (`inter_threads=1`), deci apelul „adevărat" ar
        sta oricum la coadă după ea — așteptând, mai există șansa să nu mai fie
        nevoie de el. Ocolirea n-ar câștiga timp, ar pierde doar lovitura.

        Cache-ul se golește la primul apel, lovit sau nu: e al **primei** ferestre,
        iar ferestrele 2+ n-au ce căuta în el.
        """
        self._incheiat.wait(60.0)
        with self._blocaj:
            cheie, iesire = self._cheie, self._iesire
            self._cheie = self._iesire = None
        if iesire is None:
            return self._chiar(cadre)
        self.lovit = bool(np.array_equal(cadre, cheie))
        return iesire if self.lovit else self._chiar(cadre)

    def _chiar(self, cadre):
        """Encoder-ul adevărat, numărat. Numai apelurile pe care le face
        transcrierea — cele din fundal sunt altă socoteală, plătită de nimeni."""
        t0 = time.perf_counter()
        try:
            return self._encode(cadre)
        finally:
            self.apeluri += 1
            self.timp_encode += time.perf_counter() - t0

    # ── urmărirea dictării în curs ───────────────────────────────────────

    def pregateste(self) -> None:
        """Uită dictarea de dinainte. Stă separat de `incepe` fiindcă
        măsurătoarea conduce pașii cu ceasul ei, fără fir."""
        with self._blocaj:
            self._cheie = self._iesire = None
        self.encodari, self.lovit, self.nota = 0, None, ""
        self.apeluri, self.timp_encode = 0, 0.0
        self._stop.clear()

    def incepe(self, da_bucati) -> None:
        """Pornește urmărirea. `da_bucati` întoarce ce s-a înregistrat până acum."""
        self.pregateste()
        threading.Thread(target=self._urmareste, args=(da_bucati,),
                         daemon=True).start()

    def inchide(self) -> None:
        """Nu se mai pornesc encodări noi. Ce e în aer se lasă să termine."""
        self._stop.set()

    def in_aer(self) -> bool:
        """O encodare e chiar acum în lucru. Pentru probe și pentru raport."""
        return not self._incheiat.is_set()

    def _urmareste(self, da_bucati) -> None:
        # **Pauza dintre pași crește cu cât costă pasul.** VAD-ul se plimbă de
        # fiecare dată peste toată dictarea de până acum, deci pe una de zece
        # minute un pas ajunge să coste secunde — iar o buclă cu pauză fixă ar
        # ține un miez ocupat degeaba tocmai acolo. Așa, munca din fundal nu
        # trece de jumătate de miez, oricât ar vorbi omul.
        pauza = self.pas_secunde
        while not self._stop.wait(pauza):
            bucati = da_bucati()
            if not bucati:
                continue
            try:
                t0 = time.perf_counter()
                self.pas(np.concatenate(bucati).reshape(-1))
                pauza = max(self.pas_secunde, time.perf_counter() - t0)
            except Exception as ex:
                # Se ține minte și se arată. O accelerare care cade în tăcere ar
                # apărea drept „Iris a devenit lent", și nimeni n-ar căuta aici.
                self.nota = f"devansul s-a oprit: {type(ex).__name__}: {ex}"
                return

    def pas(self, esantioane: np.ndarray) -> str:
        """Un pas de urmărire, pe eșantioanele de până acum (int16, ca de la microfon).

        Întoarce ce s-a întâmplat, ca o măsurătoare să poată conduce bucla cu
        ceasul ei. Bucla din fir și bucla din măsurătoare cheamă atunci
        **același pas**, nu două copii care s-ar putea despărți.
        """
        secunde = len(esantioane) / self.esantionare
        # Sub graniță dictarea pleacă pe iGPU, unde encoder-ul ăsta n-are ce
        # căuta; sub 30 s n-are cum să existe o fereastră plină. Verificarea
        # ieftină stă înaintea celei scumpe.
        if secunde <= max(self.granita, FEREASTRA):
            return "scurt"
        # Microfonul dă int16, măsurătoarea dă float32 decodat din fișier.
        # Amândouă trebuie să ajungă la **exact** vectorul pe care îl va vedea
        # `transcribe`; altfel cheia n-ar avea cum să lovească, iar măsurătoarea
        # ar raporta o ratare care nu e a devansului.
        fereastra = self.fereastra(esantioane.astype(np.float32) / 32768.0
                                   if esantioane.dtype == np.int16 else esantioane)
        if fereastra is None:
            return "fără fereastră"
        with self._blocaj:
            if self._cheie is not None and np.array_equal(fereastra, self._cheie):
                return "aceeași"
        if self._stop.is_set():
            return "oprit"
        self._encodeaza(fereastra)
        return "encodat"

    def fereastra(self, audio: np.ndarray):
        """Primele 30 s de vorbire filtrată, ca mel — sau `None` dacă încă nu sunt.

        Se cheamă **aceleași funcții** din `faster_whisper` pe care le cheamă
        `transcribe`, ca o schimbare în bibliotecă să strice devansul, nu să-l
        lase să mintă.

        Marginea de `n_fft`: ultimele cadre ale ferestrei citesc puțin peste
        secunda 30. Dacă acolo încă nu e audio, extractorul pune zerouri — și
        atunci cheia n-ar mai lovi când vorbirea continuă.
        """
        pachete, _ = self._aduna(audio, self._bucatile(audio, self._vad))
        if not pachete:
            return None
        lipit = np.concatenate(pachete, axis=0)
        extrage = self.model.feature_extractor
        if len(lipit) < extrage.n_samples + extrage.n_fft:
            return None
        return self._taie(extrage(lipit)[:, :extrage.nb_max_frames])

    def _encodeaza(self, fereastra) -> None:
        self._incheiat.clear()
        try:
            iesire = self._encode(fereastra)
            with self._blocaj:
                self._cheie, self._iesire = fereastra, iesire
            self.encodari += 1
        finally:
            self._incheiat.set()


# ── Programul ────────────────────────────────────────────────────────────

class Eticheta:
    """Ține minte un text, ca un `tk.Label` care nu desenează nimic.

    Există ca restul programului să nu afle că fereastra s-a schimbat: tot
    codul care spunea `self.et_nota.config(text=…)` spune la fel și acum, iar
    desenul se uită la `.text` când îi vine rândul. Fără ea, zece locuri din
    `_pompa` ar fi trebuit rescrise, și fiecare era o ocazie de greșeală.

    **`fg` se primește și se aruncă, dinadins.** Apelurile care îl trimit sunt
    reale — `_treci_in` și `_bate_ceasul` cer culori —, dar în fereastra liberă
    culoarea o dă pulsarul, prin decizia „tot scrisul ia culoarea discului".
    O primă versiune îl ținea minte într-un `self.fg` pe care nimeni nu-l citea:
    cod care pare să facă ceva și nu face, adică exact felul de minciună pe care
    o cauți apoi în altă parte. Argumentele rămân acceptate ca `_fereastra_veche`,
    unde etichetele SUNT `tk.Label` și `fg` chiar contează, să poată chema
    identic.
    """

    def __init__(self) -> None:
        self.text = ""

    def config(self, text: str | None = None, **restul) -> None:
        if text is not None:
            self.text = text


def taie_randuri(text: str, per_rand: int) -> list[str]:
    """Rupe un text în rânduri, la cuvinte. Consolas e monospațiat, deci
    numărul de caractere e o măsură exactă a lățimii, nu o aproximare."""
    randuri, curent = [], ""
    for cuvant in text.split():
        if curent and len(curent) + 1 + len(cuvant) > per_rand:
            randuri.append(curent)
            curent = cuvant
        else:
            curent = f"{curent} {cuvant}".strip()
    if curent:
        randuri.append(curent)
    return randuri


class Iris:

    def __init__(self, reglaje: dict):
        self.reglaje = reglaje
        pregateste_sunete(reglaje)
        self.model = None
        # Motorul de iGPU, plus configurarea lui de generare. Rămân None dacă
        # ruta e stinsă, dacă `openvino-genai` nu e instalat, sau dacă
        # compilarea pe iGPU a picat — și atunci tot se dictează, pe CPU.
        self.conducta = None
        self.config_igpu = None
        # Encodarea primei ferestre, luată înainte. Rămâne None dacă e stinsă
        # din configurare — și atunci se transcrie exact ca înainte.
        self.devans = None
        self.stare = "incarc"
        self.flux = None
        self.eroare_flux: list[str] = []
        self.bucati: list[np.ndarray] = []
        self.t_pornire = 0.0
        self.tinta = 0            # fereastra în care se scrie
        self.mesaje: queue.Queue = queue.Queue()
        self._construieste_fereastra()
        self._porneste_firele()

    # ── fereastra ────────────────────────────────────────────────────────

    def _construieste_fereastra(self) -> None:
        """Fereastra liberă; dacă ceva din ea cade, cea veche, cu widget-uri.

        Un desen n-are voie să omoare dictarea. Aceeași regulă ca „un microfon
        n-are voie să omoare biroul", cu o treaptă mai jos: aici cade partea
        frumoasă, nu unealta.
        """
        try:
            self._fereastra_libera()
        except Exception as ex:
            self.libera = None
            self._fereastra_veche()
            self.et_nota.config(text=f"desenul n-a pornit: "
                                     f"{type(ex).__name__}: {ex}")

    # ── fereastra liberă: pulsarul, fără cutie ───────────────────────────

    def _fereastra_libera(self) -> None:
        self.rad = tk.Tk()
        self.rad.title("Iris")
        self.rad.overrideredirect(False)
        # Deasupra tuturor, ca fereastra veche. **Nu e o preferință.** Unealta
        # se comandă din ea; dusă în spatele ferestrei în care dictezi, n-ai cum
        # să mai dai Stop cu mouse-ul, iar clickul care ar readuce-o o duce și
        # mai în spate. Pierdut la rescriere, găsit la prima folosire reală.
        self.rad.attributes("-topmost", True)
        self.rad.protocol("WM_DELETE_WINDOW", self.inchide)

        # Scara ecranului. La 175% totul se înmulțește cu 1,75 — altfel unealta
        # ar fi de trei ori mai mică decât trebuie pe un ecran ca ăsta.
        self.rad.update_idletasks()
        hwnd = ferestre.hwnd_toplevel(self.rad.winfo_id())
        self.hwnd_propriu = hwnd
        # Scara se ia de la Tk, nu de la `GetDpiForWindow`: Tk o măsoară pe
        # fereastra lui, deja creată, iar cealaltă a întors 96 pe exact aceeași
        # mașină pe care proba separată dăduse 168. Cine măsoară primește
        # răspunsul care contează — aici, câți pixeli desenează Tk.
        s = self.rad.winfo_fpixels("1i") / 96.0
        self.px = lambda logic: int(round(logic * s))
        print(f"iris: scara {s:.2f} ({DPI_RAPORT}), aplicatie {APLICATIE_RAPORT},"
              f" pid {__import__('os').getpid()}", file=sys.stderr, flush=True)

        D = self.px(200)                     # latura desenului pulsarului
        self.L, self.I = D, D + self.px(78)  # cadrul, cu loc de text dedesubt
        self.rad.geometry(f"{self.L}x{self.I}{self._pozitia_salvata()}")

        fereastra_libera.dezbraca(hwnd)
        # Clickul pe pulsar n-are voie să fure focusul din caseta în care
        # dictai — motivul pentru care există WS_EX_NOACTIVATE de la început.
        ferestre.fara_activare(hwnd)
        # Poziția se cere DUPĂ schimbarea stilurilor, nu înainte: `dezbraca`
        # trece prin `SetWindowPos`, iar Tk își reașază fereastra pe urma lui.
        # Cerută înainte, se pierdea — fereastra apărea de fiecare dată în
        # colțul unde o pune Tk implicit.
        self.rad.geometry(f"{self.L}x{self.I}{self._pozitia_salvata()}")
        self.rad.update_idletasks()

        self.panza = fereastra_libera.Panza(hwnd, self.L, self.I)
        self.scena = fereastra_libera.Scena(self.L, self.I)
        # Cele două se reglează din `iris.json`, fără cod: cât de aprins e
        # desenul și cât de întunecat e voalul de sub el. Cât de vizibil trebuie
        # să fie depinde de ce ai pe ecran, iar asta nu se poate ști de aici.
        self.pulsar = pulsar.Pulsar(
            D, D * 0.26, taria=float(self.reglaje.get("intensitate", 1.0)))
        self.voal = float(self.reglaje.get("voal", 0.5))

        # Voalul acoperă tot cadrul, nu doar discul: textul de dedesubt stă și
        # el peste ce se întâmplă să fie pe ecran, iar peste o listă de fișiere
        # nu se citea. E o elipsă, cu marginea stinsă în nimic — n-are muchie
        # nicăieri, deci nu e un chenar.
        yy, xx = np.mgrid[0:self.I, 0:self.L].astype(np.float32)
        u = (xx - self.L / 2.0) / (self.L * 0.54)
        v = (yy - self.I * 0.44) / (self.I * 0.58)
        self.voal_harta = (np.clip(1.0 - np.sqrt(u * u + v * v), 0.0, 1.0) ** 1.9
                           ).astype(np.float32)
        # Cât de întunecat e conturul de sub litere. Zero îl stinge — atunci
        # textul stă direct peste ce se întâmplă să fie pe ecran.
        self.contur = float(self.reglaje.get("contur_text", 0.55))
        self.libera = True
        self._cache_text: dict = {}
        self._cache_contur: dict = {}
        self.nivel = 0.0
        self.t_desen = time.perf_counter()

        # Pictograma de pe bara de activități: pulsarul, nu pana lui Tk.
        self.ic = tk.PhotoImage(
            data=pulsar.ppm(pulsar.Pulsar(64, 17.0).cadru(0.0, "gata")))
        self.rad.iconphoto(True, self.ic)

        # Etichetele nu mai sunt widget-uri, dar restul programului nu trebuie
        # să afle: aceleași nume, același `.config(text=…)`. Ce se schimbă e
        # doar cine le desenează.
        for nume in ("et_stare", "et_ceas", "et_tinta", "et_nota"):
            setattr(self, nume, Eticheta())
        # Câte una fiecare, nu `self.b_ascult = self.b_stop = Eticheta()`. Ăla
        # lega două nume de un singur obiect — inofensiv cât `Eticheta` e inertă,
        # capcană din clipa în care nu mai e, fiindcă `_treci_in` le dă stări
        # opuse. Un obiect care primește „normal" și „disabled" în aceeași
        # instrucțiune păstrează ultima, în tăcere.
        self.b_ascult, self.b_stop = Eticheta(), Eticheta()

        self.rad.bind("<ButtonPress-1>", self._mouse_jos)
        self.rad.bind("<B1-Motion>", self._mouse_misca)
        self.rad.bind("<ButtonRelease-1>", self._mouse_sus)
        self._apasare: dict = {}

        SEMNAL.unlink(missing_ok=True)
        self._deseneaza()

    # ── desenul ──────────────────────────────────────────────────────────

    def _masca(self, text: str, familie: str, inaltime: int,
               gros: bool = False, spatiat: float = 0.0) -> np.ndarray:
        """Textele se repetă de zeci de ori pe secundă; măștile lor, o dată."""
        cheie = (text, familie, inaltime, gros, spatiat)
        if cheie not in self._cache_text:
            if len(self._cache_text) > 60:
                self._cache_text.clear()
            self._cache_text[cheie] = fereastra_libera.masca_text(
                text, familie, inaltime, gros, spatiat)
        return self._cache_text[cheie]

    def _randuri_stare(self, text: str) -> list[str]:
        """Rândul de stare, întreg: rărit cât încape, altfel strâns, altfel rupt.

        Literele rărite („G A T A") încap la stările scurte. Un mesaj ca
        „modelul nu s-a încărcat" ieșea rărit de două ori mai lat decât cadrul și
        se tăia pe margini — exact mesajul care spune ce s-a stricat.
        """
        if not text:
            return []
        loc = self.L - self.px(8)
        lat = lambda t: self._masca(t, "Bahnschrift", self.px(11), True).shape[1]
        rarit = " ".join(text.upper())
        if lat(rarit) <= loc:
            return [rarit]
        randuri, curent = [], ""
        for cuvant in text.upper().split():
            proba = f"{curent} {cuvant}".strip()
            if curent and lat(proba) > loc:
                randuri.append(curent)
                curent = cuvant
            else:
                curent = proba
        return randuri + [curent]

    def _rand(self, text: str, familie: str, inaltime: int, culoare, y: int,
              gros: bool = False, spatiat: float = 0.0) -> None:
        """Un rând de text centrat, cu conturul lui dedesubt.

        Voalul a fost scos fiindcă pe fundal alb arăta ca o pată. Dar el nu era
        decor: era fundalul TEXTULUI. Fără nimic, „GATA" în gheață pe o pagină
        albă aproape dispare — desenul câștiga, scrisul pierdea.

        Conturul plătește doar acolo unde se datorează: sub litere, nu sub tot
        cadrul. Un pixel, nu doi — la doi arată ca un autocolant negru, încercat
        și respins la vedere. Se stinge cu `"contur_text": 0`.
        """
        masca = self._masca(text, familie, inaltime, gros, spatiat)
        if self.contur > 0:
            cheie = (text, familie, inaltime, gros, spatiat)
            if cheie not in self._cache_contur:
                if len(self._cache_contur) > 60:
                    self._cache_contur.clear()
                h, w = masca.shape
                mare = np.zeros((h + 2, w + 2), dtype=np.float32)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        # Colțurile diagonalei intră mai stins: altfel conturul
                        # iese pătrat în jurul unei litere rotunde.
                        k = 1.0 if dx == 0 or dy == 0 else 0.6
                        f = mare[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                        np.maximum(f, masca * k, out=f)
                self._cache_contur[cheie] = mare
            self.scena.centrat(self._cache_contur[cheie], pulsar.HULL,
                               y - 1, self.contur)
        self.scena.centrat(masca, culoare, y)

    def _deseneaza(self) -> None:
        t = time.perf_counter() - self.t_desen
        stare = self.stare
        # Strângerea elipselor spre centru — mecanismul `strang` din pulsar —
        # e oprită aici: la transcriere pulsarul ieșea
        # vizibil mai mic decât la ascultat, iar diferența de mărime se citea ca
        # „altă unealtă", nu ca „altă stare". Starea o spune culoarea.
        strang = 0.0
        if stare != "ascult":
            self.nivel = 0.0

        self.scena.curata()
        x0 = (self.L - self.pulsar.latura) // 2
        # Întâi voalul, ca pulsarul să aibă pe ce sta indiferent ce e dedesubt.
        if self.voal > 0:
            self.scena.pune(self.voal_harta, pulsar.HULL, 0, 0, self.voal)
        alfa, culoare = self.pulsar.alfa(t, stare, self.nivel, strang)
        self.scena.pune(alfa, culoare, x0, 0)

        # ── Tot scrisul are culoarea discului ────────────────────────────
        #
        # Până acum doar eticheta de stare urma pulsarul; ceasul și ținta erau
        # chihlimbarii fix, nota era gheață fix. Ieșea o fereastră în trei
        # culori care nu spuneau nimic împreună: la ascultat discul era roșu și
        # dedesubt scria chihlimbariu, adică exact culoarea stării *următoare*.
        # Acum, dacă discul e roșu, scrisul de jos e roșu; dacă e violet, violet.
        #
        # **Ierarhia rămâne, doar că nu mai stă pe culoare.** O ține mărimea și
        # grosimea — 11 aldin pentru stare, 9 și 8 obișnuit dedesubt — care erau
        # oricum acolo. Culoarea plătea de două ori: și ierarhie, și stare, iar
        # a doua e singura pe care o citește cineva de la un metru.
        y = self.pulsar.latura + self.px(2)
        randuri = self._randuri_stare(self.et_stare.text or "")
        for i, rand in enumerate(randuri):
            self._rand(rand, "Bahnschrift", self.px(11), culoare,
                       y + i * self.px(16), gros=True)
        y += self.px(20) + max(0, len(randuri) - 1) * self.px(16)

        if self.et_ceas.text:
            self._rand(self.et_ceas.text, "Consolas", self.px(9), culoare, y)
            y += self.px(15)

        if stare == "ascult" and self.et_tinta.text:
            # Doar cât ascultă: în rest, rândul ăsta ar fi un chenar permanent
            # în jurul unui obiect care tocmai a scăpat de chenare. Dar cât
            # ascultă e obligatoriu — fără el, „nu mi-a scris nimic" și „a
            # scris în altă fereastră" arată identic (prima oră de folosire).
            self._rand(self.et_tinta.text[:34], "Consolas", self.px(8),
                       culoare, y)
        elif self.et_nota.text:
            for rand in taie_randuri(self.et_nota.text, 40)[:2]:
                self._rand(rand, "Consolas", self.px(8), culoare, y)
                y += self.px(12)

        self.panza.arata(self.scena.bgra())
        # 20 de cadre pe secundă cât lucrează, 10 cât stă. În repaus, animația
        # costă sub 1% din mașină; nu e motiv s-o plătească de două ori.
        self.rad.after(50 if stare in ("ascult", "transcriu") else 100,
                       self._deseneaza)

    # ── mouse: pulsarul e butonul ────────────────────────────────────────
    #
    # Aceeași apăsare înseamnă două lucruri, deci se decide la ridicare: dacă
    # degetul n-a plecat mai mult de câțiva pixeli, a fost click.

    def _mouse_jos(self, ev) -> None:
        self._apasare = {"x": ev.x_root, "y": ev.y_root, "mutat": False,
                         "fx": self.rad.winfo_x(), "fy": self.rad.winfo_y()}

    def _mouse_misca(self, ev) -> None:
        if not self._apasare:
            return
        dx = ev.x_root - self._apasare["x"]
        dy = ev.y_root - self._apasare["y"]
        if abs(dx) > 4 or abs(dy) > 4:
            self._apasare["mutat"] = True
            self.rad.geometry(f"+{self._apasare['fx'] + dx}"
                              f"+{self._apasare['fy'] + dy}")

    def _mouse_sus(self, ev) -> None:
        if self._apasare and not self._apasare["mutat"]:
            self.comuta()
        self._apasare = {}

    # ── fereastra veche, plasa ───────────────────────────────────────────

    def _fereastra_veche(self) -> None:
        self.rad = tk.Tk()
        self.rad.title("Iris")
        self.rad.resizable(False, False)
        self.rad.attributes("-topmost", True)
        self.rad.geometry(self._pozitia_salvata())
        self.rad.protocol("WM_DELETE_WINDOW", self.inchide)

        cadru = tk.Frame(self.rad, padx=14, pady=12)
        cadru.pack(fill="both", expand=True)

        rand = tk.Frame(cadru)
        rand.pack(fill="x")
        self.et_stare = tk.Label(rand, text="se încarcă…", anchor="w",
                                 font=("Segoe UI", 10))
        self.et_stare.pack(side="left")
        self.et_ceas = tk.Label(rand, text="", anchor="e",
                                font=("Consolas", 10), fg="#666")
        self.et_ceas.pack(side="right")

        butoane = tk.Frame(cadru, pady=8)
        butoane.pack(fill="x")
        self.b_ascult = tk.Button(butoane, text="Ascultă", width=12,
                                  command=self.porneste, state="disabled")
        self.b_ascult.pack(side="left")
        self.b_stop = tk.Button(butoane, text="Stop", width=12,
                                command=self.opreste, state="disabled")
        self.b_stop.pack(side="right")

        # Unde se va scrie, tot timpul la vedere. Fără el, „nu mi-a trimis
        # nimic" și „a scris în altă fereastră" arată identic.
        self.et_tinta = tk.Label(cadru, text="→ (nicio fereastră)", anchor="w",
                                 fg="#06c", font=("Segoe UI", 8))
        self.et_tinta.pack(fill="x")

        self.et_nota = tk.Label(cadru, text="", anchor="w", fg="#666",
                                font=("Segoe UI", 8), wraplength=280,
                                justify="left")
        self.et_nota.pack(fill="x")

        self.rad.update_idletasks()
        hwnd = ferestre.hwnd_toplevel(self.rad.winfo_id())
        self.hwnd_propriu = hwnd
        # Ca un click pe „Stop" să nu fure focusul din caseta în care dictai.
        ferestre.fara_activare(hwnd)

        # Bara de activități își reevaluează lista doar la un ciclu
        # ascunde/arată. Prin Tk, nu cu `ShowWindow`: varianta cu ShowWindow a
        # înghețat fereastra la 136x45 cu 6 pixeli de conținut, fiindcă a prins-o
        # înainte ca geometria să fie așezată. Tk știe ce dimensiune vrea și o
        # reaplică singur la deiconify.
        self.rad.withdraw()
        self.rad.deiconify()

        # Un semnal rămas de la o instanță care a murit brusc ar face fereastra
        # să sară în față fără motiv, o dată, la pornire.
        SEMNAL.unlink(missing_ok=True)

    def _pozitia_salvata(self) -> str:
        """Poziția e ce acumulează folosirea, nu ce scrie omul — deci în stare.json.

        Lipsă sau ilizibil, fișierul dă poziția implicită: la închidere se scrie
        din nou, întreg.
        """
        try:
            stare = json.loads(STARE.read_text(encoding="utf-8-sig"))
            return stare.get("pozitie") or "+120+120"
        except Exception:
            return "+120+120"

    def _salveaza_pozitia(self) -> None:
        try:
            STARE.write_text(json.dumps(
                {"pozitie": f"+{self.rad.winfo_x()}+{self.rad.winfo_y()}"},
                ensure_ascii=False), encoding="utf-8")
        except Exception as ex:
            # Se cheamă la închidere, când fereastra nu mai are unde arăta o
            # notă — deci într-o casetă.
            _plange(f"Poziția ferestrei nu s-a salvat:\n{STARE}\n\n{type(ex).__name__}: {ex}")

    # ── firele ───────────────────────────────────────────────────────────

    def _porneste_firele(self) -> None:
        threading.Thread(target=self._incarca_model, daemon=True).start()

        self.taste = ferestre.TasteGlobale()
        for cheie, ce_face in (("tasta_comuta", "comuta"),
                               ("tasta_anuleaza", "anuleaza")):
            combinatie = self.reglaje.get(cheie)
            if not combinatie:
                continue
            try:
                self.taste.adauga(
                    combinatie,
                    lambda c=ce_face: self.mesaje.put(("tasta", c)))
            except ValueError as ex:
                self.mesaje.put(("nota", f"{cheie}: {ex}"))
        threading.Thread(target=self.taste.ruleaza, daemon=True).start()

        self.rad.after(120, self._pompa)

    def _incarca_igpu(self) -> tuple:
        """Conducta OpenVINO pe iGPU, plus configurarea ei de generare.

        **Configurarea se pune pe obiect, nu ca argumente la `generate()`.**
        Acolo `initial_prompt` e înghițit în tăcere, fără eroare — o măsurătoare
        întreagă a raportat astfel că OpenVINO strică româna, când de fapt
        promptul nu se aplicase.

        `local_files_only=True`, din același motiv ca pe calea de CPU: lipsa
        modelului trebuie să fie un refuz de două secunde, nu o descărcare tăcută
        de 1,5 GB la pornire.
        """
        import openvino_genai as ov_genai
        from huggingface_hub import snapshot_download

        cale = snapshot_download(self.reglaje["model_igpu"], local_files_only=True)
        t0 = time.perf_counter()
        conducta = ov_genai.WhisperPipeline(
            cale, device=self.reglaje["dispozitiv_igpu"])
        compilat = time.perf_counter() - t0

        config = conducta.get_generation_config()
        config.language = f"<|{self.reglaje['limba']}|>"
        config.task = "transcribe"
        # Greedy, fiindcă beam search n-are implementare pe GPU în OpenVINO
        # 2026.3 și nici în 2026.4.1 (`Not Implemented`, probat 2 octombrie
        # 2026). Nu e o alegere, e ce există.
        config.num_beams = 1
        config.initial_prompt = self.reglaje.get("prompt_initial") or ""
        config.hotwords = self.reglaje.get("hotwords") or ""
        return conducta, config, compilat

    def _incarca_model(self) -> None:
        """Încărcare + încălzire. Prima rulare a unei unelte nu e o măsurătoare:
        fără încălzire, prima dictare reală ar fi cea lentă.

        **iGPU-ul se compilează întâi, CPU-ul după, și ordinea e măsurată** —
        nu e stil. Compilarea pe iGPU lasă în urmă un tranzitoriu care frânează
        primele ~20 s de lucru pe CPU: în ordinea inversă, primele două clipuri
        au costat 11,3 s în loc de 5,2 s (+23,5% pe toată trecerea). Așa,
        încărcarea și încălzirea CTranslate2 îl absorb, și penalizarea dispare
        de tot (−0,3%).

        **Amândouă la pornire, nu la cerere.** La cerere s-ar plăti de două ori:
        5–11 s de compilare pe prima dictare scurtă, plus tranzitoriul de mai sus.
        Costă ~2,2–2,7 GB de memorie în plus, din 32 GB.

        **iGPU-ul care nu se încarcă nu e o eroare fatală.** Ruta e o accelerare,
        nu o condiție de funcționare: fără ea se dictează pe CPU, ca înainte, și
        motivul se ține minte și se arată în fereastră — nu se înghite.
        """
        conducta = config = None
        compilat, nota_igpu = 0.0, ""
        if float(self.reglaje.get("granita_igpu") or 0) > 0:
            try:
                conducta, config, compilat = self._incarca_igpu()
            except Exception as ex:
                nota_igpu = f"{type(ex).__name__}: {ex}"

        try:
            from faster_whisper import WhisperModel
            t0 = time.perf_counter()
            model = WhisperModel(
                self.reglaje["model"], device=self.reglaje["device"],
                compute_type=self.reglaje["compute_type"],
                cpu_threads=int(self.reglaje["cpu_threads"]),
                # Lipsa modelului e un refuz în două secunde, nu o descărcare
                # tăcută de 1,5 GB la prima pornire.
                local_files_only=True)
            incarcat = time.perf_counter() - t0

            t0 = time.perf_counter()
            # `vad_filter=False`, deliberat, deși dictarea reală îl folosește.
            # Cu VAD, zgomotul slab e tăiat înainte de model, nu se transcrie
            # nimic, iar încălzirea costă 0,00 s — adică nu e o încălzire, e o
            # iluzie. Măsurat: 0,14 s la prima tură, 0,00 s la următoarele.
            # Fără VAD, encoder-ul macină fereastra de 30 s, care e exact ce
            # trebuie încălzit (83% din timpul unei transcrieri).
            zgomot = (np.random.default_rng(7).normal(0, 0.01, 16000 * 2)
                      ).astype(np.float32)
            list(model.transcribe(zgomot, language=self.reglaje["limba"],
                                  vad_filter=False, beam_size=1)[0])
            incalzit = time.perf_counter() - t0

            # Devansul se leagă DUPĂ încălzire: el înlocuiește `model.encode`, iar
            # o încălzire care trece prin cache-ul gol ar măsura altceva decât
            # măsura înainte.
            devans = (Devans(model, self.reglaje)
                      if self.reglaje.get("devans") else None)
            self.mesaje.put(("model", {
                "model": model, "conducta": conducta, "config": config,
                "devans": devans, "incarcat": incarcat, "incalzit": incalzit,
                "compilat": compilat, "nota_igpu": nota_igpu}))
        except Exception as ex:
            self.mesaje.put(("eroare_fatala",
                             f"{type(ex).__name__}: {ex}"))

    # ── ciclul ───────────────────────────────────────────────────────────

    def porneste(self) -> None:
        if self.stare != "gata":
            return
        # Ținta NU se reține abia acum. E urmărită tot timpul cât programul stă
        # degeaba (`_urmareste_tinta`), fiindcă în clipul ăsta poate fi deja
        # prea târziu: dacă apeși „Ascultă" cu mouse-ul și fereastra asta a
        # apucat să se activeze, aici s-ar citi ea însăși, iar ținta ar rămâne
        # zero — textul s-ar scrie în gol. Găsit la prima folosire reală.
        self._urmareste_tinta()

        self.bucati = []
        try:
            self.flux = sd.InputStream(
                samplerate=int(self.reglaje["esantionare"]), channels=1,
                dtype="int16", device=self.reglaje["dispozitiv_intrare"],
                callback=self._primeste)
            self.flux.start()
        except Exception as ex:
            self._arata_eroare(f"microfon: {type(ex).__name__}: {ex}")
            return
        self.t_pornire = time.perf_counter()
        # De aici încolo, un fir se uită din când în când dacă s-au adunat 30 s
        # de vorbire și, dacă da, encodează prima fereastră cât încă vorbești.
        # Pe o dictare scurtă nu costă nimic: se uită la lungime și se culcă.
        if self.devans is not None:
            self.devans.incepe(lambda: self.bucati[:])
        self._treci_in("ascult")
        suna("ascult", self.reglaje)

    def _primeste(self, date, cadre, timp, stare) -> None:
        """Firul audio. Doar copiază și măsoară; nu decide nimic.

        Nivelul e RMS-ul blocului, adus în 0..1 cu factorul 7 — reglat la vedere,
        pe vorbire normală. Un număr scris de aici și citit de bucla de desen —
        nu atinge fereastra, care e a firului lui Tk.
        """
        self.bucati.append(date.copy())
        if getattr(self, "libera", None):
            rms = float(np.sqrt(np.mean(
                (date.astype(np.float32) / 32768.0) ** 2)))
            # Coborâre lină: fără ea, particulele ar zvâcni la fiecare bloc de
            # 20 ms, iar între două silabe pulsarul s-ar stinge de tot.
            self.nivel = max(min(rms * 7.0, 1.0), self.nivel * 0.82)

    def opreste(self, trimite: bool = True) -> None:
        if self.stare != "ascult":
            return
        self._inchide_fluxul()
        if self.devans is not None:
            self.devans.inchide()
        suna("stop" if trimite else "eroare", self.reglaje)

        if not trimite:
            self.bucati = []
            self._treci_in("gata")
            self.et_nota.config(text="anulat — nimic scris")
            return

        esantioane = (np.concatenate(self.bucati).reshape(-1)
                      if self.bucati else np.zeros(0, dtype=np.int16))
        self.bucati = []
        secunde = len(esantioane) / float(self.reglaje["esantionare"])
        if secunde < 0.3:
            self._treci_in("gata")
            self.et_nota.config(text=f"prea scurt ({secunde:.1f} s) — nimic scris")
            suna("eroare", self.reglaje)
            return

        self._treci_in("transcriu")
        threading.Thread(target=self._transcrie, args=(esantioane, secunde),
                         daemon=True).start()

    def anuleaza(self) -> None:
        self.opreste(trimite=False)

    def _inchide_fluxul(self) -> None:
        if self.flux is not None:
            try:
                self.flux.stop()
                self.flux.close()
            except Exception as ex:
                # Fluxul se lasă oricum: următoarea dictare deschide unul nou.
                # Eroarea se ține minte, iar `_pompa` o arată.
                if not self.eroare_flux:
                    self.eroare_flux.append(f"{type(ex).__name__}: {ex}")
            self.flux = None

    def _transcrie(self, esantioane: np.ndarray, secunde: float) -> None:
        """Firul de lucru: transcrie, curăță, scrie. Fereastra rămâne vie.

        **Ruta pe lungime se decide aici, și lungimea se știe dinainte** —
        `secunde` vine numărat din eșantioane, nu ghicit din transcriere.
        """
        try:
            t0 = time.perf_counter()
            audio = esantioane.astype(np.float32) / 32768.0
            granita = float(self.reglaje.get("granita_igpu") or 0)
            brut, unde = None, "CPU"

            if self.conducta is not None and 0 < secunde <= granita:
                try:
                    brut = str(self.conducta.generate(audio, self.config_igpu))
                    unde = "iGPU"
                except Exception as ex:
                    # **O dictare nu se pierde fiindcă un motor a picat.** Se
                    # cade pe CPU, care e oricum calea de referință, și motivul
                    # se arată — un iGPU care cedează în tăcere ar apărea drept
                    # „Iris a devenit lent", și nimeni n-ar căuta aici.
                    self.mesaje.put((
                        "nota", f"iGPU a picat, s-a transcris pe CPU: "
                                f"{type(ex).__name__}: {ex}"))

            if brut is None:
                # Implicitele de decodare NU se ating: `condition_on_previous_text`
                # și `without_timestamps` câștigau 0,14 s și ștergeau cinci cuvinte
                # pe audio care trece de o fereastră de 30 s (măsurat, 3 august).
                segmente, _ = self.model.transcribe(
                    audio, language=self.reglaje["limba"],
                    beam_size=int(self.reglaje["beam_size"]),
                    # VAD-ul e gratis și cumpără calitate — verificat în trei
                    # motoare. Fără el ies „dokar" și „end pointul".
                    vad_filter=True,
                    initial_prompt=self.reglaje.get("prompt_initial") or None)
                brut = "".join(s.text for s in segmente)
                if self.devans is not None and self.devans.lovit:
                    unde = "CPU, cu prima fereastră gata"
            durata = time.perf_counter() - t0

            text = curata(brut, self.reglaje.get("balbe") or [],
                          self.reglaje.get("halucinatii") or [])
            if not text:
                self.mesaje.put(("nimic", secunde))
                return
            if self.reglaje["spatiu_final"]:
                text += " "

            # Fără țintă, textul s-ar scrie în gol — și n-ai cum să afli, fiindcă
            # SendInput reușește oricum. Atunci NU se scrie: ajunge în clipboard,
            # cu starea care o spune. O transcriere nu se pierde fiindcă
            # programul n-a știut unde s-o pună.
            if not self.tinta:
                self.mesaje.put(("clipboard", (text, secunde, durata,
                                               "nicio fereastră țintă")))
                return

            # Focusul înapoi, dacă un click pe „Stop" l-a mutat oricum.
            if ferestre.fereastra_activa() != self.tinta:
                if not ferestre.activeaza(self.tinta):
                    self.mesaje.put(("clipboard", (text, secunde, durata,
                                                   "ținta n-a primit focusul")))
                    return
                time.sleep(0.05)

            ferestre.scrie(text, int(self.reglaje["per_lot"]),
                           float(self.reglaje["pauza_lot"]))
            self.mesaje.put(("scris", (len(text), secunde, durata, unde)))
            # După „scris", nu înainte: `_pompa` scrie ambele mesaje în aceeași
            # etichetă, iar ultimul rămâne. Un devans care a căzut e mai important
            # de citit decât câte caractere s-au scris — și oricum se vede numai
            # când chiar a căzut ceva.
            if self.devans is not None and self.devans.nota:
                self.mesaje.put(("nota", self.devans.nota))
        except Exception as ex:
            self.mesaje.put(("eroare", f"{type(ex).__name__}: {ex}"))

    # ── pompa de mesaje: singurul loc care atinge fereastra ──────────────

    def _pompa(self) -> None:
        while True:
            try:
                fel, sarcina = self.mesaje.get_nowait()
            except queue.Empty:
                break

            if fel == "model":
                self.model = sarcina["model"]
                self.conducta = sarcina["conducta"]
                self.config_igpu = sarcina["config"]
                self.devans = sarcina["devans"]
                self._treci_in("gata")
                nota = (f"{self.reglaje['model']} · încărcat "
                        f"{sarcina['incarcat']:.1f} s, încălzit "
                        f"{sarcina['incalzit']:.1f} s")
                if self.conducta is not None:
                    nota += (f" · iGPU compilat {sarcina['compilat']:.1f} s, "
                             f"sub {float(self.reglaje['granita_igpu']):.0f} s")
                elif sarcina["nota_igpu"]:
                    # Ruta cerută care n-a pornit se SPUNE. Altfel Iris ar merge
                    # liniștit pe CPU, iar cineva ar crede că iGPU-ul lucrează.
                    nota += f" · fără iGPU: {sarcina['nota_igpu']}"
                self.et_nota.config(text=nota)
            elif fel == "tasta":
                {"comuta": self.comuta, "anuleaza": self.anuleaza}[sarcina]()
            elif fel == "scris":
                caractere, secunde, durata, unde = sarcina
                self._treci_in("gata")
                self.et_nota.config(
                    text=f"scris {caractere} caractere · {secunde:.1f} s vorbite, "
                         f"{durata:.1f} s transcriere pe {unde}")
                suna("gata", self.reglaje)
            elif fel == "clipboard":
                text, secunde, durata, motiv = sarcina
                self.rad.clipboard_clear()
                self.rad.clipboard_append(text)
                self._treci_in("gata")
                self.et_nota.config(
                    text=f"{motiv} — {len(text)} caractere în clipboard, "
                         f"lipește cu Ctrl+V")
                suna("eroare", self.reglaje)
            elif fel == "nimic":
                self._treci_in("gata")
                self.et_nota.config(
                    text=f"nimic de scris din {sarcina:.1f} s de audio")
                suna("eroare", self.reglaje)
            elif fel == "nota":
                self.et_nota.config(text=str(sarcina))
            elif fel == "eroare":
                self._arata_eroare(str(sarcina))
            elif fel == "eroare_fatala":
                self.stare = "eroare"
                self.et_stare.config(text="modelul nu s-a încărcat", fg="#a00")
                self.et_nota.config(text=str(sarcina))
                suna("eroare", self.reglaje)

        if self.stare in ("gata", "incarc"):
            # Cât programul stă degeaba, ține minte ultima fereastră reală în
            # care ai fost. Se îngheață din clipa în care începi să vorbești:
            # dacă între „Ascultă" și „Stop" te muți altundeva, textul tot acolo
            # se duce de unde ai pornit.
            self._urmareste_tinta()
        if self.stare == "ascult":
            self._bate_ceasul()
        if EROARE_SUNET:
            self.et_nota.config(text=f"sunetul tace: {EROARE_SUNET[0]}")
            EROARE_SUNET.clear()
        if self.taste.erori:
            self.et_nota.config(
                text=f"tasta globală n-a putut fi înregistrată "
                     f"({self.taste.erori[0]}) — folosește butoanele")
            self.taste.erori.clear()
        if self.eroare_flux:
            self.et_nota.config(
                text=f"microfonul nu s-a închis curat: {self.eroare_flux[0]}")
            self.eroare_flux.clear()

        self._raspunde_la_semnal()
        self.rad.after(120, self._pompa)

    def _raspunde_la_semnal(self) -> None:
        """A doua pornire cere fereastra înapoi. Restaurarea se face DE AICI.

        Din firul lui Tk, prin API-ul lui: `deiconify` scoate din minimizare și
        lasă starea internă corectă, iar `lift` o aduce peste celelalte. Un alt
        proces nu poate face nici una, nici alta de încredere — vezi comentariul
        din ferestre.py.
        """
        if not SEMNAL.exists():
            return
        # Se șterge ÎNAINTE de a acționa: dacă deiconify ridică o excepție,
        # semnalul rămas ar reîncerca la fiecare 120 ms, la nesfârșit.
        try:
            SEMNAL.unlink(missing_ok=True)
        except Exception:
            return
        self.rad.deiconify()
        self.rad.lift()

    def _urmareste_tinta(self) -> None:
        """Ultima fereastră care nu e a noastră. Se ține minte până la alta."""
        activa = ferestre.fereastra_activa()
        if not activa or activa == self.hwnd_propriu:
            return
        if activa != self.tinta:
            self.tinta = activa
            nume = ferestre.titlu(activa) or "(fără titlu)"
            self.et_tinta.config(text=f"→ {nume[:44]}")

    def _bate_ceasul(self) -> None:
        scurse = time.perf_counter() - self.t_pornire
        plafon = float(self.reglaje["plafon_secunde"])
        self.et_ceas.config(text=f"{int(scurse) // 60:02d}:{int(scurse) % 60:02d}")
        if scurse >= plafon:
            self.et_nota.config(text=f"plafon de {plafon:.0f} s atins — se trimite")
            self.opreste()
        elif plafon - scurse <= 30:
            self.et_ceas.config(fg="#a00")

    def comuta(self) -> None:
        {"gata": self.porneste, "ascult": self.opreste}.get(
            self.stare, lambda: None)()

    def _treci_in(self, stare: str) -> None:
        self.stare = stare
        texte = {"incarc": "se încarcă…", "gata": "gata", "ascult": "● ascult",
                 "transcriu": "transcriu…"}
        culori = {"ascult": "#a00", "transcriu": "#a60"}
        self.et_stare.config(text=texte.get(stare, stare),
                             fg=culori.get(stare, "#000"))
        self.b_ascult.config(state="normal" if stare == "gata" else "disabled")
        self.b_stop.config(state="normal" if stare == "ascult" else "disabled")
        if stare != "ascult":
            self.et_ceas.config(text="", fg="#666")

    def _arata_eroare(self, mesaj: str) -> None:
        self._inchide_fluxul()
        self._treci_in("gata")
        self.et_nota.config(text=f"eroare: {mesaj}")
        suna("eroare", self.reglaje)

    def inchide(self) -> None:
        self._inchide_fluxul()
        # Firul e daemon, deci n-ar ține procesul în viață — dar o encodare
        # pornită în timp ce interpretorul se stinge n-are niciun rost.
        if self.devans is not None:
            self.devans.inchide()
        self._salveaza_pozitia()
        # DIB-ul și DC-ul pânzei se eliberează explicit. Sistemul le-ar recupera
        # oricum la ieșirea procesului — dar `masca_text` eliberează corect ale
        # ei, la fiecare apel, iar o pânză care nu-și eliberează nimic e o
        # inconsecvență, nu o alegere. Se cheamă ÎNAINTE de `destroy`: după, nu
        # mai există fereastra căreia îi aparține harta.
        if getattr(self, "panza", None) is not None:
            self.panza.scoate_cadrul()
        self.rad.destroy()

    def ruleaza(self) -> None:
        self.rad.mainloop()


def main() -> int:
    # Înaintea oricărui altceva, și mai ales înaintea modelului: a doua instanță
    # cerea 4 GB pe care mașina nu-i avea și cădea cu `mkl_malloc`. Al doilea
    # click pe scurtătură înseamnă „arată-mi fereastra", nu „mai pornește una".
    if not ferestre.suntem_singura_instanta():
        # Nu restaurăm noi fereastra celuilalt proces — îi lăsăm un semnal, pe
        # care bucla lui îl vede în cel mult 120 ms. Fișier gol, șters la citire.
        try:
            SEMNAL.write_text("", encoding="utf-8")
        except Exception as ex:
            _plange(f"Iris rulează deja, dar fereastra lui nu s-a putut chema:\n"
                    f"{SEMNAL}\n\n{type(ex).__name__}: {ex}")
        return 0

    try:
        reglaje = incarca_config()
    except Exception as ex:
        _plange(f"Configurarea nu se citește:\n{CONFIG}\n\n{type(ex).__name__}: {ex}")
        return 1
    try:
        Iris(reglaje).ruleaza()
    except Exception:
        _plange(traceback.format_exc())
        return 1
    return 0


def _plange(mesaj: str) -> None:
    """Pornit fără consolă, un traceback n-are unde să apară. Deci într-o casetă."""
    try:
        from tkinter import messagebox
        rad = tk.Tk()
        rad.withdraw()
        messagebox.showerror("Iris", mesaj)
        rad.destroy()
    except Exception:
        print(mesaj, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
