import process

test_words = [
    "хГума",
    "дГакхайкхор",
    "КТант",
    "хТоттийна",
    "хГусамнанас",
    "ХТара",
    "хГокхул",
    "хТораннан",
    "тахана",
    "генара",
]

print("Dictionary loaded:", len(process.PALOCHKA_DICTIONARY))
print()

for word in test_words:
    candidates = process.generate_palochka_candidates(word)
    valid = [c for c in candidates if c in process.PALOCHKA_DICTIONARY]

    print("WORD:", word)
    print("CANDIDATES:", sorted(candidates))
    print("VALID:", valid)

    if len(valid) == 1:
        print("WOULD FIX:", word, "->", process.preserve_case(word, valid[0]))
    else:
        print("WOULD FIX: no")

    print("-" * 40)