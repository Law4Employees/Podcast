#!/usr/bin/env python3
"""Render a podcast script to WAV with the show's voice and pronunciation rules.

Usage: python3 tts.py script.txt episode.wav [--speed 1.0]

Write the script with normal spellings (EEOC, ADA, AI, Kwall Barack Nadeau).
This script:
  - says all-caps acronyms letter by letter with clean letter sounds
    (no "uh" before letters), except those in SAY_AS_WORD;
  - says the firm name and show name correctly;
  - lowers the voice one half-step (same speed);
  - pauses 0.35 s between sentences and 0.7 s between paragraphs;
  - treats a paragraph that is only "[Chapter: Title]" as a chapter marker (not spoken)
    and writes the chapter start times to episode.chapters.json for publish.py --chapters.
"""
import argparse, json, os, re, subprocess, sys, tempfile
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

MODEL = "/home/claude/tts/kokoro-v1.0.onnx"
VOICES = "/home/claude/tts/voices-v1.0.bin"
VOICE = "af_heart"
LANG = "en-us"
# Lower the voice one half-step without changing speed (1.0 = no change).
PITCH = 0.9439

LETTERS = {
    "A": "ˈeɪ", "B": "bˈiː", "C": "sˈiː", "D": "dˈiː", "E": "ˈiː", "F": "ˈɛf",
    "G": "dʒˈiː", "H": "ˈeɪtʃ", "I": "ˈaɪ", "J": "dʒˈeɪ", "K": "kˈeɪ", "L": "ˈɛl",
    "M": "ˈɛm", "N": "ˈɛn", "O": "ˈoʊ", "P": "pˈiː", "Q": "kjˈuː", "R": "ˈɑːɹ",
    "S": "ˈɛs", "T": "tˈiː", "U": "jˈuː", "V": "vˈiː", "W": "dˈʌbəljˌuː",
    "X": "ˈɛks", "Y": "wˈaɪ", "Z": "zˈiː",
}
# All-caps words that are spoken as words, not spelled out.
SAY_AS_WORD = {"ERISA", "OSHA", "COBRA", "CHOICE", "HIPAA", "WARN", "USERRA", "CARES", "PRO"}
# Exact replacements made before anything else (real spelling -> spoken spelling).
# Exact pronunciations (phonemes) for names the voice gets wrong.
NAME_PHONEMES = {
    "Kwall Barack Nadeau": "kwˈɔːl bˈɛɹək neɪdˈuː",
    "Employee Rights Weekly": "ɛmplɔɪˈiː ɹˌaɪts wˈiːkli",
    # Longer forms first so the plural is matched before the singular.
    "comparators": "kəmpˈæɹəɾɚz",
    "Comparators": "kəmpˈæɹəɾɚz",
    "comparator": "kəmpˈæɹəɾɚ",
    "Comparator": "kəmpˈæɹəɾɚ",
    # "em-PLOY-er" with a clear "y" glide; the default blurs the "oy" into the "er".
    "employers": "ɛmplˈɔɪjɚz",
    "Employers": "ɛmplˈɔɪjɚz",
    "employer": "ɛmplˈɔɪjɚ",
    "Employer": "ɛmplˈɔɪjɚ",
    # "KOH-vid", not "KAH-vid". Listing COVID here also keeps it from being spelled out as letters.
    "COVID-19": "kˈoʊvɪd nˈaɪntiːn",
    "Covid-19": "kˈoʊvɪd nˈaɪntiːn",
    "covid-19": "kˈoʊvɪd nˈaɪntiːn",
    "COVID": "kˈoʊvɪd",
    "Covid": "kˈoʊvɪd",
    "covid": "kˈoʊvɪd",
    # Firm names said alone (the full firm name above is matched first).
    "Barack": "bˈɛɹək",
    "Nadeau": "neɪdˈuː",
    # Legal Latin.
    "pro se": "pɹˌoʊ sˈeɪ",
    "prima facie": "pɹˈaɪmə fˈeɪʃə",
    "sua sponte": "sˌuːə spˈɑːnteɪ",
    # Case names.
    "Swierkiewicz": "swɪɹkˈɛvɪtʃ",
    "Faragher": "fˈæɹəɡɚ",
    "Muldrow": "mˈʌldɹoʊ",
    "Gessner": "ɡˈɛsnɚ",
    "Cucina": "kuːtʃˈiːnə",
    "Napoletana": "nˌɑːpoʊlɛtˈɑːnə",
    # Florida places.
    "Kissimmee": "kɪsˈɪmi",
    "Ocala": "oʊkˈælə",
    "Brevard": "bɹəvˈɑːɹd",
    # Acronyms that lawyers say as words.
    "PIPs": "pˈɪps",
    "PIP": "pˈɪp",
    "SOX": "sˈɑːks",
    "GINA": "dʒˈiːnə",
    "FOIA": "fˈɔɪə",
}
REPLACE = {
    "Title VII": "Title Seven",
    "AIR21": "Air twenty-one",
    " v. ": " versus ",
    "Fla. Stat.": "Florida Statutes",
}
ACRONYM = re.compile(r"\b([A-Z]{2,6})(s?)\b")
# Whole words only; an optional possessive 's is said as "z".
NAMES = re.compile(r"\b(" + "|".join(re.escape(n) for n in NAME_PHONEMES) + r")('s)?\b")
ROMAN = {"I": 1, "V": 5, "X": 10}
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                "nineteen", "twenty"]
# Roman numerals after these words are said as numbers: "Title IX" -> "Title nine", "Counts I and II" -> "Counts one and two".
ROMAN_AFTER = re.compile(r"\b(Titles?|Counts?|Chapters?|Articles?|Parts?)((?:(?:\s*,)?\s+(?:and\s+|or\s+|through\s+)?[IVX]{1,5}\b)+)")


def roman_to_words(numeral):
    total = 0
    for i, c in enumerate(numeral):
        v = ROMAN[c]
        total += -v if i + 1 < len(numeral) and ROMAN[numeral[i + 1]] > v else v
    return NUMBER_WORDS[total] if 0 < total < len(NUMBER_WORDS) else numeral


def speakable(sentence):
    for a, b in REPLACE.items():
        sentence = sentence.replace(a, b)
    sentence = ROMAN_AFTER.sub(lambda m: m.group(1) + re.sub(r"\b[IVX]{1,5}\b", lambda r: roman_to_words(r.group(0)), m.group(2)), sentence)
    # "Section 1981" is said "nineteen eighty-one", not "nineteen hundred eighty-one".
    sentence = re.sub(r"§§?\s*", "Section ", sentence)
    sentence = re.sub(r"\b(Sections?\s+)(1[0-9])([1-9][0-9])\b", r"\1\2 \3", sentence)
    return sentence


def to_phonemes(k, sentence):
    sentence = speakable(sentence)
    # Undo hyphen or period spellings like E-E-O-C or E.E.O.C.
    sentence = re.sub(r"\b(?:[A-Z][-.]){1,5}[A-Z]\b\.?", lambda m: re.sub(r"[-.]", "", m.group(0)), sentence)
    tokens = sorted([(m.start(), m.end(), "name", m) for m in NAMES.finditer(sentence)] +
                    [(m.start(), m.end(), "acr", m) for m in ACRONYM.finditer(sentence) if m.group(1) not in SAY_AS_WORD],
                    key=lambda t: t[0])
    parts, pos = [], 0
    for start, end, kind, val in tokens:
        if start < pos:
            continue
        if kind == "name":
            before = sentence[pos:start]
            # A lone "a" right before the name would be read as the letter "ay"; say it as "uh".
            article = re.search(r"\b[aA]\s*$", before)
            if article:
                before = before[:article.start()]
            spoken = NAME_PHONEMES[val.group(1)]
            if before.strip():
                ph = k.tokenizer.phonemize(before, LANG).rstrip()
                # "the" before a vowel sound: say "thee", not "thuh" ("the employer").
                if ph.endswith("ðə") and spoken.lstrip("ˈˌ")[:1] in "aeiouæɑɐɔəɛɜɪʊʌ":
                    ph = ph[:-2] + "ðɪ"
                parts.append(ph)
            if article:
                parts.append("ɐ")
            parts.append(spoken + ("z" if val.group(2) else ""))
            pos = end
            continue
        m = val
        word, plural = m.group(1), m.group(2)
        before = sentence[pos:m.start()]
        # A lone "a" right before the acronym would be read as the letter "ay"; say it as "uh".
        article = re.search(r"\b[aA]\s*$", before)
        if article:
            before = before[:article.start()]
        if before.strip():
            ph = k.tokenizer.phonemize(before, LANG).rstrip()
            # "the" before a letter that starts with a vowel sound: say "thee", not "thuh".
            if word[0] in "AEFHILMNORSX" and ph.endswith("ðə"):
                ph = ph[:-2] + "ðɪ"
            parts.append(ph)
        if article:
            parts.append("ɐ")
        # Say the letters together like a person would: light stress on each, main stress on the last.
        spoken = "".join(LETTERS[c].replace("ˈ", "ˌ") for c in word[:-1]) + LETTERS[word[-1]]
        if plural:
            spoken += "z"
        parts.append(spoken)
        pos = m.end()
    rest = sentence[pos:]
    if rest.strip():
        parts.append(k.tokenizer.phonemize(rest, LANG))
    return " ".join(p.strip() for p in parts if p.strip())


CHAPTER = re.compile(r"^\[Chapter:\s*(.+?)\s*\]$", re.IGNORECASE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--pitch", type=float, default=PITCH)
    ap.add_argument("--show-phonemes", action="store_true")
    ap.add_argument("--chapters", help="where to write chapter start times as JSON "
                    "(default: the output path with .chapters.json; written only if the script has chapter lines)")
    a = ap.parse_args()
    k = Kokoro(MODEL, VOICES)
    text = open(a.script).read()
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    sr, chunks, chapters = 24000, [], []
    for i, p in enumerate(paras):
        # A paragraph that is only "[Chapter: Title]" is not spoken; it starts a chapter at this point.
        # The pitch change keeps the length the same, so these times hold for the final audio.
        mark = CHAPTER.match(p)
        if mark:
            start = sum(len(c) for c in chunks) / sr
            if chapters and abs(chapters[-1]["start"] - start) < 0.01:
                chapters.pop()
            chapters.append({"title": mark.group(1), "start": round(start, 3)})
            print(f"paragraph {i + 1}/{len(paras)} done (chapter: {mark.group(1)})", file=sys.stderr)
            continue
        for s in re.split(r"(?<=[.!?])\s+", p):
            if not s.strip():
                continue
            ph = to_phonemes(k, s)
            if a.show_phonemes:
                print(ph)
            audio, sr = k.create(ph, voice=VOICE, speed=a.speed, lang=LANG, is_phonemes=True)
            chunks += [audio, np.zeros(int(sr * 0.35), dtype=audio.dtype)]
        chunks.append(np.zeros(int(sr * 0.35), dtype=np.float32))
        print(f"paragraph {i + 1}/{len(paras)} done", file=sys.stderr)
    audio = np.concatenate(chunks)
    if chapters:
        if chapters[0]["start"] > 0:
            chapters.insert(0, {"title": "Introduction", "start": 0.0})
        path = a.chapters or os.path.splitext(a.out)[0] + ".chapters.json"
        with open(path, "w") as f:
            json.dump(chapters, f, indent=2)
        print(f"{len(chapters)} chapters written to {path}", file=sys.stderr)
    if abs(a.pitch - 1.0) < 1e-6:
        sf.write(a.out, audio, sr)
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        raw = tmp.name
    sf.write(raw, audio, sr)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-af",
                    f"asetrate={sr}*{a.pitch},aresample={sr},atempo={1 / a.pitch}", a.out], check=True)
    os.remove(raw)


if __name__ == "__main__":
    main()
