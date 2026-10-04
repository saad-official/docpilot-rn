"""Turning a question into what each retriever wants.

    "How do I use useRouter with expo-router in SDK 58?"
      full-text (english)   'use or userouter or expo-router or sdk or 58'
      full-text (simple)    'userouter or expo-router'          (API-looking tokens only)
      API names (boost)     ['useRouter', 'expo-router']

Why OR: `websearch_to_tsquery` ANDs its terms, and a natural-language question almost never
has every one of its words on one docs page, so an AND query returns nothing for most real
questions. `ts_rank_cd` still ranks chunks matching more terms higher. Stop words are
dropped here (the english config would drop them too; the simple config would not).
"""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    """a about above after again all am an and any are as at be been before being below
    between both but by can could did do does doing down during each few for from further
    had has have having he her here hers him his how i if in into is it its itself just me
    more most my no nor not now of off on once only or other our out over own same she
    should so some such than that the their them then there these they this those through
    to too under until up very was we were what when where which while who whom why will
    with would you your yours i'm can't don't doesn't isn't want need use using get make
    way ways possible please tell show explain thing things set""".split()  # noqa: SIM905
)

WORD_RE = re.compile(r"[@A-Za-z0-9_][\w@./-]*[\w]|[A-Za-z0-9]")

# What an API name looks like in Expo / React Native docs.
API_PATTERNS = [
    re.compile(r"@[\w-]+/[\w.-]+"),  # @expo/vector-icons, @react-navigation/native
    re.compile(r"\bexpo-[a-z0-9-]+\b"),  # expo-notifications, expo-router
    re.compile(r"\breact-native-[a-z0-9-]+\b"),  # react-native-reanimated
    re.compile(r"\buse[A-Z]\w+\b"),  # useRouter, useLocalSearchParams
    re.compile(r"\b[A-Z]\w*(?:Screen|View|List|Provider|Navigator|Modal)\b"),  # SplashScreen
    re.compile(r"\b[a-z]+[A-Z]\w*\b"),  # camelCase: scheduleNotificationAsync
    re.compile(r"\b[A-Z][a-z0-9]+[A-Z]\w*\b"),  # PascalCase: FlatList, SafeAreaView
    re.compile(r"\b[\w-]+\.(?:json|js|ts|tsx|plist|xml|gradle|config\.js)\b"),  # app.json
    re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b"),  # EXPO_PUBLIC_, UIBackgroundModes-like consts
]


def api_names(question: str) -> list[str]:
    """API-looking tokens in the question, in order, de-duplicated (case-insensitive)."""
    found: list[tuple[int, str]] = []
    for pattern in API_PATTERNS:
        for match in pattern.finditer(question):
            found.append((match.start(), match.group(0)))
    seen: set[str] = set()
    out: list[str] = []
    for _, token in sorted(found):
        key = token.lower()
        # Drop tokens contained in a longer one already kept (expo-router in @x/expo-router).
        if key in seen or any(key in kept.lower() for kept in out):
            continue
        seen.add(key)
        out.append(token)
    return out


def terms(question: str) -> list[str]:
    out: list[str] = []
    for token in WORD_RE.findall(question):
        lowered = token.lower().strip("./-")
        if not lowered or lowered in STOPWORDS or lowered in out:
            continue
        out.append(lowered)
    return out


def _quote(term: str) -> str:
    # websearch_to_tsquery treats `-x` as NOT and `"..."` as a phrase; keep terms literal.
    return term.replace('"', "").lstrip("-")


def english_query(question: str) -> str:
    return " or ".join(_quote(t) for t in terms(question))


def simple_query(question: str) -> str:
    return " or ".join(_quote(t.lower()) for t in api_names(question))
