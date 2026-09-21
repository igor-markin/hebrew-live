"""Cheap text-script guard, not audio language identification."""
import unicodedata


def clearly_non_hebrew(text):
    letters=[char for char in text if char.isalpha()]
    return bool(letters) and not any('HEBREW' in unicodedata.name(char,'') for char in letters)
