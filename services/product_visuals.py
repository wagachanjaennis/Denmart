"""Local, deterministic catalogue artwork used when an exact product photo is unavailable.

The storefront should never show a broken/empty image box.  These visuals are deliberately
catalogue-oriented rather than pretending to be a photograph of a specific SKU.
"""

from html import escape
import hashlib
import re


PALETTES = [
    ("#fff8ef", "#d9692b", "#183f35"),
    ("#eef8f4", "#23805f", "#163b4b"),
    ("#f5f3ff", "#6c55bd", "#2f234f"),
    ("#fff2f3", "#c84b58", "#4c1e28"),
    ("#fff9df", "#bf8c12", "#4b3510"),
    ("#eff5fb", "#3b6ea8", "#173653"),
    ("#f3f1ea", "#7c6a48", "#2f2b24"),
]


def _palette(seed: str):
    digest = hashlib.sha1((seed or "product").encode("utf-8")).digest()
    return PALETTES[digest[0] % len(PALETTES)]


def _clean(value, fallback=""):
    return escape(str(value or fallback), quote=True)


def _short_lines(text: str, width: int = 25, max_lines: int = 3):
    words = re.findall(r"\S+", str(text or "").strip())
    lines = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and len(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
        if len(lines) >= max_lines:
            break
    if len(lines) < max_lines and line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines and words:
        joined = " ".join(lines)
        original = " ".join(words)
        if joined != original and not lines[-1].endswith("…"):
            lines[-1] = lines[-1][: max(1, width - 1)] + "…"
    return lines


def _kind(name: str, category: str = ""):
    t = f"{name} {category}".lower()
    if any(x in t for x in ("milk", "yoghurt", "yogurt", "lala", "cheese", "butter", "cream", "egg")):
        return "dairy"
    if any(x in t for x in ("bread", "loaf", "bun", "cake", "mandazi", "pastry")):
        return "bakery"
    if any(x in t for x in ("oil", "vinegar", "sauce", "mchuzi")):
        return "oil"
    if any(x in t for x in ("juice", "cola", "fanta", "sprite", "water", "drink", "energy", "soda")):
        return "drink"
    if any(x in t for x in ("detergent", "bleach", "cleaner", "soap", "dishwash", "harpic", "omo", "ariel", "sunlight")):
        return "cleaning"
    if any(x in t for x in ("flour", "rice", "maize", "sugar", "grain", "pasta", "spaghetti", "noodle", "cereal")):
        return "bag"
    if any(x in t for x in ("tea", "coffee", "cocoa")):
        return "tea"
    if any(x in t for x in ("toothpaste", "shampoo", "lotion", "vaseline", "colgate", "nivea", "dove", "detol", "dettol", "deodorant")):
        return "care"
    if any(x in t for x in ("fresh produce", "potato", "onion", "tomato", "banana", "apple", "orange", "avocado", "mango", "spinach", "sukuma", "carrot", "cabbage")):
        return "produce"
    if any(x in t for x in ("chicken", "beef", "goat", "sausage", "bacon", "fish", "meat")):
        return "meat"
    if any(x in t for x in ("frozen", "ice cream", "mccain")):
        return "frozen"
    if any(x in t for x in ("baby", "pampers", "huggies", "cerelac", "nan")):
        return "baby"
    if any(x in t for x in ("book", "stationery", "pen", "notebook", "paper")):
        return "stationery"
    if any(x in t for x in ("electronics", "bulb", "battery", "charger", "cable", "appliance", "phone")):
        return "electronics"
    return "general"


def _shape(kind: str, fg: str, accent: str):
    if kind == "dairy":
        return f"""
        <path d='M294 174h212l42 56v348c0 22-18 40-40 40H292c-22 0-40-18-40-40V230l42-56z' fill='{fg}'/>
        <path d='M294 174h212v54H294z' fill='{accent}' opacity='.22'/>
        <path d='M298 300h204' stroke='{accent}' stroke-width='18' stroke-linecap='round' opacity='.7'/>
        <circle cx='400' cy='392' r='55' fill='#ffffff' opacity='.88'/>
        <path d='M400 355c-28 39-30 53-14 70 18 18 49 10 49-18 0-16-12-31-35-52z' fill='{accent}' opacity='.85'/>
        """
    if kind == "bakery":
        return f"""
        <path d='M240 360c0-68 71-124 160-124s160 56 160 124v178c0 34-28 62-62 62H302c-34 0-62-28-62-62z' fill='{fg}'/>
        <path d='M240 388c60 22 260 22 320 0v68c-75 24-245 24-320 0z' fill='{accent}' opacity='.28'/>
        <path d='M302 332c24-32 63-49 98-49 39 0 76 17 98 49' fill='none' stroke='#fff' stroke-width='18' stroke-linecap='round' opacity='.85'/>
        <path d='M342 397v90M400 397v90M458 397v90' stroke='#fff' stroke-width='12' stroke-linecap='round' opacity='.52'/>
        """
    if kind == "oil":
        return f"""
        <path d='M326 208h148v54l28 38v288c0 24-20 44-44 44H342c-24 0-44-20-44-44V300l28-38z' fill='{fg}'/>
        <path d='M356 180h88v42h-88z' fill='{accent}'/>
        <rect x='320' y='386' width='160' height='150' rx='20' fill='#fff' opacity='.86'/>
        <path d='M350 444h100M350 476h80' stroke='{accent}' stroke-width='15' stroke-linecap='round' opacity='.72'/>
        """
    if kind == "drink":
        return f"""
        <path d='M334 192h132v44l22 34v306c0 22-18 40-40 40H352c-22 0-40-18-40-40V270l22-34z' fill='{fg}'/>
        <path d='M362 166h76v39h-76z' fill='{accent}'/>
        <path d='M334 328h132v220H334z' fill='#fff' opacity='.82'/>
        <circle cx='400' cy='398' r='38' fill='{accent}' opacity='.72'/>
        """
    if kind == "cleaning" or kind == "care":
        return f"""
        <path d='M322 212h124c28 0 50 22 50 50v302c0 30-24 54-54 54H358c-30 0-54-24-54-54V290c0-34 14-52 48-78z' fill='{fg}'/>
        <path d='M358 184h76v48h-76z' fill='{accent}'/>
        <rect x='328' y='358' width='112' height='160' rx='18' fill='#fff' opacity='.86'/>
        <path d='M348 404h72M348 438h56' stroke='{accent}' stroke-width='13' stroke-linecap='round' opacity='.78'/>
        """
    if kind == "bag":
        return f"""
        <path d='M278 242l34-58h176l34 58 16 356c1 26-19 48-45 48H307c-26 0-46-22-45-48z' fill='{fg}'/>
        <path d='M312 184h176' stroke='{accent}' stroke-width='24' stroke-linecap='round'/>
        <rect x='318' y='334' width='164' height='152' rx='22' fill='#fff' opacity='.86'/>
        <circle cx='400' cy='386' r='34' fill='{accent}' opacity='.72'/>
        """
    if kind == "tea":
        return f"""
        <rect x='266' y='244' width='268' height='360' rx='28' fill='{fg}'/>
        <path d='M266 334h268v160H266z' fill='#fff' opacity='.86'/>
        <path d='M330 400h140M330 438h98' stroke='{accent}' stroke-width='16' stroke-linecap='round'/>
        <circle cx='400' cy='302' r='34' fill='{accent}' opacity='.7'/>
        """
    if kind == "produce":
        return f"""
        <path d='M400 556c-114 0-182-68-142-160 18-41 61-66 106-67 20-76 75-113 124-115-9 43-1 83 23 120 40 12 69 47 69 88 0 82-68 134-180 134z' fill='{fg}'/>
        <path d='M404 536c16-116 40-202 92-288M448 338c30-24 62-33 100-34' fill='none' stroke='#fff' stroke-width='14' stroke-linecap='round' opacity='.78'/>
        """
    if kind == "meat":
        return f"""
        <path d='M250 420c0-92 79-166 176-166 53 0 86 18 112 45 35 37 48 87 36 136-14 61-75 111-151 111H312c-35 0-62-28-62-62z' fill='{fg}'/>
        <ellipse cx='450' cy='408' rx='54' ry='40' fill='#fff' opacity='.8'/>
        <circle cx='452' cy='408' r='14' fill='{accent}' opacity='.75'/>
        """
    if kind == "frozen":
        return f"""
        <path d='M274 244h252l-12 358H286z' fill='{fg}'/>
        <path d='M274 244h252v82H274z' fill='{accent}' opacity='.8'/>
        <path d='M340 410l60 50 60-50M400 356v172M344 470l56-46 56 46' stroke='#fff' stroke-width='14' stroke-linecap='round' stroke-linejoin='round' opacity='.85'/>
        """
    if kind == "baby":
        return f"""
        <path d='M294 246h212v356c0 28-22 50-50 50H344c-28 0-50-22-50-50z' fill='{fg}'/>
        <circle cx='400' cy='372' r='74' fill='#fff' opacity='.88'/>
        <circle cx='374' cy='364' r='7' fill='{accent}'/><circle cx='426' cy='364' r='7' fill='{accent}'/>
        <path d='M377 400c16 17 30 17 46 0' fill='none' stroke='{accent}' stroke-width='10' stroke-linecap='round'/>
        """
    if kind == "stationery":
        return f"""
        <rect x='292' y='190' width='218' height='410' rx='18' fill='{fg}' transform='rotate(-7 401 395)'/>
        <rect x='316' y='222' width='170' height='338' rx='12' fill='#fff' opacity='.9' transform='rotate(-7 401 395)'/>
        <path d='M350 340h98M350 376h80M350 412h70' stroke='{accent}' stroke-width='14' stroke-linecap='round'/>
        """
    if kind == "electronics":
        return f"""
        <rect x='246' y='236' width='308' height='260' rx='28' fill='{fg}'/>
        <rect x='286' y='274' width='228' height='160' rx='18' fill='#fff' opacity='.9'/>
        <path d='M338 526h124M368 496v30M432 496v30' stroke='{accent}' stroke-width='18' stroke-linecap='round'/>
        """
    return f"""
        <rect x='274' y='226' width='252' height='352' rx='28' fill='{fg}'/>
        <rect x='310' y='282' width='180' height='170' rx='22' fill='#fff' opacity='.88'/>
        <circle cx='400' cy='340' r='38' fill='{accent}' opacity='.75'/>
        <path d='M342 414h116' stroke='{accent}' stroke-width='14' stroke-linecap='round'/>
        """


def product_visual_svg(product, category_name: str = "") -> str:
    name = str(getattr(product, "name", "Product") or "Product")
    brand = str(getattr(product, "brand", "") or "Everyday")
    pack = str(getattr(product, "pack_size", "") or "")
    kind = _kind(name, category_name)
    bg, fg, accent = _palette(f"{brand}|{name}|{category_name}")
    title_lines = _short_lines(name, 23, 3)
    title_svg = "".join(
        f"<text x='400' y='{690 + i*28}' text-anchor='middle' font-size='24' font-weight='800' fill='#1c2b2c'>{_clean(line)}</text>"
        for i, line in enumerate(title_lines)
    )
    pack_label = pack if pack and pack.lower() not in {"unit", "piece", "pack"} else category_name
    return f"""<svg xmlns='http://www.w3.org/2000/svg' width='800' height='800' viewBox='0 0 800 800' role='img' aria-label='{_clean(name)} catalogue visual'>
<defs>
 <linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='{bg}'/><stop offset='1' stop-color='#ffffff'/></linearGradient>
 </defs>
<rect width='800' height='800' rx='44' fill='url(#g)'/>
<circle cx='650' cy='142' r='74' fill='{fg}' opacity='.07'/><circle cx='134' cy='648' r='108' fill='{accent}' opacity='.06'/>
<g>{_shape(kind, fg, accent)}</g>
<text x='400' y='86' text-anchor='middle' font-size='22' font-weight='950' letter-spacing='2' fill='{accent}'>{_clean(brand.upper()[:28])}</text>
{title_svg}
<text x='400' y='776' text-anchor='middle' font-size='18' font-weight='700' fill='#70807f'>{_clean(pack_label[:38])}</text>
</svg>"""
