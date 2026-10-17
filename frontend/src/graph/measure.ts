import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CardBody } from "../canvas/CardBody";
import type { VisibleNode } from "./visible";

// Fixed card width per level: phase, step, deeper.
export const CARD_WIDTHS = [220, 190, 170] as const;
export const cardWidth = (depth: number): number => CARD_WIDTHS[Math.min(depth, 2)]!;
// An open node is a frame. Its title block is measured at this width, so the frame is never narrower.
export const FRAME_MIN_WIDTH = 340;
export const FRAME_PAD = 16;

export type Variant = "card" | "header";
export type Sizer = {
  card(vn: VisibleNode): { width: number; height: number };
  // Height of the title block of an open frame.
  header(vn: VisibleNode): number;
};

export const caretOf = (vn: VisibleNode): string =>
  vn.container ? "▾" : vn.expandable ? "▸" : "";

// Real height of one card variant at a fixed width.
export type DomMeasure = (vn: VisibleNode, variant: Variant, width: number) => number;

function key(vn: VisibleNode, variant: Variant, width: number): string {
  const n = vn.node;
  const chips = vn.chips.shown.map((e) => `${e.op}${e.target}`).join("\u0001");
  return [
    vn.id, variant, width, n.title, n.summary, n.stale, caretOf(vn), chips, vn.chips.more,
  ].join("|");
}

export function createSizer(measure: DomMeasure): Sizer & { cache: Map<string, number> } {
  const cache = new Map<string, number>();
  const heightOf = (vn: VisibleNode, variant: Variant, width: number): number => {
    const k = key(vn, variant, width);
    let h = cache.get(k);
    if (h === undefined) {
      h = measure(vn, variant, width);
      cache.set(k, h);
    }
    return h;
  };
  return {
    cache,
    card: (vn) => {
      const width = cardWidth(vn.depth);
      return { width, height: heightOf(vn, "card", width) };
    },
    header: (vn) => heightOf(vn, "header", FRAME_MIN_WIDTH),
  };
}

// Offscreen render with the real CSS. The host inherits the page font from <body>.
// Static markup keeps this synchronous and legal inside effects (flushSync is not).
let host: HTMLElement | null = null;

export const measureInDom: DomMeasure = (vn, variant, width) => {
  if (!host) {
    host = document.createElement("div");
    host.className = "measure-host";
    document.body.appendChild(host);
  }
  host.style.width = `${width}px`;
  host.innerHTML = renderToStaticMarkup(
    createElement(CardBody, {
      node: vn.node, depth: vn.depth, chips: vn.chips, caret: caretOf(vn), variant,
    }),
  );
  const el = host.firstElementChild as HTMLElement;
  // Round up and add 1px so sub-pixel text never clips.
  return Math.ceil(el.getBoundingClientRect().height) + 1;
};

// One cache for the page. Keys carry the text, so edits invalidate themselves.
export const pageSizer = createSizer(measureInDom);
