import type { ReactNode } from "react";
import { policyKinds, policyLocales, policyRoute, type PolicyBlock, type PolicyDocument } from "./source";

const labels = {
  en: { terms: "Service agreement", privacy: "Privacy statement", heading: "SuperLivePlus policy documents", introduction: "This document describes SuperLivePlus. Source language: English.", navigation: "Policy documents", source: "Bundled source", version: "Application version" },
  "zh-Hans": { terms: "服务协议", privacy: "隐私声明", heading: "SuperLivePlus 政策文件", introduction: "本文件适用于 SuperLivePlus。源文件语言：简体中文。", navigation: "政策文件", source: "应用内源文件", version: "应用版本" },
};
const focus = "rounded px-2 py-1 underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#226594]";

function Blocks({ blocks }: { blocks: PolicyBlock[] }): ReactNode {
  return blocks.map((block, index) => {
    switch (block.type) {
      case "paragraph": return <p key={index} className="my-3 whitespace-pre-line break-words leading-7">{block.text}</p>;
      case "heading": {
        // The page owns h1. Keep source section hierarchy below that heading.
        const Heading = `h${Math.min(6, Math.max(2, block.level + 1))}` as "h2" | "h3" | "h4" | "h5" | "h6";
        return <Heading key={index} className="mb-3 mt-7 break-words text-lg font-semibold leading-7">{block.text}</Heading>;
      }
      case "list": {
        const List = block.ordered ? "ol" : "ul";
        return <List key={index} className={`my-3 space-y-2 pl-6 ${block.ordered ? "list-decimal" : "list-disc"}`}>
          {block.items.map((item, itemIndex) => <li key={itemIndex}><Blocks blocks={item} /></li>)}
        </List>;
      }
      case "table": return <div key={index} className="my-4 max-w-full overflow-x-auto rounded-lg border border-[var(--wso-border)]" tabIndex={0}>
        <table className="w-full border-collapse text-left text-sm"><tbody>{block.rows.map((row, rowIndex) => <tr key={rowIndex} className="border-b border-[var(--wso-border)] last:border-b-0">{row.map((cell, cellIndex) => <td key={cellIndex} className="min-w-36 break-words border-r border-[var(--wso-border)] p-3 align-top last:border-r-0"><Blocks blocks={cell} /></td>)}</tr>)}</tbody></table>
      </div>;
    }
  });
}

export function PolicyReader({ document }: { document: PolicyDocument }) {
  const copy = labels[document.locale];
  return <main lang={document.locale} className="mx-auto min-w-0 max-w-5xl p-4 text-[var(--wso-text)] md:p-6">
    <header className="mb-4">
      <p className="mb-2 text-sm text-[var(--wso-muted)]">{copy.heading}</p>
      <h1 className="text-2xl font-semibold">SuperLivePlus · {copy[document.kind]}</h1>
      <p className="mt-3 text-sm leading-6 text-[var(--wso-muted)]">{copy.introduction}</p>
      <nav aria-label={copy.navigation} className="mt-4 flex flex-wrap gap-2">
        {policyLocales.flatMap(locale => policyKinds.map(kind => <a key={`${locale}-${kind}`} href={policyRoute(locale, kind)} lang={locale} aria-current={locale === document.locale && kind === document.kind ? "page" : undefined} className={focus}>{locale === "en" ? "English" : "简体中文"} · {labels[locale][kind]}</a>))}
      </nav>
    </header>
    <article className="wso-card min-w-0 p-4 md:p-6" aria-label={`SuperLivePlus ${copy[document.kind]}`}><Blocks blocks={document.blocks} /></article>
    <footer className="mt-4 break-words text-xs leading-6 text-[var(--wso-muted)]">
      <p>{copy.version}: 1.18.1 · {copy.source}: {document.source_reference}</p>
    </footer>
  </main>;
}
