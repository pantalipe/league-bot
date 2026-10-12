"""Curated Slayer daily macro plan and dependency metadata."""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence


ACTIVATIONS = ("ativar_scrolls", "montar_besta")
REPEATED_MACROS = {"blorb": (3, 300), "free_wpacs": (3, 600)}
FINISHED_DAILIES = "collect_finished_dailys"
BLOCKED_MACROS = set()

MACROS_BY_CATEGORY: Dict[str, tuple] = {
    "ativacoes": ACTIVATIONS,
    "coletas": (
        "beast_colletct_free", "blorb", "cobinar_equip", "colheita_arma_alma",
        "collect_familiar", "mailbox", "free_item_shop", "free_wpacs", "loja_guild_free",
        "pet_guild", "refinamento_skill", "refinamento_skill_completed",
    ),
    "missoes": (
        "cubo_de_melhora", "dragao_dormente", "floresta_circulacao",
        "cave_treinoxp", "treinador",
    ),
    "coletas_finais": (FINISHED_DAILIES,),
}

MACRO_CATALOG = tuple(name for names in MACROS_BY_CATEGORY.values() for name in names)
DEFAULT_MACROS = MACRO_CATALOG

BONUS_DEPENDENCIES = {
    "cubo_de_melhora": ACTIVATIONS,
    "cave_treinoxp": ACTIVATIONS,
}
FINISHED_DAILY_DEPENDENCIES = ("free_wpacs", "cobinar_equip")


def missing_bonus_dependencies(macros: Iterable[str]) -> Dict[str, tuple]:
    selected = set(macros)
    return {
        target: tuple(dep for dep in dependencies if dep not in selected)
        for target, dependencies in BONUS_DEPENDENCIES.items()
        if target in selected and any(dep not in selected for dep in dependencies)
    }


def missing_daily_dependencies(macros: Iterable[str]) -> Dict[str, tuple]:
    selected = set(macros)
    missing = missing_bonus_dependencies(selected)
    if FINISHED_DAILIES in selected:
        absent = tuple(name for name in FINISHED_DAILY_DEPENDENCIES if name not in selected)
        if absent:
            missing[FINISHED_DAILIES] = absent
    return missing


def ordered_macros(macros: Sequence[str], rng=None) -> List[str]:
    """Order known tasks by stage and keep unknown additions before final collection."""
    from league_bot.daily import shuffled_order

    selected = list(dict.fromkeys(macros))
    known = set(MACRO_CATALOG)
    ordered: List[str] = []
    # Start repeatable pickups early so their cooldown can elapse during the rest
    # of the flow. Scrolls and mount still precede combat tasks.
    early = [name for name in REPEATED_MACROS if name in selected]
    if rng is not None:
        rng.shuffle(early)
    ordered.extend(early)
    for category, names in MACROS_BY_CATEGORY.items():
        if category == "coletas_finais":
            continue
        group = [name for name in names if name in selected and name not in REPEATED_MACROS
                 and name != "refinamento_skill_completed"]
        if rng is not None:
            rng.shuffle(group)
        ordered.extend(group)
    unknown = [name for name in selected if name not in known]
    if unknown:
        ordered.extend(shuffled_order(unknown, (), rng) if rng is not None else unknown)
    if "refinamento_skill_completed" in selected:
        ordered.append("refinamento_skill_completed")
    ordered.extend(name for name in MACROS_BY_CATEGORY["coletas_finais"] if name in selected)
    return ordered
