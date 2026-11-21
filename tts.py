#!/usr/bin/env python3
"""Render a podcast script to WAV with the show's voice and pronunciation rules.

Usage: python3 tts.py script.txt episode.wav [--speed 1.0]

Write the script with normal spellings (EEOC, ADA, AI, Kwall Barack Nadeau).
This script:
  - says all-caps acronyms letter by letter with clean letter sounds
    (no "uh" before letters), except those in SAY_AS_WORD;
  - says the firm name correctly;
  - pauses 0.35 s between sentences and 0.7 s between paragraphs.
"""
import argparse, re, sys
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

MODEL = "/home/claude/tts/kokoro-v1.0.onnx"
VOICES = "/home/claude/tts/voices-v1.0.bin"
VOICE = "af_heart"
LANG = "en-us"

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
}
REPLACE = {
    "Title VII": "Title Seven",
    "AIR21": "Air twenty-one",
}
ACRONYM = re.compile(r"\b([A-Z]{2,6})(s?)\b")
NAMES = re.compile("|".join(re.escape(n) for n in NAME_PHONEMES))


def to_phonemes(k, sentence):
    for a, b in REPLACE.items():
        sentence = sentence.replace(a, b)
    # Undo hyphen or period spellings like E-E-O-C or E.E.O.C.
    sentence = re.sub(r"\b(?:[A-Z][-.]){1,5}[A-Z]\b\.?", lambda m: re.sub(r"[-.]", "", m.group(0)), sentence)
    tokens = sorted([(m.start(), m.end(), "name", m.group(0)) for m in NAMES.finditer(sentence)] +
                    [(m.start(), m.end(), "acr", m) for m in ACRONYM.finditer(sentence) if m.group(1) not in SAY_AS_WORD],
                    key=lambda t: t[0])
    parts, pos = [], 0
    for start, end, kind, val in tokens:
        if start < pos:
            continue
        if kind == "name":
            before = sentence[pos:start]
            if before.strip():
                parts.append(k.tokenizer.phonemize(before, LANG))
            parts.append(NAME_PHONEMES[val])
            pos = end
            continue
        m = val
        word, plural = m.group(1), m.group(2)
        before = sentence[pos:m.start()]
        if before.strip():
            ph = k.tokenizer.phonemize(before, LANG).rstrip()
            # "the" before a letter that starts with a vowel sound: say "thee", not "thuh".
            if word[0] in "AEFHILMNORSX" and ph.endswith("ðə"):
                ph = ph[:-2] + "ðɪ"
            parts.append(ph)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--show-phonemes", action="store_true")
    a = ap.parse_args()
    k = Kokoro(MODEL, VOICES)
    text = open(a.script).read()
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    sr, chunks = 24000, []
    for i, p in enumerate(paras):
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
    sf.write(a.out, np.concatenate(chunks), sr)


if __name__ == "__main__":
    main()
