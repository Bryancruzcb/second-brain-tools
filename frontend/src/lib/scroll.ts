export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Scroll an element into view, animated unless the user asked for reduced motion. */
export function scrollToId(
  id: string,
  block: ScrollLogicalPosition = "start",
): void {
  document.getElementById(id)?.scrollIntoView({
    behavior: prefersReducedMotion() ? "auto" : "smooth",
    block,
  });
}
