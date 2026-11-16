"""Ro'yxat ko'rinishida sovg'a qo'shish (bot va Mini App admin paneli uchun umumiy)."""
import re

RARITIES = {
    "common": "Oddiy", "rare": "Noyob", "epic": "Epik", "legendary": "Afsonaviy", "mythic": "Mifik",
}
RARITY_ALIASES = {
    "c": "common", "oddiy": "common", "common": "common",
    "r": "rare", "noyob": "rare", "rare": "rare",
    "e": "epic", "epik": "epic", "epic": "epic",
    "l": "legendary", "afsonaviy": "legendary", "legendary": "legendary",
    "m": "mythic", "mifik": "mythic", "mythic": "mythic",
}
_LINE_RE = re.compile(r"^(.+?)\s+(\d+)\s+(\d+(?:[.,]\d+)?)%?(?:\s+(\w+))?$")


def auto_rarity(prob: float) -> str:
    if prob <= 0.5:
        return "mythic"
    if prob <= 2:
        return "legendary"
    if prob <= 8:
        return "epic"
    if prob <= 25:
        return "rare"
    return "common"


def parse_item_line(line: str):
    """«Nomi | narx | foiz | daraja | havola» yoki «Nomi narx foiz [daraja]». None — tushunilmadi."""
    line = (line or "").strip()
    if not line:
        return None
    if re.search(r"[|;\t]", line):
        parts = [x.strip() for x in re.split(r"[|;\t]", line)]
        if len(parts) < 3:
            return None
        name, price, prob = parts[0], parts[1], parts[2]
        rarity = parts[3] if len(parts) > 3 else ""
        image = parts[4] if len(parts) > 4 else ""
    else:
        m = _LINE_RE.match(line)
        if not m:
            return None
        name, price, prob, rarity = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        image = ""
    try:
        price_n = int(price.replace(" ", "").replace("_", ""))
        prob_n = float(prob.replace("%", "").replace(",", "."))
    except ValueError:
        return None
    if not name or price_n < 0 or prob_n <= 0:
        return None
    rarity_key = RARITY_ALIASES.get(rarity.lower()) if rarity else None
    if rarity.startswith("http"):
        image, rarity_key = rarity, None
    elif rarity and not rarity_key:
        return None
    return {"name": name[:80], "price": price_n, "prob": prob_n,
            "rarity": rarity_key or auto_rarity(prob_n),
            "image": image if image.startswith("https://") else ""}


def parse_case_line(line: str):
    """«Nomi | narx» yoki «Nomi narx»."""
    line = (line or "").strip()
    if not line:
        return None
    if re.search(r"[|;\t]", line):
        parts = [x.strip() for x in re.split(r"[|;\t]", line)]
    else:
        m = re.match(r"^(.+?)\s+(\d+)$", line)
        parts = [m.group(1), m.group(2)] if m else []
    try:
        name, price = parts[0], int(parts[1].replace(" ", ""))
        if not name or price < 0:
            return None
        return name[:80], price
    except Exception:
        return None
