"""Utilidades de texto compartidas entre apps (sin dependencias externas)."""
import re
import unicodedata


def normalize(text):
    """Minúsculas + sin acentos/diacríticos + espacios colapsados.

    Pensado para matching tolerante de palabras clave sobre texto con typos
    y acentos inconsistentes (ej. "Cordinación" → "cordinacion").
    """
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', text.lower()).strip()
