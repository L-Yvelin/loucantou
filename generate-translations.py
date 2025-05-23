import json
import re
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString, Tag

project_root = Path(__file__).parent
translations_dir = project_root / "translations"
output_root = project_root


def extract_fragments_for_tag(tag, key_base):
    fragments = {}
    for idx, node in enumerate(tag.contents):
        if isinstance(node, NavigableString):
            text = node.strip()
            if text:
                fragments[f"{key_base}.text[{idx}]"] = text
        elif isinstance(node, Tag):
            cls = "-".join(node.get("class", []))
            fragments[f"{key_base}>{node.name}[{idx}].{cls}"] = node.get_text(
                strip=True)
    return fragments


def apply_fragments_to_tag(tag, key_base, translations):
    new_contents = []
    for idx, node in enumerate(tag.contents):
        key_txt = f"{key_base}.text[{idx}]"
        key_tag = None
        if isinstance(node, Tag):
            cls = "-".join(node.get("class", []))
            key_tag = f"{key_base}>{node.name}[{idx}].{cls}"
        if key_txt in translations:
            new_contents.append(translations[key_txt])
        elif key_tag and key_tag in translations:
            inner_html = translations[key_tag]
            new_node = BeautifulSoup(inner_html, "html.parser")
            node.clear()
            node.append(new_node)
            new_contents.append(node)
        else:
            new_contents.append(node)
    tag.clear()
    for part in new_contents:
        tag.append(part)


def apply_translations(soup, translations):
    for selector, text in translations.items():
        if "@" in selector:
            sel, attr = selector.rsplit("@", 1)
            sel = sel.strip()
            for tag in soup.select(sel):
                tag[attr] = text
        elif re.search(r"\.text\[\d+\]$|>", selector):
            key_base = selector.rsplit(".", 1)[0]
            sel = key_base.split(">")[0]
            for tag in soup.select(sel):
                apply_fragments_to_tag(tag, key_base, translations)
        else:
            for tag in soup.select(selector.strip()):
                tag.clear()
                new_content = BeautifulSoup(text, "html.parser")
                tag.append(new_content)


for translation_file in translations_dir.glob("*.json"):
    match = re.match(r"(.+\.html)\.(\w+)\.json", translation_file.name)
    if not match:
        continue
    html_name, lang = match.groups()
    html_file = project_root / html_name
    if not html_file.exists():
        print(f"⚠️ HTML file not found for: {translation_file.name}")
        continue
    soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
    translations = json.loads(translation_file.read_text(encoding="utf-8"))
    apply_translations(soup, translations)
    output_dir = output_root / lang
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / html_name
    output_path.write_text(str(soup), encoding="utf-8")
    print(f"✅ Generated {output_path.relative_to(project_root)}")
