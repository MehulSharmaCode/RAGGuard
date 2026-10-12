import type { LucideIcon } from "lucide-react";
import { LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "destructive";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-ink-900 text-paper-50 border border-ink-900 hover:bg-ink-700 hover:border-ink-700 disabled:bg-ink-300 disabled:border-ink-300 disabled:text-paper-50",
  secondary:
    "bg-paper-50 text-ink-900 border border-line-strong hover:bg-paper-200 disabled:text-ink-500 disabled:border-paper-300",
  ghost: "bg-transparent text-ink-700 border border-transparent hover:bg-paper-200 hover:text-ink-900 disabled:text-ink-500",
  destructive:
    "bg-fail text-paper-50 border border-fail hover:opacity-90 disabled:opacity-50",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-2.5 gap-1.5 text-13",
  md: "h-9 px-3.5 gap-2 text-14",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: LucideIcon;
  loading?: boolean;
  children?: ReactNode;
}

export function Button({
  variant = "secondary",
  size = "md",
  icon: Icon,
  loading = false,
  disabled,
  className = "",
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  const IconToRender = loading ? LoaderCircle : Icon;
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex shrink-0 items-center justify-center rounded-sm font-medium whitespace-nowrap transition-colors duration-150 ease-out disabled:cursor-not-allowed ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    >
      {IconToRender && (
        <IconToRender
          aria-hidden="true"
          size={16}
          strokeWidth={1.75}
          className={loading ? "animate-spin" : undefined}
        />
      )}
      {children}
    </button>
  );
}
