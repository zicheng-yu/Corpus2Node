import { type HTMLAttributes } from "react";
import clsx from "clsx";
import "./Pill.css";

export interface PillProps extends HTMLAttributes<HTMLButtonElement> {
  active?: boolean;
}

export function Pill({ active, className, children, ...rest }: PillProps) {
  return (
    <button
      type="button"
      className={clsx("pill", active && "pill-active", className)}
      aria-pressed={active}
      {...rest}
    >
      {children}
    </button>
  );
}

type BadgeVariant = "default" | "success" | "danger" | "warning" | "info" | "accent";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export function Badge({ variant = "default", className, children, ...rest }: BadgeProps) {
  return (
    <span className={clsx("badge", `badge-${variant}`, className)} {...rest}>
      {children}
    </span>
  );
}
