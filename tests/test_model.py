"""Integrare: modelul Whisper real, încărcat ca în `iris.py` (`local_files_only`).

Se SARE, cu motivul spus, când modelul nu e în cache-ul HuggingFace — testul nu
descarcă nimic. Descărcarea: vezi README, „Installation", pasul 3.
"""
import numpy as np
import pytest

import iris

faster_whisper = pytest.importorskip("faster_whisper")


@pytest.fixture(scope="module")
def model():
    reglaje = iris.incarca_config()
    try:
        return faster_whisper.WhisperModel(
            reglaje["model"], device="cpu", compute_type="int8",
            cpu_threads=4, local_files_only=True)
    except Exception as ex:
        pytest.skip(f"modelul `{reglaje['model']}` nu e în cache-ul HuggingFace "
                    f"({type(ex).__name__}); vezi README, pasul 3")


def test_tacerea_nu_scrie_nimic(model):
    # Pe tăcere, cu VAD-ul pornit ca în `iris.py`, nu trebuie să iasă text.
    tacere = np.zeros(16000 * 3, dtype=np.float32)
    segmente, info = model.transcribe(tacere, language="ro", beam_size=1,
                                      vad_filter=True)
    reglaje = iris.incarca_config()
    text = iris.curata("".join(s.text for s in segmente),
                       reglaje["balbe"], reglaje["halucinatii"])
    assert info.language == "ro"
    assert text == ""


def test_devansul_se_leaga_de_model(model):
    # `Devans` înlocuiește `model.encode` pe instanță; o dictare scurtă nu-l atinge.
    reglaje = iris.incarca_config()
    devans = iris.Devans(model, reglaje)
    assert model.encode == devans.encode
    assert devans.pas(np.zeros(16000 * 5, dtype=np.int16)) == "scurt"
