"""Rândul de stare de sub pulsar: întreg, oricât de lung, fără fereastră deschisă."""
import types

import iris


def gazda(latime_logica: int = 200, scara: float = 1.5):
    """Exact câmpurile de care au nevoie `_randuri_stare` și `_masca` — fără Tk."""
    px = lambda v: int(round(v * scara))
    g = types.SimpleNamespace(L=px(latime_logica), px=px, _cache_text={})
    for nume in ("_masca", "_randuri_stare"):
        setattr(g, nume, types.MethodType(getattr(iris.Iris, nume), g))
    return g


def latime(g, text):
    return g._masca(text, "Bahnschrift", g.px(11), True).shape[1]


def test_starile_scurte_raman_rarite():
    g = gazda()
    for stare in ("gata", "● ascult", "transcriu…", "se încarcă…"):
        assert g._randuri_stare(stare) == [" ".join(stare.upper())]


def test_eroarea_incape_intreaga():
    g = gazda()
    randuri = g._randuri_stare("modelul nu s-a încărcat")
    assert " ".join(randuri) == "MODELUL NU S-A ÎNCĂRCAT"
    assert all(latime(g, r) <= g.L for r in randuri)


def test_textul_lung_se_rupe_fara_sa_piarda_cuvinte():
    g = gazda(latime_logica=120)
    text = "tasta globală n-a putut fi înregistrată de sistem"
    randuri = g._randuri_stare(text)
    assert len(randuri) > 1
    assert " ".join(randuri).split() == text.upper().split()
    assert all(latime(g, r) <= g.L for r in randuri)


def test_fara_text_fara_randuri():
    assert gazda()._randuri_stare("") == []
