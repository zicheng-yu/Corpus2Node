import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";
import clsx from "clsx";
import "./Input.css";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, className, id, ...rest }, ref) => {
    return (
      <div className="input-wrap">
        {label && (
          <label className="input-label" htmlFor={id}>
            {label}
          </label>
        )}
        <input ref={ref} id={id} className={clsx("input", className)} {...rest} />
      </div>
    );
  },
);

Input.displayName = "Input";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, className, id, ...rest }, ref) => {
    return (
      <div className="input-wrap">
        {label && (
          <label className="input-label" htmlFor={id}>
            {label}
          </label>
        )}
        <textarea ref={ref} id={id} className={clsx("textarea", className)} {...rest} />
      </div>
    );
  },
);

Textarea.displayName = "Textarea";
