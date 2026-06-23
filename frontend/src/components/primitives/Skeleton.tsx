import { type HTMLAttributes } from "react";
import clsx from "clsx";
import "./Skeleton.css";

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  width?: string | number;
  height?: string | number;
}

export function Skeleton({ width, height, className, style, ...rest }: SkeletonProps) {
  return (
    <div
      className={clsx("skeleton", className)}
      style={{ width, height, ...style }}
      aria-hidden="true"
      {...rest}
    />
  );
}
