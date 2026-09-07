"use client";

import { MiniWorkspace } from "./MiniWorkspace";

export function Hero() {
  return (
    <section id="top" className="mx-auto max-w-6xl px-6 pb-8 pt-16 sm:pt-20">
      <div className="mx-auto max-w-3xl text-center">
        <h1 className="text-[48px] font-medium leading-[1.05] tracking-[-0.035em] text-ink sm:text-[64px] md:text-[72px]">
          Atlas
        </h1>
        <div className="mt-8 flex items-center justify-center gap-3">
          <a href="#notes" className="btn-primary focus-ring h-11 px-5 text-[15px]">
            Open vault
          </a>
        </div>
      </div>

      <div className="mx-auto mt-14 max-w-5xl">
        <div className="browser-frame">
          <div className="browser-chrome">
            <div className="traffic" aria-hidden>
              <span />
              <span />
              <span />
            </div>
            <div className="url-bar mono">
              <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-[var(--success)]" />
              localhost:3000/vault
            </div>
            <div className="w-[54px]" aria-hidden />
          </div>
          <MiniWorkspace />
        </div>
      </div>
    </section>
  );
}
