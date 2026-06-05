"""
corrections.py — optional dictionary correction pass for pdf2json.

PDFs sometimes yield slightly mangled words. After the structural extraction is
done, this pass fixes *genuine* misspellings (e.g. "Univrsity" -> "University")
while doing its best to leave proper nouns, codes, and numbers untouched.

It is deliberately conservative:
  - tokens with any digit are never touched (codes, cutoffs, years);
  - tokens shorter than 4 characters are skipped;
  - all-caps acronyms of 5 chars or fewer are skipped;
  - a token is only replaced when the spell checker is confident AND the
    suggestion is within edit distance 1 of the original — long proper nouns
    (KENYATTA, CHUKA, ...) have no near dictionary match, so they survive.

If `pyspellchecker` is not installed the pass is skipped with a warning, so the
converter still runs.
"""

import sys

try:
    from spellchecker import SpellChecker
    _HAVE_SPELL = True
except Exception:  # pragma: no cover - import guard
    _HAVE_SPELL = False


# Domain words pdfplumber output is full of that the generic dictionary would
# otherwise try to "fix". Anything here is protected.
_PROTECTED = {
    "kuccps", "jkuat", "diploma", "bachelor", "programme", "programmes",
    "cutoff", "cutoffs", "prog",
}


def _looks_correctable(token):
    """True if we are willing to consider correcting this token at all."""
    if len(token) < 4:
        return False
    if any(ch.isdigit() for ch in token):
        return False
    if not any(ch.isalpha() for ch in token):
        return False
    # all-caps short acronyms: leave alone (e.g. "ISO", "BA", "BSC")
    if token.isupper() and len(token) <= 5:
        return False
    if token.lower() in _PROTECTED:
        return False
    return True


def _edit_distance_one(a, b):
    """Cheap check: are a and b within Levenshtein distance 1? (case-insensitive)"""
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    # find first differing position
    i = 0
    while i < min(la, lb) and a[i] == b[i]:
        i += 1
    if la == lb:  # substitution: rest must match
        return a[i + 1:] == b[i + 1:]
    if la < lb:  # insertion into a
        return a[i:] == b[i + 1:]
    return a[i + 1:] == b[i:]  # deletion from a


def _restore_case(original, suggestion):
    """Make the suggestion match the original's casing pattern."""
    if original.isupper():
        return suggestion.upper()
    if original[:1].isupper():
        return suggestion.capitalize()
    return suggestion


def make_corrector(enabled=True, quiet=False):
    """Return a function token->token. A no-op if disabled or unavailable."""
    if not enabled:
        return lambda token: token
    if not _HAVE_SPELL:
        if not quiet:
            sys.stderr.write(
                "note: pyspellchecker not installed — skipping word correction "
                "(pip install pyspellchecker)\n"
            )
        return lambda token: token

    spell = SpellChecker(distance=1)
    cache = {}

    def correct(token):
        if token in cache:
            return cache[token]
        result = token
        if _looks_correctable(token):
            lower = token.lower()
            if lower not in spell:  # unknown word
                cand = spell.correction(lower)
                if cand and cand != lower and _edit_distance_one(lower, cand):
                    result = _restore_case(token, cand)
        cache[token] = result
        return result

    return correct


def _correct_phrase(text, correct):
    """Apply the corrector token-by-token, preserving spacing."""
    if not text:
        return text
    return " ".join(correct(tok) for tok in text.split())


def apply_corrections(sections, enabled=True, quiet=False):
    """Mutate `sections` in place, correcting labels and cell values.

    Returns the number of tokens changed (for reporting)."""
    correct = make_corrector(enabled, quiet=quiet)
    changed = 0

    def fix(text):
        nonlocal changed
        new = _correct_phrase(text, correct)
        if new != text:
            changed += sum(1 for a, b in zip(text.split(), new.split()) if a != b)
        return new

    for sec in sections:
        if sec.get("heading"):
            sec["heading"] = fix(sec["heading"])
        labels = sec.get("labels") or []
        new_labels = [fix(lbl) for lbl in labels]
        # remap rows if any label text changed
        relabel = {old: new for old, new in zip(labels, new_labels) if old != new}
        sec["labels"] = new_labels
        for row in sec.get("rows", []):
            if relabel:
                for old, new in relabel.items():
                    if old in row:
                        row[new] = row.pop(old)
            for key in list(row.keys()):
                row[key] = fix(row[key])
    return changed
