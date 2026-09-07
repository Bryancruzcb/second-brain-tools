"use client";

import { productName } from "@/data/mock";

export function FooterStrip() {
  return (
    <footer className="border-t border-hairline">
      <div className="mx-auto flex max-w-6xl items-center px-6 py-10">
        <span className="text-[13px] font-medium tracking-[-0.01em] text-muted">
          {productName}
        </span>
      </div>
    </footer>
  );
}
