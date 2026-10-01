"""Derive inert, deterministic SuperLivePlus policy content from reviewed APK assets.

No source HTML, attribute, CSS, script or external resource is shipped. Hyperlink
labels remain text. Regeneration requires exactly the four reviewed source files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "apps/web/src/features/tvt/policies/generated-content.json"
APK_SHA256 = "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281"
SOURCES = (
    (
        "en",
        "terms",
        "ServiceTerms_en.html",
        "7973f409b90d62127488bf496de299dc537c32832b1c27b9d37f020ce2525544",
        158863,
    ),
    (
        "en",
        "privacy",
        "PrivacyStatement_en.html",
        "e2f542f723b332188db98d428a49b15d5430b4b3e2722338b2df8aed31882f1b",
        47981,
    ),
    (
        "zh-Hans",
        "terms",
        "ServiceTerms_zh-Hans.html",
        "9580039561c539e348a2a45f6682b54fe3f2681749817baceb3e99e6fc9f3965",
        196817,
    ),
    (
        "zh-Hans",
        "privacy",
        "PrivacyStatement_zh-Hans.html",
        "ff1a8d79ee2ee6b2b095129a0187a54f7e39c83f2b8e233b71988a72e513028d",
        38500,
    ),
)
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
BLOCKED = {
    "head",
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "svg",
    "math",
    "audio",
    "video",
    "canvas",
    "noscript",
    "template",
    "form",
    "button",
    "select",
    "textarea",
}
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ol", "ul", "table"}
Block = dict[str, Any]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


class Node:
    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.children: list[Node | str] = []


class VisiblePolicy(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("body")
        self.stack = [self.root]
        self.in_body = False
        self.suppressed: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self.suppressed:
            if tag not in VOID:
                self.suppressed.append(tag)
            return
        hidden = "hidden" in attributes or bool(
            re.search(
                r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
                attributes.get("style") or "",
                re.IGNORECASE,
            )
        )
        if tag in BLOCKED or hidden:
            if tag not in VOID:
                self.suppressed.append(tag)
            return
        if tag == "body":
            self.in_body = True
            return
        if not self.in_body:
            return
        if tag == "br":
            self.stack[-1].children.append("\n")
        elif tag not in VOID:
            node = Node(tag)
            self.stack[-1].children.append(node)
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.suppressed:
            if tag in self.suppressed:
                del self.suppressed[
                    len(self.suppressed) - 1 - self.suppressed[::-1].index(tag) :
                ]
            return
        if tag == "body":
            self.in_body = False
        else:
            for index in range(len(self.stack) - 1, 0, -1):
                if self.stack[index].tag == tag:
                    del self.stack[index:]
                    break

    def handle_data(self, data: str) -> None:
        if self.in_body and not self.suppressed:
            self.stack[-1].children.append(re.sub(r"\s+", " ", data))


def text_content(node: Node | str) -> str:
    if isinstance(node, str):
        return node
    return "".join(text_content(child) for child in node.children)


def normalized_text(value: str) -> str:
    return "\n".join(
        re.sub(r"[^\S\n]+", " ", line).strip() for line in value.split("\n")
    ).strip()


def descendants(node: Node, tag: str) -> list[Node]:
    return [
        item
        for child in node.children
        if isinstance(child, Node)
        for item in ([child] if child.tag == tag else descendants(child, tag))
    ]


def blocks_from(children: list[Node | str]) -> list[Block]:
    blocks: list[Block] = []
    pending: list[str] = []

    def flush() -> None:
        text = normalized_text("".join(pending))
        if text:
            blocks.append({"type": "paragraph", "text": text})
        pending.clear()

    for child in children:
        if isinstance(child, str):
            pending.append(child)
            continue
        if child.tag in BLOCK_TAGS:
            flush()
            if child.tag == "p" or child.tag.startswith("h"):
                text = normalized_text(text_content(child))
                if text:
                    blocks.append(
                        {"type": "paragraph", "text": text}
                        if child.tag == "p"
                        else {
                            "type": "heading",
                            "level": int(child.tag[1]),
                            "text": text,
                        }
                    )
            elif child.tag in ("ol", "ul"):
                items: list[list[Block]] = []
                for item in child.children:
                    if isinstance(item, Node) and item.tag == "li":
                        items.append(blocks_from(item.children))
                    else:
                        # The APK privacy HTML places real paragraphs directly
                        # under ul. Keep them after the preceding item, in order,
                        # without inventing a new bullet or discarding text.
                        loose = blocks_from([item])
                        if items:
                            items[-1].extend(loose)
                        else:
                            blocks.extend(loose)
                if items:
                    blocks.append(
                        {"type": "list", "ordered": child.tag == "ol", "items": items}
                    )
            elif child.tag == "table":
                rows = [
                    [
                        blocks_from(cell.children)
                        for cell in row.children
                        if isinstance(cell, Node) and cell.tag in ("td", "th")
                    ]
                    for row in descendants(child, "tr")
                ]
                if rows:
                    blocks.append({"type": "table", "rows": rows})
        elif any(
            isinstance(item, Node)
            and (
                item.tag in BLOCK_TAGS
                or descendants(item, "p")
                or descendants(item, "ol")
                or descendants(item, "ul")
            )
            for item in child.children
        ):
            flush()
            blocks.extend(blocks_from(child.children))
        else:
            pending.append(text_content(child))
    flush()
    return blocks


def extract_blocks(html: str) -> list[Block]:
    parser = VisiblePolicy()
    parser.feed(html)
    parser.close()
    result = blocks_from(parser.root.children)
    if not result:
        raise ValueError("policy has no visible body content")
    return result


def generate_bundle(apk_root: Path) -> dict[str, Any]:
    documents = []
    for locale, kind, filename, digest, size in SOURCES:
        source = apk_root / "apktool/assets/agreement" / filename
        raw = source.read_bytes()
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"reviewed source mismatch: {filename}")
        blocks = extract_blocks(raw.decode("utf-8-sig"))
        documents.append(
            {
                "locale": locale,
                "kind": kind,
                "source_reference": "agreement/" + filename,
                "source_sha256": digest,
                "source_bytes": size,
                "content_sha256": hashlib.sha256(canonical_bytes(blocks)).hexdigest(),
                "blocks": blocks,
            }
        )
    return {
        "schema_version": 1,
        "app_version": "1.18.1",
        "source_apk_sha256": APK_SHA256,
        "derivation": "visible-body-structured-v1",
        "documents": documents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    bundle = generate_bundle(args.apk_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    print("Generated four verified SuperLivePlus 1.18.1 policy documents")


if __name__ == "__main__":
    main()
