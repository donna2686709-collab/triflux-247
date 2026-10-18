import xml.etree.ElementTree as ET

from core.network import download


def _local_name(tag):
    if not tag:
        return ""

    if "}" in tag:
        return tag.split("}", 1)[1]

    return tag


def item_title(item):
    for child in item:
        if _local_name(child.tag) == "title":
            return "".join(child.itertext()).strip()

    return ""


def item_link(item):
    for child in item:
        if _local_name(child.tag) != "link":
            continue

        href = child.attrib.get("href", "").strip()

        if href:
            return href

        text = "".join(child.itertext()).strip()

        if text:
            return text

    return ""


def item_id(item):
    preferred = (
        "id",
        "guid",
    )

    for wanted in preferred:
        for child in item:
            if _local_name(child.tag) == wanted:
                value = "".join(child.itertext()).strip()

                if value:
                    return value

    return item_link(item) or item_title(item)


def fetch_latest_feed(url, sec=False):
    data = download(
        url,
        sec=sec,
    )

    root = ET.fromstring(data)

    items = []

    for element in root.iter():
        name = _local_name(element.tag)

        if name in ("item", "entry"):
            items.append(element)

    return items
