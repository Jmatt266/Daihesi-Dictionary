#!/usr/bin/env python3
"""Rebuild daihesi.html from a fresh export of the 'Daihesi Language' Google Doc.

Usage:
    python3 build.py [EXPORT] [-o OUTPUT] [-t TEMPLATE]

EXPORT can be either
  * the JSON returned by the Google Docs read_document tool
    ({"elements": [{"style": "HEADING_1", "text": "..."}, ...]}), or
  * a plain-text export (Google Docs: File > Download > Plain text (.txt)).
Defaults: EXPORT=doc-export.json, TEMPLATE=template.html, OUTPUT=daihesi.html,
all relative to this script's folder. Standard library only.

Headwords are capitalized as they are added to the lexicon (the first letter
only). Entries that begin with a hyphen or an apostrophe — affixes and
contractions — are left unchanged. Lookups in the page are case-insensitive.
"""
import argparse, base64, datetime, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
H1_NAMES = ["Phonology", "Affixes", "Grammar", "Vocabulary", "Compound Words"]
POS_WORDS = {"noun", "verb", "adjective", "adverb", "numeral", "pronoun", "preposition",
             "conjunction", "determiner", "interjection", "article", "proper", "helping",
             "past", "participle", "particle", "prefix", "suffix", "phrase", "title",
             "present", "contraction", "plural", "form"}
ENTRY_RE = re.compile(r"^(?P<hw>.+?) \((?P<pron>[^()]*)\) (?P<rest>\(.+)$")
POS_RE = re.compile(r"\(([a-z]+(?: [a-z]+)*(?:, [a-z]+(?: [a-z]+)*)*)\)\s*")


# ---------------------------------------------------------------- loading
def load_paragraphs(path):
    """Return a list of (style, text) paragraphs."""
    raw = open(path, encoding="utf-8-sig").read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict) and "elements" in data:
        return [(e.get("style") or "", (e.get("text") or "").strip()) for e in data["elements"]], data.get("revisionId", "")
    return infer_styles(raw.splitlines()), ""


def infer_styles(lines):
    """Rebuild heading levels for a plain-text export."""
    out, h1 = [], None
    for line in lines:
        t = re.sub(r"^[*•\-]\s+(?=\S)", "• ", line.strip()) if line.strip().startswith(("* ", "• ")) else line.strip()
        if not t:
            continue
        style = ""
        if t in H1_NAMES or t.startswith("Changelog"):
            style, h1 = "HEADING_1", t
        elif h1 == "Vocabulary" and re.fullmatch(r"[A-Z]", t):
            style = "HEADING_2"
        elif h1 == "Phonology" and t in ("Vowels", "Consonants"):
            style = "HEADING_2"
        elif h1 == "Affixes" and t in ("Suffixes", "Prefixes"):
            style = "HEADING_2"
        elif h1 == "Grammar" and re.match(r"^\d+\. \S", t) and " = " not in t and len(t) < 60:
            style = "HEADING_2"
        out.append((style, t))
    return out


def sections(paras):
    """{H1 title: [(h2 title or None, [lines])]}"""
    res, cur, sub = {}, None, None
    for style, text in paras:
        if style == "HEADING_1":
            cur = text.split(" (")[0] if text.startswith("Changelog") else text
            res[cur] = [[None, []]]
        elif cur is None:
            continue
        elif style == "HEADING_2":
            res[cur].append([text, []])
        elif text:
            res[cur][-1][1].append(text)
    return res


# ---------------------------------------------------------------- parsing
def split_gloss(gloss):
    """'General - overall, whole' -> terms; keeps notes in () and []."""
    notes = re.findall(r"[(\[]([^)\]]*)[)\]]", gloss)
    clean = re.sub(r"\s*[(\[][^)\]]*[)\]]", "", gloss)
    parts = []
    if " - " in clean:
        main, qual = clean.split(" - ", 1)
        parts = [main] + re.split(r"\s*[,;/]\s*", qual)
    else:
        parts = re.split(r"\s*[,;/]\s*", clean)
    terms = []
    for p in parts:
        p = p.strip(" .")
        if not p or p.lower().startswith(("unique meaning", "english name")):
            continue
        if p.lower() not in [x.lower() for x in terms]:
            terms.append(p)
    return terms, notes


# Affixes and contractions are filed under a leading hyphen or apostrophe.
_LEADING_UNCHANGED = set("-‐‑‒–—―'’‘`´ʼʹ")
CAPITALIZED = []


def capitalize_headword(hw):
    """Capitalize the first letter of a lexicon headword.

    The rest of the spelling is preserved. A headword that already begins
    with a hyphen or an apostrophe is returned unchanged so affixes and
    contractions stay in the form the language document gives them.
    """
    if not hw or hw[0] in _LEADING_UNCHANGED:
        return hw
    capped = hw[0].upper() + hw[1:]
    if capped != hw:
        CAPITALIZED.append((hw, capped))
    return capped


def parse_entry(text):
    m = ENTRY_RE.match(text)
    if not m or " — English: " not in text:
        return None
    body, gloss = m.group("rest").rsplit(" — English: ", 1)
    body = re.sub(r"\(([a-z]+(?: [a-z]+)*) \(([a-z]+(?: [a-z]+)*)\)\)", r"(\1, \2)", body)  # "(verb (present))"
    senses, pos_all = [], []
    pieces = POS_RE.split(body)
    # pieces: ['', pos1, def1, pos2, def2, ...]; non-POS parentheticals must be re-joined
    i, cur = 1, None
    while i < len(pieces):
        tok = pieces[i]
        if i % 2 == 1:
            words = set(re.split(r"[ ,]+", tok))
            if words <= POS_WORDS:
                cur = {"pos": tok, "def": ""}
                senses.append(cur)
                pos_all += [p.strip() for p in tok.split(",")]
            elif cur is not None:
                cur["def"] += "(" + tok + ") "
        else:
            if cur is None:
                cur = {"pos": "", "def": ""}
                senses.append(cur)
            cur["def"] += tok
        i += 1
    for s in senses:
        s["def"] = s["def"].strip()
    terms, notes = split_gloss(gloss.strip())
    hw = capitalize_headword(m.group("hw").strip())
    return {"h": hw, "p": m.group("pron").strip(), "s": senses,
            "pos": list(dict.fromkeys(pos_all)), "g": gloss.strip(), "en": terms, "n": notes,
            "l": strip_accents(hw[:1]).upper()}


def strip_accents(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def parse_phonology(sec):
    out = {"vowels": [], "vowelLetters": "", "vowelNotes": [], "rules": [], "consonants": ""}
    for title, lines in sec:
        if title == "Vowels":
            in_rules = False
            for i, t in enumerate(lines):
                parts = t.split(" — ")
                if i == 0 and "—" not in t:
                    out["vowelLetters"] = t
                elif t.rstrip(":").lower() == "vowel rules":
                    in_rules = True
                elif in_rules:
                    out["rules"].append(t)
                elif len(parts) >= 2 and len(parts[0]) <= 8:
                    ipa = parts[1] if len(parts) >= 3 else ""
                    out["vowels"].append({"v": parts[0], "ipa": ipa, "d": " — ".join(parts[2:] if ipa else parts[1:])})
                else:
                    out["vowelNotes"].append(t)
        elif title == "Consonants":
            out["consonants"] = " ".join(lines)
        elif lines:
            out["vowelNotes"] += lines
    return out


def parse_affixes(sec):
    out = {"suffixes": [], "prefixes": [], "notes": []}
    for title, lines in sec:
        key = "prefixes" if (title or "").lower().startswith("prefix") else "suffixes"
        for t in lines:
            m = re.match(r"^(\S+)\s+—\s+(.*)$", t)
            if not m:
                out["notes"].append(t)
                continue
            desc, en = m.group(2), ""
            b = re.search(r"\s*\[([^\]]+)\]\s*$", desc)
            if b:
                en, desc = b.group(1), desc[:b.start()]
            out[key].append({"a": m.group(1), "d": desc.strip(), "en": en})
    return out


FUNC_SECTIONS = ("article", "pronoun", "to be", "helping", "negation")


def parse_grammar(sec):
    rules, func = [], []
    for title, lines in sec:
        if title is None and not lines:
            continue
        rules.append({"t": title or "", "lines": lines})
        if title and any(k in title.lower() for k in FUNC_SECTIONS):
            for line in lines:
                for piece in re.split(r"\s+\|\s+|\.\s+", line):
                    m = re.match(r"^([A-Za-z][a-z/ ]*?)(?:\s*\([^)]*\))?\s*=\s*([^\s,.;()]+)", piece.strip())
                    if not m:
                        continue
                    for en in m.group(1).split("/"):
                        func.append({"en": en.strip(), "da": m.group(2).strip(), "src": title})
    return rules, func


def parse_compounds(sec):
    out = []
    for _, lines in sec:
        for t in lines:
            if " — " not in t:
                continue
            da, en = t.split(" — ", 1)
            das = [x.strip() for x in da.split("|") if x.strip()]
            ens = []
            for alt in re.split(r"\s+[|/]\s+", en):
                alt = alt.strip()
                ens.append(re.sub(r"\s+and\s+", " ", alt, flags=re.I).strip())
            out.append({"da": das, "en": ens, "raw": t})
    return out


def build_data(paras, revision=""):
    CAPITALIZED.clear()
    sec = sections(paras)
    entries, unparsed = [], []
    for title, lines in sec.get("Vocabulary", []):
        for t in lines:
            if t.startswith("(no entries"):
                continue
            e = parse_entry(t)
            (entries.append(e) if e else unparsed.append(t))
    grammar, func = parse_grammar(sec.get("Grammar", []))
    title = next((t for s, t in paras if s == "TITLE"), "Daihesi Language")
    return {
        "meta": {"title": title, "revision": revision,
                 "built": datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
                 "count": len(entries)},
        "entries": entries,
        "phonology": parse_phonology(sec.get("Phonology", [])),
        "affixes": parse_affixes(sec.get("Affixes", [])),
        "grammar": grammar,
        "func": func,
        "compounds": parse_compounds(sec.get("Compound Words", [])),
    }, unparsed


def asset(*names):
    """First existing file among names, relative to this script."""
    for name in names:
        path = os.path.join(HERE, name)
        if os.path.isfile(path) and os.path.getsize(path):
            return path
    return os.path.join(HERE, names[0])


def data_uri(path):
    """Inline an image so the HTML stays self-contained; empty if missing."""
    if not os.path.exists(path):
        return ""
    return "data:image/png;base64," + base64.b64encode(open(path, "rb").read()).decode()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", nargs="?", default=os.path.join(HERE, "doc-export.json"))
    ap.add_argument("-o", "--output", default=os.path.join(HERE, "daihesi.html"))
    ap.add_argument("-t", "--template", default=os.path.join(HERE, "template.html"))
    ap.add_argument("--json", help="also write the parsed data to this JSON file")
    a = ap.parse_args()
    paras, rev = load_paragraphs(a.export)
    data, unparsed = build_data(paras, rev)
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = open(a.template, encoding="utf-8").read()
    if "__DAIHESI_DATA_JSON__" not in html:
        sys.exit("template is missing the __DAIHESI_DATA_JSON__ placeholder")
    html = html.replace("__LOGO_DATA_URI__", data_uri(asset("assets/logo.png", "hakelimebel-gold.png")))
    html = html.replace("__FAVICON_DATA_URI__", data_uri(asset("assets/favicon.png", "hakelimebel-gold.png")))
    open(a.output, "w", encoding="utf-8").write(html.replace("__DAIHESI_DATA_JSON__", blob))
    if a.json:
        json.dump(data, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"entries: {len(data['entries'])}  suffixes: {len(data['affixes']['suffixes'])}  "
          f"prefixes: {len(data['affixes']['prefixes'])}  grammar sections: {len(data['grammar'])}  "
          f"function words: {len(data['func'])}  compounds: {len(data['compounds'])}  "
          f"headwords capitalized: {len(CAPITALIZED)}")
    for t in unparsed:
        print("WARNING: could not parse entry:", t[:120], file=sys.stderr)
    print("wrote", a.output, f"({os.path.getsize(a.output)//1024} KB)")


if __name__ == "__main__":
    main()
