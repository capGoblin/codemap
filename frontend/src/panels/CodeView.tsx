import { useEffect, useRef } from "react";
import type { FunctionDetail } from "../api/types";

export type Cite = { file: string; start: number; end: number };

export const citeLabel = (c: Cite): string => {
  const name = c.file.split("/").at(-1) ?? c.file;
  return c.start === c.end ? `${name}:${c.start}` : `${name}:${c.start}\u2013${c.end}`;
};

const inside = (c: Cite, file: string, line: number) =>
  c.file === file && line >= c.start && line <= c.end;

// Full function code with line numbers. Cited lines have a tint; the clicked cite is stronger
// and scrolls into view.
export function CodeView({
  functions, cited, active,
}: {
  functions: FunctionDetail[];
  cited: Cite[];
  active: (Cite & { seq: number }) | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!active || !box.current) return;
    const el = box.current.querySelector<HTMLElement>(
      `[data-file="${active.file.replace(/["\\]/g, "\\$&")}"][data-line="${active.start}"]`,
    );
    el?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [active]);

  return (
    <div className="code-view" data-testid="code-view" ref={box}>
      {functions.map((f, i) => (
        <div className="fn" key={i}>
          <div className="fn-head">
            {f.anchor.file}:{f.anchor.start_line}
          </div>
          <div className="code">
            {f.code.split("\n").map((text, j) => {
              const line = f.anchor.start_line + j;
              const isActive = active !== null && inside(active, f.anchor.file, line);
              const isCited = cited.some((c) => inside(c, f.anchor.file, line));
              return (
                <div
                  key={j}
                  className={`code-line${isActive ? " hl-active" : isCited ? " hl" : ""}`}
                  data-file={f.anchor.file}
                  data-line={line}
                >
                  <span className="ln">{line}</span>
                  <span className="lt">{text}</span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
