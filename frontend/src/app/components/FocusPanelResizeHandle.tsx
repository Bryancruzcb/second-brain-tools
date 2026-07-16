'use client';

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';

interface Props {
  controlsId: string;
  defaultWidth: number;
  edge: 'left' | 'right';
  label: string;
  maxWidth: number;
  minWidth: number;
  onResize: (width: number) => void;
  width: number;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export default function FocusPanelResizeHandle({
  controlsId,
  defaultWidth,
  edge,
  label,
  maxWidth,
  minWidth,
  onResize,
  width,
}: Props) {
  const dragStart = useRef({ active: false, x: 0, width });
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      if (!dragStart.current.active) return;
      const movement = event.clientX - dragStart.current.x;
      const widthDelta = edge === 'right' ? movement : -movement;
      onResize(clamp(dragStart.current.width + widthDelta, minWidth, maxWidth));
    };

    const finishDrag = () => {
      if (!dragStart.current.active) return;
      dragStart.current.active = false;
      document.body.classList.remove('focus-panel-resizing');
      setIsDragging(false);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', finishDrag);
    window.addEventListener('pointercancel', finishDrag);
    window.addEventListener('blur', finishDrag);
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', finishDrag);
      window.removeEventListener('pointercancel', finishDrag);
      window.removeEventListener('blur', finishDrag);
      document.body.classList.remove('focus-panel-resizing');
    };
  }, [edge, maxWidth, minWidth, onResize]);

  const finishDrag = () => {
    dragStart.current.active = false;
    document.body.classList.remove('focus-panel-resizing');
    setIsDragging(false);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Home') {
      event.preventDefault();
      onResize(minWidth);
      return;
    }
    if (event.key === 'End') {
      event.preventDefault();
      onResize(maxWidth);
      return;
    }
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;

    event.preventDefault();
    const dividerMovement = event.key === 'ArrowRight' ? 24 : -24;
    const widthDelta = edge === 'right' ? dividerMovement : -dividerMovement;
    onResize(clamp(width + widthDelta, minWidth, maxWidth));
  };

  return (
    <div
      className={`focus-resize-handle handle-${edge}${isDragging ? ' is-dragging' : ''}`}
      role="separator"
      aria-controls={controlsId}
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemax={maxWidth}
      aria-valuemin={minWidth}
      aria-valuenow={width}
      aria-valuetext={`${width} pixels wide`}
      tabIndex={0}
      title="Drag to resize · Double-click to reset"
      onDoubleClick={() => onResize(defaultWidth)}
      onKeyDown={handleKeyDown}
      onPointerDown={(event) => {
        event.preventDefault();
        dragStart.current = { active: true, x: event.clientX, width };
        document.body.classList.add('focus-panel-resizing');
        setIsDragging(true);
      }}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
    >
      <span aria-hidden="true" />
    </div>
  );
}
