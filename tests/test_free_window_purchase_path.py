"""Ilmaisen ikkunan aikana ostaminen pitaa olla mahdollista (16.8.2026).

MITATTU TAPAUS. Villen havainto: "toi keep it after that buttoni ei ohjaa
mihinkaan". Ikkunan bannerin ainoa nappi kutsui `goUpgrade()`, joka nostaa
`upgradeOpen`-lipun. Mutta:

    const premium = $derived(forcePremium || !!auth.sub);
    $effect(() => { if (premium && upgradeOpen) upgradeOpen = false; });
    {#if upgradeOpen && !premium}

Ilmaisikkuna antaa kayttajalle synteettisen tilauksen (plan 'gw1-3-free'),
joten `auth.sub` on tosi ja `premium` on tosi. Nappi nosti lipun ja efekti
laski sen samassa hetkessa, eika naytto renderoitynyt koskaan.

🔴 Tama ei ollut kosmeettinen. Ikkuna PIILOTTAA paywallin, joten tuo nappi
oli ainoa ostopolku ikkunan aikana. Kukaan ei ole voinut ostaa siita
hetkesta kun ikkuna avattiin - eli tulonmenetys koko GW1-GW3:n ajan.

Vikaluokka on tuttu: yksi lippu palveli kahta eri kysymysta. "Saako tama
kayttaja tyokalut auki" ja "onko tama kayttaja maksanut" ovat ikkunan
aikana ERI kysymyksia, ja niin kauan kuin ne jakoivat muuttujan, toinen
niista vastasi vaarin.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "web" / "pro-spa" / "src" / "lib" / "components" / "ToolsHome.svelte"
FREE_PLAN = "gw1-3-free"


def _src() -> str:
    return TOOLS.read_text(encoding="utf-8")


def test_paid_premium_excludes_the_free_window_plan():
    """Ostopolun portin on erotettava maksettu tilaus ikkunatilauksesta."""
    src = _src()
    m = re.search(r"const paidPremium = \$derived\((.*?)\);", src, re.S)
    assert m, "paidPremium-johdannaista ei loydy ToolsHome.sveltesta"
    body = m.group(1)
    assert FREE_PLAN in body, (
        f"paidPremium ei sulje pois ikkunatilausta ('{FREE_PLAN}'). Ilman sita "
        f"ikkunan kayttaja lasketaan maksaneeksi eika paase ostamaan.")


def test_upgrade_view_is_not_gated_by_the_bare_premium_flag():
    """Sekä renderointiehto etta sulkeva efekti pitaa katsoa paidPremiumia.

    Riittaa etta TOISESSA lukee `premium`, ja polku on taas kuollut: efekti
    sulkee nakymän vaikka ehto paastaisi sen lapi.
    """
    src = _src()

    render = re.search(r"\{#if upgradeOpen && !(\w+)\}", src)
    assert render, "upgrade-nakyman renderointiehtoa ei loydy"
    assert render.group(1) == "paidPremium", (
        f"renderointiehto katsoo lippua '{render.group(1)}', ei paidPremiumia")

    # Sulkeva efekti on AIKEEN mukainen. 16.8 iltapaivalla tama korjattiin
    # kahdesti: ensin 'premium' tappoi Keep-napin, sitten pelkka 'paidPremium'
    # jatti juuri rekisteroityneen jumiin upgrade-sivulle. Molemmat haarat
    # tarvitaan, ja kumpikin katsoo ERI lippua.
    gate = re.search(
        r"upgradeIntent === 'gate' && (\w+)\) upgradeOpen = false;", src)
    assert gate, "gate-aikeen sulkevaa haaraa ei loydy"
    assert gate.group(1) == "premium", (
        f"gate-haara katsoo lippua '{gate.group(1)}', ei premiumia. "
        f"Ikkunan kautta rekisteroitynyt jaa jumiin upgrade-sivulle.")

    keep = re.search(
        r"upgradeIntent === 'keep' && (\w+)\) upgradeOpen = false;", src)
    assert keep, "keep-aikeen sulkevaa haaraa ei loydy"
    assert keep.group(1) == "paidPremium", (
        f"keep-haara katsoo lippua '{keep.group(1)}', ei paidPremiumia. "
        f"\"Keep it after that\" sulkisi itsensa heti.")


def test_tools_stay_open_during_the_window():
    """Negatiivinen kontrolli toiseen suuntaan: korjaus ei saa sulkea
    tyokaluja ikkunan kayttajalta. Tyokalugate katsoo YHA `premium`ia."""
    src = _src()
    assert re.search(r"if \(t\.premium && !premium\)", src), (
        "tyokalugate ei enaa katso `premium`-lippua. Jos se vaihdettiin "
        "paidPremiumiin, ilmaisikkunan kayttaja menetti juuri ne tyokalut "
        "jotka ikkunan oli tarkoitus avata.")


def test_negative_control_mutation_is_caught():
    """Palauta vanha vika -> porttien PITAA kaatua."""
    mutated = _src().replace(
        "upgradeIntent === 'keep' && paidPremium",
        "upgradeIntent === 'keep' && premium")
    keep = re.search(
        r"upgradeIntent === 'keep' && (\w+)\) upgradeOpen = false;", mutated)
    assert keep and keep.group(1) == "premium", (
        "negatiivinen kontrolli ei purrut: en saanut vanhaa vikaa takaisin, "
        "joten portti ei mittaa sita mita luulen sen mittaavan")
