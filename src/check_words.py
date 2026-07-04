from pathlib import Path

words = set(Path("rules/palochka_words.txt").read_text(encoding="utf-8").splitlines())

targets = [
    "\u0445\u04c0\u0443\u043c\u0430",
    "\u043a\u04c0\u0430\u043d\u0442",
    "\u0442\u04c0\u0430\u044c\u0445\u044c\u0430",
    "\u0434\u04c0\u0430",
    "\u0445\u04c0\u0430\u0440\u0430",
    "\u0445\u04c0\u0443\u043d",
]

print("loaded:", len(words))

for target in targets:
    print(f"{target}: {target in words}")