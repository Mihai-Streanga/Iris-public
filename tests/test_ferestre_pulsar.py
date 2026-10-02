"""Tasta globală descifrată și desenul pulsarului — fără să deschidă o fereastră."""
import struct
import zlib

import numpy as np
import pytest

import ferestre
import pulsar


def test_tasta_implicita():
    mod, cod = ferestre.descifreaza_tasta("ctrl+alt+space")
    assert mod == ferestre.MOD_CONTROL | ferestre.MOD_ALT | ferestre.MOD_NOREPEAT
    assert cod == 0x20


@pytest.mark.parametrize("combinatie", ["", "space", "ctrl+alt", "ctrl+nimic"])
def test_tasta_refuzata(combinatie):
    with pytest.raises(ValueError):
        ferestre.descifreaza_tasta(combinatie)


def test_unitati_utf16_pentru_emoji_si_diacritice():
    # Ce trece de BMP cere două evenimente: o pereche de surogate.
    assert list(ferestre._unitati_utf16("ș")) == [0x0219]
    assert list(ferestre._unitati_utf16("😀")) == [0xD83D, 0xDE00]


def test_png_valid():
    rgba = np.zeros((4, 3, 4), dtype=np.uint8)
    date = pulsar.png(rgba)
    assert date.startswith(b"\x89PNG\r\n\x1a\n")
    lungime, eticheta = struct.unpack(">I4s", date[8:16])
    assert eticheta == b"IHDR"
    latime, inaltime, _, tip = struct.unpack(">IIBB", date[16:26])
    assert (latime, inaltime, tip) == (3, 4, 6)
    crc = struct.unpack(">I", date[16 + lungime:20 + lungime])[0]
    assert crc == zlib.crc32(date[12:16 + lungime]) & 0xFFFFFFFF


@pytest.mark.parametrize("stare", ["incarc", "gata", "ascult", "transcriu", "eroare"])
def test_pulsarul_deseneaza_fiecare_stare(stare):
    p = pulsar.Pulsar(64, 17.0)
    alfa, culoare = p.alfa(1.0, stare, nivel=0.5)
    assert alfa.shape == (64, 64)
    assert 0.0 <= alfa.min() and alfa.max() <= 1.0
    assert alfa.max() > 0.1
    assert tuple(culoare.astype(int)) == pulsar.MIEZ[stare]


def test_culoarea_spune_starea():
    assert len(set(pulsar.MIEZ.values())) == len(pulsar.MIEZ)
