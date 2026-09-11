export function BrandMark() {
  return (
    <span
      aria-hidden
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px]"
      style={{ background: "var(--accent)" }}
    >
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <circle cx="6" cy="6" r="2.2" fill="white" />
        <circle cx="2.2" cy="3.2" r="1.1" fill="white" opacity="0.85" />
        <circle cx="9.5" cy="3.8" r="1.1" fill="white" opacity="0.85" />
        <circle cx="3" cy="9" r="1.1" fill="white" opacity="0.85" />
        <path
          d="M3.2 3.5L5 5.2M8.8 4.2L6.8 5.4M3.6 8.4L5.2 6.6"
          stroke="white"
          strokeWidth="0.9"
          opacity="0.7"
        />
      </svg>
    </span>
  );
}
