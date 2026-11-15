"""
Every language setting is a prompt variable, so any language a model can speak
works for practice, feedback and reports. This table only adds what a prompt
can't: the codes speech engines need, and how to count "enough to grade".

    stt  - ISO 639-1 code for Whisper-style transcription (None = let it detect)
    tts  - BCP 47 tag for picking a browser voice
    chars - count characters, not words, when deciding if a turn is gradeable
    rtl  - right-to-left script, for report layout
"""

LANGUAGES = [
    # id, English name, native name, stt, tts, chars, rtl
    ("en", "English", "English", "en", "en-US", False, False),
    ("zh-CN", "Chinese (Mandarin, Simplified)", "简体中文", "zh", "zh-CN", True, False),
    ("zh-TW", "Chinese (Mandarin, Traditional)", "繁體中文", "zh", "zh-TW", True, False),
    ("yue", "Cantonese", "粵語", "yue", "zh-HK", True, False),
    ("ja", "Japanese", "日本語", "ja", "ja-JP", True, False),
    ("ko", "Korean", "한국어", "ko", "ko-KR", False, False),
    ("es", "Spanish", "Español", "es", "es-ES", False, False),
    ("fr", "French", "Français", "fr", "fr-FR", False, False),
    ("de", "German", "Deutsch", "de", "de-DE", False, False),
    ("it", "Italian", "Italiano", "it", "it-IT", False, False),
    ("pt-BR", "Portuguese (Brazil)", "Português (Brasil)", "pt", "pt-BR", False, False),
    ("pt-PT", "Portuguese (Portugal)", "Português (Portugal)", "pt", "pt-PT", False, False),
    ("ru", "Russian", "Русский", "ru", "ru-RU", False, False),
    ("uk", "Ukrainian", "Українська", "uk", "uk-UA", False, False),
    ("pl", "Polish", "Polski", "pl", "pl-PL", False, False),
    ("nl", "Dutch", "Nederlands", "nl", "nl-NL", False, False),
    ("sv", "Swedish", "Svenska", "sv", "sv-SE", False, False),
    ("no", "Norwegian", "Norsk", "no", "nb-NO", False, False),
    ("da", "Danish", "Dansk", "da", "da-DK", False, False),
    ("fi", "Finnish", "Suomi", "fi", "fi-FI", False, False),
    ("el", "Greek", "Ελληνικά", "el", "el-GR", False, False),
    ("cs", "Czech", "Čeština", "cs", "cs-CZ", False, False),
    ("hu", "Hungarian", "Magyar", "hu", "hu-HU", False, False),
    ("ro", "Romanian", "Română", "ro", "ro-RO", False, False),
    ("tr", "Turkish", "Türkçe", "tr", "tr-TR", False, False),
    ("ar", "Arabic", "العربية", "ar", "ar-SA", False, True),
    ("he", "Hebrew", "עברית", "he", "he-IL", False, True),
    ("fa", "Persian", "فارسی", "fa", "fa-IR", False, True),
    ("ur", "Urdu", "اردو", "ur", "ur-PK", False, True),
    ("hi", "Hindi", "हिन्दी", "hi", "hi-IN", False, False),
    ("bn", "Bengali", "বাংলা", "bn", "bn-IN", False, False),
    ("th", "Thai", "ไทย", "th", "th-TH", True, False),
    ("vi", "Vietnamese", "Tiếng Việt", "vi", "vi-VN", False, False),
    ("id", "Indonesian", "Bahasa Indonesia", "id", "id-ID", False, False),
    ("ms", "Malay", "Bahasa Melayu", "ms", "ms-MY", False, False),
    ("tl", "Filipino", "Filipino", "tl", "fil-PH", False, False),
    ("sw", "Swahili", "Kiswahili", "sw", "sw-KE", False, False),
    ("ca", "Catalan", "Català", "ca", "ca-ES", False, False),
]

def _entry(id, name, native, stt, tts, chars, rtl):
    return {"id": id, "name": name, "native": native, "stt": stt, "tts": tts, "chars": chars, "rtl": rtl}


_BY_ID = {row[0]: _entry(*row) for row in LANGUAGES}


def resolve(value):
    """
    A known id gives its full entry. Anything else is a language the user typed in
    ("Hokkien", "Swiss German"): the prompts still work, speech engines auto-detect.
    """
    value = (value or "").strip() or "en"
    if value in _BY_ID:
        return dict(_BY_ID[value])
    return _entry(value, value, value, None, None, False, False)


def label(lang):
    """How a language is named inside prompts: 'Spanish (Español)'."""
    if lang["name"] == lang["native"]:
        return lang["name"]
    return f'{lang["name"]} ({lang["native"]})'


def all_languages():
    return [dict(v) for v in _BY_ID.values()]
