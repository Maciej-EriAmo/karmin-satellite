#!/usr/bin/env python3
"""
kernel_boundary.py — straznik granicy JADRO <-> OPROGRAMOWANIE (KarmazynOS)
==========================================================================
Maciej Mazur, Warsaw 2026

Jedna regula, ktorej zlamanie spowodowalo balagan:
    JADRO NIGDY NIE IMPORTUJE OPROGRAMOWANIA.

Czyta pliki .py (plaski katalog albo rozdzielone kernel/ + software/) i sprawdza
te regule przez AST — nie po stringach, tylko po realnych instrukcjach import.
Twardy blad (exit 1), gdy plik jadra importuje modul oprogramowania POZA oslona
`if __name__ == "__main__"`. Importy pod ta oslona = OSTRZEZENIE (szew D5:
self-test jadra zalezy od jezyka). Doradczo: pliki oprogramowania siegajace do
WNETRZA jadra zamiast do fasady 'karmazyn_kernel'.

Uzycie:
    python3 kernel_boundary.py .                  # plaski katalog
    python3 kernel_boundary.py kernel/ software/  # po rozdzieleniu
    # exit 0 = granica czysta, exit 1 = twarde naruszenie (do CI)

FIX v1.1 (audyt 2026-07):
  Kolizje nazw modulow miedzy katalogami (np. kernel/foo.py i software/foo.py)
  wczesniej cicho nadpisywaly wpis w slowniku — jeden z plikow NIE byl
  skanowany. Teraz: KAZDY znaleziony plik jest skanowany (lista, nie dict),
  a duplikaty nazw sa raportowane jako OSTRZEZENIE.
"""

import ast
import os
import sys
from typing import List, Tuple

KERNEL = {
    "karmazyn_atom",
    "karmazyn_hrr",
    "karmazyn_substrate",
    "karmazyn_atomstore",
    "karmazyn_kernel",      # publiczna fasada — czesc powierzchni jadra
    "karmazyn_backend",     # przełącznik native|python — część jadra (enterprise 2026-07)
    "karmazyn_substrate_native",  # most Rust (PyO3/ctypes) — implementacja substratu
}

INTERNAL_PREFIXES = ("karmazyn_", "luneta")
FACADE = "karmazyn_kernel"


def _module_base(name: str) -> str:
    return (name or "").split(".")[0]


def _is_main_guard(test: ast.expr) -> bool:
    if not isinstance(test, ast.Compare):
        return False
    if not (isinstance(test.left, ast.Name) and test.left.id == "__name__"):
        return False
    for op, cmp in zip(test.ops, test.comparators):
        if isinstance(op, ast.Eq) and isinstance(cmp, ast.Constant) \
                and cmp.value == "__main__":
            return True
    return False


def _walk(node: ast.AST, guarded: bool, out: List[Tuple[str, bool]]) -> None:
    """Sprawdza KAZDY wezel (nie tylko dzieci) — stad poprawne zliczanie
    importow takze wewnatrz `if __name__ == '__main__'` i try/except."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            out.append((_module_base(alias.name), guarded))
        return
    if isinstance(node, ast.ImportFrom):
        if node.module:                       # from X import ... / from .X import ...
            out.append((_module_base(node.module), guarded))
        else:                                  # from . import X  (modul w names)
            for alias in node.names:
                out.append((_module_base(alias.name), guarded))
        return
    if isinstance(node, ast.If) and _is_main_guard(node.test):
        for sub in node.body:
            _walk(sub, True, out)
        for sub in node.orelse:
            _walk(sub, guarded, out)
        return
    for child in ast.iter_child_nodes(node):
        _walk(child, guarded, out)


def imports_of(path: str) -> List[Tuple[str, bool]]:
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    out: List[Tuple[str, bool]] = []
    _walk(tree, False, out)
    return out


def _internal(mod: str) -> bool:
    return any(mod.startswith(p) for p in INTERNAL_PREFIXES)


def _collect(paths: List[str]) -> List[Tuple[str, str]]:
    """Zbiera (nazwa_modulu, sciezka) dla KAZDEGO pliku .py — bez gubienia
    duplikatow nazw (FIX v1.1)."""
    entries: List[Tuple[str, str]] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    if n.endswith(".py"):
                        entries.append((n[:-3], os.path.join(root, n)))
        elif p.endswith(".py"):
            entries.append((os.path.basename(p)[:-3], p))
    return entries


def scan(paths: List[str]) -> int:
    entries = _collect(paths)

    hard: List[str] = []
    warn: List[str] = []
    advice: List[str] = []

    # FIX v1.1: duplikaty nazw modulow (rozne sciezki, ta sama nazwa) —
    # raport zamiast cichego nadpisania; wszystkie i tak sa skanowane.
    by_name = {}
    for mod, path in entries:
        by_name.setdefault(mod, []).append(path)
    for mod, ps in sorted(by_name.items()):
        if len(ps) > 1:
            warn.append(f"{mod}: {len(ps)} pliki o tej samej nazwie modulu: "
                        + ", ".join(ps))

    for mod, path in sorted(entries):
        is_kernel = mod in KERNEL
        for imported, guarded in imports_of(path):
            if not _internal(imported):
                continue
            if is_kernel and imported not in KERNEL:
                if guarded:
                    warn.append(f"{mod} -> {imported}  (pod __main__, self-test — szew D5)")
                else:
                    hard.append(f"{mod} -> {imported}  (TWARDE: jadro importuje oprogramowanie)")
            elif (not is_kernel) and imported in KERNEL and imported != FACADE:
                advice.append(f"{mod} -> {imported}  (wnetrze jadra zamiast fasady '{FACADE}')")

    print("=" * 64)
    print("  STRAZNIK GRANICY JADRO <-> OPROGRAMOWANIE")
    print("=" * 64)
    present = sorted({m for m, _ in entries if m in KERNEL})
    print(f"  plikow .py: {len(entries)}  |  moduly jadra obecne: {present}")

    if hard:
        print("\n[TWARDE NARUSZENIA] jadro importuje oprogramowanie:")
        for v in hard: print(f"  XX {v}")
    else:
        print("\n[OK] zaden plik jadra nie importuje oprogramowania (poza __main__).")
    if warn:
        print("\n[OSTRZEZENIA] importy testowe pod __main__ / duplikaty nazw:")
        for v in warn: print(f"  !! {v}")
    if advice:
        print(f"\n[DORADCZO] oprogramowanie siega do wnetrza jadra (uzyj '{FACADE}'):")
        for v in advice: print(f"  -> {v}")

    print("=" * 64)
    if hard:
        print(f"WYNIK: NARUSZENIE ({len(hard)}). Jadro zmieszane z oprogramowaniem.")
        return 1
    print("WYNIK: granica czysta (twarda regula spelniona).")
    return 0


if __name__ == "__main__":
    sys.exit(scan(sys.argv[1:] or ["."]))