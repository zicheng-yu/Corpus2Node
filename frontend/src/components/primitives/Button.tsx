import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";
import "./Button.css";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "ghost" | "danger" | "link";
  size?: "sm" | "md";
  loading?: boolean;
  iconLeft?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", loading, iconLeft, children, className, disabled, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        className={clsx(
          "btn",
          `btn-${size}`,
          `btn-${variant}`,
          className,
        )}
        disabled={disabled || loading}
        {...rest}
      >
        {loading ? (
          <span className="btn-spinner" aria-hidden="true" />
        ) : iconLeft ? (
          <span aria-hidden="true">{iconLeft}</span>
        ) : null}
        {children}
      </button>
    );
  },
);

Button.displayName = "Button";
