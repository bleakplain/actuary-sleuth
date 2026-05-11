import React from 'react';

interface ClickableDivProps extends React.HTMLAttributes<HTMLDivElement> {
  onActivate: () => void;
}

export function ClickableDiv({ onActivate, onClick, onKeyDown, tabIndex = 0, role = 'button', ...rest }: ClickableDivProps) {
  return (
    <div
      role={role}
      tabIndex={tabIndex}
      onClick={(e: React.MouseEvent<HTMLDivElement>) => {
        onActivate();
        onClick?.(e);
      }}
      onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onActivate();
        }
        onKeyDown?.(e);
      }}
      {...rest}
    />
  );
}