"""Curățenia textului: ce ajunge în casetă după transcriere.

Fără model, fără microfon, fără fereastră — doar funcțiile deterministe.
"""
import json

import pytest

import iris

REGLAJE = json.loads((iris.ACASA / "iris.json").read_text(encoding="utf-8-sig"))
BALBE = REGLAJE["balbe"]
HALUCINATII = REGLAJE["halucinatii"]


def test_fara_linie_noua():
    # Invarianta principală: un `\n` în caseta unui chat trimite fraza.
    text = iris.curata("Prima frază.\nA doua\r\nfrază.\t Gata.", BALBE)
    assert "\n" not in text and "\r" not in text and "\t" not in text
    assert text == "Prima frază. A doua frază. Gata."


def test_balbele_dispar_fara_resturi_de_punctuatie():
    assert iris.curata("Deci, ăăă, mergem acasă.", BALBE) == "Deci, mergem acasă."
    assert iris.curata("Hmm, bun.", BALBE) == "bun."


def test_balba_nu_mananca_un_cuvant():
    # „mama" conține „m", „Ema" conține „e" — tiparele merg pe cuvânt întreg.
    assert iris.curata("Mama și Ema au plecat.", BALBE) == "Mama și Ema au plecat."


def test_halucinatia_se_taie_numai_intreaga():
    text = "Am terminat raportul. Mulțumim pentru vizionare!"
    assert iris.curata(text, BALBE, HALUCINATII) == "Am terminat raportul."


def test_halucinatia_nu_taie_o_fraza_reala():
    text = "Le-am spus mulțumim pentru vizionare și am plecat."
    assert iris.curata(text, BALBE, HALUCINATII) == text


def test_numai_halucinatie_da_text_gol():
    assert iris.curata("Abonați-vă la canal.", BALBE, HALUCINATII) == ""


@pytest.mark.parametrize("text, per_rand, asteptat", [
    ("", 10, []),
    ("unu doi trei", 7, ["unu doi", "trei"]),
    ("cuvantfoartelung scurt", 5, ["cuvantfoartelung", "scurt"]),
])
def test_taie_randuri(text, per_rand, asteptat):
    assert iris.taie_randuri(text, per_rand) == asteptat


def test_configurarea_se_contopeste_un_nivel(tmp_path, monkeypatch):
    cfg = tmp_path / "iris.json"
    # Cu BOM, cum îl scrie PowerShell 5.1.
    cfg.write_text(json.dumps({"beam_size": 1, "volum_pe_sunet": {"gata": 0.05}}),
                   encoding="utf-8-sig")
    monkeypatch.setattr(iris, "CONFIG", cfg)
    monkeypatch.setitem(iris.IMPLICITE, "volum_pe_sunet", {"stop": 0.3})
    reglaje = iris.incarca_config()
    assert reglaje["beam_size"] == 1
    assert reglaje["volum_pe_sunet"] == {"stop": 0.3, "gata": 0.05}
    assert reglaje["model"] == iris.IMPLICITE["model"]


def test_configurarea_lipsa_da_implicitele(tmp_path, monkeypatch):
    monkeypatch.setattr(iris, "CONFIG", tmp_path / "nu-exista.json")
    assert iris.incarca_config() == iris.IMPLICITE


def test_sunetele_din_configurare_exista():
    for nume, cale in REGLAJE["sunete_fisiere"].items():
        assert (iris.ACASA / cale).is_file(), f"{nume}: {cale}"
